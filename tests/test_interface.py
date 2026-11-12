"""USB identification uses metadata only and never overlaps a tool operation."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication

from app.controller import OperationController
from app.interface import (BOARD_NAMES, DetectedInterface, InterfaceDiscovery,
                           InterfaceProbe, InterfaceState, UsbCandidate,
                           parse_identity, usb_inventory)
from app.transport import TransportError
from tests.test_transport import FakePort


class RecordingController(QObject):
    idle = Signal()

    def __init__(self):
        super().__init__()
        self.busy = False
        self.worker = None
        self.started = []

    def start(self, worker):
        if self.busy:
            return False
        self.busy, self.worker = True, worker
        self.started.append(worker)
        return True

    def finish(self, success=True):
        worker = self.worker
        if success:
            worker.finished.emit("interface_probe", DetectedInterface(worker.candidate, "pico_w"))
        else:
            worker.failed.emit("Port is busy")
        self.busy, self.worker = False, None
        self.idle.emit()


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = QSettings(str(Path(self.temp.name) / "test.ini"), QSettings.Format.IniFormat)
        self.state = InterfaceState()
        self.controller = RecordingController()
        self.allowed = True
        self.discovery = InterfaceDiscovery(self.state, self.controller, self.settings,
                                            lambda: self.allowed)
        # Deterministic inventory events; no physical USB or timer in these tests.
        self.discovery.active = True
        self.pico = UsbCandidate("COM9", serial="unit-1", location="usb-1")

    def test_inventory_filters_uart_bluetooth_micropython_and_bootloader(self):
        devices = [SimpleNamespace(device=port, vid=vid, pid=pid, serial_number="s", location="u")
                   for port, vid, pid in (("COM1", None, None), ("COM2", 0x1A86, 0x7523),
                                          ("COM3", 0x2E8A, 5), ("COM4", 0x2E8A, 3),
                                          ("COM9", 0x2E8A, 10), ("COM10", 0x2E8A, 9))]
        with patch("app.interface.list_ports.comports", return_value=devices), patch("app.transport.serial.Serial") as serial:
            found = usb_inventory()
        self.assertEqual({p.port for p in found}, {"COM9", "COM10"})
        serial.assert_not_called()

    def test_metadata_preserves_all_board_names_and_does_not_guess_legacy_model(self):
        for board, name in BOARD_NAMES.items():
            info = parse_identity(self.pico, f"INFO VERSION=0.4.0 BUILD=abc BOARD={board} I2C_DELAY_US=5")
            self.assertEqual(info.name, name)
            self.assertEqual((info.version, info.build), ("0.4.0", "abc"))
        self.assertIn("model not reported", parse_identity(self.pico, "INFO legacy firmware").name)
        for invalid in ("OK", "INFO VERSION=1", "INFO BOARD=<bad>"):
            with self.assertRaises(TransportError):
                parse_identity(self.pico, invalid)

    def test_probe_sends_only_hello_caps_info_and_closes_without_release(self):
        port = FakePort()
        port.replies += [b"CAPS INFO TAGGED SMBUS1\n", b"@00000002 INFO VERSION=0.4.0 BUILD=abc BOARD=pico_w\n"]
        result, failed = [], []
        probe = InterfaceProbe(self.pico)
        probe.finished.connect(lambda action, device: result.append(device))
        probe.failed.connect(failed.append)
        with patch("app.transport.serial.Serial", return_value=port), patch("app.transport.secrets.randbits", return_value=0):
            probe.run()
        self.assertEqual(failed, [])
        self.assertEqual(result[0].name, "Pico W (RP2040)")
        self.assertEqual(port.written, [b"HELLO\n", b"CAPS\n", b"@00000002 INFO\n"])
        self.assertFalse(port.is_open)

    def test_probe_supports_legacy_and_rejects_foreign_firmware(self):
        for replies, successful in (([b"OK PICO_ITE_EC_PROGRAMMER 2\n", b"ERR COMMAND\n"], True),
                                    ([b"Unrelated device\n"], False)):
            port = FakePort()
            port.replies = list(replies)
            result, failed = [], []
            probe = InterfaceProbe(self.pico)
            probe.finished.connect(lambda action, device: result.append(device))
            probe.failed.connect(failed.append)
            with patch("app.transport.serial.Serial", return_value=port):
                probe.run()
            self.assertEqual(bool(result), successful)
            self.assertEqual(bool(failed), not successful)
            self.assertFalse(port.is_open)
            self.assertNotIn(b"RELEASE\n", port.written)

    def test_probe_rejects_unrelated_usb_before_opening_it(self):
        probe = InterfaceProbe(UsbCandidate("COM1", None, None))
        with patch("app.transport.serial.Serial") as serial:
            probe.run()
        serial.assert_not_called()

    def test_startup_already_connected_requires_successful_handshake(self):
        self.discovery.update_inventory([self.pico])
        self.assertIsNone(self.state.currentData())
        self.assertEqual(self.state.status, "Checking…")
        self.controller.finish()
        self.assertEqual(self.state.currentData(), "COM9")
        self.assertEqual(self.state.status, "Connected")

    def test_arrival_detach_and_replug_on_different_com(self):
        self.discovery.update_inventory([])
        self.assertEqual(self.controller.started, [])
        self.discovery.update_inventory([self.pico])
        self.controller.finish()
        generation = self.state.generation
        self.discovery.update_inventory([])
        self.assertIsNone(self.state.currentData())
        self.assertGreater(self.state.generation, generation)
        replacement = UsbCandidate("COM12", serial="unit-1")
        self.discovery.update_inventory([replacement])
        self.controller.finish()
        self.assertEqual(self.state.currentData(), "COM12")

    def test_discovery_waits_for_usb_owner_and_still_detects_detach_while_busy(self):
        self.controller.busy = True
        self.discovery.update_inventory([self.pico])
        self.assertEqual(self.controller.started, [])
        self.controller.busy = False
        self.controller.idle.emit()
        self.controller.finish()
        self.controller.busy = True  # EC/battery worker owns the device now.
        self.discovery.update_inventory([])
        self.assertIsNone(self.state.currentData())
        self.discovery.update_inventory([self.pico])
        self.assertEqual(len(self.controller.started), 1)

    def test_no_probe_while_pending_operation_or_shutdown_gate_is_closed(self):
        self.allowed = False
        self.discovery.update_inventory([self.pico])
        self.assertEqual(self.controller.started, [])
        self.allowed = True
        self.discovery.update_inventory([self.pico])
        self.assertEqual(len(self.controller.started), 1)

    def test_confirmed_device_is_sticky_and_does_not_get_reprobed_on_each_poll(self):
        self.discovery.update_inventory([self.pico])
        self.controller.finish()
        another = UsbCandidate("COM8", serial="other")
        for _ in range(3):
            self.discovery.update_inventory([another, self.pico])
        self.assertEqual(len(self.controller.started), 1)
        self.assertEqual(self.state.currentData(), "COM9")

    def test_saved_usb_serial_has_priority_when_com_number_changes(self):
        self.settings.setValue("interface/serial", "unit-1")
        self.settings.setValue("interface/port", "COM3")
        other = UsbCandidate("COM3", serial="other")
        self.discovery.update_inventory([other, self.pico])
        self.assertEqual(self.controller.worker.candidate, self.pico)

    def test_busy_or_incompatible_port_retries_with_backoff_and_checks_next_pico(self):
        other = UsbCandidate("COM8", serial="other")
        self.discovery.update_inventory([self.pico, other])
        self.controller.finish(success=False)
        self.assertEqual(self.controller.worker.candidate, self.pico)
        self.controller.finish(success=False)
        self.assertIsNone(self.state.currentData())
        self.discovery.update_inventory([self.pico, other])
        self.assertEqual(len(self.controller.started), 2)
        with patch("app.interface.time.monotonic", return_value=time.monotonic() + 6):
            self.discovery.update_inventory([self.pico, other])
        self.assertEqual(len(self.controller.started), 3)

    def test_late_probe_after_detach_and_identical_replug_is_discarded(self):
        self.discovery.update_inventory([self.pico])
        worker = self.controller.worker
        self.discovery.update_inventory([])
        self.discovery.update_inventory([self.pico])
        worker.finished.emit("interface_probe", DetectedInterface(self.pico, "pico_w"))
        self.assertIsNone(self.state.currentData())

    def test_inventory_failure_does_not_invent_a_disconnect(self):
        self.discovery.update_inventory([self.pico])
        self.controller.finish()
        self.discovery.inventory_failed("Windows enumeration temporarily failed")
        self.assertEqual(self.state.currentData(), "COM9")

    def test_stopped_discovery_ignores_pending_inventory_and_probe_results(self):
        self.discovery.update_inventory([self.pico])
        self.discovery.stop()
        self.controller.finish()
        self.discovery.update_inventory([self.pico])
        self.assertIsNone(self.state.currentData())

    def test_inventory_runs_off_ui_thread_and_stops_cleanly(self):
        started, release = threading.Event(), threading.Event()
        threads = []

        def blocking_inventory():
            threads.append(threading.get_ident())
            started.set()
            release.wait(3)
            return []

        controller = OperationController()
        watcher = InterfaceDiscovery(InterfaceState(), controller, self.settings,
                                     lambda: True, inventory=blocking_inventory)
        watcher.start()
        try:
            self.assertTrue(started.wait(2))
            self.assertNotEqual(threads, [threading.get_ident()])
            watcher.stop()
        finally:
            release.set()
            deadline = time.monotonic() + 3
            while watcher.thread is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.001)
        self.assertIsNone(watcher.thread)
        self.assertFalse(controller.busy)


if __name__ == "__main__":
    unittest.main()
