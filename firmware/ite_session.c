/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "ite_bus.h"
#include "ite_dbgr.h"
#include "usb_output.h"
uint64_t dbgr_hold_until_us, dbgr_next_feed_us;
bool dbgr_ite5, dbgr_extended;

void dbgr_select_family(bool ite5) {
    if (ite5 != dbgr_ite5) {
        dbgr_end_session();
        dbgr_extended = false;
    }
    dbgr_ite5 = ite5;
}

/* IT51xx/IT55xx use the original two-byte ID. Newer IT5xxxx put the
 * additional byte at F02085, as in Chromium util/iteflash.cc. */
bool dbgr_target_identity(uint32_t *id, uint8_t *version) {
    uint8_t high, low;
    if (!dbgr_reg_read(0x02, version) || !dbgr_reg_read(0x00, &high) ||
        !dbgr_reg_read(0x01, &low)) return false;
    *id = ((uint32_t)high << 8) | low;
    bool extended = false;
    if (dbgr_ite5 && high != 0x51 && high != 0x55 && (high & 0xf0) != 0x80) {
        uint8_t third;
        if (!dbgr_reg_write(0x80, 0xf0) || !dbgr_reg_write(0x2f, 0x20) ||
            !dbgr_reg_write(0x2e, 0x85) || !dbgr_reg_read(0x30, &third)) return false;
        *id |= (uint32_t)third << 16;
        extended = third == 5;
        if (!extended) { i2c_error = "ITE_CHIP_ID"; return false; }
    }
    if (*id == 0 || *id == 0xffff) { i2c_error = "ITE_CHIP_ID"; return false; }
    dbgr_extended = extended;
    return true;
}

bool dbgr_feed_watchdog(void) {
    if (dbgr_extended && !dbgr_reg_write(0x80, 0xf0)) return false;
    return dbgr_reg_write(0x2f, 0x1f) && dbgr_reg_write(0x2e, 0x07) &&
           dbgr_reg_write(0x30, 0x5c);
}
/* Some targets keep the watchdog running after the disable sequence.
 * Feed only after a successful DBGR entry; expire the hold automatically
 * after 30 seconds without an operation.
 */
void dbgr_end_session(void) {
    dbgr_hold_until_us = 0;
    wave_entry_rate = 0;
    release_bus();
}
void dbgr_hold_refresh(void) {
    dbgr_hold_until_us = time_us_64() + 30000000u;
    dbgr_next_feed_us = time_us_64() + 10000u;
}

void dbgr_hold_tick(void) {
    if (!dbgr_hold_until_us) return;
    uint64_t now = time_us_64();
    if (now >= dbgr_hold_until_us) {
        dbgr_hold_until_us = 0;
        return;
    }
    if (now < dbgr_next_feed_us) return;
    uint8_t saved_register;
    bool restore = ite_selected_register(&saved_register);
    if (!dbgr_feed_watchdog()) {
        dbgr_hold_until_us = 0;
        return;
    }
    /* Legacy hosts split register selection and data across USB requests.
     * Keep their cursor intact when feeding between those requests. */
    if (restore && !ite_write_i2c(0x5a, &saved_register, 1)) {
        dbgr_hold_until_us = 0;
        return;
    }
    dbgr_next_feed_us = time_us_64() + 10000u;
}


void enter_dbgr_fast(void) {
    dbgr_hold_until_us = 0;
    if (!adjacent_bus_pins()) { usb_puts("ERR ENTERDBGR_PINS"); return; }
    static const unsigned rates[] = {200000, 300000, 400000,
                                     500000, 600000, 800000};
    unsigned selected_rate = 0;
    if (wave_entry_rate) {
        if (dbgr_reg_write(0x07, 0x7f)) selected_rate = wave_entry_rate;
        wave_entry_rate = 0;
    }
    for (unsigned i = 0; !selected_rate &&
                         i < sizeof rates / sizeof rates[0]; ++i) {
        waveform(false, rates[i]);
        if (dbgr_reg_write(0x07, 0x7f)) {
            selected_rate = rates[i];
            break;
        }
    }
    if (!selected_rate) {
        usb_printf("ERR ENTERDBGR_NO_ACK %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    static const uint8_t stop_sequence[][2] = {
        {0x06, 0xff}, {0x05, 0xfe}, {0x04, 0}, {0x08, 0},
        {0x07, 0}, {0x06, 0}
    };
    for (unsigned i = 0; i < sizeof stop_sequence / sizeof stop_sequence[0]; ++i) {
        if (!dbgr_reg_write(stop_sequence[i][0], stop_sequence[i][1])) {
            usb_printf("ERR ENTERDBGR_STOP_%u %s\n", i,
                   i2c_error ? i2c_error : "I2C_UNKNOWN");
            return;
        }
    }
    uint8_t ver;
    uint32_t id;
    if (!dbgr_target_identity(&id, &ver)) {
        usb_printf("ERR ENTERDBGR_ID %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    /* Extended IT5xxxx requires an explicit CPU reset/halt before flash
     * access; legacy IT51xx/IT55xx retain the follow-mode stop sequence. */
    if (dbgr_extended && !dbgr_reg_write(0x27, 0x81)) {
        usb_puts("ERR ENTERDBGR_HALT"); return;
    }
    if (dbgr_extended && !dbgr_reg_write(0x80, 0xf0)) {
        usb_puts("ERR ENTERDBGR_ADDRESS"); return;
    }
    static const uint8_t watchdog_sequence[][2] = {
        /* Restart at F01F07, then disable via F01F05. */
        {0x2f, 0x1f}, {0x2e, 0x07}, {0x30, 0x5c},
        {0x2f, 0x1f}, {0x2e, 0x05}, {0x30, 0x10}
    };
    for (unsigned i = 0; i < sizeof watchdog_sequence / sizeof watchdog_sequence[0]; ++i) {
        if (!dbgr_reg_write(watchdog_sequence[i][0], watchdog_sequence[i][1])) {
            usb_printf("ERR ENTERDBGR_WDT_%u %s\n", i,
                   i2c_error ? i2c_error : "I2C_UNKNOWN");
            return;
        }
    }
    sleep_us(1000);
    if (!dbgr_reg_write(0x30, 0x30)) {
        usb_printf("ERR ENTERDBGR_WDT_FINAL %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    sleep_us(1000);
    uint8_t watchdog;
    if (!dbgr_reg_write(0x2f, 0x1f) ||
        !dbgr_reg_write(0x2e, 0x05) ||
        !dbgr_reg_read(0x30, &watchdog)) {
        usb_printf("ERR ENTERDBGR_WDT_READ %s\n",
               i2c_error ? i2c_error : "I2C_UNKNOWN");
        return;
    }
    usb_printf("ENTERDBGR RATE=%u CHIPID=%04lX CHIPVER=%02X WDT=%02X\n",
           selected_rate, (unsigned long)id, ver, watchdog);
    dbgr_hold_refresh();
}

