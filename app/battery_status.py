# SPDX-License-Identifier: GPL-2.0-or-later
"""Operational battery lockout, separate from controller memory access.

TI SLUUBU5A chapters 3 and 15.1.40: PF/SS, FUSE, inhibit and FET flags.
SEC1/SEC0 (sealed/unsealed) deliberately have no effect on battery status.
"""


def battery_status(chip):
    result = {"state": "unknown", "label": "Unknown",
              "reason": "Read verified controller diagnostics to check battery operation.",
              "charge_fet": None, "discharge_fet": None,
              "charge_allowed": None, "discharge_allowed": None}
    if chip.get("status_layout") != "ti_bq40":
        return result

    def word(name):
        value = chip.get(name)
        return value if type(value) is int and 0 <= value <= 0xFFFFFFFF else None

    operation, pf, safety = word("operation"), word("permanent_failure"), word("safety")
    if operation is not None:
        result.update(charge_fet=bool(operation & 4), discharge_fet=bool(operation & 2),
                      charge_allowed=not bool(operation & (1 << 14)),
                      discharge_allowed=not bool(operation & (1 << 13)))

    def state(code, label, reason):
        return dict(result, state=code, label=label, reason=reason)

    if pf or (operation is not None and operation & (1 << 12)):
        return state("locked", "Locked", "Permanent-failure lockout reported by the controller.")
    if operation is not None and operation & (1 << 5):
        return state("locked", "Locked", "Controller fuse signal is active; check the pack hardware.")
    if safety or (operation is not None and operation & (1 << 11)):
        return state("protected", "Protection active", "A safety protection is active; identify and correct its cause.")
    if operation is None or pf is None or safety is None:
        return state("unknown", "Unknown", "Operation, PF and safety readings are required to confirm battery status.")
    if operation & ((1 << 31) | (1 << 30) | (1 << 29) | (1 << 16) | (1 << 10) | (1 << 6)):
        return state("inhibited", "Output disabled", "Shutdown, disconnect or emergency-stop state reported; PF is clear.")
    if operation & ((1 << 14) | (1 << 13)):
        return state("inhibited", "Inhibited", "Charging or discharging is disabled; no permanent-failure lockout reported.")
    if not result["charge_fet"] or not result["discharge_fet"]:
        return state("inhibited", "Output limited", "A charge/discharge FET is off; check pack presence and operating conditions.")
    return state("unlocked", "Unlocked", "PF and safety flags are clear; charge and discharge FETs are on.")


def recovery_unavailable(chip):
    """One reason for refusing PF recovery, shared by UI and worker."""
    status = battery_status(chip)
    if status["state"] != "locked":
        return "No confirmed battery lockout to clear."
    if not chip.get("recovery_supported"):
        return "PF recovery is not implemented for this controller/firmware."
    if chip.get("safety") != 0:
        return "Resolve active or unread safety protections before clearing PF."
    operation = chip.get("operation")
    if type(operation) is not int:
        return "Read controller operation status before recovery."
    if operation & ((1 << 5) | (1 << 6)):
        return "Fuse or emergency-stop state requires hardware diagnosis."
    if not chip.get("permanent_failure") and not operation & (1 << 12):
        return "No permanent-failure condition to reset."
    if chip.get("security") not in ("Sealed", "Unsealed", "Full access"):
        return "Read controller service-access state before recovery."
    return ""
