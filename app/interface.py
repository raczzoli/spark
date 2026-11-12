# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Discover our USB firmware without issuing commands to an attached target."""
from dataclasses import dataclass
import time

from serial.tools import list_ports
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from .transport import PicoTransport, TransportError


BOARD_NAMES = {
    "pico": "Pico (RP2040)", "pico_w": "Pico W (RP2040)",
    "pico2": "Pico 2 (RP2350)", "pico2_w": "Pico 2 W (RP2350)",
    "waveshare_rp2040_zero": "Waveshare RP2040 Zero",
    "waveshare_rp2350_tiny": "Waveshare RP2350 Tiny",
    "waveshare_rp2350_zero": "Waveshare RP2350 Zero",
    "waveshare_rp2350_usb_a": "Waveshare RP2350 USB-A",
    "seeed_xiao_rp2040": "Seeed XIAO RP2040",
    "seeed_xiao_rp2350": "Seeed XIAO RP2350",
}


@dataclass(frozen=True)
class UsbCandidate:
    port: str
    vid: int = 0x2E8A
    pid: int = 0x000A
    serial: str = ""
    location: str = ""

    @property
    def supported_usb(self):
        # Default Pico SDK CDC IDs used by our RP2040 and RP2350 builds.
        return self.vid == 0x2E8A and self.pid in (0x000A, 0x0009)


@dataclass(frozen=True)
class DetectedInterface:
    usb: UsbCandidate
    board: str = ""
    version: str = ""
    build: str = ""

    @property
    def name(self):
        return BOARD_NAMES.get(self.board, self.board.replace("_", " ") if self.board
                               else "Pico · model not reported")


def usb_inventory():
    """Inspect USB metadata only. Never open ordinary COM/Bluetooth ports."""
    devices = [UsbCandidate(p.device, p.vid, p.pid, p.serial_number or "", p.location or "")
               for p in list_ports.comports()]
    return sorted((p for p in devices if p.supported_usb), key=lambda p: p.port)


def parse_identity(usb, info):
    if info == "INFO legacy firmware":
        return DetectedInterface(usb)
    if not info.startswith("INFO "):
        raise TransportError("Invalid firmware identity")
    fields = dict(part.split("=", 1) for part in info.split()[1:] if "=" in part)
    board = fields.get("BOARD", "")
    if not board or len(board) > 80 or not all(c.isalnum() or c == "_" for c in board):
        raise TransportError("Firmware did not report a valid board model")
    return DetectedInterface(usb, board, fields.get("VERSION", ""), fields.get("BUILD", ""))


class DiscoveryTransport(PicoTransport):
    COMMAND_TIMEOUTS = {"CAPS": 1, "INFO": 1}


class InterfaceProbe(QObject):
    finished = Signal(str, object)
    failed = Signal(str)
    action = "interface_probe"

    def __init__(self, candidate):
        super().__init__()
        self.candidate = candidate

    @Slot()
    def run(self):
        try:
            if not self.candidate.supported_usb:
                raise TransportError("Unsupported USB identity")
            # Generic transport closes USB only: no RELEASE, pin setup, EC or SMBus IO.
            with DiscoveryTransport(self.candidate.port, timeout=1) as link:
                device = parse_identity(self.candidate, link.firmware_info())
            self.finished.emit(self.action, device)
        except Exception as exc:
            self.failed.emit(str(exc))


class InterfaceState(QObject):
    """Confirmed interface shared by both tools; generation invalidates old results."""
    changed = Signal()
    status_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.device = None
        self.generation = 0
        self.status = "Not connected"
        self.detail = "Connect a Pico running the supplied firmware. Detection is automatic."

    def currentData(self):
        return self.device.usb.port if self.device else None

    def set_status(self, status, detail=""):
        self.status, self.detail = status, detail
        self.status_changed.emit()

    def set_device(self, device):
        if self.device == device:
            return
        self.device = device
        self.generation += 1
        self.status = "Connected" if device else "Not connected"
        self.detail = (f"Board: {device.board or 'not reported'}\n"
                       f"Firmware: {device.version or 'legacy'} · {device.build or 'build not reported'}\n"
                       f"USB serial: {device.usb.serial or 'not reported'}" if device else
                       "Connect a Pico running the supplied firmware. Detection is automatic.")
        self.changed.emit()
        self.status_changed.emit()


