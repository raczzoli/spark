# SPDX-License-Identifier: GPL-2.0-or-later
"""Controller model profiles and documented firmware storage.

Profiles describe memory geometry without restricting compatible silicon IDs.
The current models share the TI flash mailbox: SLVUBH2B covers the DH interface;
SLVUAN1A covers TPS65981/82/86. External SPI capacity is always selected manually.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PDModel:
    name: str
    external_spi: bool
    # Fixed internal flash capacity, when documented for the exact model.
    capacity: int | None = None


MODELS = (
    PDModel("TPS65987S", external_spi=True),
    PDModel("TPS65987D (DH)", external_spi=True),
    PDModel("TPS65988 (DH)", external_spi=True),
    PDModel("TPS65981", external_spi=True),
    PDModel("TPS65982", external_spi=True),
    PDModel("TPS65986", external_spi=True),
)

# Default host addresses, followed by discovery of firmware-overridden addresses.
HOST_ADDRESSES = (0x38, 0x3F, *range(0x20, 0x28))

# Suggested external SPI capacities, never model-specific defaults.
FLASH_CAPACITIES = tuple(64 * 1024 * 2**power for power in range(9))


def valid_capacity(size):
    return isinstance(size, int) and 0 < size <= 2**32 and size % 4096 == 0
