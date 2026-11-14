# SPDX-License-Identifier: GPL-2.0-or-later
"""SBS decoding and the versioned TI bq40z50-R3 diagnostic/service profile.

References: SBS Smart Battery Data 1.1; TI SLUUBU5A chapters 12 and 15.
The SBS-only profile never issues ManufacturerAccess. Automatic diagnostics
confirm the controller identity before interpreting manufacturer-specific data.
"""
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, date
from .transport import PicoTransport, TransportError
from .battery_status import battery_status, recovery_unavailable

WORDS = {0x03:"Battery mode",0x08:"Temperature",0x09:"Voltage",0x0A:"Current",
         0x0B:"Average current",0x0C:"Capacity error",0x0D:"State of charge",
         0x0F:"Remaining capacity",0x10:"Full charge capacity",0x11:"Run time to empty",
         0x12:"Average time to empty",0x13:"Average time to full",0x14:"Requested charge current",
         0x15:"Requested charge voltage",0x16:"Battery status",0x17:"Cycle count",
         0x18:"Design capacity",0x19:"Design voltage",0x1A:"Specification",
         0x1B:"Manufacture date",0x1C:"Serial number"}
TEXTS = {0x20:"manufacturer",0x21:"device",0x22:"chemistry"}
STATUS_FLAGS = {15:"Overcharge alarm",14:"Terminate charge alarm",12:"Overtemperature alarm",
                11:"Terminate discharge alarm",9:"Remaining capacity alarm",8:"Remaining time alarm"}


class BatteryError(RuntimeError):
    pass


class BatteryTransport(PicoTransport):
    def __init__(self, port, pins=(7,9), pullups=True, pec="auto", address=0x0B):
        if pins[0] == pins[1] or any(p not in (*range(23),26,27,28) for p in pins):
            raise ValueError("Select two different supported GPIOs")
        if not 8 <= address <= 0x77 or pec not in ("auto","on","off"):
            raise ValueError("Invalid SMBus address or PEC mode")
        self.opened = False
        self.address, self.pec_mode, self.pec = address, pec, False
        super().__init__(port, timeout=3)
        try:
            if not self.supports("SMBUS1"):
                raise BatteryError("This Pico firmware has no battery support. Install the matching new UF2 (SMBUS1).")
            answer = self.command(f"SMBOPEN {pins[0]} {pins[1]} {int(pullups)} 5")
            self.opened = True
            match = re.fullmatch(r"SMBOPEN SDA=(\d+) SCL=(\d+) DATA=([01]) CLOCK=([01])", answer)
            if not match or tuple(map(int,match.group(1,2))) != tuple(pins):
                raise TransportError("Invalid SMBus open acknowledgement")
            if match.group(3,4) != ("1","1"):
                raise BatteryError("SMBus is not idle HIGH. Check the pin mapping, common ground and pull-ups.")
        except Exception:
            try:
                self.close()
            except Exception:
                pass  # Preserve the actual connection failure.
            raise

    def close(self):
        if not self.port.is_open:
            return
        try:
            if self.opened and self._synchronized:
                if self.command("SMBCLOSE") != "OK":
                    raise TransportError("SMBus cleanup was not acknowledged")
        finally:
            self.opened = False
            super().close()

    def read_word(self, reg, pec=None):
        check = self.pec if pec is None else pec
        answer = self.command(f"SMBRW {self.address:02X} {reg:02X} {int(check)}")
        match = re.fullmatch(r"SMBWORD ([0-9A-F]{2}) ([0-9A-F]{4}) PEC=(OK|OFF)", answer)
        if not match or int(match[1],16) != reg or match[3] != ("OK" if check else "OFF"):
            self._synchronized = False
            raise TransportError("Invalid SMBus word response")
        return int(match[2],16)

    def read_block(self, reg):
        answer = self.command(f"SMBRB {self.address:02X} {reg:02X} {int(self.pec)}")
        match = re.fullmatch(r"SMBBLOCK ([0-9A-F]{2}) ((?:[0-9A-F]{2}){1,34}) PEC=(OK|OFF)", answer)
        if not match or int(match[1],16) != reg or match[3] != ("OK" if self.pec else "OFF"):
            self._synchronized = False
            raise TransportError("Invalid SMBus block response")
        if len(match[2]) > (68 if reg==0x44 else 64):
            self._synchronized = False
            raise TransportError("Oversized standard SMBus block response")
        return bytes.fromhex(match[2])

    def _write_word(self, reg, value):
        if not 0 <= value <= 0xFFFF:
            raise ValueError("SMBus word is outside 16 bits")
        if self.command(f"SMBWW {self.address:02X} {reg:02X} {value:04X} {int(self.pec)}") != "OK":
            raise TransportError("SMBus write was not acknowledged")

    def _write_block(self, reg, data):
        if not 1 <= len(data) <= 32:
            raise ValueError("SMBus block must contain 1–32 bytes")
        if self.command(f"SMBWB {self.address:02X} {reg:02X} {data.hex().upper()} {int(self.pec)}") != "OK":
            raise TransportError("SMBus block write was not acknowledged")

    def query_ti(self, subcommand):
        # Only documented read requests. Service writes are kept separate.
        if subcommand not in (0x0001,0x0002,0x0051,0x0053,0x0054,0x0071):
            raise BatteryError("Unsupported diagnostic query")
        self._write_block(0x44, subcommand.to_bytes(2,"little"))
        time.sleep(.003)
        data = self.read_block(0x44)
        if len(data) < 4 or int.from_bytes(data[:2],"little") != subcommand:
            raise BatteryError("Controller did not return the expected TI diagnostic response")
        return data[2:]

    def query_ti_legacy(self, subcommand):
        """Allowlisted TI diagnostic selector on 0x00, response on 0x23."""
        if subcommand not in (0x0001, 0x0002, 0x0051, 0x0053, 0x0054):
            raise BatteryError("Unsupported diagnostic query")
        self._write_word(0x00, subcommand)
        time.sleep(.01)
        return self.read_block(0x23)


