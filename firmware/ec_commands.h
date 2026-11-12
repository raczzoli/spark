/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#pragma once
#include <stdbool.h>
bool ec_command(char *cmd);
bool ite_command(char *cmd);
bool ene_command(char *cmd);
unsigned ec_command_budget(const char *cmd);
const char *ec_capabilities(void);
