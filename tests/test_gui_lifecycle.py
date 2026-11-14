# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from PySide6.QtCore import QSettings, QThread, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from app.gui import Window
from app.interface import DetectedInterface, UsbCandidate
from app.ene import EneFlashProtocol


class GuiLifecycleTests(unittest.TestCase):
    def test_ite5_connect_exposes_all_flash_operations_without_status_labels(self):
        from app.flash_protocols import protocol_for
        for family, chip in (("IT51xx", 0x5122), ("IT55xx", 0x5570), ("IT51xx", 0x51526)):
            self.window.model.setCurrentText(family)
            identity = (chip, 2)
            protocol = protocol_for(identity, bytes.fromhex("FFFFFE"))
            self.window.on_finished("connect", (identity, True, protocol))
            self.assertTrue(self.window.read.isEnabled())
            self.assertTrue(self.window.write.isEnabled())
            self.assertTrue(self.window.erase.isEnabled())
            self.assertIn(f"CHIP ID 0x{chip:04X}", self.window.identity_details.text())
            self.assertNotIn("experimental", self.window.identity_details.text().lower())
            self.assertNotIn("untested", self.window.identity_details.text().lower())

    def test_kb9548_connect_exposes_read_write_and_full_image_size(self):
        self.window.manufacturer.setCurrentText("ENE")
        self.window.model.setCurrentText("KB9548QF2")
        self.assertEqual(self.window.flash_size.value(), 160)
        self.assertFalse(self.window.flash_size.isEnabled())
        identity = (0xA0, 0x07)
        self.window.on_finished("connect", (identity, False, EneFlashProtocol("KB9548QF2", identity)))
        self.assertTrue(self.window.read.isEnabled())
        self.assertTrue(self.window.write.isEnabled())
        self.assertTrue(self.window.erase.isEnabled())
        self.assertIn("KB9548QF2", self.window.identity.text())

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = QSettings(str(Path(self.temp.name) / "ui.ini"), QSettings.Format.IniFormat)
        self.window = Window(settings=settings, auto_discovery=False)
        self.window.port.set_device(DetectedInterface(UsbCandidate("SIMULATED"), "pico_w"))
        self.window.manufacturer.setCurrentText("ITE")
        self.window.model.setCurrentText("IT8xxx")
        self.window.flash_size.setValue(256)
        self.window.connected_identity = (0x8227, 3)
        self.window.connected_protocol = SimpleNamespace(name="test", program_method="aai_v2")
        self.window.update_buttons()

    def tearDown(self):
        self.window.reset_identity()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_keepalive_owns_usb_off_gui_thread(self):
        calls = []
        class Session:
            def __init__(self, *args):
                pass
            def refresh(self, identity):
                calls.append(("refresh", QThread.currentThread() == QApplication.instance().thread()))
                return identity
            def close(self):
                calls.append(("close", QThread.currentThread() == QApplication.instance().thread()))
        status = self.window.status.text()
        with patch("app.operations.DeviceSession", Session):
            self.window.refresh_debug_hold()
            deadline = time.monotonic() + 5
            while self.window.controller.thread is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.001)
        self.assertIsNone(self.window.controller.thread)
        self.assertEqual(calls, [("refresh", False), ("close", False)])
        self.assertEqual(self.window.status.text(), status)
        self.assertTrue(self.window.write.isEnabled())

    def test_failure_invalidates_all_flash_buttons(self):
        self.window.controller.worker = SimpleNamespace(action="read")
        self.window.on_failed("USB disconnected")
        self.assertEqual(self.window.status.text(), "Read failed - check the USB connection")
        self.assertIsNone(self.window.connected_identity)
        self.assertFalse(self.window.read.isEnabled())
        self.assertFalse(self.window.write.isEnabled())
        self.assertFalse(self.window.erase.isEnabled())
        self.assertFalse(self.window.keepalive.isActive())

    def test_power_cycle_prompt_closes_when_operation_fails(self):
        self.window.controller.worker = SimpleNamespace(action="connect")
        self.window.show_power_cycle_prompt()
        self.assertIsNotNone(self.window.power_prompt)
        self.window.on_failed("No ACK")
        self.assertEqual(self.window.status.text(), "Connection failed - EC did not respond")
        self.assertIsNone(self.window.power_prompt)

    def test_flash_operation_waits_for_keepalive_started_during_dialog(self):
        def confirm(*args):
            self.window.controller.thread = Mock()
            self.window.controller.worker = SimpleNamespace(action="keepalive")
            return QMessageBox.StandardButton.Yes
        with patch("app.gui.QMessageBox.question", side_effect=confirm):
            self.window.start("erase")
        self.assertEqual(self.window.controller.worker.action, "keepalive")
        self.assertEqual(self.window._pending_operation, ("erase", None))
        with patch.object(self.window, "start") as start:
            self.window.controller._on_thread_finished()
            start.assert_called_once_with("erase", None, confirmed=True)
        self.assertIsNone(self.window._pending_operation)

    def test_ene_models_fixed_size_and_buttons(self):
        self.window.manufacturer.setCurrentText("ENE")
        self.assertEqual([self.window.model.itemText(i) for i in range(self.window.model.count())],
                         ["KB9012QF", "KB9022Q", "KB9028Q", "KB902FQ C", "KB9052QD", "KB9548QF2"])
        for family in ("KB9012QF", "KB9022Q", "KB9028Q", "KB902FQ C", "KB9052QD"):
            self.window.model.setCurrentText(family)
            self.assertEqual(self.window.flash_size.value(), 128)
            self.assertFalse(self.window.flash_size.isEnabled())
        self.window.model.setCurrentText("KB9052QD")
        self.assertEqual(self.window.flash_size.value(), 128)
        self.assertFalse(self.window.flash_size.isEnabled())
        identity = (0xD0, 0x0B)
        protocol = EneFlashProtocol("KB9052QD", identity)
        self.window.on_finished("connect", (identity, False, protocol))
        self.assertTrue(self.window.read.isEnabled())
        self.assertTrue(self.window.write.isEnabled())
        self.assertTrue(self.window.erase.isEnabled())
        self.assertIn("KB9052QD", self.window.identity.text())
        self.assertEqual("HW 0xD0  /  EDI 0x0B", self.window.identity_details.text())
        self.assertIn("128 KiB (model default)", self.window.identity.text())
        self.assertFalse(self.window.keepalive.isActive())
        # Busy/idle transitions must not accidentally unlock a fixed size.
        self.window.controller.thread = Mock()
        self.window.update_buttons()
        self.window.controller.thread = None
        self.window.update_buttons()
        self.assertFalse(self.window.flash_size.isEnabled())
        self.window.flash_size.setValue(160)
        self.assertEqual(self.window.flash_size_bytes(), 128*1024)
        self.window.manufacturer.setCurrentText("ITE")
        self.assertIsNone(self.window.model.currentData())
        self.assertFalse(self.window.detect.isEnabled())
        self.window.model.setCurrentText("IT8xxx")
        self.assertTrue(self.window.flash_size.isEnabled())
        self.assertEqual(self.window.flash_size.value(), 256)
        self.assertIsNone(self.window.connected_identity)

    def test_ite_numeric_input_rejects_unsupported_ranges_and_uses_bytes(self):
        self.window.flash_size.setValue(160)
        self.assertFalse(self.window.read.isEnabled())
        self.assertFalse(self.window.write.isEnabled())
        self.assertFalse(self.window.erase.isEnabled())
        self.assertIn("unsupported size", self.window.identity.text())
        self.window.flash_size.setValue(128)
        self.assertTrue(self.window.read.isEnabled())
        self.assertTrue(self.window.write.isEnabled())
        self.assertEqual(self.window.flash_size_bytes(), 128*1024)
        self.window.flash_size.stepUp()
        self.assertEqual(self.window.flash_size_bytes(), 192*1024)

    def test_model_pinout_and_phase_colors(self):
        self.window.manufacturer.setCurrentText("ENE")
        self.assertEqual(self.window.ene_wiring.text(), "")
        self.assertIsNone(self.window.create_wiring_dialog())
        for model in ("KB9012QF", "KB9022Q", "KB9028Q", "KB902FQ C", "KB9052QD"):
            self.window.model.setCurrentText(model)
            self.assertIn("View wiring diagram", self.window.ene_wiring.text())
            from app.wiring_diagram import WiringDiagram
            dialog = self.window.create_wiring_dialog()
            diagram = dialog.findChild(WiringDiagram)
            self.assertEqual(diagram.model.name, model)
            self.assertIn("GP4 = EC pin 62", diagram.accessibleName())
            self.assertIn("EC pin 42 (KSO3)", diagram.accessibleName())
            dialog.deleteLater()
        for phase, color in (("Read", "#15803d"), ("Erase", "#dc2626"),
                             ("Programming", "#ea580c"), ("Verification", "#15803d")):
            self.window.set_progress_phase(phase)
            self.assertIn(color, self.window.progress.styleSheet())

    def test_ene_read_filename_uses_selected_group(self):
        self.window.manufacturer.setCurrentText("ENE")
        self.window.model.setCurrentText("KB9022Q")
        self.window.pending_read = bytes(128)
        self.window.pending_identity = (0xB1, 0x07)
        try:
            with patch("app.gui.QFileDialog.getSaveFileName", return_value=("", "")) as save:
                self.window.save_read()
            self.assertIn("ENE-KB9022Q-HWB1", save.call_args.args[2])
        finally:
            self.window.pending_read = self.window.pending_identity = None

    def test_connect_has_no_read_percentage_and_logs_do_not_replace_state(self):
        w = self.window
        w.begin_operation("connect")
        w.update_buttons()
        self.assertEqual(w.progress.maximum(), 0)
        self.assertEqual(w.percent.text(), "")
        self.assertIn("Connecting", w.status.text())
        w.on_worker_status("Image SHA-256 abcdef")
        self.assertIn("Connecting", w.status.text())
        w.finish_progress()
        w.set_status("EC connected", "success")
        w.note("Background diagnostic")
        self.assertEqual(w.status.text(), "EC connected")

    def test_each_phase_resets_bytes_time_and_percent_and_failure_stops_animation(self):
        w = self.window
        w.begin_operation("write")
        for phase in ("Erase", "Programming", "Verification"):
            with patch("app.gui.time.monotonic", return_value=100):
                w.set_progress_phase(phase)
            self.assertEqual(w.percent.text(), "0%")
            self.assertEqual(w.progress.value(), 0)
            self.assertEqual(w._phase_done, 0)
            with patch("app.gui.time.monotonic", return_value=110):
                w.set_transfer(128*1024, 256*1024)
                w.set_progress_value(50)
            self.assertEqual(w.transfer.text(), "128 / 256 KiB")
            self.assertIn("~10 s remaining", w.timing.text())
        w.controller.worker = SimpleNamespace(action="read")
        w.on_failed("Timeout USB CDC")
        self.assertFalse(w.progress_timer.isActive())
        self.assertEqual(w.progress.value(), 50)
        self.assertEqual(w.percent.text(), "Stopped")
        self.assertEqual(w.status.property("tone"), "error")
        self.assertFalse(w.write.isEnabled())
        w.begin_operation("connect")
        w.controller.worker = SimpleNamespace(action="connect")
        w.on_failed("ERR ADDRESS_NACK")
        self.assertEqual(w.progress.maximum(), 100)
        self.assertIn("EC did not respond", w.status.text())

    def test_cancelled_save_preserves_read_and_explicit_discard_unlocks_controls(self):
        w = self.window
        data = bytes(range(128))
        with patch("app.gui.QFileDialog.getSaveFileName", return_value=("", "")):
            w.on_finished("read", ((0x8227, 3), data))
        self.assertEqual(w.pending_read, data)
        self.assertFalse(w.write.isEnabled())
        self.assertFalse(w.read.isEnabled())
        self.assertTrue(w.save_read_button.isEnabled())
        self.assertFalse(w.result_actions.isHidden())
        with patch("app.gui.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            w.discard_read()
        self.assertEqual(w.pending_read, data)
        with patch("app.gui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            w.discard_read()
        self.assertIsNone(w.pending_read)
        self.assertTrue(w.write.isEnabled())
        self.assertTrue(w.manufacturer.isEnabled())

    def test_saved_read_remembers_directory_and_opens_its_folder(self):
        w = self.window
        target = Path(self.temp.name) / "dump.bin"
        w.pending_read = bytes(range(128))
        w.pending_identity = (0x8227, 3)
        with patch("app.gui.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            w.save_read()
        self.assertEqual(target.read_bytes(), bytes(range(128)))
        self.assertIsNone(w.pending_read)
        self.assertEqual(w.last_directory("images"), target.parent)
        self.assertEqual(w.status.text(), "Read saved")
        self.assertTrue(w.write.isEnabled())
        with patch("app.gui.QDesktopServices.openUrl", return_value=True) as open_url:
            w.open_saved_folder()
        self.assertEqual(open_url.call_args.args[0].toLocalFile(), target.parent.as_posix())

    def test_same_interface_preserves_connection_missing_device_invalidates_it(self):
        w = self.window
        w.port.set_device(DetectedInterface(UsbCandidate("SIMULATED"), "pico_w"))
        self.assertEqual(w.connected_identity, (0x8227, 3))
        w.port.set_device(None)
        self.assertIsNone(w.connected_identity)
        self.assertFalse(w.detect.isEnabled())
        self.assertIn("USB", w.next_step.text())

    def test_compact_layout_and_field_positions_are_stable_between_brands(self):
        w = self.window
        w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        w.resize(1040, 790)
        w.show()
        self.app.processEvents()
        positions = [control.mapTo(w, control.rect().topLeft()).x()
                     for control in (w.manufacturer, w.model)]
        size_x = w.flash_size.mapTo(w, w.flash_size.rect().topLeft()).x()
        scl_right = w.scl.mapTo(w, w.scl.rect().topRight()).x()
        self.assertEqual(size_x - scl_right, 13)
        w.manufacturer.setCurrentText("ENE")
        w.model.setCurrentText("KB902FQ C")
        self.app.processEvents()
        self.assertEqual(positions, [control.mapTo(w, control.rect().topLeft()).x()
                                   for control in (w.manufacturer, w.model)])
        size_x = w.flash_size.mapTo(w, w.flash_size.rect().topLeft()).x()
        model_right = w.model.mapTo(w, w.model.rect().topRight()).x()
        self.assertEqual(size_x - model_right, 13)
        self.assertTrue(w.log.isVisible())
        self.assertEqual(w.ec_scroll.verticalScrollBar().maximum(), 0)
        self.assertIn("128 KiB (model default)", w.identity.text())
        self.assertEqual("Flash size for the selected model.", w.flash_size.toolTip())


if __name__ == "__main__":
    unittest.main()