def signed(value):
    return value - 65536 if value & 0x8000 else value


@dataclass
class Snapshot:
    timestamp: str
    words: dict
    strings: dict
    errors: dict
    pec: bool
    profile: str = "sbs"
    controller: dict = field(default_factory=dict)

    def raw(self, reg, default=0):
        return self.words.get(f"{reg:02X}", default)

    @property
    def identity(self):
        return (self.strings.get("manufacturer"),self.strings.get("device"),self.raw(0x1C),
                self.raw(0x18),self.raw(0x19))

    @property
    def metrics(self):
        spec = self.raw(0x1A)
        vscale, iscale = 10 ** ((spec >> 8)&15), 10 ** ((spec >> 12)&15)
        energy = bool(self.raw(0x03)&0x8000)
        design, full = self.raw(0x18,None), self.raw(0x10,None)
        voltage, current, temp = self.raw(0x09,None),self.raw(0x0A,None),self.raw(0x08,None)
        return {"voltage": voltage*vscale/1000 if voltage is not None else None,
                "current": signed(current)*iscale/1000 if current is not None else None,
                "temperature": temp/10-273.15 if temp is not None else None,
                "soc":self.raw(0x0D,None),"cycles":self.raw(0x17,None),
                "health":full/design*100 if full is not None and design else None,
                "design_capacity":design*iscale*(10 if energy else 1) if design is not None else None,
                "full_capacity":full*iscale*(10 if energy else 1) if full is not None else None,
                "remaining_capacity":self.raw(0x0F)*iscale*(10 if energy else 1) if self.raw(0x0F,None) is not None else None,
                "capacity_unit":"mWh" if energy else "mAh"}

    @property
    def manufacture_date(self):
        raw = self.raw(0x1B)
        try:
            return date(1980+(raw >> 9),(raw >> 5)&15,raw&31).isoformat()
        except ValueError:
            return "Not reported"

    def export(self):
        return dict(asdict(self),metrics=self.metrics,manufacture_date=self.manufacture_date,
                    battery_status=battery_status(self.controller),
                    findings=diagnose(self),capacity_note="Capacity and health are estimates reported by the battery controller; no controlled discharge test was performed.")


