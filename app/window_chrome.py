# SPDX-License-Identifier: GPL-2.0-or-later
"""Spark title bar with native Windows move, resize and maximize behavior."""
import sys

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QMainWindow

from .version import APP_NAME, VERSION


class CaptionButton(QAbstractButton):
    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action
        self.hovered = False
        self.setFixedSize(46, 40)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_action(action)

    def set_action(self, action):
        self.action = action
        name = {"minimize": "Minimize", "maximize": "Maximize", "restore": "Restore", "close": "Close"}[action]
        self.setAccessibleName(name)
        self.setToolTip(name)
        self.update()

    def set_hovered(self, hovered):
        if self.hovered != hovered:
            self.hovered = hovered
            self.update()

    def enterEvent(self, event):
        self.set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.set_hovered(False)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.hovered or self.isDown():
            color = ("#b83949" if self.isDown() else "#d44354") if self.action == "close" else (
                "#233344" if self.isDown() else "#293543")
            painter.fillRect(self.rect(), QColor(color))
        painter.setPen(QPen(QColor("#ffffff" if self.hovered else "#b9c7d7"), 1.25))
        painter.translate(self.width() / 2, self.height() / 2)
        if self.action == "minimize":
            painter.drawLine(-5, 1, 5, 1)
        elif self.action == "maximize":
            painter.drawRect(QRectF(-5, -5, 10, 10))
        elif self.action == "restore":
            painter.drawPolyline([QPoint(-2, -5), QPoint(5, -5), QPoint(5, 2)])
            painter.drawRect(QRectF(-5, -2, 7, 7))
        else:
            painter.drawLine(-5, -5, 5, 5)
            painter.drawLine(-5, 5, 5, -5)


class TitleBar(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("sparkTitleBar")
        self.setFixedHeight(40)
        self.setAccessibleName("Spark window title bar")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 0, 0)
        row.setSpacing(9)
        self.name = QLabel(APP_NAME)
        self.name.setObjectName("sparkWindowName")
        self.version = QLabel(VERSION)
        self.version.setObjectName("sparkWindowVersion")
        for label in (self.name, self.version):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row.addWidget(label)
        row.addStretch()
        self.minimize = CaptionButton("minimize", self)
        self.maximize = CaptionButton("maximize", self)
        self.close_button = CaptionButton("close", self)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(0)
        for button in (self.minimize, self.maximize, self.close_button):
            buttons.addWidget(button)
        row.addLayout(buttons)
        self.minimize.clicked.connect(window.showMinimized)
        self.maximize.clicked.connect(self.toggle_maximized)
        # All close paths retain Window.closeEvent's operation/backup guards.
        self.close_button.clicked.connect(window.close)

    def toggle_maximized(self):
        window = self.window()
        window.showNormal() if window.isMaximized() else window.showMaximized()

    def sync_state(self):
        self.maximize.set_action("restore" if self.window().isMaximized() else "maximize")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            if self.window().windowHandle().startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


def resize_hit_test(x, y, width, height, border):
    """Win32 hit codes for a frame, including signed/multi-monitor coordinates."""
    if not (0 <= x < width and 0 <= y < height):
        return None
    left, right = x < border, x >= width - border
    top, bottom = y < border, y >= height - border
    if top:
        return 13 if left else 14 if right else 12
    if bottom:
        return 16 if left else 17 if right else 15
    return 10 if left else 11 if right else None


