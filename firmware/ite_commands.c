/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include <stdio.h>
#include <string.h>
#include "ite_bus.h"
#include "ite_dbgr.h"
#include "ite_flash.h"
#include "ec_commands.h"
#include "command_parse.h"
#include "usb_output.h"
#define MAX_XFER 64
#define MAX_PROGRAM 256

bool ite_command(char *cmd) {
    unsigned a, b; char hex[MAX_XFER*2+1]; uint8_t buf[MAX_XFER]; size_t len; int used;
    if ((sscanf(cmd,"I2CTIMING %3u%n",&a,&used)==1 && cmd[used] == 0)) {
        usb_puts(bus_set_timing(a) ? "OK" : "ERR I2CTIMING"); return true;
    }
    if ((sscanf(cmd,"REGREAD %8x%n",&a,&used)==1 && cmd[used] == 0)) {
        uint8_t value;
        if (a > 255) { usb_puts("ERR ARG"); return true; }
        if (!dbgr_reg_read(a,&value)) usb_printf("ERR %s\n", i2c_error ? i2c_error : "REG_READ");
        else usb_printf("REG %02X %02X\n", a, value);
        return true;
    }
    if ((sscanf(cmd,"REGWRITE %8x %8x%n",&a,&b,&used)==2 && cmd[used] == 0)) {
        if (a > 255 || b > 255) { usb_puts("ERR ARG"); return true; }
        if (!dbgr_reg_write(a,b)) usb_printf("ERR %s\n", i2c_error ? i2c_error : "REG_WRITE");
        else usb_puts("OK");
        return true;
    }
    if (!strcmp(cmd,"SESSION")) {
        uint8_t high, low, ver;
        if (!dbgr_reg_read(0x02,&ver) || !dbgr_reg_read(0x00,&high) ||
            !dbgr_reg_read(0x01,&low)) {
            usb_printf("ERR %s\n", i2c_error ? i2c_error : "SESSION_ID"); return true;
        }
        if ((high & 0xf0u) != 0x80u) { usb_puts("ERR SESSION_ID"); return true; }
        dbgr_hold_refresh();
        usb_printf("SESSION CHIPID=%02X%02X CHIPVER=%02X\n", high,low,ver);
        return true;
    }
    if (!strcmp(cmd,"SPISTATUS")) { flash_status(); return true; }
    if ((sscanf(cmd,"FLASHID %8x%n",&a,&used)==1 && cmd[used] == 0)) {
        if (a != 0x79 && a != 0x35) { usb_puts("ERR ARG"); return true; }
        flash_identify(a); return true;
    }
    if ((sscanf(cmd,"ERASESECTOR %8x %8x%n",&a,&b,&used)==2 && cmd[used] == 0)) {
        erase_flash_sector(a,b); return true;
    }
    if (!strcmp(cmd,"HOLDDBGR")) {
        usb_printf("HOLDDBGR %s\n", dbgr_hold_until_us ? "ACTIVE" : "INACTIVE");
        return true;
    }
    if (!strcmp(cmd,"ENTERDBGR")) { enter_dbgr_fast(); return true; }
    if ((sscanf(cmd,"READPAGE %8x%n",&a,&used)==1 && cmd[used] == 0)) { read_flash_page(a); return true; }
    if ((sscanf(cmd,"AAI64 %8x %128s%n",&a,hex,&used)==2 && cmd[used] == 0)) {
        if (!parse_hex(hex,buf,sizeof buf,&len) || len != 64) {
            usb_puts("ERR AAI64_DATA"); return true;
        }
        program_flash_block(a,buf,64); return true;
    }
    if ((sscanf(cmd,"AAIV2_64 %8x %128s%n",&a,hex,&used)==2 && cmd[used] == 0)) {
        if (!parse_hex(hex,buf,sizeof buf,&len) || len != 64) {
            usb_puts("ERR AAIV2_64_DATA"); return true;
        }
        program_flash_v2_block(a,buf,64,false); return true;
    }
    if (!strncmp(cmd,"AAIV2_256 ",10)) {
        char program_hex[MAX_PROGRAM*2+1];
        uint8_t program_data[MAX_PROGRAM];
        if ((sscanf(cmd,"AAIV2_256 %8x %512s%n",&a,program_hex,&used)!=2 || cmd[used] != 0) ||
            !parse_hex(program_hex,program_data,sizeof program_data,&len) ||
            len != MAX_PROGRAM) {
            usb_puts("ERR AAIV2_256_DATA"); return true;
        }
        program_flash_v2_block(a,program_data,MAX_PROGRAM,false); return true;
    }
    if ((sscanf(cmd,"PAGE64 %8x %128s%n",&a,hex,&used)==2 && cmd[used] == 0)) {
        if (!parse_hex(hex,buf,sizeof buf,&len) || len != 64) {
            usb_puts("ERR PAGE64_DATA"); return true;
        }
        program_flash_v2_block(a,buf,64,true); return true;
    }
    if (!strncmp(cmd,"AAI256 ",7)) {
        char program_hex[MAX_PROGRAM*2+1];
        uint8_t program_data[MAX_PROGRAM];
        if ((sscanf(cmd,"AAI256 %8x %512s%n",&a,program_hex,&used)!=2 || cmd[used] != 0) ||
            !parse_hex(program_hex,program_data,sizeof program_data,&len) ||
            len != MAX_PROGRAM) {
            usb_puts("ERR AAI256_DATA"); return true;
        }
        program_flash_block(a,program_data,MAX_PROGRAM); return true;
    }
    if (!strcmp(cmd,"WAVEPOWER")) { wave_at_power_on(); return true; }
    if ((sscanf(cmd,"PINS %3u %3u%n",&a,&b,&used)==2 && cmd[used] == 0)) {
        if (!valid_pin(a)||!valid_pin(b)||a==b) { usb_puts("ERR PINS"); return true; }
        if (a != sda_pin || b != scl_pin) {
            dbgr_hold_until_us = 0;
            wave_entry_rate = 0;
        }
        ite_set_pins(a,b); usb_puts("OK"); return true;
    }
    if (!strcmp(cmd,"WAVESWEEP")) {
        if (!adjacent_bus_pins()) { usb_puts("ERR NEED_CONSECUTIVE_PINS"); return true; }
        static const unsigned rates[] = {200000, 300000, 400000, 500000, 600000, 800000};
        usb_printf("SWEEP");
        for (unsigned i = 0; i < sizeof rates / sizeof rates[0]; ++i) {
            waveform(false, rates[i]);
            bool ack = probe_write_address(0x5a);
            usb_printf(" %u:%s", rates[i], ack ? "ACK" : (i2c_error ? i2c_error : "ERROR"));
            if (ack) break;
        }
        usb_puts("");
        return true;
    }
    if ((sscanf(cmd,"WRITE %8x %128s%n",&a,hex,&used)==2 && cmd[used] == 0)) {
        if (a>0x7f || !parse_hex(hex,buf,sizeof buf,&len)) { usb_puts("ERR ARG"); return true; }
        if (ite_write_i2c(a,buf,len)) usb_puts("OK");
        else usb_printf("ERR %s\n", i2c_error ? i2c_error : "I2C_UNKNOWN");
        return true;
    }
    if ((sscanf(cmd,"READ %8x %3u%n",&a,&b,&used)==2 && cmd[used] == 0)) {
        if (a>0x7f || b<1 || b>MAX_XFER) { usb_puts("ERR ARG"); return true; }
        if (!read_i2c(a,buf,b)) {
            usb_printf("ERR %s\n", i2c_error ? i2c_error : "I2C_UNKNOWN");
            return true;
        }
        usb_printf("DATA "); for (uint i=0;i<b;++i) usb_printf("%02X",buf[i]); usb_puts(""); return true;
    }
    return false;
}
