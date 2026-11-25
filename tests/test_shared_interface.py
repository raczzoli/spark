"""Automatic connection state is shared by both tools, independent of their tabs."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QComboBox, QToolButton
from app.gui import Window
from app.interface import DetectedInterface, UsbCandidate
from tests.test_battery import sample


class SharedInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = QSettings(str(Path(self.temp.name) / "ui.ini"), QSettings.Format.IniFormat)
        self.w = Window(self.settings, auto_discovery=False)

    def connect_pico(self, port="COM11"):
        self.w.port.set_device(DetectedInterface(UsbCandidate(port), "pico_w", "0.4.0", "test"))

    def tearDown(self):
        self.w.battery.stop_monitor()
        self.w.connected_identity = None
        self.w.pending_read = None
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()

    def test_bar_is_above_main_tabs_and_outside_both_pages(self):
        w = self.w
        self.connect_pico()
        w.show()
        self.app.processEvents()
        self.assertIs(w.port, w.battery.port)
        self.assertFalse(w.ec_scroll.isAncestorOf(w.interface_bar))
        self.assertFalse(w.battery.isAncestorOf(w.interface_bar))
        self.assertEqual(w.interface_bar.device_label.text(), "COM11 — Pico W (RP2040)")
        self.assertEqual(w.interface_bar.status_label.text(), "Connected")
        self.assertEqual(w.interface_bar.findChildren(QComboBox), [])
        self.assertEqual(w.interface_bar.findChildren(QToolButton), [])
        self.assertLessEqual(w.interface_bar.height(), 38)
        self.assertLess(w.interface_bar.geometry().bottom(), w.workspaces.tabBar().y())
        for index in (0, 1, 2):
            w.workspaces.setCurrentIndex(index)
            self.app.processEvents()
            self.assertTrue(w.interface_bar.isVisible())
            self.assertGreater(w.workspaces.widget(index).mapTo(w.workspaces, w.workspaces.widget(index).rect().topLeft()).y(), w.workspaces.tabBar().geometry().bottom())

    def test_detected_interface_survives_mode_changes(self):
        w = self.w
        self.connect_pico("COM12")
        with patch.object(w.discovery, "request_scan") as discover:
            w.workspaces.setCurrentIndex(2)
            self.assertEqual(w.battery.port.currentData(), "COM12")
            w.workspaces.setCurrentIndex(0)
            self.assertEqual(w.port.currentData(), "COM12")
            discover.assert_not_called()
        self.assertEqual(self.settings.value("interface/port"), "COM12")

    def test_initial_state_does_not_trust_a_saved_com_port(self):
        self.assertIsNone(self.w.port.currentData())
        self.assertEqual(self.w.interface_bar.device_label.text(), "Not connected")
        self.assertFalse(self.w.battery.read_button.isEnabled())
        self.settings.setValue("interface/port", "COM12")
        other = Window(self.settings, auto_discovery=False)
        self.assertIsNone(other.port.currentData())
        other.close()
        other.deleteLater()

    def test_disconnect_invalidates_both_tools_and_retains_last_reading(self):
        w = self.w
        self.connect_pico()
        w.connected_identity = (0x8227, 3)
        w.battery.on_finished("battery_read", sample())
        w.battery.profile.setCurrentIndex(1)
        w.battery.latest_valid = True
        w.port.set_device(None)
        self.assertIsNone(w.connected_identity)
        self.assertFalse(w.battery.latest_valid)
        self.assertIsNotNone(w.battery.snapshot)
        self.assertEqual(w.battery.profile.currentData(), "auto")
        self.assertEqual(w.interface_bar.device_label.text(), "Not connected")
        self.assertFalse(w.battery.read_button.isEnabled())

    def test_status_remains_readable_during_operations_unsaved_read_and_live_capture(self):
        w = self.w
        self.connect_pico()
        w.controller.thread = Mock()
        try:
            w.update_buttons()
            self.assertTrue(w.interface_bar.isEnabled())
        finally:
            w.controller.thread = None
        w.pending_read = b"unsaved"
        w.update_buttons()
        self.assertTrue(w.interface_bar.isEnabled())
        w.pending_read = None
        w.workspaces.setCurrentIndex(2)
        w.battery.sections.setCurrentIndex(1)
        with patch.object(w.battery, "start"):
            w.battery.toggle_monitor()
        self.assertTrue(w.interface_bar.isEnabled())
        w.battery.stop_monitor()

    def test_late_connect_result_cannot_restore_ec_after_unplug(self):
        w = self.w
        self.connect_pico()
        w.controller.worker = Mock(interface_generation=w.port.generation)
        w.port.set_device(None)
        w.on_finished("connect", ((0x8227, 3), True, None))
        self.assertIsNone(w.connected_identity)
        self.assertFalse(w.keepalive.isActive())

    def test_late_battery_result_cannot_enable_service_after_replug(self):
        w = self.w
        self.connect_pico()
        w.controller.worker = Mock(interface_generation=w.port.generation)
        w.port.set_device(None)
        self.connect_pico("COM12")
        w.battery.on_finished("battery_read", sample())
        self.assertIsNotNone(w.battery.snapshot)
        self.assertFalse(w.battery.latest_valid)
        self.assertFalse(w.battery.access_button.isEnabled())

    def test_completed_ec_backup_is_retained_when_pico_disconnects(self):
        w = self.w
        self.connect_pico()
        w.controller.worker = Mock(interface_generation=w.port.generation)
        w.port.set_device(None)
        with patch.object(w, "save_read"):
            w.on_finished("read", ((0x8227, 3), b"completed backup"))
        self.assertEqual(w.pending_read, b"completed backup")
        self.assertIsNone(w.connected_identity)

    def test_cancelled_close_during_ec_write_keeps_detection_active(self):
        w = self.w
        w.discovery.active = True
        w.controller.thread = Mock()
        w.controller.worker = Mock(action="write")
        try:
            with patch("app.gui.QMessageBox.information"):
                w.close()
            self.assertTrue(w.discovery.active)
            self.assertFalse(w._close_when_idle)
        finally:
            w.controller.thread = None

    def test_close_during_inventory_scan_waits_for_thread_cleanup(self):
        import time
        w = self.w
        w.discovery.inventory = lambda: []
        w.discovery.start()
        w.close()
        deadline = time.monotonic() + 3
        while w.discovery.thread is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.001)
        self.assertIsNone(w.discovery.thread)
        self.assertFalse(w.discovery.active)
        self.assertTrue(w._close_when_idle)


if __name__ == "__main__":
    unittest.main()
