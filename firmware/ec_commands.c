/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
/* EC command routing and legacy ITE/ENE coexistence rules. */
#include <string.h>
#include "ec_commands.h"
#include "device_runtime.h"
#include "ene_edi.h"
#include "usb_output.h"

const char *ec_capabilities(void) {
    return "CAPS AAI64 AAI256 AAIV2_64 AAIV2_256 PAGE64 ENE_EDI ENE_EDI_V2 TAGGED REGIO SPISTATUS FLASHID ERASESECTOR SESSION ITE5 INFO I2CTIMING SMBUS1";
}
unsigned ec_command_budget(const char *cmd) {
    unsigned budget = 3000;
    if (!strcmp(cmd,"WAVEPOWER")) budget = 45000;
    else if (!strcmp(cmd,"ENTERDBGR") || !strcmp(cmd,"WAVESWEEP")) budget = 5000;
    else if (!strncmp(cmd,"AAI",3) || !strncmp(cmd,"PAGE64 ",7) ||
             !strncmp(cmd,"ERASESECTOR ",12)) budget = 20000;
    return budget;
}
bool ec_command(char *cmd) {
    if (!strcmp(cmd,"ENDSESSION")) {
        usb_puts(device_end_session() ? "OK" : "ERR ENE_CLOSE");
        return true;
    }
    if (!strcmp(cmd,"RELEASE") || !strcmp(cmd,"ENECLOSE")) {
        usb_puts(device_release() ? "OK" : "ERR ENE_CLOSE");
        return true;
    }
    if (ene_command(cmd)) return true;
    if (ene_is_open()) { usb_puts("ERR ENE_ACTIVE"); return true; }
    return ite_command(cmd);
}
