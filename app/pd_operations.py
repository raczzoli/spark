# SPDX-License-Identifier: GPL-2.0-or-later
"""PD operations on the shared USB worker, including complete verification."""
import hashlib
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from .pd import PDTransport, PDDevice, PDConnection, PDError


class PDWorker(QObject):
    finished = Signal(str, object)
    failed = Signal(str)
    phase = Signal(str)
    transfer = Signal(object, object)
    status = Signal(str)

    def __init__(self, action, port, pins, address, size, expected=None, image_path=None):
        super().__init__()
        self.action, self.port, self.pins = action, port, pins
        self.address, self.size = address, size
        self.expected, self.image_path = expected, image_path

    def stage(self, name, operation):
        self.phase.emit(name)
        self.transfer.emit(0, self.size)
        return operation()

    @Slot()
    def run(self):
        destructive = False
        try:
            if self.action != "pd_connect":
                PDDevice.validate_range(self.size)
            image = None
            if self.action == "pd_write":
                image = Path(self.image_path).read_bytes()
                if len(image) != self.size:
                    raise PDError(f"Image has {len(image)} bytes; selected flash size is {self.size} bytes")
                self.status.emit(f"Image SHA-256: {hashlib.sha256(image).hexdigest()}")
            with PDTransport(self.port, self.pins, self.address) as bus:
                pd = PDDevice(bus)
                identity = pd.identify()
                if self.expected is not None and identity.fingerprint != self.expected.fingerprint:
                    raise PDError("Connected controller changed; identify it again before continuing")
                if self.action == "pd_connect":
                    pd.read_block(0)
                    result = PDConnection(identity, bus.address)
                elif self.action == "pd_read":
                    data = self.stage("Read", lambda: pd.read_flash(self.size, self.transfer.emit))
                    self.status.emit(f"Read SHA-256: {hashlib.sha256(data).hexdigest()}")
                    result = identity, data
                elif self.action in ("pd_write", "pd_erase"):
                    # Confirm read access before changing any flash contents.
                    pd.read_block(0)
                    destructive = True
                    self.stage("Erase", lambda: pd.erase_flash(self.size, self.transfer.emit))
                    if image is not None:
                        self.stage("Programming", lambda: pd.write_flash(image, self.transfer.emit))
                    self.stage("Verification", lambda: pd.verify_flash(
                        image if image is not None else b"\xff" * self.size, self.transfer.emit))
                    result = identity
                else:
                    raise ValueError(f"Unknown PD action: {self.action}")
            self.finished.emit(self.action, result)
        except Exception as exc:
            prefix = "Flash operation stopped after erase began. Restore a complete image before powering off. " if destructive else ""
            self.failed.emit(prefix + str(exc))
