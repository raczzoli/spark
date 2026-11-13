# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Presentation-only widgets for the programmer window."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
    QTabBar, QStackedWidget,
)
from .models import FAMILIES_BY_MANUFACTURER
from .version import APP_NAME


def label(text, name="muted"):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def panel(parent_layout):
    widget = QFrame()
    widget.setObjectName("panel")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(16, 10, 16, 10)
    layout.setSpacing(8)
    parent_layout.addWidget(widget)
    return layout


def field(row, title, control):
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    caption = label(title, "fieldLabel")
    caption.setBuddy(control)
    control.setAccessibleName(title)
    layout.addWidget(caption)
    layout.addWidget(control)
    row.addWidget(box)
    return box, caption


def button(text, callback, name=""):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    widget.clicked.connect(callback)
    return widget


class InterfaceBar(QFrame):
    """Compact, read-only USB status shared by both workspaces."""
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.setObjectName("interfaceBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 4, 20, 4)
        row.setSpacing(8)
        row.addWidget(label("Interface:", "interfaceLabel"))
        self.port = state
        self.device_label = label("Not connected", "interfaceDevice")
        self.device_label.setAccessibleName("Detected USB interface")
        row.addWidget(self.device_label)
        self.separator = label("|", "interfaceSeparator")
        row.addWidget(self.separator)
        self.status_label = label("", "interfaceStatus")
        row.addWidget(self.status_label)
        row.addStretch()
        state.status_changed.connect(self.update_status)
        self.update_status()

    def update_status(self):
        device = self.port.device
        self.device_label.setText(f"{device.usb.port} — {device.name}" if device else self.port.status)
        self.separator.setVisible(device is not None)
        self.status_label.setVisible(device is not None)
        self.status_label.setText("Connected" if device else "")
        self.setToolTip(self.port.detail)


class WorkspaceTabs(QWidget):
    """Shared interface status, tab navigation, then the selected tool page."""
    currentChanged = Signal(int)

    def __init__(self, interface, parent=None):
        super().__init__(parent)
        self.setObjectName("workspaces")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._tabs = QTabBar()
        self._tabs.setExpanding(False)
        self._tabs.setDrawBase(False)
        self._pages = QStackedWidget()
        layout.addWidget(interface)
        layout.addWidget(self._tabs)
        layout.addWidget(self._pages, 1)
        self._tabs.currentChanged.connect(self._change)

    def _change(self, index):
        self._pages.setCurrentIndex(index)
        self.currentChanged.emit(index)

    def addTab(self, page, text):
        self._pages.addWidget(page)
        return self._tabs.addTab(text)

    def currentIndex(self):
        return self._tabs.currentIndex()

    def setCurrentIndex(self, index):
        self._tabs.setCurrentIndex(index)

    def tabBar(self):
        return self._tabs

    def count(self):
        return self._tabs.count()

    def tabText(self, index):
        return self._tabs.tabText(index)

    def widget(self, index):
        return self._pages.widget(index)

    def setTabEnabled(self, index, enabled):
        self._tabs.setTabEnabled(index, enabled)
        self._pages.widget(index).setEnabled(enabled)

    def isTabEnabled(self, index):
        return self._tabs.isTabEnabled(index)


def build_layout(w):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    w.ec_scroll = scroll
    w.setCentralWidget(scroll)
    root = QWidget()
    root.setObjectName("root")
    scroll.setWidget(root)
    outer = QVBoxLayout(root)
    outer.setContentsMargins(18, 12, 18, 10)
    outer.setSpacing(10)
    header = QHBoxLayout()
    header.addWidget(label("PROGRAMMER & TARGET", "sectionLabel"))
    header.addStretch()
    w.connection_badge = label("Disconnected", "badge")
    header.addWidget(w.connection_badge)
    target = panel(outer)
    target.addLayout(header)
    row = QHBoxLayout()
    row.setSpacing(12)
    w.manufacturer = QComboBox()
    w.manufacturer.setFixedWidth(180)
    w.manufacturer.setPlaceholderText("Select brand")
    w.manufacturer.addItems(FAMILIES_BY_MANUFACTURER)
    w.manufacturer.setCurrentIndex(-1)
    field(row, "Manufacturer", w.manufacturer)
    w.model = QComboBox()
    w.model.setFixedWidth(190)
    w.model.setPlaceholderText("Select model")
    field(row, "Model / Family", w.model)
    for name, value in (("sda", 7), ("scl", 6)):
        spin = QSpinBox()
        spin.setFixedWidth(80)
        spin.setRange(0, 28)
        spin.setValue(value)
        spin.setToolTip(f"Pico GPIO connected to EC {name.upper()}")
        setattr(w, name, spin)
        box, caption = field(row, name.upper(), spin)
        setattr(w, name + "_field", box)
        setattr(w, name + "_label", caption)
    w.flash_size = QSpinBox()
    w.flash_size.setFixedWidth(136)
    w.flash_size.setRange(0, 256)
    w.flash_size.setSingleStep(64)
    w.flash_size.setSuffix(" KiB")
    w.flash_size.setSpecialValueText("Set size")
    w.flash_size.setKeyboardTracking(False)
    for spin in (w.sda, w.scl, w.flash_size):
        spin.lineEdit().setTextMargins(8, 0, 0, 0)
    for control in (w.manufacturer, w.model, w.sda, w.scl, w.flash_size):
        control.setFixedHeight(40)
    field(row, "Size", w.flash_size)
    row.addStretch(1)
    target.addLayout(row)
    w.ene_wiring = QLabel()
    w.ene_wiring.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.ene_wiring.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse |
                                       Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
    w.ene_wiring.linkActivated.connect(w.show_wiring_diagram)
    policy = w.ene_wiring.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    w.ene_wiring.setSizePolicy(policy)
    w.ene_wiring.setFixedHeight(20)
    target.addWidget(w.ene_wiring)
    row = QHBoxLayout()
    row.addStretch()
    w.detect = button("Connect to EC", lambda: w.start("connect"), "primary")
    w.detect.setMinimumWidth(160)
    row.addWidget(w.detect)
    row.addStretch()
    target.addLayout(row)
    w.identity = label("EC not connected", "identity")
    w.identity.setWordWrap(True)
    target.addWidget(w.identity)
    w.identity_details = label("", "technical")
    w.identity_details.setWordWrap(True)
    w.identity_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    target.addWidget(w.identity_details)

    operations = panel(outer)
    row = QHBoxLayout()
    row.addWidget(label("OPERATIONS", "sectionLabel"))
    row.addStretch()
    row.addWidget(label("Write includes erase and verification", "muted"))
    operations.addLayout(row)
    row = QHBoxLayout()
    row.setSpacing(10)
    w.read = button("↓  Read", lambda: w.start("read"), "action")
    w.write = button("↑  Write", lambda: w.start("write"), "action")
    w.erase = button("×  Erase", lambda: w.start("erase"), "danger")
    for widget in (w.read, w.write, w.erase):
        row.addWidget(widget, 1)
    w.read.setAccessibleName("Read")
    w.write.setAccessibleName("Write (erase, write and verify)")
    w.erase.setAccessibleName("Erase")
    operations.addLayout(row)
    w.next_step = label("Select a programmer", "hint")
    w.next_step.setWordWrap(True)
    operations.addWidget(w.next_step)
    row = QHBoxLayout()
    w.status = label("Ready", "operationStatus")
    w.status.setWordWrap(True)
    row.addWidget(w.status, 1)
    w.percent = label("", "percent")
    row.addWidget(w.percent)
    operations.addLayout(row)
    w.progress = QProgressBar()
    w.progress.setRange(0, 100)
    w.progress.setValue(0)
    w.progress.setTextVisible(False)
    w.progress.setAccessibleName("Current operation progress")
    operations.addWidget(w.progress)
    row = QHBoxLayout()
    w.transfer = label("", "technical")
    w.timing = label("", "technical")
    row.addWidget(w.transfer, 1)
    row.addWidget(w.timing)
    operations.addLayout(row)
    w.result_actions = QWidget()
    row = QHBoxLayout(w.result_actions)
    row.setContentsMargins(0, 0, 0, 0)
    w.save_read_button = button("Save…", w.save_read, "primary")
    w.discard_read_button = button("Discard", w.discard_read, "quiet")
    w.open_folder_button = button("Open folder", w.open_saved_folder, "quiet")
    for widget in (w.save_read_button, w.discard_read_button, w.open_folder_button):
        row.addWidget(widget)
    row.addStretch()
    operations.addWidget(w.result_actions)
    w.result_actions.hide()

    w.journal = QWidget()
    journal_layout = QVBoxLayout(w.journal)
    journal_layout.setContentsMargins(0, 0, 0, 0)
    journal_layout.setSpacing(6)
    journal_layout.addWidget(label("LOG", "sectionLabel"))
    w.log = QPlainTextEdit()
    w.log.setReadOnly(True)
    w.log.setAccessibleName("Operation log")
    w.log.setMinimumHeight(54)
    w.log.setMaximumHeight(64)
    journal_layout.addWidget(w.log)
    outer.addWidget(w.journal)
    outer.addStretch(1)
    credit = label(f"{APP_NAME} by R89 Repairs | www.r89-repairs.ro", "credit")
    credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.statusBar().setSizeGripEnabled(False)
    w.statusBar().addPermanentWidget(credit, 1)