class InventoryWorker(QObject):
    found = Signal(object)
    failed = Signal(str)

    def __init__(self, inventory):
        super().__init__()
        self.inventory = inventory

    @Slot()
    def scan(self):
        try:
            self.found.emit(self.inventory())
        except Exception as exc:
            self.failed.emit(str(exc))


class InterfaceDiscovery(QObject):
    """Poll USB inventory off the UI thread; serialize identification with tool IO."""
    scan_requested = Signal()
    stopped = Signal()

    def __init__(self, state, controller, settings, allowed, parent=None,
                 inventory=usb_inventory, probe_factory=InterfaceProbe):
        super().__init__(parent)
        self.state, self.controller, self.settings = state, controller, settings
        self.allowed, self.inventory, self.probe_factory = allowed, inventory, probe_factory
        self.active = False
        self.thread = None
        self.scanning = False
        self.candidates = []
        self.retry_after = {}
        self.probing = None
        self.probe_valid = False
        self.timer = QTimer(self)
        self.timer.setInterval(800)
        self.timer.timeout.connect(self.request_scan)
        controller.idle.connect(self.maybe_probe)

    def start(self):
        if self.thread is not None:
            return
        self.active = True
        self.thread = QThread(self)
        self.worker = InventoryWorker(self.inventory)
        self.worker.moveToThread(self.thread)
        self.scan_requested.connect(self.worker.scan)
        self.worker.found.connect(self.update_inventory)
        self.worker.failed.connect(self.inventory_failed)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()
        self.timer.start()
        self.request_scan()

    def stop(self):
        self.active = False
        self.timer.stop()
        if self.thread is not None:
            self.thread.quit()

    @Slot()
    def _thread_finished(self):
        self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.scanning = False
        self.stopped.emit()

    def request_scan(self):
        if self.active and not self.scanning:
            self.scanning = True
            self.scan_requested.emit()

    @Slot(object)
    def update_inventory(self, devices):
        self.scanning = False
        if not self.active:
            return
        self.candidates = [d for d in devices if d.supported_usb]
        if self.probing is not None and self.probing not in self.candidates:
            self.probe_valid = False
        self.retry_after = {d: t for d, t in self.retry_after.items() if d in self.candidates}
        if self.state.device and self.state.device.usb not in self.candidates:
            self.state.set_device(None)
        if not self.candidates and not self.state.device:
            self.state.set_status("Not connected", "Connect a Pico running the supplied firmware.")
        self.maybe_probe()

    @Slot(str)
    def inventory_failed(self, message):
        self.scanning = False
        if self.active:
            # An enumeration error does not prove an existing USB device vanished.
            self.state.set_status(self.state.status, f"USB detection will retry: {message}")

    @Slot()
    def maybe_probe(self):
        if (not self.active or self.state.device or self.probing is not None or
                self.controller.busy or not self.allowed()):
            return
        now = time.monotonic()
        serial = self.settings.value("interface/serial", "")
        port = self.settings.value("interface/port", "")
        available = sorted(self.candidates, key=lambda d: (not (serial and d.serial == serial),
                                                          d.port != port, d.port))
        candidate = next((d for d in available if self.retry_after.get(d, 0) <= now), None)
        if candidate is None:
            return
        worker = self.probe_factory(candidate)
        worker.finished.connect(self.probe_finished)
        worker.failed.connect(self.probe_failed)
        self.probing = candidate
        self.probe_valid = True
        self.state.set_status("Checking…", f"Identifying firmware on {candidate.port}.")
        if not self.controller.start(worker):
            self.probing = None
            worker.deleteLater()

    @Slot(str, object)
    def probe_finished(self, action, device):
        candidate, self.probing = self.probing, None
        if self.active and self.probe_valid and candidate == device.usb and candidate in self.candidates:
            self.retry_after.pop(candidate, None)
            self.state.set_device(device)

    @Slot(str)
    def probe_failed(self, message):
        candidate, self.probing = self.probing, None
        if not self.active or candidate not in self.candidates:
            return
        self.retry_after[candidate] = time.monotonic() + 5
        self.state.set_status("Not connected", f"{candidate.port}: {message}\n"
                              "Use the supplied firmware; close other apps using this Pico. Retrying automatically.")
