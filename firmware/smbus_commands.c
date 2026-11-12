/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <stdio.h>
#include <string.h>
#include "smbus.h"
#include "i2c_bus.h"
#include "ite_dbgr.h"
#include "ene_edi.h"
#include "command_parse.h"
#include "usb_output.h"

bool smb_command(char *cmd) {
    unsigned a,b,c,d;int used;uint16_t value;uint8_t data[SMB_MAX_BLOCK];size_t len;
    if (!strcmp(cmd,"SMBCLOSE")) { smb_close();usb_puts("OK");return true; }
    if (!strncmp(cmd,"SMBOPEN ",8)) {
        if (sscanf(cmd,"SMBOPEN %3u %3u %1u %2u%n",&a,&b,&c,&d,&used)!=4 || cmd[used] ||
            !valid_pin(a) || !valid_pin(b) || a==b || c>1 || (d!=5 && d!=10)) {
            usb_puts("ERR SMB_ARGUMENT");return true;
        }
        dbgr_end_session();
        if (!ene_close()) { usb_puts("ERR ENE_CLOSE");return true; }
        if (!smb_open(a,b,c,d)) { usb_printf("ERR %s\n",smb_error());return true; }
        bool sda,scl;smb_levels(&sda,&scl);
        usb_printf("SMBOPEN SDA=%u SCL=%u DATA=%u CLOCK=%u\n",a,b,sda,scl);
        return true;
    }
    if (strncmp(cmd,"SMB",3)) return false;
    if (!smb_active()) { usb_puts("ERR SMB_NOT_OPEN");return true; }
    if (!strcmp(cmd,"SMBLINES")) {
        bool sda,scl;smb_levels(&sda,&scl);
        usb_printf("SMBLINES DATA=%u CLOCK=%u\n",sda,scl);return true;
    }
    if (sscanf(cmd,"SMBRW %2x %2x %1u%n",&a,&b,&c,&used)==3 && !cmd[used]) {
        if (a<8 || a>0x77 || b>255 || c>1) { usb_puts("ERR SMB_ARGUMENT");return true; }
        if (smb_read_word(a,b,c,&value)) usb_printf("SMBWORD %02X %04X PEC=%s\n",b,value,c ? "OK" : "OFF");
        else usb_printf("ERR %s\n",smb_error());
        return true;
    }
    if (sscanf(cmd,"SMBRB %2x %2x %1u%n",&a,&b,&c,&used)==3 && !cmd[used]) {
        if (a<8 || a>0x77 || b>255 || c>1) { usb_puts("ERR SMB_ARGUMENT");return true; }
        if (!smb_read_block(a,b,c,data,&len)) { usb_printf("ERR %s\n",smb_error());return true; }
        usb_printf("SMBBLOCK %02X ",b);
        for (size_t i=0;i<len;++i) usb_printf("%02X",data[i]);
        usb_printf(" PEC=%s\n",c ? "OK" : "OFF");return true;
    }
    if (sscanf(cmd,"SMBWW %2x %2x %4x %1u%n",&a,&b,&c,&d,&used)==4 && !cmd[used]) {
        if (a<8 || a>0x77 || b>255 || c>65535 || d>1) { usb_puts("ERR SMB_ARGUMENT");return true; }
        if (smb_write_word(a,b,d,c)) usb_puts("OK");
        else usb_printf("ERR %s\n",smb_error());
        return true;
    }
    char hex[65];
    if (sscanf(cmd,"SMBWB %2x %2x %64s %1u%n",&a,&b,hex,&c,&used)==4 && !cmd[used]) {
        if (a<8 || a>0x77 || b>255 || c>1 || !parse_hex(hex,data,sizeof data,&len)) {
            usb_puts("ERR SMB_ARGUMENT");return true;
        }
        if (smb_write_block(a,b,c,data,len)) usb_puts("OK");
        else usb_printf("ERR %s\n",smb_error());
        return true;
    }
    usb_puts("ERR SMB_ARGUMENT");return true;
}
