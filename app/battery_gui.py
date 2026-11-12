# SPDX-License-Identifier: GPL-2.0-or-later
"""Compact battery workflow: connect/read, overview, measurements, controller."""
import csv
import html
import json
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPdfWriter, QPageSize, QTextDocument
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit, QComboBox,
    QCheckBox, QScrollArea, QFrame, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QDialog, QDialogButtonBox, QSizePolicy, QToolButton, QMenu,
)
from .battery import WORDS, diagnose, signed
from .battery_status import battery_status, recovery_unavailable
from .battery_catalog import connection_for
from .battery_operations import BatteryWorker
from .battery_widgets import BatterySelector, ConnectorDiagram, MetricCard, CellVoltages, TrendPlot, ConnectionSpinBox
from .gui_layout import label, button


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().hide()
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.setShowGrid(False)
    return widget


def frame():
    widget = QFrame()
    widget.setObjectName("panel")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(6)
    return widget, layout


def scroll_page():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    content.setObjectName("batteryBody")
    scroll.setWidget(content)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 10, 0, 0)
    layout.setSpacing(10)
    return scroll, layout


class KeyDialog(QDialog):
    def __init__(self, action, parent):
        super().__init__(parent)
        self.setWindowTitle(action)
        layout = QVBoxLayout(self)
        note = label("Enter this battery's two key words. Keys are not saved.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.fields = []
        for i in (1, 2):
            layout.addWidget(label(f"Key word {i} · four hexadecimal digits", "fieldLabel"))
            field = QLineEdit()
            field.setMaxLength(4)
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText("4 hex digits")
            layout.addWidget(field)
            self.fields.append(field)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)
        self.resize(400, 210)

    def keys(self):
        values = []
        for field in self.fields:
            value = field.text().strip()
            if len(value) != 4 or any(c not in "0123456789abcdefABCDEF" for c in value):
                raise ValueError("Each key word must contain exactly four hexadecimal digits")
            values.append(int(value, 16))
        return tuple(values)


