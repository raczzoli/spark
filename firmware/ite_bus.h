/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include "i2c_bus.h"
bool ite_write_i2c(uint8_t addr, const uint8_t *buf, size_t len);
bool ite_selected_register(uint8_t *reg);
void ite_set_pins(uint sda, uint scl);
