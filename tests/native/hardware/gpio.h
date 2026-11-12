/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include "pico/stdlib.h"
bool gpio_get(uint pin);
void gpio_pull_up(uint pin);
void gpio_disable_pulls(uint pin);
void busy_wait_us(uint64_t us);
