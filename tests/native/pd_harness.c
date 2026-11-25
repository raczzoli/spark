/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "i2c_bus.h"
#include "pd_commands.h"
#include "usb_output.h"

const char *i2c_error;
static uint8_t selected, parameters[64], result[64], command[4];
static unsigned tasks, parameter_count;
static const char *fault;
static uint64_t clock_us;
uint64_t time_us_64(void) { clock_us += 10000; return clock_us; }
void sleep_us(uint64_t us) { clock_us += us; }

bool write_i2c(uint8_t address, const uint8_t *data, size_t count) {
    (void)address;
    selected = data[0];
    if (count == 1) return true;
    if (count != (size_t)data[1] + 2 || data[1] > 64) abort();
    if (selected == 9) {
        if (!strcmp(fault, "parameter_nack")) { i2c_error = "INJECTED_NACK"; return false; }
        parameter_count = data[1];
        memcpy(parameters, data + 2, parameter_count);
    } else if (selected == 8) {
        ++tasks;
        memcpy(command, data + 2, 4);
        if (!strcmp(fault, "unsupported")) { memcpy(command, "!CMD", 4); return true; }
        if (!strcmp(fault, "timeout")) return true;
        if (!memcmp(command, "FLrd", 4)) {
            uint32_t offset = (uint32_t)parameters[0] | (uint32_t)parameters[1] << 8
                            | (uint32_t)parameters[2] << 16 | (uint32_t)parameters[3] << 24;
            for (unsigned i = 0; i < 16; ++i) result[i] = (uint8_t)(offset + i);
        } else result[0] = 0;
        memset(command, 0, 4);
    }
    return true;
}

bool read_i2c(uint8_t address, uint8_t *data, size_t count) {
    (void)address;
    data[0] = selected == 8 ? 4 : 64;
    if (!strcmp(fault, "length")) data[0] = 0;
    memcpy(data + 1, selected == 8 ? command : result, count - 1);
    return true;
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    fault = argc > 2 ? argv[2] : "";
    usb_reply_begin(false, 0);
    if (!pd_command(argv[1])) puts("NOT_PD");
    printf("TASKS=%u PARAMS=%u\n", tasks, parameter_count);
    return 0;
}
