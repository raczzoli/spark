/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
static inline int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c-'0';
    if (c >= 'A' && c <= 'F') return c-'A'+10;
    if (c >= 'a' && c <= 'f') return c-'a'+10;
    return -1;
}
static inline bool parse_hex(const char *s, uint8_t *buf, size_t capacity, size_t *len) {
    size_t n = strlen(s);
    if (!n || (n & 1) || n > capacity*2) return false;
    for (size_t i=0; i<n; i+=2) {
        int h=hex_digit(s[i]), l=hex_digit(s[i+1]);
        if (h<0 || l<0) return false;
        buf[i/2]=(uint8_t)((h<<4)|l);
    }
    *len=n/2; return true;
}
