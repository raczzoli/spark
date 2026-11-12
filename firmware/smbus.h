/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "pico/stdlib.h"
#define SMB_MAX_BLOCK 34 /* TI MAC: two echoed command bytes plus 32 data bytes. */

bool smb_open(uint sda, uint scl, bool pullups, unsigned delay_us);
void smb_close(void);
bool smb_active(void);
void smb_levels(bool *sda, bool *scl);
void smb_tick(void);
const char *smb_error(void);
bool smb_read_word(uint8_t addr, uint8_t reg, bool pec, uint16_t *value);
bool smb_read_block(uint8_t addr, uint8_t reg, bool pec, uint8_t data[SMB_MAX_BLOCK], size_t *len);
bool smb_write_word(uint8_t addr, uint8_t reg, bool pec, uint16_t value);
bool smb_write_block(uint8_t addr, uint8_t reg, bool pec, const uint8_t *data, size_t len);
bool smb_command(char *cmd);
