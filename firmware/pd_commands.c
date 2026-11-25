/* SPDX-License-Identifier: GPL-2.0-or-later */
/* TI 4CC mailbox transport. No controller device IDs are assumed. */
#include <stdio.h>
#include <string.h>
#include "pd_commands.h"
#include "i2c_bus.h"
#include "usb_output.h"
#include "command_parse.h"

static const char *pd_error;

static bool reg_read(uint8_t addr, uint8_t reg, uint8_t *data, size_t count) {
    uint8_t raw[65];
    if (!write_i2c(addr, &reg, 1) || !read_i2c(addr, raw, count + 1)) {
        pd_error = i2c_error ? i2c_error : "PD_I2C_READ";
        return false;
    }
    if (raw[0] < count || raw[0] > 64) {
        pd_error = "PD_REGISTER_LENGTH";
        return false;
    }
    memcpy(data, raw + 1, count);
    return true;
}

static bool reg_write(uint8_t addr, uint8_t reg, const uint8_t *data, size_t count) {
    uint8_t packet[66];
    packet[0] = reg;
    packet[1] = (uint8_t)count;
    memcpy(packet + 2, data, count);
    if (!write_i2c(addr, packet, count + 2)) {
        pd_error = i2c_error ? i2c_error : "PD_I2C_WRITE";
        return false;
    }
    return true;
}

static bool task(uint8_t addr, const char *code, const uint8_t *input, size_t in_len,
                 uint8_t *output, size_t out_len) {
    uint8_t state[4];
    if (!reg_read(addr, 8, state, 4)) return false;
    if (memcmp(state, "\0\0\0\0", 4) && memcmp(state, "!CMD", 4)) {
        pd_error = "PD_COMMAND_BUSY";
        return false;
    }
    /* Do not execute a command if its parameter write failed. */
    if (in_len && !reg_write(addr, 9, input, in_len)) return false;
    if (!reg_write(addr, 8, (const uint8_t *)code, 4)) return false;
    uint64_t limit = time_us_64() + 2500000;
    while (true) {
        if (!reg_read(addr, 8, state, 4)) return false;
        if (!memcmp(state, "\0\0\0\0", 4)) break;
        if (!memcmp(state, "!CMD", 4)) {
            pd_error = "PD_COMMAND_UNSUPPORTED";
            return false;
        }
        if (time_us_64() >= limit) {
            pd_error = "PD_COMMAND_TIMEOUT";
            return false;
        }
        sleep_us(500);
    }
    return !out_len || reg_read(addr, 9, output, out_len);
}

static void hex_encode(const uint8_t *data, size_t count, char *hex) {
    static const char digits[] = "0123456789ABCDEF";
    for (size_t i = 0; i < count; ++i) {
        hex[2*i] = digits[data[i] >> 4];
        hex[2*i+1] = digits[data[i] & 15];
    }
    hex[2*count] = 0;
}

bool pd_command(char *cmd) {
    unsigned addr, count;
    unsigned long long address;
    int used;
    char code[5], input_hex[129];
    uint8_t input[64], output[256];
    static char hex[513];
    size_t in_len;
    pd_error = NULL;
    if (!strncmp(cmd, "PDTASK ", 7)) {
        if (sscanf(cmd, "PDTASK %2x %4s %128s %3u%n", &addr, code, input_hex, &count, &used) != 4
                || cmd[used] || addr < 8 || addr > 0x77 || strlen(code) != 4 || count > 64) {
            usb_puts("ERR PD_ARGUMENT");
            return true;
        }
        in_len = 0;
        if (strcmp(input_hex, "-") && !parse_hex(input_hex, input, sizeof input, &in_len)) {
            usb_puts("ERR PD_ARGUMENT");
            return true;
        }
        if (!task((uint8_t)addr, code, input, in_len, output, count)) {
            usb_printf("ERR %s\n", pd_error);
            return true;
        }
        hex_encode(output, count, hex);
        usb_printf("PDTASK %s\n", hex);
        return true;
    }
    if (!strncmp(cmd, "PDREAD ", 7)) {
        if (sscanf(cmd, "PDREAD %2x %16llx %3u%n", &addr, &address, &count, &used) != 3
                || cmd[used] || addr < 8 || addr > 0x77 || !count || count > 256 || count % 16
                || address % 16 || address > 0xFFFFFFFFull || address + count > 0x100000000ull) {
            usb_puts("ERR PD_ARGUMENT");
            return true;
        }
        for (unsigned offset = 0; offset < count; offset += 16) {
            uint32_t next = (uint32_t)(address + offset);
            for (unsigned i = 0; i < 4; ++i) input[i] = (uint8_t)(next >> (8*i));
            if (!task((uint8_t)addr, "FLrd", input, 4, output + offset, 16)) {
                usb_printf("ERR %s\n", pd_error);
                return true;
            }
        }
        hex_encode(output, count, hex);
        usb_printf("PDREAD %08lX %s\n", (unsigned long)address, hex);
        return true;
    }
    return false;
}
