/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
/* Lifecycle boundary shared by EC and battery tools. */
#include "device_runtime.h"
#include "i2c_bus.h"
#include "ite_dbgr.h"
#include "ene_edi.h"
#include "smbus.h"

void device_tick(void) {
    if (smb_active()) smb_tick();
    else dbgr_hold_tick();
}
bool device_release(void) {
    smb_close();
    /* RELEASE retains the ITE debug hold for legacy host connections. */
    bool okay = ene_close();
    release_bus();
    return okay;
}
bool device_end_session(void) {
    smb_close();
    dbgr_end_session();
    return ene_close();
}
