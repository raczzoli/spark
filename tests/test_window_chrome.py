"""Custom caption controls retain native behavior and EC close protections."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.gui import Window
from app.window_chrome import resize_hit_test


class WindowChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = QSettings(str(Path(self.temp.name) / "chrome.ini"), QSettings.Format.IniFormat)
        self.window = Window(settings, auto_discovery=False)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.controller.thread = self.window.controller.worker = None
        self.window.pending_read = None
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_caption_maximize_restore_double_click_and_minimize(self):
        window = self.window
        original = window.geometry()
        QTest.mouseClick(window.title_bar.maximize, Qt.MouseButton.LeftButton)
        self.assertTrue(window.isMaximized())
        self.assertEqual(window.title_bar.maximize.accessibleName(), "Restore")
        QTest.mouseClick(window.title_bar.maximize, Qt.MouseButton.LeftButton)
        self.assertFalse(window.isMaximized())
        self.assertEqual(window.geometry(), original)
        QTest.mouseDClick(window.title_bar, Qt.MouseButton.LeftButton)
        self.assertTrue(window.isMaximized())
        window.showNormal()
        QTest.mouseClick(window.title_bar.minimize, Qt.MouseButton.LeftButton)
        self.assertTrue(window.isMinimized())

    def test_caption_drag_requests_the_os_move_operation(self):
        handle = Mock()
        handle.startSystemMove.return_value = True
        with patch.object(self.window, "windowHandle", return_value=handle):
            QTest.mouseClick(self.window.title_bar, Qt.MouseButton.LeftButton)
        handle.startSystemMove.assert_called_once_with()

    def test_custom_close_keeps_running_ec_write_and_detection_alive(self):
        window = self.window
        window.discovery.active = True
        window.controller.thread = Mock()
        window.controller.worker = Mock(action="write")
        with patch("app.gui.QMessageBox.information") as message:
            QTest.mouseClick(window.title_bar.close_button, Qt.MouseButton.LeftButton)
        message.assert_called_once()
        self.assertTrue(window.controller.busy)
        self.assertTrue(window.isVisible())
        self.assertTrue(window.discovery.active)
        self.assertFalse(window._close_when_idle)

    def test_custom_close_keeps_unsaved_backup_when_cancelled(self):
        self.window.pending_read = b"unsaved EC backup"
        with patch("app.gui.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            QTest.mouseClick(self.window.title_bar.close_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.pending_read, b"unsaved EC backup")
        self.assertTrue(self.window.isVisible())

    def test_resize_edges_corners_and_client_area_are_distinct(self):
        for point, expected in (((1, 1), 13), ((50, 1), 12), ((99, 1), 14),
                                ((1, 40), 10), ((99, 40), 11),
                                ((1, 79), 16), ((50, 79), 15), ((99, 79), 17),
                                ((50, 40), None), ((-1, 40), None), ((100, 40), None)):
            with self.subTest(point=point):
                self.assertEqual(resize_hit_test(*point, 100, 80, 5), expected)


class NativeWindowChromeTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Native Windows frame verification")
    def test_native_caption_hit_testing_and_taskbar_safe_maximize(self):
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-m", "tests.native.window_chrome_smoke"],
            cwd=Path(__file__).resolve().parents[1],
            env=dict(os.environ, QT_QPA_PLATFORM="windows"),
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("native_chrome_ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
