# SPDX-License-Identifier: GPL-2.0-or-later
"""Verified controller discovery and diagnostic layouts, independent of pinouts.

TI SLUUBU5A sections 15.1, 15.35–15.38; live ID 4555 / firmware 0003
diagnostics were checked on the connected LGC AC14B8K. This is a diagnostic
compatibility profile, not an assertion that all BQ40 parts share service keys.
"""
from .battery import BatteryError, read_ti_diagnostics
from .transport import TransportError


def diagnostic_error(bus, error):
    if not bus._synchronized or "PEC" in str(error):
        raise error
    return str(error)


def identify_controller(bus, snapshot, explicit=False):
    """A live SBS identity permits a TI identity query, never a service operation.

    ManufacturerAccess is not standardized across vendors. Unknown live SBS
    identities require an explicit profile until a verified discovery path is
    added. Selecting a connector from the catalog never chooses that path.
    """
    maker = snapshot.strings.get("manufacturer", "").casefold().strip()
    model = snapshot.strings.get("device", "").casefold().strip()
    expected = {("lgc", "ac14b8k"): 0x4555}.get((maker, model))
    if model.startswith("bq40z50") and maker in ("ti", "texas inst.", "texas instruments"):
        expected = 0x4500
    if expected is None and not explicit:
        return {"note": "No verified automatic controller probe for this battery identity. "
                        "SBS data remains available; choose a matching controller profile."}
    try:
        device = bus.query_ti_legacy(0x0001)
        if len(device) != 2:
            raise BatteryError("Invalid TI device identity length")
        code = int.from_bytes(device, "little")
        if expected is not None and code != expected:
            raise BatteryError(f"Controller ID 0x{code:04X} differs from the verified identity. "
                               "No controller-specific status or service request was sent.")
        if code not in (0x4500, 0x4555):
            return {"device_type": f"{code:04X}", "name": f"Controller ID 0x{code:04X}",
                    "note": "Controller identity read; its diagnostic profile is not implemented."}
        if code == 0x4500:
            result = read_ti_diagnostics(bus)
            result["identified_by"] = "TI DeviceType + FirmwareVersion"
            return result
        fw = bus.query_ti_legacy(0x0002)
        # FirmwareVersion fields are MSB first. DeviceType, status and cells
        # use little endian; treating every field alike breaks identification.
        if len(fw) != 11 or int.from_bytes(fw[:2], "big") != code:
            raise BatteryError("Firmware identity does not match the detected controller")
        version = int.from_bytes(fw[2:4], "big")
        result = {"name": "TI controller 0x4555", "device_type": "4555",
                  "firmware": f"{version:04X}", "firmware_display": f"{version >> 8}.{version & 255:02X}",
                  "firmware_raw": fw.hex().upper(), "service_supported": False, "recovery_supported": False,
                  "identified_by": "TI DeviceType + FirmwareVersion",
                  "note": "Diagnostic layout verified on LGC AC14B8K, ID 4555 / firmware 0003. "
                          "PF recovery and service access require their own controller-specific profile."}
        if version != 0x0003:
            result["note"] = "Controller identified; this firmware revision's diagnostic layout is not verified."
            return result
        result["status_layout"] = "ti_bq40"
        errors = {}
        for name, selector in (("operation", 0x54), ("safety", 0x51), ("permanent_failure", 0x53)):
            try:
                data = bus.query_ti_legacy(selector)
                if len(data) != 4:
                    raise BatteryError(f"Invalid {name} status length")
                result[name] = int.from_bytes(data, "little")
            except (BatteryError, TransportError) as error:
                errors[name] = diagnostic_error(bus, error)
        if "operation" in result:
            result["security"] = {1: "Full access", 2: "Unsealed", 3: "Sealed"}.get(
                (result["operation"] >> 8) & 3, "Unknown")
        try:
            cells = [bus.read_word(reg) for reg in (0x3F, 0x3E, 0x3D, 0x3C)]
            active = [v for v in cells if v]
            total_mV = snapshot.metrics["voltage"] * 1000
            if (len(active) < 2 or any(v > 5000 for v in active) or
                    abs(sum(active) - total_mV) > max(250, total_mV * .03)):
                raise BatteryError("Reported cell voltages do not agree with the pack voltage")
            result["cells_mV"] = cells
            result["imbalance_mV"] = max(active) - min(active)
            result["cells_source"] = "TI read-word 0x3F / 0x3E / 0x3D / 0x3C"
        except (BatteryError, TransportError) as error:
            errors["cells"] = diagnostic_error(bus, error)
        if errors:
            result["diagnostic_errors"] = errors
        return result
    except (BatteryError, TransportError) as error:
        return {"note": diagnostic_error(bus, error), "service_supported": False}