class _WindowsFrame:
    """Keep OS window semantics while drawing the entire caption ourselves.

    Microsoft: /windows/win32/dwm/customframe and
    /windows/apps/desktop/modernize/ui/apply-snap-layout-menu.
    No target/USB work belongs in this adapter.
    """
    def __init__(self, window):
        import ctypes
        from ctypes import wintypes
        self.window, self.ctypes, self.types = window, ctypes, wintypes
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.dwm = ctypes.WinDLL("dwmapi")
        self.max_pressed = False

        class MinMaxInfo(ctypes.Structure):
            _fields_ = [(name, wintypes.POINT) for name in
                        ("reserved", "max_size", "max_position", "min_track", "max_track")]

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        class TrackMouseEvent(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwnd", wintypes.HWND), ("hover_time", wintypes.DWORD)]

        class Margins(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]

        self.MinMaxInfo, self.MonitorInfo = MinMaxInfo, MonitorInfo
        self.TrackMouseEvent, self.Margins = TrackMouseEvent, Margins
        bindings = {
            "GetWindowLongW": (wintypes.LONG, [wintypes.HWND, ctypes.c_int]),
            "SetWindowLongW": (wintypes.LONG, [wintypes.HWND, ctypes.c_int, wintypes.LONG]),
            "SetWindowPos": (wintypes.BOOL, [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]),
            "GetWindowRect": (wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]),
            "ScreenToClient": (wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]),
            "IsZoomed": (wintypes.BOOL, [wintypes.HWND]),
            "MonitorFromWindow": (wintypes.HANDLE, [wintypes.HWND, wintypes.DWORD]),
            "MonitorFromRect": (wintypes.HANDLE, [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]),
            "GetMonitorInfoW": (wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]),
            "TrackMouseEvent": (wintypes.BOOL, [ctypes.POINTER(TrackMouseEvent)]),
        }
        for name, (result, arguments) in bindings.items():
            function = getattr(self.user, name)
            function.restype, function.argtypes = result, arguments
        self.dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        self.dwm.DwmSetWindowAttribute.restype = wintypes.LONG
        self.dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(Margins)]
        self.dwm.DwmExtendFrameIntoClientArea.restype = wintypes.LONG

    def configure(self):
        hwnd = int(self.window.winId())
        style = self.user.GetWindowLongW(hwnd, -16)  # GWL_STYLE
        # WS_OVERLAPPEDWINDOW restores resize, system menu, animations and Snap.
        self.user.SetWindowLongW(hwnd, -16, style | 0x00CF0000)
        self.user.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0037)  # FRAMECHANGED, no move/size/z-order/activation
        dark = self.ctypes.c_int(1)
        self.dwm.DwmSetWindowAttribute(hwnd, 20, self.ctypes.byref(dark), self.ctypes.sizeof(dark))
        self.dwm.DwmExtendFrameIntoClientArea(hwnd, self.ctypes.byref(self.Margins(1, 1, 1, 1)))

    def position(self, message):
        x = self.ctypes.c_short(message.lParam & 0xFFFF).value
        y = self.ctypes.c_short((message.lParam >> 16) & 0xFFFF).value
        point = self.types.POINT(x, y)
        self.user.ScreenToClient(message.hWnd, self.ctypes.byref(point))
        ratio = self.window.devicePixelRatioF()
        return QPoint(round(point.x / ratio), round(point.y / ratio))

    def hit_test(self, point):
        window = self.window
        if not window.isMaximized() and not window.isFullScreen():
            hit = resize_hit_test(point.x(), point.y(), window.width(), window.height(), 5)
            if hit is not None:
                return hit
        bar = window.title_bar
        local = bar.mapFrom(window, point)
        if not bar.rect().contains(local):
            return None
        if bar.maximize.geometry().contains(local):
            return 9  # HTMAXBUTTON: Windows 11 Snap Layouts
        if any(button.geometry().contains(local) for button in (bar.minimize, bar.close_button)):
            return None
        return 2  # HTCAPTION: OS dragging, Snap and double-click maximize

    def handle(self, pointer):
        message = self.types.MSG.from_address(int(pointer))
        if message.message == 0x0083:  # WM_NCCALCSIZE: no native title bar
            if self.user.IsZoomed(message.hWnd):
                # Windows maximizes the resize frame beyond the monitor. Keep
                # the custom client area inside the work area, above the taskbar.
                rectangle = self.types.RECT.from_address(message.lParam)
                monitor = self.user.MonitorFromRect(self.ctypes.byref(rectangle), 2)
                info = self.MonitorInfo()
                info.size = self.ctypes.sizeof(info)
                if self.user.GetMonitorInfoW(monitor, self.ctypes.byref(info)):
                    rectangle.left, rectangle.top = info.work.left, info.work.top
                    rectangle.right, rectangle.bottom = info.work.right, info.work.bottom
            return True, 0
        if message.message == 0x0024:  # WM_GETMINMAXINFO: respect this monitor's taskbar and DPI
            monitor = self.user.MonitorFromWindow(message.hWnd, 2)
            info = self.MonitorInfo()
            info.size = self.ctypes.sizeof(info)
            if self.user.GetMonitorInfoW(monitor, self.ctypes.byref(info)):
                limits = self.MinMaxInfo.from_address(message.lParam)
                limits.max_position.x = info.work.left - info.monitor.left
                limits.max_position.y = info.work.top - info.monitor.top
                limits.max_size.x = info.work.right - info.work.left
                limits.max_size.y = info.work.bottom - info.work.top
                ratio = self.window.devicePixelRatioF()
                limits.min_track.x = round(self.window.minimumWidth() * ratio)
                limits.min_track.y = round(self.window.minimumHeight() * ratio)
                return True, 0
        if message.message == 0x0084:  # WM_NCHITTEST
            hit = self.hit_test(self.position(message))
            if hit is not None:
                return True, hit
        button = self.window.title_bar.maximize
        if message.message == 0x00A0:  # WM_NCMOUSEMOVE
            button.set_hovered(message.wParam == 9)
            tracking = self.TrackMouseEvent(self.ctypes.sizeof(self.TrackMouseEvent), 0x12, message.hWnd, 0)
            self.user.TrackMouseEvent(self.ctypes.byref(tracking))  # NONCLIENT | LEAVE
        elif message.message == 0x00A1 and message.wParam == 9:  # WM_NCLBUTTONDOWN
            self.max_pressed = True
            button.setDown(True)
            return True, 0
        elif message.message == 0x00A2 and self.max_pressed:  # WM_NCLBUTTONUP
            self.max_pressed = False
            button.setDown(False)
            if self.hit_test(self.position(message)) == 9:
                button.click()
            return True, 0
        elif message.message == 0x02A2:  # WM_NCMOUSELEAVE
            self.max_pressed = False
            button.setDown(False)
            button.set_hovered(False)
        return False, 0


class SparkWindow(QMainWindow):
    """Window frame only; application close/worker policy stays in gui.Window."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._native_frame = None
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.title_bar = TitleBar(self)
        self.setMenuWidget(self.title_bar)
        self._sync_frame()

    def _sync_frame(self):
        margin = 0 if self.isMaximized() or self.isFullScreen() else 5
        self.setContentsMargins(margin, margin, margin, margin)
        self.title_bar.sync_state()

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32" and QGuiApplication.platformName() == "windows":
            if self._native_frame is None:
                self._native_frame = _WindowsFrame(self)
            self._native_frame.configure()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            self._sync_frame()

    def nativeEvent(self, event_type, message):
        frame = getattr(self, "_native_frame", None)
        if frame is not None:
            handled, result = frame.handle(message)
            if handled:
                return True, result
        return super().nativeEvent(event_type, message)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isMaximized() and not self.isFullScreen():
            painter = QPainter(self)
            painter.setPen(QColor("#303b49"))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
