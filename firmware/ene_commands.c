/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include <stdio.h>
#include <string.h>
#include "ene_edi.h"
#include "ite_dbgr.h"
#include "ec_commands.h"
#include "command_parse.h"
#include "usb_output.h"

bool ene_command(char *cmd) {
    unsigned a; size_t len; int used;
    if (!strcmp(cmd,"ENERX")) {
        const uint8_t *rx = ene_last_rx();
        usb_printf("ENERX ");
        for (unsigned i=0; i<36; ++i) usb_printf("%02X", rx[i]);
        usb_puts("");
        return true;
    }
    if (!strcmp(cmd,"ENEOPEN") || !strncmp(cmd,"ENEOPEN ",8)) {
        char family[16] = "KB9052"; /* Preserve the old KB9052-only command. */
        if (strcmp(cmd,"ENEOPEN") &&
            (sscanf(cmd,"ENEOPEN %15s%n",family,&used)!=1 || cmd[used]!=0)) {
            usb_puts("ERR ENEOPEN_FAMILY"); return true;
        }
        uint8_t hw = 0, id = 0;
        if (!ene_is_open()) dbgr_end_session();
        if (!ene_open_family(family, &hw, &id)) {
            usb_printf("ERR %s HW=%02X EDI=%02X\n", ene_error(), hw, id);
            return true;
        }
        usb_printf("ENEOPEN HW=%02X EDI=%02X\n", hw, id);
        return true;
    }
    if ((sscanf(cmd,"ENEREADPAGE %8x%n",&a,&used)==1 && cmd[used] == 0)) {
        uint8_t page[128];
        if (!ene_read_page(a, page)) { usb_printf("ERR %s\n", ene_error()); return true; }
        usb_printf("ENEPAGE %05X ", a);
        for (unsigned i=0; i<sizeof page; ++i) usb_printf("%02X", page[i]);
        usb_puts("");
        return true;
    }
    if ((sscanf(cmd,"ENEERASEPAGE %8x%n",&a,&used)==1 && cmd[used] == 0)) {
        if (!ene_erase_page(a)) { usb_printf("ERR %s\n", ene_error()); return true; }
        usb_printf("ENEERASEPAGE %05X OK\n", a);
        return true;
    }
    if (!strncmp(cmd,"ENEWRITEPAGE ",13)) {
        char page_hex[257];
        uint8_t page[128];
        if ((sscanf(cmd,"ENEWRITEPAGE %8x %256s%n",&a,page_hex,&used)!=2 || cmd[used] != 0) ||
            !parse_hex(page_hex,page,sizeof page,&len) || len != sizeof page) {
            usb_puts("ERR ENEWRITEPAGE_DATA"); return true;
        }
        if (!ene_write_page(a,page)) { usb_printf("ERR %s\n", ene_error()); return true; }
        usb_printf("ENEWRITEPAGE %05X OK\n", a);
        return true;
    }
    return false;
}
