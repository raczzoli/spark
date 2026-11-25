# SPDX-License-Identifier: GPL-2.0-or-later
"""PD workspace lifecycle and dialog handling with isolated application settings."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import hashlib
import json
import unittest
from unittest.mock import patch, Mock
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox
from app.gui import Window
from app.interface import DetectedInterface, UsbCandidate
from app.pd import PDIdentity, PDConnection
from app.pd_models import PDModel, MODELS


class PDGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.w = Window(self.settings, auto_discovery=False)
        self.pd = self.w.pd
        self.identity = PDIdentity(bytes(4), b"XYZ9", bytes(4), bytes(range(16)), "APP")

    def tearDown(self):
        self.w.connected_identity = None
        self.w.pending_read = None
        self.pd.pending_read = None
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()

    def connect(self, capacity=256 * 1024):
        self.w.port.set_device(DetectedInterface(UsbCandidate("COM11"), "pico", "0.4.0", "test"))
        self.w.workspaces.setCurrentIndex(1)
        if self.pd.model.currentIndex() < 0:
            self.pd.model.setCurrentIndex(0)
        self.pd.on_finished("pd_connect", PDConnection(self.identity, 0x38))
        if capacity is not None:
            self.pd.size.setEditText(f"{capacity // 1024} KiB")

    def test_tab_order_and_shared_interface(self):
        self.assertEqual([self.w.workspaces.tabText(i) for i in range(3)],
                         ["EC Programmer", "PD Controller", "Battery Analyzer"])
        self.assertIs(self.pd.port, self.w.port)
        self.assertEqual(self.pd.model.placeholderText(), "Select model")
        self.assertEqual(self.pd.model.currentIndex(), -1)
        self.assertFalse(self.pd.connect_button.isEnabled())

    def test_external_size_is_visible_before_and_after_connection(self):
        self.assertFalse(self.pd.size_field.isHidden())
        self.assertFalse(self.pd.size.isEnabled())
        self.assertTrue(self.pd.memory_note.isHidden())
        self.pd.model.setCurrentIndex(0)
        self.assertTrue(self.pd.size.isEnabled())
        self.assertEqual(self.pd.size.currentText(), "")
        self.assertIn("external SPI", self.pd.memory_note.text())
        self.assertIn("locate the flash chip", self.pd.memory_note.text())
        self.connect()
        self.assertTrue(self.pd.write_button.isEnabled())
        self.assertFalse(self.pd.size_field.isHidden())
        self.assertTrue(self.pd.size.isEnabled())
        self.assertFalse(hasattr(self.pd, "address"))
        self.assertFalse(hasattr(self.pd, "protocol"))
        self.assertFalse(hasattr(self.pd, "wiring"))
        self.assertEqual(self.pd._address, 0x38)

    def test_external_capacity_requires_selection_and_is_not_saved(self):
        self.connect(capacity=None)
        self.assertFalse(self.pd.size_field.isHidden())
        self.assertEqual(self.pd.size.currentText(), "")
        self.assertFalse(self.pd.read_button.isEnabled())
        self.assertTrue(self.pd.connect_button.isEnabled())
        self.pd.size.setCurrentIndex(self.pd.size.findData(512 * 1024))
        self.assertFalse(self.pd.size_field.isHidden())
        self.assertTrue(self.pd.read_button.isEnabled())
        self.assertEqual(self.pd._capacity, 512 * 1024)
        self.assertFalse(any(key.startswith("pd/memory/") for key in self.settings.allKeys()))

    def test_capacity_never_defaults_from_controller_model(self):
        for model in MODELS:
            self.pd.model.setCurrentText(model.name)
            self.connect(capacity=None)
            self.assertIsNone(self.pd._capacity)
            self.assertFalse(self.pd.size_field.isHidden())
            self.assertEqual(self.pd.size.currentText(), "")
            self.assertIn(model.name, self.pd.memory_note.text())

    def test_changing_external_size_updates_the_active_range(self):
        self.connect()
        self.pd.size.setCurrentIndex(self.pd.size.findData(128 * 1024))
        self.assertEqual(self.pd._capacity, 128 * 1024)
        self.assertTrue(self.pd.write_button.isEnabled())
        self.assertIn("128 KiB", self.pd.identity_details.text())
        self.pd.size.clearEditText()
        self.assertIsNone(self.pd._capacity)
        self.assertFalse(self.pd.size_field.isHidden())
        self.assertFalse(self.pd.write_button.isEnabled())

    def test_invalid_edit_cannot_leave_a_previous_capacity_active(self):
        self.connect()
        self.pd.size.setEditText("257 KiB")
        self.assertIsNone(self.pd._capacity)
        self.assertFalse(self.pd.write_button.isEnabled())

    def test_manual_size_can_be_selected_before_connecting(self):
        self.w.port.set_device(DetectedInterface(UsbCandidate("COM11"), "pico", "0.4.0", "test"))
        self.pd.model.setCurrentIndex(0)
        self.pd.size.setCurrentIndex(self.pd.size.findData(128 * 1024))
        self.assertEqual(self.pd._capacity, 128 * 1024)
        self.assertFalse(self.pd.read_button.isEnabled())
        self.pd.on_finished("pd_connect", PDConnection(self.identity, 0x38))
        self.assertEqual(self.pd._capacity, 128 * 1024)
        self.assertTrue(self.pd.read_button.isEnabled())

    def test_internal_model_capacity_is_shown_and_cannot_be_edited(self):
        # Exercise the presentation for a future profile without advertising a
        # controller or claiming its programming protocol is implemented.
        model = PDModel("Internal flash fixture", external_spi=False, capacity=128 * 1024)
        self.pd.model.addItem(model.name, model)
        self.pd.model.setCurrentIndex(self.pd.model.count() - 1)
        self.assertEqual(self.pd._capacity, 128 * 1024)
        self.assertEqual(self.pd.size.currentText(), "128 KiB")
        self.assertFalse(self.pd.size_field.isHidden())
        self.assertFalse(self.pd.size.isEnabled())
        self.assertIn("internal flash", self.pd.memory_note.text())
        self.w.port.set_device(DetectedInterface(UsbCandidate("COM11"), "pico", "0.4.0", "test"))
        self.pd.update_controls()
        self.assertEqual(self.pd._capacity, 128 * 1024)
        self.assertFalse(self.pd.size.isEnabled())
        self.pd.model.setCurrentIndex(0)
        self.assertEqual(self.pd.size.currentText(), "")
        self.assertIsNone(self.pd._capacity)
        self.assertTrue(self.pd.size.isEnabled())

    def test_sda_scl_text_insets_match_ite(self):
        self.assertEqual(self.pd.sda.lineEdit().textMargins(), self.w.sda.lineEdit().textMargins())
        self.assertEqual(self.pd.scl.lineEdit().textMargins(), self.w.scl.lineEdit().textMargins())

    def test_connect_asks_worker_to_discover_address_and_does_not_require_capacity(self):
        self.w.port.set_device(DetectedInterface(UsbCandidate("COM11"), "pico", "0.4.0", "test"))
        with patch.object(self.w.controller, "start", return_value=False), patch("app.pd_gui.PDWorker") as worker:
            self.pd.start("pd_connect")
            worker.assert_not_called()
            self.pd.model.setCurrentIndex(0)
            self.pd.start("pd_connect")
        self.assertEqual(worker.call_args.args[3:5], (None, 0))

    def test_replug_invalidates_connection_without_losing_unsaved_flash(self):
        self.connect()
        self.pd.pending_read = b"original flash"
        self.w.port.set_device(None)
        self.assertIsNone(self.pd.identity)
        self.assertEqual(self.pd.pending_read, b"original flash")
        self.assertFalse(self.pd.write_button.isEnabled())

    def test_unsaved_pd_read_blocks_other_tools_until_discarded(self):
        self.connect()
        with patch.object(self.pd, "save_read"):
            self.pd.on_finished("pd_read", (self.identity, bytes(4096)))
        self.assertFalse(self.w.workspaces.isTabEnabled(0))
        self.assertFalse(self.w.workspaces.isTabEnabled(2))
        self.assertTrue(self.w.workspaces.isTabEnabled(1))
        self.pd.discard_read()
        self.assertTrue(self.w.workspaces.isTabEnabled(0))
        self.assertTrue(self.w.workspaces.isTabEnabled(2))

    def test_cancelled_save_keeps_read_and_existing_backup_cannot_be_overwritten(self):
        self.connect()
        self.pd.pending_read = b"new read"
        path = Path(self.temp.name) / "backup.bin"
        path.write_bytes(b"original")
        with patch("app.pd_gui.QFileDialog.getSaveFileName", return_value=("", "")):
            self.pd.save_read()
        self.assertEqual(self.pd.pending_read, b"new read")
        with patch("app.pd_gui.QFileDialog.getSaveFileName", return_value=(str(path), "")), patch("app.pd_gui.QMessageBox.warning"):
            self.pd.save_read()
        self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(self.pd.pending_read, b"new read")

    def test_saving_retained_read_after_usb_loss(self):
        self.connect()
        self.pd.pending_read = b"complete read"
        self.pd._read_uid = self.identity.uid.hex()
        self.w.port.set_device(None)
        path = Path(self.temp.name) / "saved.bin"
        with patch("app.pd_gui.QFileDialog.getSaveFileName", return_value=(str(path), "")):
            self.pd.save_read()
        self.assertEqual(path.read_bytes(), b"complete read")
        self.assertIsNone(self.pd.pending_read)
        metadata = json.loads(Path(str(path) + ".pd.json").read_text())
        self.assertEqual(metadata["uid"], self.identity.uid.hex())
        self.assertEqual(metadata["sha256"], hashlib.sha256(b"complete read").hexdigest())

    def test_cached_capacity_and_matching_backup_never_preselect_external_size(self):
        path = Path(self.temp.name) / "original.bin"
        data = bytes(range(256)) * 1024
        path.write_bytes(data)
        Path(str(path) + ".pd.json").write_text(json.dumps({
            "format": "spark-pd-backup-1", "image": path.name, "size": len(data),
            "uid": self.identity.uid.hex(), "sha256": hashlib.sha256(data).hexdigest(),
        }))
        self.settings.setValue("pd/backup_dir", self.temp.name)
        self.settings.setValue("pd/memory/" + self.identity.uid.hex().upper() + "/size", len(data))
        self.connect(capacity=None)
        self.assertIsNone(self.pd._capacity)
        self.assertEqual(self.pd.size.currentText(), "")
        self.assertFalse(self.pd.size_field.isHidden())
        self.assertFalse(self.pd.read_button.isEnabled())

    def test_reconnecting_another_controller_requires_a_new_size_selection(self):
        self.connect()
        other = PDIdentity(bytes(4), b"XYZ9", bytes(4), bytes(reversed(range(16))), "APP")
        self.pd.on_finished("pd_connect", PDConnection(other, 0x38))
        self.assertIsNone(self.pd._capacity)
        self.assertEqual(self.pd.size.currentText(), "")
        self.assertFalse(self.pd.read_button.isEnabled())

    def test_disconnect_and_model_changes_clear_external_size(self):
        self.connect()
        self.w.port.set_device(None)
        self.assertIsNone(self.pd._capacity)
        self.assertEqual(self.pd.size.currentText(), "")
        self.connect()
        self.pd.model.setCurrentIndex(1)
        self.assertIsNone(self.pd._capacity)
        self.assertEqual(self.pd.size.currentText(), "")

    def test_failed_connection_clears_external_size(self):
        self.connect()
        self.pd.on_failed("No response")
        self.assertIsNone(self.pd._capacity)
        self.assertEqual(self.pd.size.currentText(), "")
        self.assertFalse(self.pd.write_button.isEnabled())

    def test_selected_size_is_passed_to_the_operation_worker(self):
        self.connect(capacity=128 * 1024)
        with patch.object(self.w.controller, "start", return_value=False), patch("app.pd_gui.PDWorker") as worker:
            self.pd.start("pd_read")
        self.assertEqual(worker.call_args.args[3:5], (0x38, 128 * 1024))

    def test_late_connect_result_does_not_restore_identity_after_replug(self):
        self.connect()
        self.pd._context = self.pd.context()
        self.w.port.set_device(None)
        self.pd.on_finished("pd_connect", PDConnection(self.identity, 0x38))
        self.assertIsNone(self.pd.identity)
        self.assertFalse(self.pd.erase_button.isEnabled())

    def test_usb_loss_during_erase_confirmation_stops_before_worker_creation(self):
        self.connect()
        def unplug(*args):
            self.w.port.set_device(None)
            return QMessageBox.StandardButton.Yes
        with patch("app.pd_gui.QMessageBox.question", side_effect=unplug), patch("app.pd_gui.PDWorker") as worker:
            self.pd.start("pd_erase")
        worker.assert_not_called()

    def test_busy_shared_controller_disables_pd_operations(self):
        self.connect()
        self.w.controller.thread = Mock()
        self.w.controller.worker = Mock(action="write")
        try:
            self.w.update_buttons()
            self.assertFalse(self.pd.connect_button.isEnabled())
            self.assertFalse(self.pd.erase_button.isEnabled())
            self.assertFalse(self.w.workspaces.tabBar().isEnabled())
        finally:
            self.w.controller.thread = None
            self.w.controller.worker = None

    def test_close_retains_unsaved_pd_backup_if_discard_is_declined(self):
        self.connect()
        self.pd.pending_read = b"unsaved"
        with patch("app.gui.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.w.close())
        self.assertEqual(self.pd.pending_read, b"unsaved")


if __name__ == "__main__":
    unittest.main()
