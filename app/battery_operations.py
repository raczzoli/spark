# SPDX-License-Identifier: GPL-2.0-or-later
"""All battery USB work runs under the application's shared operation owner."""
from PySide6.QtCore import QObject, Signal, Slot
from .battery import BatteryTransport, read_snapshot, service


class BatteryWorker(QObject):
    finished = Signal(str, object)
    failed = Signal(str)
    status = Signal(str)
    warning = Signal(str)

    def __init__(self, action, port, pins, pullups=True, pec="auto", address=0x0B,
                 profile="sbs", expected=None, keys=None):
        super().__init__()
        self.action = action
        self.port,self.pins,self.pullups,self.pec,self.address=port,pins,pullups,pec,address
        self.profile,self.expected,self.keys=profile,expected,keys

    @Slot()
    def run(self):
        bus=None
        result=error=cleanup=None
        try:
            bus=BatteryTransport(self.port,self.pins,self.pullups,self.pec,self.address)
            if self.action in ("battery_read","battery_poll"):
                result=read_snapshot(bus,self.profile,self.status.emit)
                if self.expected is not None and result.identity!=self.expected.identity:
                    raise RuntimeError("A different battery is connected. Stop monitoring and read it as a new battery.")
            else:
                result=service(bus,self.action.removeprefix("battery_"),self.expected,self.keys)
        except Exception as exc:
            # Serial payloads may include key material; never include a command in logs.
            error=f"{type(exc).__name__}: {exc}"
        finally:
            self.keys=None
            if bus is not None:
                try: bus.close()
                except Exception as exc: cleanup=f"Battery interface cleanup failed: {exc}. Reconnect before continuing."
        if error is not None: self.failed.emit(error)
        elif cleanup is not None: self.failed.emit(cleanup)
        else: self.finished.emit(self.action,result)