def read_snapshot(bus, profile="sbs", progress=lambda text: None):
    spec = bus.read_word(0x1A, pec=False)
    revision,version,vscale,iscale=spec&15,(spec>>4)&15,(spec>>8)&15,(spec>>12)&15
    if revision!=1 or version not in (1,2,3) or vscale>3 or iscale>3:
        raise BatteryError(f"Unsupported SBS specification/scaling word 0x{spec:04X}")
    bus.pec = bus.pec_mode == "on" or (bus.pec_mode == "auto" and version == 3)
    words,strings,errors = {},{},{}
    for reg,name in WORDS.items():
        progress(name)
        try:
            words[f"{reg:02X}"] = bus.read_word(reg)
        except TransportError as exc:
            # Transport loss or checksum failure must never become plausible data.
            if not bus._synchronized or "PEC" in str(exc) or reg in (0x03,0x09,0x16,0x18,0x1A,0x1C):
                raise
            errors[name] = str(exc)
    for reg,name in TEXTS.items():
        try:
            strings[name]=bus.read_block(reg).decode("ascii",errors="replace").rstrip("\0").strip()
        except TransportError as exc:
            if not bus._synchronized or "PEC" in str(exc):
                raise
            errors[name]=str(exc)
    if words["1A"] != spec:
        raise BatteryError("Battery specification changed during the read; reconnect")
    result=Snapshot(datetime.now(timezone.utc).isoformat(),words,strings,errors,bus.pec)
    if profile=="ti_bq40z50":
        result.controller=read_ti_diagnostics(bus)
        result.profile=profile
    elif profile in ("auto", "ti_bq"):
        from .battery_controllers import identify_controller
        result.profile = profile
        result.controller = identify_controller(bus, result, explicit=profile == "ti_bq")
        if result.controller.get("service_supported"):
            result.profile = "ti_bq40z50"
    return result


def read_ti_diagnostics(bus):
    device=bus.query_ti(0x0001)
    if len(device)!=2 or int.from_bytes(device,"little")!=0x4500:
        raise BatteryError("This battery did not identify as a TI bq40z50. No service command was sent.")
    fw=bus.query_ti(0x0002)
    if len(fw)!=11 or int.from_bytes(fw[:2],"big")!=0x4500:
        raise BatteryError("Invalid bq40z50 firmware identity")
    version=int.from_bytes(fw[2:4],"big")
    result={"name":"TI bq40z50","device_type":"4500","firmware":f"{version:04X}",
            "firmware_display":f"{version >> 8}.{version & 255:02X}",
            "firmware_raw":fw.hex().upper(),"service_supported":version>>8==3}
    if not result["service_supported"]:
        result["note"]="Firmware revision is outside the documented R3 service profile. Standard readings remain available."
        return result
    result["status_layout"] = "ti_bq40"
    result["recovery_supported"] = True
    for name,subcmd in (("operation",0x54),("safety",0x51),("permanent_failure",0x53)):
        data=bus.query_ti(subcmd)
        if len(data)!=4:
            raise BatteryError(f"Invalid TI {name} status length")
        result[name]=int.from_bytes(data,"little")
    result["security"]={1:"Full access",2:"Unsealed",3:"Sealed"}.get((result["operation"]>>8)&3,"Unknown")
    data=bus.query_ti(0x71)
    if len(data)!=32:
        raise BatteryError("Invalid TI cell diagnostic length")
    # Preserve cell positions; zero entries denote unused series inputs.
    result["cells_mV"]=[int.from_bytes(data[i:i+2],"little") for i in range(0,8,2)]
    cells=[v for v in result["cells_mV"] if v]
    result["imbalance_mV"]=max(cells)-min(cells) if cells else None
    return result


def service(bus, action, expected, keys=None):
    if expected is None or action not in ("seal","unseal","full_access","clear_pf"):
        raise BatteryError("Read the supported battery before choosing a service action")
    if action == "clear_pf" and (expected.profile != "ti_bq40z50" or
            expected.controller.get("device_type") != "4500" or
            not expected.controller.get("recovery_supported")):
        raise BatteryError("PF recovery is not implemented for this controller/firmware")
    current=read_snapshot(bus)
    if current.identity != tuple(expected.identity):
        raise BatteryError("Battery identity changed. Read the connected battery before any service operation.")
    if not current.pec:
        raise BatteryError("Service requires the identified bq40z50-R3 profile and verified PEC")
    current.controller=read_ti_diagnostics(bus)
    current.profile="ti_bq40z50"
    chip=current.controller
    if not chip.get("service_supported") or not current.pec:
        raise BatteryError("Service requires the identified bq40z50-R3 profile and verified PEC")
    if action == "clear_pf":
        return recover_pf(bus, current, keys)
    if action=="seal":
        bus._write_word(0x00,0x0030)
        expected_state="Sealed"
    elif action in ("unseal","full_access"):
        if not keys or len(keys)!=2 or any(not 0<=v<=0xFFFF for v in keys):
            raise BatteryError("Enter the two 16-bit key words supplied for this battery")
        if action=="full_access" and chip["security"]!="Unsealed":
            raise BatteryError("Unseal this battery before requesting full access")
        if action=="unseal" and chip["security"]!="Sealed":
            raise BatteryError("Unseal requires a currently sealed battery")
        # No automatic key guesses or retries; the pair stays within one worker.
        bus._write_word(0x00,keys[0]);bus._write_word(0x00,keys[1])
        expected_state="Unsealed" if action=="unseal" else "Full access"
    else:
        raise BatteryError("Unsupported service action")
    time.sleep(.05)
    after=read_snapshot(bus,"ti_bq40z50")
    if after.identity!=current.identity or after.controller.get("security")!=expected_state:
        raise BatteryError("Controller did not confirm the requested security state. No key retry was attempted.")
    return after