class BatteryPage(QWidget):
    state_changed = Signal()

    def __init__(self, controller, settings, interface, parent=None):
        super().__init__(parent)
        self.setObjectName("batteryWorkspace")
        self.controller, self.settings = controller, settings
        # Wiring references belong to this session, never to a previous pack.
        self.settings.remove("battery/reference")
        self.port = interface.port
        self.entry = self.snapshot = None
        self.snapshot_reference = None
        self.latest_valid = False
        self._configuration_revision = 0
        self.history, self.messages = [], []
        self.monitoring = False
        self._error_details = ""
        self._access_action = None
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.poll)
        self._build()
        self._connect_controls()
        self.controller.started.connect(self.update_controls)
        self.controller.idle.connect(self.update_controls)
        self.refresh_wiring()
        self.update_controls()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 8)
        layout.setSpacing(8)
        self.header = QFrame()
        self.header.setObjectName("batteryHeader")
        header = QGridLayout(self.header)
        header.setContentsMargins(12, 8, 12, 6)
        header.setHorizontalSpacing(10)
        header.setVerticalSpacing(6)
        header.setColumnMinimumWidth(0, 66)
        header.setColumnStretch(1, 1)
        header.addWidget(label("Battery", "fieldLabel"), 0, 0)
        self.battery_choice = BatterySelector()
        self.read_button = button("Read battery", lambda: self.start("battery_read"), "primary")
        header.addWidget(self.battery_choice, 0, 1)
        header.addWidget(self.read_button, 0, 2)
        header.addWidget(label("PINOUT", "sectionLabel"), 1, 0, Qt.AlignmentFlag.AlignVCenter)
        wiring = QHBoxLayout()
        wiring.setContentsMargins(0, 0, 0, 0)
        wiring.setSpacing(14)
        self.diagram = ConnectorDiagram()
        self.diagram.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.diagram.customContextMenuRequested.connect(self.connector_menu)
        self.diagram.pin_selected.connect(self.show_contact)
        wiring.addWidget(self.diagram)
        metadata = QVBoxLayout()
        metadata.setSpacing(3)
        self.wiring_meta = label("No connector reference selected.", "muted")
        self.wiring_meta.setWordWrap(True)
        self.wiring_meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.connection_hint = label("", "technical")
        self.connection_hint.setWordWrap(True)
        metadata.addWidget(self.wiring_meta)
        metadata.addWidget(self.connection_hint)
        wiring.addLayout(metadata, 1)
        header.addLayout(wiring, 1, 1, 1, 2)
        layout.addWidget(self.header)

        self.sections = QTabWidget()
        self.sections.setObjectName("batterySections")
        self._build_general()
        self._build_measurements()
        self._build_controller()
        layout.addWidget(self.sections, 1)
        feedback = QHBoxLayout()
        feedback.setContentsMargins(2, 0, 0, 0)
        self.status = label("Choose a battery reference, check the wiring, then Read battery.", "batteryFeedback")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status.setMinimumHeight(24)
        self.feedback_details = QToolButton()
        self.feedback_details.setText("Details")
        self.feedback_details.setObjectName("batteryInlineAction")
        self.feedback_details.clicked.connect(self.show_feedback_details)
        self.feedback_details.hide()
        feedback.addWidget(self.status, 1)
        feedback.addWidget(self.feedback_details)
        layout.addLayout(feedback)

    def _build_general(self):
        self.general_scroll, layout = scroll_page()
        row = QHBoxLayout()
        identity = QVBoxLayout()
        identity.setSpacing(2)
        self.summary = label("General information", "batteryIdentity")
        self.identity_subtitle = label("Read the connected battery to load its information.", "muted")
        identity.addWidget(self.summary)
        identity.addWidget(self.identity_subtitle)
        row.addLayout(identity, 1)
        self.export_button = QToolButton()
        self.export_button.setText("Save report")
        self.export_button.setObjectName("batteryReport")
        self.export_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.export_button)
        for kind, title in (("pdf", "PDF report"), ("json", "JSON snapshot"), ("csv", "CSV measurements")):
            menu.addAction(title, lambda checked=False, k=kind: self.export_report(k))
        self.export_button.setMenu(menu)
        self.export_button.hide()
        row.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)

        metrics, metric_layout = frame()
        metric_layout.setContentsMargins(3, 2, 3, 2)
        metric_row = QHBoxLayout()
        metric_row.setSpacing(0)
        self.cards = {}
        for key, title, unit in (
            ("voltage", "Pack voltage", "V"), ("soc", "Charge", "%"),
            ("health", "Reported health", "%"), ("cycles", "Cycles", ""),
            ("current", "Current", "A"), ("temperature", "Temperature", "°C"),
        ):
            card = MetricCard(title, unit)
            card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.cards[key] = card
            metric_row.addWidget(card, 1)
        metric_layout.addLayout(metric_row)
        layout.addWidget(metrics)

        condition = QHBoxLayout()
        condition.setSpacing(10)
        self.access_panel, access = frame()
        self.access_panel.setMinimumWidth(210)
        self.access_panel.setMaximumWidth(280)
        access.addWidget(label("BATTERY STATUS", "sectionLabel"))
        row = QHBoxLayout()
        self.access_value = label("Unknown", "batteryState")
        self.access_button = button("Unlock battery", self.unlock_battery_clicked, "small")
        self.access_button.hide()
        row.addWidget(self.access_value, 1)
        row.addWidget(self.access_button)
        access.addLayout(row)
        self.access_hint = label("Read battery to check operation.", "muted")
        self.access_hint.setWordWrap(True)
        access.addWidget(self.access_hint)
        self.identify_link = QToolButton()
        self.identify_link.setText("Identify controller →")
        self.identify_link.setObjectName("batteryInlineAction")
        self.identify_link.clicked.connect(lambda: self.sections.setCurrentIndex(2))
        access.addWidget(self.identify_link, 0, Qt.AlignmentFlag.AlignLeft)
        access.addStretch()
        condition.addWidget(self.access_panel)
        cell_panel, cells = frame()
        row = QHBoxLayout()
        row.addWidget(label("CELL BALANCE", "sectionLabel"))
        self.balance_value = label("Unknown", "batteryBalance")
        self.balance_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(self.balance_value, 1)
        cells.addLayout(row)
        self.cells = CellVoltages()
        cells.addWidget(self.cells)
        condition.addWidget(cell_panel, 1)
        layout.addLayout(condition)

        information, box = frame()
        fields = QGridLayout()
        fields.setHorizontalSpacing(18)
        fields.setVerticalSpacing(8)
        self.info_values = {}
        for i, (key, title) in enumerate((
            ("manufacturer", "Manufacturer"), ("chemistry", "Chemistry"),
            ("serial", "Serial number"), ("date", "Manufactured"),
            ("remaining", "Remaining capacity"), ("full", "Full capacity"),
            ("design", "Design capacity"), ("design_voltage", "Design voltage"),
        )):
            field = QVBoxLayout()
            field.setSpacing(2)
            field.addWidget(label(title, "muted"))
            value = label("—", "batteryValue")
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            field.addWidget(value)
            fields.addLayout(field, i // 4, i % 4)
            fields.setColumnStretch(i % 4, 1)
            self.info_values[key] = value
        box.addLayout(fields)
        layout.addWidget(information)
        self.findings = label("", "batteryFinding")
        self.findings.setWordWrap(True)
        self.findings.setMaximumHeight(44)
        self.findings.hide()
        layout.addWidget(self.findings)
        layout.addStretch()
        self.sections.addTab(self.general_scroll, "General info")

    def _build_measurements(self):
        self.measurements_scroll, layout = scroll_page()
        row = QHBoxLayout()
        row.addWidget(label("Measurement history", "batteryIdentity"), 1)
        self.plot_metric = QComboBox()
        for key, (name, unit, color) in TrendPlot.LABELS.items():
            self.plot_metric.addItem(name, key)
        row.addWidget(self.plot_metric)
        self.monitor_button = QToolButton()
        self.monitor_button.setText("Live readings")
        self.monitor_button.setObjectName("batteryLive")
        self.monitor_button.setCheckable(True)
        self.monitor_button.clicked.connect(self.toggle_monitor)
        row.addWidget(self.monitor_button)
        layout.addLayout(row)
        self.measurement_note = label("Read battery once, or turn on Live readings for updates every 3 seconds.", "muted")
        self.measurement_note.setWordWrap(True)
        layout.addWidget(self.measurement_note)
        self.plot = TrendPlot()
        layout.addWidget(self.plot, 1)
        self.history_info = label("No measurements recorded.", "muted")
        layout.addWidget(self.history_info)
        self.sections.addTab(self.measurements_scroll, "Measurements")

    def _build_controller(self):
        self.controller_scroll, layout = scroll_page()
        layout.setSpacing(8)
        identity, identity_layout = frame()
        identity_layout.setContentsMargins(12, 8, 12, 8)
        row = QHBoxLayout()
        row.addWidget(label("BATTERY CONTROLLER", "sectionLabel"))
        row.addStretch()
        self.controller_badge = label("Not read", "badge")
        row.addWidget(self.controller_badge)
        identity_layout.addLayout(row)
        self.controller_details = label("Controller not identified", "batteryIdentity")
        self.controller_details.setWordWrap(True)
        identity_layout.addWidget(self.controller_details)
        self.controller_help = label("Use Read battery above to identify the connected controller.", "muted")
        self.controller_help.setWordWrap(True)
        identity_layout.addWidget(self.controller_help)
        layout.addWidget(identity)

        overview = QHBoxLayout()
        overview.setSpacing(10)
        access_panel, access = frame()
        access.addWidget(label("BATTERY OPERATION", "sectionLabel"))
        row = QHBoxLayout()
        self.controller_access_value = label("Not read", "batteryState")
        row.addWidget(self.controller_access_value, 1)
        self.controller_access_button = button("Unlock battery", self.unlock_battery_clicked, "small")
        self.controller_access_button.hide()
        row.addWidget(self.controller_access_button)
        access.addLayout(row)
        self.controller_access_help = label("Read battery to check PF, protection and output status.", "muted")
        self.controller_access_help.setWordWrap(True)
        access.addWidget(self.controller_access_help)
        self.controller_service_note = label("Recovery actions appear for a confirmed battery lockout.", "batteryBalance")
        self.controller_service_note.setWordWrap(True)
        access.addWidget(self.controller_service_note)
        access.addStretch()
        overview.addWidget(access_panel, 1)

        checks_panel, checks = frame()
        checks.addWidget(label("BATTERY CHECKS", "sectionLabel"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)
        self.controller_cells = label("Not read", "batteryValue")
        self.controller_protection = label("Not read", "batteryBalance")
        for index, (title, value) in enumerate((("Cell voltages", self.controller_cells),
                                                ("Protection", self.controller_protection))):
            value.setWordWrap(True)
            grid.addWidget(label(title, "muted"), index, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, index, 1)
        checks.addLayout(grid)
        checks.addStretch()
        overview.addWidget(checks_panel, 1)
        layout.addLayout(overview)

        self.connection_options = QToolButton()
        self.connection_options.setObjectName("batteryInlineAction")
        self.connection_options.setText("Advanced")
        self.connection_options.setArrowType(Qt.ArrowType.RightArrow)
        self.connection_options.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.connection_options.setCheckable(True)
        self.connection_options.toggled.connect(self.show_connection_options)
        layout.addWidget(self.connection_options, 0, Qt.AlignmentFlag.AlignLeft)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(2, 4, 2, 4)
        advanced_layout.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(label("Identification method", "fieldLabel"))
        self.profile = QComboBox()
        self.profile.addItem("Automatic identification", "auto")
        self.profile.addItem("TI bq40z50-R3 · experimental", "ti_bq40z50")
        self.profile.addItem("Standard SBS · basic readings only", "sbs")
        self.profile.addItem("TI BQ · identify controller", "ti_bq")
        row.addWidget(self.profile, 1)
        advanced_layout.addLayout(row)
        self.profile_hint = label("Read battery also identifies supported controllers and reads their access state and cell voltages.", "muted")
        self.profile_hint.setWordWrap(True)
        advanced_layout.addWidget(self.profile_hint)
        row = QHBoxLayout()
        row.addWidget(label("Controller memory access", "fieldLabel"))
        self.security_value = label("Unknown", "batteryValue")
        row.addWidget(self.security_value, 1)
        self.security_button = button("Unseal", self.access_clicked, "small")
        self.security_button.hide()
        row.addWidget(self.security_button)
        advanced_layout.addLayout(row)
        note = label("Seal / Unseal protects controller settings. It does not clear battery faults.", "muted")
        note.setWordWrap(True)
        advanced_layout.addWidget(note)
        row = QHBoxLayout()
        row.addWidget(label("Full access requires this battery's keys and a supported service profile.", "muted"), 1)
        self.full_access_button = button("Full access…", lambda: self.start_service("full_access"), "small")
        self.full_access_button.hide()
        row.addWidget(self.full_access_button)
        advanced_layout.addLayout(row)
        advanced_layout.addWidget(label("Connection settings", "fieldLabel"))
        connection = QWidget()
        advanced = QGridLayout(connection)
        advanced.setContentsMargins(0, 2, 0, 4)
        self.sda, self.scl = ConnectionSpinBox(), ConnectionSpinBox()
        for widget, key, default in ((self.sda, "sda", 7), (self.scl, "scl", 9)):
            widget.setRange(0, 28)
            widget.setPrefix("GP")
            widget.setValue(self.settings.value(f"battery/{key}", default, type=int))
            widget.setToolTip("Supported GPIOs: 0–22 and 26–28")
        self.address = ConnectionSpinBox()
        self.address.setRange(8, 0x77)
        self.address.setDisplayIntegerBase(16)
        self.address.setPrefix("0x")
        self.address.setValue(self.settings.value("battery/address", 0x0B, type=int))
        self.pec = QComboBox()
        for text, value in (("Automatic", "auto"), ("Require PEC", "on"), ("No PEC", "off")):
            self.pec.addItem(text, value)
        for col, (title, control) in enumerate((("DATA", self.sda), ("CLOCK", self.scl),
                                               ("Address · 7-bit", self.address), ("Checksum", self.pec))):
            advanced.addWidget(label(title, "fieldLabel"), 0, col)
            advanced.addWidget(control, 1, col)
        self.pullups = QCheckBox("Internal pull-ups")
        self.pullups.setChecked(True)
        self.pullups.setToolTip("Weak pull-ups for short test leads.")
        advanced.addWidget(self.pullups, 2, 0, 1, 4)
        advanced_layout.addWidget(connection)
        advanced_layout.addWidget(label("Diagnostic data", "fieldLabel"))
        self.details = table(["Reported parameter", "Value", "Raw"])
        self.details.setFixedHeight(220)
        advanced_layout.addWidget(self.details)
        layout.addWidget(self.advanced)
        self.advanced.hide()
        layout.addStretch()
        self.sections.addTab(self.controller_scroll, "Controller")

    def _connect_controls(self):
        self.sections.currentChanged.connect(lambda _index: self.stop_monitor())
        self.battery_choice.entry_selected.connect(self.reference_changed)
        for widget in (self.sda, self.scl, self.address):
            widget.valueChanged.connect(self.configuration_changed)
        for widget in (self.profile, self.pec):
            widget.currentIndexChanged.connect(self.configuration_changed)
        self.pullups.toggled.connect(self.configuration_changed)
        self.plot_metric.currentIndexChanged.connect(self.change_plot)

    def show_connection_options(self, checked):
        self.advanced.setVisible(checked)
        self.connection_options.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def note(self, text):
        self.messages.append(str(text))
        self.messages = self.messages[-100:]

    def set_feedback(self, text, tone="", details=""):
        self.status.setText(text)
        self.status.setToolTip(details or text)
        self._error_details = details
        self.feedback_details.setVisible(bool(details))
        self._tone(self.status, tone)

    @staticmethod
    def _tone(widget, value):
        if widget.property("tone") != value:
            widget.setProperty("tone", value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def show_feedback_details(self):
        message = QMessageBox(self)
        message.setWindowTitle("Battery operation")
        message.setIcon(QMessageBox.Icon.Information)
        message.setText(self.status.text())
        message.setDetailedText(self._error_details)
        message.exec()

    def reference_changed(self, entry):
        self._configuration_revision += 1
        self.stop_monitor()
        self.reset_profile()
        self.entry = entry
        self.diagram.mirrored = False
        self.refresh_wiring()
        if self.snapshot is not None:
            self.latest_valid = False
            self.mark_previous_reading()
            self.details.setRowCount(0)
            self.controller_details.setText("Controller not identified · read again.")
            self.render_condition()
            self.set_feedback("Wiring reference changed · read the connected battery again.")
        self.update_controls()

    def reset_profile(self):
        # A different pack/adapter must not inherit another pack's OEM queries.
        blocked = self.profile.blockSignals(True)
        self.profile.setCurrentIndex(0)
        self.profile.blockSignals(blocked)
        self.profile_hint.setText("Read battery also identifies supported controllers and reads their access state and cell voltages.")

    def port_changed(self, *args):
        self.reset_profile()
        self.configuration_changed()

    def refresh_wiring(self):
        self.diagram.set_entry(self.entry, self.sda.value(), self.scl.value())
        self.connection_hint.setText(f"DATA GP{self.sda.value()} · CLOCK GP{self.scl.value()} · GND\nB+ stays disconnected")
        if not self.entry:
            self.wiring_meta.setText("No connector reference selected.")
            self.wiring_meta.setToolTip("A battery can still be read using a separately confirmed pinout.")
            return
        entry = self.entry
        count = len(entry["pins"])
        certainty = "communication verified" if entry["verification"] == "communication_verified" else "source documented"
        if entry.get("pin_count_inferred"):
            certainty = "source positions · confirm connector"
        self.wiring_meta.setText(f"{count} positions · {certainty}")
        self.wiring_meta.setToolTip(entry["orientation"] + "\n" + entry.get("notes", "") +
                                  "\nRight-click the connector for details and its source.")

    def connector_menu(self, point):
        if not self.entry:
            return
        menu = QMenu(self)
        mirror = menu.addAction("Mirror connector")
        mirror.setCheckable(True)
        mirror.setChecked(self.diagram.mirrored)
        mirror.triggered.connect(self.mirror_view)
        menu.addAction("Connector details…", lambda: self.show_contact())
        menu.addAction("Open source", self.open_source)
        menu.exec(self.diagram.mapToGlobal(point))

    def mirror_view(self, checked=False):
        self.diagram.mirrored = not self.diagram.mirrored
        self.diagram.update()

    def open_source(self):
        if self.entry:
            QDesktopServices.openUrl(QUrl(self.entry["sources"][0]["url"]))

    def show_contact(self, number=None):
        if not self.entry:
            return
        lines = []
        for pin in self.entry["pins"]:
            target, purpose = connection_for(pin, self.entry, self.sda.value(), self.scl.value())
            lines.append(f"{pin['number']}: {pin['label']} → {target} · {purpose}")
        message = QMessageBox(self)
        message.setWindowTitle(self.entry["model"] + " · connector")
        message.setText(lines[number - 1] if number else self.entry["orientation"])
        message.setDetailedText("\n".join(lines) + "\n\n" + self.entry.get("notes", ""))
        message.exec()

    def configuration_changed(self, *args):
        self._configuration_revision += 1
        self.stop_monitor()
        self.latest_valid = False
        self.details.setRowCount(0)
        self.controller_details.setText("Controller not identified · read again.")
        for key, widget in (("sda", self.sda), ("scl", self.scl), ("address", self.address)):
            self.settings.setValue(f"battery/{key}", widget.value())
        self.refresh_wiring()
        self.render_condition()
        if self.snapshot is not None:
            self.mark_previous_reading()
            self.set_feedback("Connection settings changed · read the battery again.")
        self.profile_hint.setText(
            "Experimental R3 profile · identify before access operations; this battery's keys are required."
            if self.profile.currentData() == "ti_bq40z50" else
            "Standard SBS only · controller diagnostics disabled." if self.profile.currentData() == "sbs" else
            "Read battery also identifies supported controllers and reads their access state and cell voltages.")
        if not self.pins_valid():
            self.set_feedback("Select two different GPIOs from 0–22 or 26–28.", "error")
        self.update_controls()

    def mark_previous_reading(self):
        self.identity_subtitle.setText(
            f"Previous reading · {self.snapshot.strings.get('manufacturer', 'Smart battery')} · {self.snapshot.timestamp}")

    def pins_valid(self):
        available = (*range(23), 26, 27, 28)
        return self.sda.value() != self.scl.value() and all(
            value in available for value in (self.sda.value(), self.scl.value()))

    def service_permitted(self, action):
        chip = self.snapshot.controller if self.snapshot else {}
        ready = (not self.controller.busy and not self.monitoring and self.latest_valid
                 and chip.get("service_supported") and self.snapshot.pec
                 and self.profile.currentData() in ("auto", "ti_bq40z50", "ti_bq")
                 and self.snapshot.profile == "ti_bq40z50")
        state = chip.get("security")
        if action == "clear_pf":
            return bool(ready and not recovery_unavailable(chip))
        return bool(ready and {"unseal": state == "Sealed", "full_access": state == "Unsealed",
                              "seal": state in ("Unsealed", "Full access")}.get(action, False))

    def update_controls(self):
        busy = self.controller.busy
        live_read = self.live_read_in_progress()
        foreground_busy = busy and not live_read
        configurable = not foreground_busy
        configured = self.port.currentData() is not None and self.pins_valid()
        for control in (self.battery_choice, self.sda, self.scl,
                        self.address, self.pec, self.pullups, self.profile):
            control.setEnabled(configurable)
        self.read_button.setEnabled(not busy and not self.monitoring and configured)
        action = getattr(self.controller.worker, "action", "")
        self.read_button.setText("Reading…" if busy and action == "battery_read" and not live_read else "Read battery")
        for control in (self.access_button, self.controller_access_button):
            control.setText("Unlocking…" if busy and action == "battery_clear_pf" else "Unlock battery")
            control.setEnabled(self.service_permitted("clear_pf"))
        self.security_button.setText(
            {"battery_unseal": "Unsealing…", "battery_seal": "Sealing…"}.get(action) if busy and
            action in ("battery_unseal", "battery_seal") else "Unseal" if self._access_action == "unseal" else "Seal")
        self.security_button.setEnabled(self.service_permitted(self._access_action))
        self.monitor_button.setEnabled(self.monitoring or (not busy and configured))
        self.monitor_button.setText("Stop" if self.monitoring else "Stopping…" if live_read else "Live readings")
        self.monitor_button.setAccessibleName("Stop live readings" if self.monitoring else "Live readings")
        self.monitor_button.setChecked(self.monitoring)
        self.export_button.setVisible(self.snapshot is not None)
        self.export_button.setEnabled(self.snapshot is not None and not foreground_busy)
        self.full_access_button.setEnabled(self.service_permitted("full_access"))
        self.state_changed.emit()

    def start(self, action, keys=None):
        if self.controller.busy or self.port.currentData() is None or not self.pins_valid():
            return
        live_read = self.monitoring and action in ("battery_read", "battery_poll")
        self.set_feedback("Live readings · updating…" if live_read else "Reading battery…" if action in ("battery_read", "battery_poll")
                          else "Checking battery identity and clearing PF lockout…" if action == "battery_clear_pf"
                          else "Checking identity and applying the access request…")
        worker = BatteryWorker(
            action, self.port.currentData(), (self.sda.value(), self.scl.value()),
            self.pullups.isChecked(), self.pec.currentData(), address=self.address.value(),
            profile=self.profile.currentData(),
            expected=self.snapshot if action != "battery_read" else None, keys=keys)
        worker.interface_generation = self.port.generation
        worker.live_read = live_read
        worker.battery_context = {
            "configuration": self._configuration_revision, "reference": self.entry,
            "pins": (self.sda.value(), self.scl.value()), "address": self.address.value(),
        }
        worker.finished.connect(self.on_finished)
        worker.failed.connect(self.on_failed)
        if not self.controller.start(worker):
            worker.deleteLater()

    def toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
        elif not self.controller.busy and self.port.currentData() is not None and self.pins_valid():
            self.monitoring = True
            self.timer.start()
            self.start("battery_poll" if self.latest_valid else "battery_read")
            self.update_controls()

    def stop_monitor(self):
        was_monitoring = self.monitoring
        self.timer.stop()
        self.monitoring = False
        if was_monitoring:
            self.set_feedback("Stopping live readings · finishing current read…" if self.live_read_in_progress() else
                              "Live readings stopped · last measurement retained." if self.snapshot else "Live readings stopped.")
        if hasattr(self, "monitor_button"):
            self.update_controls()

    def poll(self):
        if self.monitoring and not self.controller.busy:
            self.start("battery_poll")

    def live_read_in_progress(self):
        return self.controller.busy and getattr(self.controller.worker, "live_read", False) is True

    def render_condition(self):
        chip = self.snapshot.controller if self.snapshot and self.latest_valid else {}
        security = chip.get("security")
        self._access_action = {"Sealed": "unseal", "Unsealed": "seal", "Full access": "seal"}.get(security)
        state = battery_status(chip)
        self.access_value.setText(state["label"])
        tone = "success" if state["state"] == "unlocked" else "" if state["state"] == "unknown" else "warning"
        self._tone(self.access_value, tone)
        self.access_hint.setText(state["reason"])
        self.access_hint.setToolTip(state["reason"])
        self.identify_link.setVisible(state["state"] == "unknown")
        supported = bool(chip.get("service_supported"))
        for control in (self.access_button, self.controller_access_button):
            control.setVisible(state["state"] == "locked")
            control.setToolTip(recovery_unavailable(chip) or "Clear stored PF data and verify battery operation.")
        self.security_value.setText(security or "Unknown")
        self.security_button.setVisible(bool(self._access_action) and supported)
        self.full_access_button.setVisible(supported and security == "Unsealed")
        cells = chip.get("cells_mV")
        self.cells.set_voltages(cells)
        active = [v for v in cells or [] if v]
        if len(active) >= 2:
            spread = max(active) - min(active)
            # A visible comparison reference, not an OEM pass/fail specification.
            self.balance_value.setText(f"Δ {spread} mV · {'within' if spread <= 50 else 'over'} 50 mV")
            self._tone(self.balance_value, "success" if spread <= 50 else "warning")
            self.balance_value.setToolTip("50 mV is a display comparison reference, not the manufacturer's limit. Interpret at the battery's charge state and load.")
        else:
            self.balance_value.setText("Unknown" if not active else "Not applicable · one cell")
            self._tone(self.balance_value, "")
            self.balance_value.setToolTip(chip.get("diagnostic_errors", {}).get("cells", chip.get("note", "Balance cannot be inferred from the total pack voltage.")))
        self.render_controller(chip)

    def render_controller(self, chip):
        identified = bool(chip.get("device_type") or chip.get("name"))
        self.controller_help.setVisible(not identified)
        self.controller_badge.setText("Identified" if identified else "Read again" if self.snapshot else "Not read")
        self.controller_badge.setProperty("state", "connected" if identified else "idle")
        self.controller_badge.style().unpolish(self.controller_badge)
        self.controller_badge.style().polish(self.controller_badge)
        firmware = chip.get("firmware_display", chip.get("firmware", "Not reported"))
        self.controller_details.setText(
            f"{chip.get('name', 'Controller')} · firmware {firmware}" if identified else "Controller not identified")
        self.controller_details.setToolTip(chip.get("note", ""))
        self.controller_help.setText(
            "Identity read from the connected battery." if identified else
            "This battery needs a supported identification method. See Advanced." if self.latest_valid else
            "Use Read battery above to identify the connected controller.")
        state = battery_status(chip)
        self.controller_access_value.setText(state["label"] if self.latest_valid else "Not read")
        self._tone(self.controller_access_value, "success" if state["state"] == "unlocked" else
                   "" if state["state"] == "unknown" else "warning")
        self.controller_access_help.setText(state["reason"])
        self.controller_service_note.setText(
            recovery_unavailable(chip) or "Unlock resets PF diagnostics, resets the controller and verifies the result."
            if state["state"] == "locked" else
            "Safety protections follow their own recovery conditions; Unseal does not clear them."
            if state["state"] == "protected" else "")
        self.controller_service_note.setVisible(bool(self.controller_service_note.text()))
        self._tone(self.controller_service_note, "warning" if state["state"] == "locked" else "")
        cells = [v for v in chip.get("cells_mV", []) if v]
        self.controller_cells.setText(
            f"{len(cells)} cells read · difference {max(cells) - min(cells)} mV" if len(cells) >= 2 else
            "1 cell read" if cells else "Not available" if self.latest_valid else "Not read")
        safety, failure = chip.get("safety"), chip.get("permanent_failure")
        self.controller_protection.setText(
            "Permanent fault reported" if failure else "Protection active" if safety else
            "No faults reported" if safety == 0 and failure == 0 else
            "Partially checked" if safety is not None or failure is not None else
            "Not available" if self.latest_valid else "Not read")
        self._tone(self.controller_protection, "warning" if failure or safety else
                   "success" if safety == 0 and failure == 0 else "")

    def on_finished(self, action, snapshot):
        if self.snapshot is None or self.snapshot.identity != snapshot.identity:
            self.history.clear()
            self.plot.reset_ranges()
        self.snapshot, self.latest_valid = snapshot, True
        context = getattr(self.controller.worker, "battery_context", None)
        current_configuration = (not isinstance(context, dict) or
                                 context["configuration"] == self._configuration_revision)
        if (self.port.currentData() is None or
                getattr(self.controller.worker, "interface_generation", self.port.generation)
                != self.port.generation):
            self.latest_valid = False
        if not current_configuration:
            self.latest_valid = False
        self.snapshot_reference = context["reference"] if isinstance(context, dict) else self.entry
        metrics = snapshot.metrics
        self.history.append({"timestamp": snapshot.timestamp, "metrics": metrics})
        self.history = self.history[-10000:]
        self.plot.history = self.history
        self.plot.update()
        for key, card in self.cards.items():
            value = metrics.get(key)
            text = "—" if value is None else f"{value:.3f}" if key in ("voltage", "current") else (
                f"{value:.1f}" if key in ("temperature", "health") else f"{value:.0f}")
            card.set_value(text)
        self.summary.setText(snapshot.strings.get("device") or "Smart battery")
        time = datetime.fromisoformat(snapshot.timestamp).astimezone().strftime("%H:%M:%S")
        self.identity_subtitle.setText(f"{snapshot.strings.get('manufacturer', 'Manufacturer not reported')} · {snapshot.strings.get('chemistry', 'Chemistry not reported')} · read {time}")
        capacity = lambda key: f"{metrics[key]:g} {metrics['capacity_unit']}" if metrics[key] is not None else "Not reported"
        scale = 10 ** ((snapshot.raw(0x1A) >> 8) & 15)
        values = {
            "manufacturer": snapshot.strings.get("manufacturer", "Not reported"),
            "chemistry": snapshot.strings.get("chemistry", "Not reported"),
            "serial": str(snapshot.raw(0x1C)), "date": snapshot.manufacture_date,
            "remaining": capacity("remaining_capacity"), "full": capacity("full_capacity"),
            "design": capacity("design_capacity"),
            "design_voltage": f"{snapshot.raw(0x19) * scale / 1000:.3f} V" if snapshot.raw(0x19, None) is not None else "Not reported",
        }
        for key, value in values.items():
            self.info_values[key].setText(value)
            self.info_values[key].setToolTip(value)
        findings = diagnose(snapshot)
        warnings = [finding for finding in findings if finding["level"] == "warning"]
        shown = warnings or findings
        self.findings.setText(" · ".join(item["text"] for item in shown[:2]))
        self.findings.setToolTip("\n".join(item["text"] for item in findings))
        self.findings.show()
        self._tone(self.findings, "warning" if warnings else "")
        self.render_condition()
        self.populate_details()
        count=len(self.history)
        self.history_info.setText(f"{count} {'reading' if count == 1 else 'readings'} · latest {time} · {'PEC verified' if snapshot.pec else 'no PEC'}")
        self.set_feedback(f"{'Live · ' if self.monitoring else ''}Read complete · {time} · {'PEC verified' if snapshot.pec else 'PEC not used'}",
                          "success" if snapshot.pec else "")
        if action == "battery_clear_pf":
            self.set_feedback("PF recovery verified · battery reports Unlocked.", "success")
        elif action not in ("battery_read", "battery_poll"):
            self.set_feedback("Controller confirmed the requested access state.", "success")
        if self.live_read_in_progress() and not self.monitoring:
            self.set_feedback("Live readings stopped · last measurement retained.")
        if not self.latest_valid:
            self.set_feedback("Previous reading · connection settings changed. Read again." if not current_configuration else
                              "Previous reading · Pico disconnected. Read again after reconnecting.")
        self.update_controls()

    def parameter_value(self, reg):
        snapshot, metrics = self.snapshot, self.snapshot.metrics
        value = snapshot.raw(reg)
        for code, key, unit in ((0x08, "temperature", "°C"), (0x09, "voltage", "V"),
                                (0x0A, "current", "A"), (0x0D, "soc", "%")):
            if reg == code:
                return f"{metrics[key]:.3f} {unit}"
        for code, key in ((0x0F, "remaining_capacity"), (0x10, "full_capacity"), (0x18, "design_capacity")):
            if reg == code:
                return f"{metrics[key]:g} {metrics['capacity_unit']}"
        if reg in (0x11, 0x12, 0x13):
            return "Not available" if value == 0xFFFF else f"{value} min"
        if reg == 0x0B:
            scale = 10 ** ((snapshot.raw(0x1A) >> 12) & 15)
            return f"{signed(value) * scale / 1000:.3f} A"
        if reg == 0x14:
            return f"{value} mA"
        if reg == 0x15:
            return f"{value / 1000:.3f} V"
        if reg == 0x19:
            return self.info_values["design_voltage"].text()
        if reg == 0x1B:
            return snapshot.manufacture_date
        return str(value)

    def populate_details(self):
        rows = [(name.replace("_", " ").title(), str(value), "")
                for name, value in self.snapshot.controller.items()]
        for reg, name in WORDS.items():
            if f"{reg:02X}" in self.snapshot.words:
                rows.append((name, self.parameter_value(reg), f"0x{self.snapshot.raw(reg):04X}"))
        rows.extend((name, "Not reported", error) for name, error in self.snapshot.errors.items())
        self.details.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, text in enumerate(values):
                self.details.setItem(row, col, QTableWidgetItem(text))

    def on_failed(self, message):
        self.stop_monitor()
        self.latest_valid = False
        self.render_condition()
        context = getattr(self.controller.worker, "battery_context", None)
        pins = context["pins"] if isinstance(context, dict) else (self.sda.value(), self.scl.value())
        address = context["address"] if isinstance(context, dict) else self.address.value()
        hints = {
            "SMB_CLOCK_DRIVE": f"CLOCK GP{pins[1]} could not be driven LOW · check GPIO selection and wiring.",
            "SMB_DATA_DRIVE": f"DATA GP{pins[0]} could not be driven LOW · check GPIO selection and wiring.",
            "SMB_ADDRESS_NACK": f"No battery reply at 0x{address:02X} · check address, DATA, CLOCK and GND.",
            "SMB_PEC": "Checksum mismatch · reading rejected; check the wiring.",
            "SMB_CLOCK_TIMEOUT": "CLOCK stayed LOW · check its connection and pull-ups.",
        }
        text = next((hint for code, hint in hints.items() if code in message), "Battery operation failed · open Details.")
        self.set_feedback(text, "error", message)
        self.note(message)
        self.update_controls()

    def change_plot(self):
        self.plot.metric_key = self.plot_metric.currentData()
        self.plot.update()

    def access_clicked(self):
        if self._access_action:
            self.start_service(self._access_action)

    def unlock_battery_clicked(self):
        self.start_service("clear_pf")

    def start_service(self, action):
        if not self.service_permitted(action):
            return
        self.stop_monitor()
        keys = None
        stages = (action,) if action in ("unseal", "full_access") else ()
        if action == "clear_pf":
            state = self.snapshot.controller.get("security")
            stages = ("unseal", "full_access") if state == "Sealed" else (("full_access",) if state == "Unsealed" else ())
            keys = {}
        for stage in stages:
            dialog = KeyDialog("Unseal controller" if stage == "unseal" else "Full access", self)
            try:
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                pair = dialog.keys()
                if action == "clear_pf":
                    keys[stage] = pair
                else:
                    keys = pair
            except ValueError as exc:
                self.set_feedback(str(exc), "error")
                return
            finally:
                for field in dialog.fields:
                    field.clear()
                dialog.deleteLater()
        text = {
            "unseal": "Unseal controller settings using the supplied keys? Battery protection faults are unchanged.",
            "full_access": "Request full controller access using the supplied keys?",
            "seal": "Seal controller settings? Battery operational status is unchanged.",
            "clear_pf": "Experimental bq40z50-R3 recovery: clear stored PF diagnostics and reset the controller after the fault has been repaired? "
                        "The current diagnostic snapshot is retained in the result. Battery operation must be verified before success is reported.",
        }[action]
        if QMessageBox.question(self, "Confirm controller access", text,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        if self.service_permitted(action):
            self.start("battery_" + action, keys)

    def export_report(self, kind="pdf"):
        if self.snapshot is None:return
        snapshot=self.snapshot;history=list(self.history);entry=self.snapshot_reference
        path,chosen=QFileDialog.getSaveFileName(self,"Save battery report",str(Path(self.settings.value("battery/report_dir",str(Path.home()))) / ("battery-report." + kind)),
                    "PDF report (*.pdf);;JSON diagnostic snapshot (*.json);;CSV measurement history (*.csv)",
                    {"pdf":"PDF report (*.pdf)","json":"JSON diagnostic snapshot (*.json)","csv":"CSV measurement history (*.csv)"}[kind])
        if not path:return
        try:
            target=Path(path)
            if not target.suffix:
                target=target.with_suffix(".json" if "JSON" in chosen else ".csv" if "CSV" in chosen else ".pdf")
            data=snapshot.export()
            if entry:data["connector_reference"]={key:entry[key] for key in ("model","manufacturer","sources","verification","orientation")}
            if target.suffix.lower()==".json":target.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
            elif target.suffix.lower()==".csv":
                with target.open("w",newline="",encoding="utf-8-sig") as handle:
                    writer=csv.writer(handle);writer.writerow(["timestamp_utc","voltage_V","current_A","temperature_C","soc_percent","reported_health_percent","cycles"])
                    for point in history:writer.writerow([point["timestamp"],*[point["metrics"].get(key) for key in ("voltage","current","temperature","soc","health","cycles")]])
            elif target.suffix.lower()==".pdf":
                e=lambda value:html.escape(str(value))
                rows="".join(f"<tr><td>{e(key.replace('_',' ').title())}</td><td>{e(value)}</td></tr>" for key,value in snapshot.metrics.items())
                findings="".join(f"<li>{e(item['text'])}</li>" for item in diagnose(snapshot))
                controller=""
                if snapshot.controller:
                    controller="<h2>Controller diagnostics</h2><table width='100%'>"+"".join(f"<tr><td>{e(key)}</td><td>{e(value)}</td></tr>" for key,value in snapshot.controller.items())+"</table>"
                operation = data["battery_status"]
                controller = (f"<h2>Battery operation</h2><p>{e(operation['label'])}: {e(operation['reason'])}</p>"
                              f"<p>Controller memory access: {e(snapshot.controller.get('security', 'Unknown'))}</p>" + controller)
                document=QTextDocument();document.setHtml(f"<style>body{{font-family:Segoe UI;color:#18283a}}h1{{color:#176f87}}td{{padding:7px;border-bottom:1px solid #dde3e9}}</style><h1>Battery diagnostic report</h1><p>{e(snapshot.strings.get('manufacturer',''))} {e(snapshot.strings.get('device',''))}</p><p>Read at {e(snapshot.timestamp)} · serial {snapshot.raw(0x1C)} · PEC {'verified' if snapshot.pec else 'not validated'}</p><table width='100%'>{rows}</table>{controller}<h2>Findings</h2><ul>{findings}</ul><p>{e(data['capacity_note'])}</p><p>Software by R89 Repairs</p>")
                writer=QPdfWriter(str(target));writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4));document.print_(writer)
                if not target.is_file() or target.stat().st_size<100:raise OSError("PDF output could not be created")
            else:raise ValueError("Choose PDF, JSON or CSV")
            self.settings.setValue("battery/report_dir",str(target.parent));self.note(f"Report saved: {target}");self.set_feedback(f"Report saved · {target.name}", "success")
        except Exception as exc:self.set_feedback("Report could not be saved.", "error", str(exc))

