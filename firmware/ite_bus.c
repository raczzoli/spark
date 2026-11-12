/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
/* ITE register cursor tracking is independent of the electrical bus. */
#include "ite_bus.h"
static uint8_t selected_register;
static bool selected_register_valid;

bool ite_selected_register(uint8_t *reg) {
    *reg = selected_register;
    return selected_register_valid;
}
bool ite_write_i2c(uint8_t addr, const uint8_t *buf, size_t len) {
    bool ok = write_i2c(addr, buf, len);
    if (ok && addr == 0x5a && len == 1) {
        selected_register = buf[0];
        selected_register_valid = true;
    }
    return ok;
}
void ite_set_pins(uint sda, uint scl) {
    if (sda != sda_pin || scl != scl_pin) selected_register_valid = false;
    set_pins(sda, scl);
}
