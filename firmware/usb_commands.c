/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include <stdio.h>
#include <string.h>
#include "i2c_bus.h"
#include "ec_commands.h"
#include "command_parse.h"
#include "usb_commands.h"
#include "usb_output.h"
#include "version.h"
#include "smbus.h"

static void dispatch(char *cmd) {
    if (!strcmp(cmd,"HELLO")) { usb_puts("OK PICO_ITE_EC_PROGRAMMER 2"); return; }
    if (!strcmp(cmd,"CAPS")) { usb_puts(ec_capabilities()); return; }
    if (!strcmp(cmd,"INFO")) {
        usb_printf("INFO VERSION=%s BUILD=%s BOARD=%s I2C_DELAY_US=%u\n",
                   EC_VERSION, EC_BUILD_ID, EC_BOARD, bus_timing());
        return;
    }
    if (!strncmp(cmd,"SYNC ",5)) { usb_printf("SYNC %s\n", cmd+5); return; }
    if (smb_command(cmd)) return;
    if (smb_active() && strcmp(cmd,"ENDSESSION") && strcmp(cmd,"RELEASE")) {
        usb_puts("ERR SMB_ACTIVE");return;
    }
    if (!ec_command(cmd)) usb_puts("ERR COMMAND");
}

void usb_command(char *cmd) {
    uint32_t tag = 0;
    bool tagged = cmd[0] == '@';
    if (tagged) {
        if (strlen(cmd) < 11 || cmd[9] != ' ') {
            usb_reply_begin(false,0); usb_puts("ERR TAG"); return;
        }
        for (unsigned i=1; i<=8; ++i) {
            int digit = hex_digit(cmd[i]);
            if (digit < 0) { usb_reply_begin(false,0); usb_puts("ERR TAG"); return; }
            tag = (tag << 4) | (unsigned)digit;
        }
        cmd += 10;
    }
    usb_reply_begin(tagged,tag);
    /* A command cannot occupy the bus indefinitely. Host timeouts exceed
     * this budget; WAVEPOWER has its own 40-second reset window. */
    unsigned budget = ec_command_budget(cmd);
    bus_set_deadline(budget);
    dispatch(cmd);
    bus_set_deadline(0);
}
