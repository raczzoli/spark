"""Exercise real HWND messages invisibly, with isolated settings and no USB."""
import ctypes
from ctypes import wintypes
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QSettings, Qt
from PySide6.QtWidgets import QApplication

from app.gui import Window


def main():
    app = QApplication([])
    with TemporaryDirectory() as directory:
        settings = QSettings(str(Path(directory) / "native.ini"), QSettings.Format.IniFormat)
        window = Window(settings, auto_discovery=False)
        window.setWindowOpacity(0)
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        window.show()
        app.processEvents()
        try:
            frame, hwnd = window._native_frame, int(window.winId())
            assert frame is not None
            user = frame.user
            user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.SendMessageW.restype = ctypes.c_ssize_t
            user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user.GetClientRect.restype = wintypes.BOOL
            user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            user.ClientToScreen.restype = wintypes.BOOL

            def coordinates(point):
                ratio = window.devicePixelRatioF()
                native = wintypes.POINT(round(point.x() * ratio), round(point.y() * ratio))
                assert user.ClientToScreen(hwnd, ctypes.byref(native))
                return (native.x & 0xFFFF) | ((native.y & 0xFFFF) << 16)

            outer, client = wintypes.RECT(), wintypes.RECT()
            assert user.GetWindowRect(hwnd, ctypes.byref(outer))
            assert user.GetClientRect(hwnd, ctypes.byref(client))
            assert (client.right, client.bottom) == (outer.right - outer.left, outer.bottom - outer.top)
            assert user.SendMessageW(hwnd, 0x84, 0, coordinates(QPoint(1, 1))) == 13
            title_point = window.title_bar.mapTo(window, QPoint(210, 20))
            assert user.SendMessageW(hwnd, 0x84, 0, coordinates(title_point)) == 2
            button = window.title_bar.maximize
            original = window.geometry()
            for maximized in (True, False):
                point = button.mapTo(window, button.rect().center())
                location = coordinates(point)
                assert user.SendMessageW(hwnd, 0x84, 0, location) == 9
                user.SendMessageW(hwnd, 0xA1, 9, location)
                user.SendMessageW(hwnd, 0xA2, 9, location)
                app.processEvents()
                assert window.isMaximized() is maximized
                assert button.accessibleName() == ("Restore" if maximized else "Maximize")
                if maximized:
                    info = frame.MonitorInfo()
                    info.size = ctypes.sizeof(info)
                    assert user.GetMonitorInfoW(user.MonitorFromWindow(hwnd, 2), ctypes.byref(info))
                    origin = wintypes.POINT()
                    assert user.ClientToScreen(hwnd, ctypes.byref(origin))
                    assert user.GetClientRect(hwnd, ctypes.byref(client))
                    assert (origin.x, origin.y, client.right, client.bottom) == (
                        info.work.left, info.work.top, info.work.right - info.work.left,
                        info.work.bottom - info.work.top)
                else:
                    assert window.geometry() == original
            assert user.GetWindowLongW(hwnd, -16) & 0x00CF0000 == 0x00CF0000
            assert window.battery.battery_choice.currentText() == ""
            assert not settings.contains("battery/reference")
            print("native_chrome_ok", flush=True)
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    main()