def recover_pf(bus, current, keys):
    """R3 recovery; never replay reset/key writes or disable protection.

    TI SLUUBU5A 15.1.25/15.1.35: reset stored PF data, then reset the IC.
    Only a fresh post-reset operational status can confirm a recovered battery.
    """
    chip = current.controller
    if (chip.get("device_type"), chip.get("firmware", "")[:2]) != ("4500", "03"):
        raise BatteryError("PF recovery requires the documented bq40z50-R3 profile")
    reason = recovery_unavailable(chip)
    if reason:
        raise BatteryError(reason)
    key_pairs = keys if isinstance(keys, dict) else {}
    stages = ("unseal", "full_access") if chip["security"] == "Sealed" else (
        ("full_access",) if chip["security"] == "Unsealed" else ())
    # Validate every required pair before changing controller access.
    for stage in stages:
        pair = key_pairs.get(stage)
        if not pair or len(pair) != 2 or any(type(v) is not int or not 0 <= v <= 0xFFFF for v in pair):
            raise BatteryError(f"The battery's two {stage.replace('_', ' ')} key words are required")
    before = current.export()
    for stage in stages:
        for value in key_pairs[stage]:
            bus._write_word(0x00, value)
        time.sleep(.05)
        chip = read_ti_diagnostics(bus)
        if chip.get("security") != {"unseal": "Unsealed", "full_access": "Full access"}[stage]:
            raise BatteryError("Controller did not confirm service access. No PF reset or key retry was sent.")
    # Recheck pack and firmware after service access changes, before clearing data.
    fresh = read_snapshot(bus)
    if fresh.identity != current.identity or not fresh.pec:
        raise BatteryError("Battery identity or PEC changed before PF recovery")
    chip = read_ti_diagnostics(bus)
    if (chip.get("device_type"), chip.get("firmware")) != (
            current.controller.get("device_type"), current.controller.get("firmware")):
        raise BatteryError("Controller identity changed before PF recovery")
    reason = recovery_unavailable(chip)
    if reason or chip.get("security") != "Full access":
        raise BatteryError(reason or "Full access is required for PF recovery")
    bus._write_word(0x00, 0x0029)
    bus._write_word(0x00, 0x0041)
    time.sleep(.5)
    after = read_snapshot(bus, "ti_bq40z50")
    if after.identity != current.identity or battery_status(after.controller)["state"] != "unlocked":
        raise BatteryError("PF recovery was not confirmed. Read battery again; no reset retry was sent.")
    after.controller["recovery"] = {"method": "PF data reset + device reset",
                                     "before": before, "verified": True}
    return after


def diagnose(snapshot):
    findings=[]
    status=snapshot.raw(0x16)
    for bit,name in STATUS_FLAGS.items():
        if status&(1<<bit): findings.append({"level":"warning","text":name})
    if not status&0x80: findings.append({"level":"warning","text":"Gauge is not initialized; capacity estimates may be unreliable."})
    if status&15: findings.append({"level":"warning","text":f"SBS device error code {status&15}"})
    health=snapshot.metrics["health"]
    if health is not None and health<80:
        findings.append({"level":"info","text":f"Reported full capacity is {health:.0f}% of design capacity. This is a gauge estimate."})
    chip=snapshot.controller
    if chip.get("permanent_failure"):
        findings.append({"level":"warning","text":f"Permanent-failure flags active: 0x{chip['permanent_failure']:08X}. Investigate the cause before recovery."})
    if chip.get("safety"):
        findings.append({"level":"warning","text":f"Protection flags active: 0x{chip['safety']:08X}."})
    if chip.get("operation",0)&(1<<14): findings.append({"level":"info","text":"BMS reports charging disabled."})
    if chip.get("operation",0)&(1<<13): findings.append({"level":"info","text":"BMS reports discharging disabled."})
    if not snapshot.pec: findings.append({"level":"info","text":"These readings have no PEC checksum validation."})
    if snapshot.errors: findings.append({"level":"info","text":f"{len(snapshot.errors)} optional values were not reported."})
    if not findings: findings.append({"level":"success","text":"No alarm flags reported by the battery. Load capacity has not been tested."})
    return findings
