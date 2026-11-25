# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Spark: EC and PD programming and battery diagnostics in one application."""

import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt, QUrl, QCoreApplication, QEvent, QTemporaryDir
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog,
    QMessageBox, QVBoxLayout,
)

from .ec import save_new
from .models import FAMILIES_BY_MANUFACTURER
from .ene_models import ene_model
from .wiring_diagram import WiringDiagram
from .style import STYLESHEET
from .gui_layout import build_layout, InterfaceBar, WorkspaceTabs
from .battery_gui import BatteryPage
from .pd_gui import PDPage
from .interface import InterfaceState, InterfaceDiscovery

from .operations import Worker, resolve_read_size
from .controller import OperationController
from .session import validate_ite_pins
from .version import APP_NAME, VERSION, BUILD_ID
from .window_chrome import SparkWindow


class Window(SparkWindow):
    def __init__(self, settings=None, auto_discovery=True):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} · {VERSION}")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumSize(840, 560)
        available = self.screen().availableGeometry()
        self.resize(min(1040, available.width() - 40), max(560, min(790, available.height() - 60)))
        # Keep existing connection settings and directories across the Spark rename.
        self.settings = settings if settings is not None else QSettings("R89 Repairs", "EC Programmer")
        self.saved_path = None
        self._phase_started = None
        self._phase_done = self._phase_total = 0
        self._foreground_action = None
        self._operation_active = False
        self._result_tone = ""
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(500)
        self.progress_timer.timeout.connect(self.update_timing)
        self.controller = OperationController(self)
        self.controller.started.connect(self.update_buttons)
        self.controller.idle.connect(self.on_thread_finished)
        self._close_when_idle = False
        self._shutdown_complete = False
        self._pending_operation = None
        self.power_prompt = None
        self.pending_read = None
        self.pending_identity = None
        self.connected_identity = None
        self.connected_protocol = None
        self._manual_flash_size_kib = 0
        self.keepalive = QTimer(self)
        self.keepalive.setInterval(5000)
        self.keepalive.timeout.connect(self.refresh_debug_hold)

        self.port = InterfaceState(self)
        self.interface_bar = InterfaceBar(self.port)
        build_layout(self)
        ec_page = self.takeCentralWidget()
        self.workspaces = WorkspaceTabs(self.interface_bar)
        self.workspaces.addTab(ec_page, "EC Programmer")
        self.pd = PDPage(self.controller, self.settings, self.interface_bar)
        self.pd.state_changed.connect(self.update_buttons)
        self.workspaces.addTab(self.pd, "PD Controller")
        self.battery = BatteryPage(self.controller, self.settings, self.interface_bar)
        self.battery.state_changed.connect(self.update_buttons)
        self.workspaces.addTab(self.battery, "Battery Analyzer")
        self.setCentralWidget(self.workspaces)
        self.workspaces.currentChanged.connect(self.on_workspace_changed)

        self.port.changed.connect(self.on_interface_changed)
        self.manufacturer.currentIndexChanged.connect(self.on_manufacturer_changed)
        self.model.currentIndexChanged.connect(self.on_model_changed)
        self.sda.valueChanged.connect(self.reset_identity)
        self.scl.valueChanged.connect(self.reset_identity)
        self.flash_size.valueChanged.connect(self.on_flash_size_changed)
        self.discovery = InterfaceDiscovery(
            self.port, self.controller, self.settings,
            lambda: self._pending_operation is None
            and not self._close_when_idle and not self.battery.monitoring, self)
        self.discovery.stopped.connect(self.on_discovery_stopped)
        self.on_manufacturer_changed()
        self.note("Select a target and connect to the EC.")
        self.log.appendPlainText(f"{APP_NAME} {VERSION} | Build {BUILD_ID}")
        if auto_discovery:
            self.discovery.start()

    def note(self, message):
        self.log.appendPlainText(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}")

    def on_interface_changed(self):
        if self.port.device:
            self.settings.setValue("interface/port", self.port.currentData())
            self.settings.setValue("interface/serial", self.port.device.usb.serial)
        self.reset_identity()
        self.pd.port_changed()
        self.battery.port_changed()

    def update_buttons(self):
        idle = not self.controller.busy
        background_read = self.battery.live_read_in_progress()
        ui_ready = idle or background_read
        if hasattr(self, "workspaces"):
            self.workspaces.tabBar().setEnabled(ui_ready)
            for index in range(self.workspaces.count()):
                self.workspaces.setTabEnabled(index, (self.pending_read is None or index == 0)
                                              and (self.pd.pending_read is None or index == 1))
            self.pd.update_controls()
        config_enabled = ui_ready and self.pending_read is None and self._pending_operation is None
        port_selected = self.port.currentData() is not None
        profile = self.model.currentData()
        for control in (self.manufacturer, self.sda, self.scl):
            control.setEnabled(config_enabled)
        self.model.setEnabled(config_enabled and
                              self.manufacturer.currentText() in FAMILIES_BY_MANUFACTURER)
        self.flash_size.setEnabled(config_enabled and profile is not None and
                                   profile.fixed_flash_size is None)
        self.detect.setEnabled(config_enabled and port_selected and profile is not None)
        self.read.setEnabled(idle and self.pending_read is None and (port_selected and profile is not None and
                              profile.read_protocol and self.connected_identity is not None and
                              self.flash_size_bytes() in profile.flash_sizes))
        destructive_ready = (idle and self.pending_read is None and port_selected and
                             profile is not None and profile.read_protocol and
                             self.connected_identity is not None and
                             self.connected_protocol is not None and
                             self.flash_size_bytes() in profile.flash_sizes)
        self.write.setEnabled(destructive_ready)
        self.erase.setEnabled(destructive_ready)
        pending = self.pending_read is not None
        self.result_actions.setVisible(pending or self.saved_path is not None)
        self.save_read_button.setVisible(pending)
        self.discard_read_button.setVisible(pending)
        self.save_read_button.setEnabled(idle)
        self.discard_read_button.setEnabled(idle)
        self.open_folder_button.setVisible(not pending and self.saved_path is not None)
        if self._operation_active:
            hint = "Operation in progress"
        elif pending:
            hint = "Save the read or discard it to continue."
        elif not port_selected:
            hint = "Connect Pico by USB. The interface is detected automatically."
        elif self.manufacturer.currentIndex() < 0:
            hint = "Select a manufacturer."
        elif profile is None:
            hint = "Select a model / family."
        elif self.connected_identity is None:
            hint = "Check the wiring, then connect to the EC."
        elif not profile.read_protocol:
            hint = "Reads chip ID and revision only. Flash read/write/erase are not implemented for this family."
        elif self.flash_size_bytes() not in profile.flash_sizes:
            hint = "Select a supported flash size to enable operations."
        elif self.connected_protocol is None:
            hint = "Read is available; the write protocol could not be identified."
        else:
            hint = "Ready to read, write or erase."
        self.next_step.setText(hint)
        state = "busy" if self._operation_active else ("connected" if self.connected_identity else "idle")
        self.connection_badge.setText("Connecting…" if self._operation_active and self._foreground_action == "connect"
                                      else "Busy" if self._operation_active else
                                      "Connected" if self.connected_identity else "Disconnected")
        self.set_property(self.connection_badge, "state", state)

    @staticmethod
    def set_property(widget, key, value):
        if widget.property(key) != value:
            widget.setProperty(key, value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def set_status(self, text, tone=""):
        self.status.setText(text)
        self.status.setToolTip("")
        self._result_tone = tone
        self.set_property(self.status, "tone", tone)

    def begin_operation(self, action):
        self._foreground_action = action
        self._operation_active = True
        self.saved_path = None
        self._phase_started = None
        self._phase_done = self._phase_total = 0
        self.progress_timer.stop()
        self.set_status("Connecting to EC…" if action == "connect" else "Preparing operation…")
        self.percent.clear()
        self.transfer.clear()
        self.transfer.setToolTip("")
        self.timing.clear()
        self.progress.setRange(0, 0)
        self.progress.setFormat("")
        self.progress.setStyleSheet("QProgressBar::chunk { background: #226db4; }")
        self.progress.show()

    def set_progress_phase(self, phase):
        color = {"Erase": "#dc2626", "Programming": "#ea580c"}.get(phase, "#15803d")
        self.progress.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")
        label = {"Programming": "Writing", "Verification": "Verifying", "Erase": "Erasing", "Read": "Reading"}.get(phase, phase)
        self.set_status(label)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat(f"{phase}: %p%")
        self.progress.show()
        self.percent.setText("0%")
        self._phase_done = 0
        self._phase_total = self.flash_size_bytes() or 0
        self._phase_started = time.monotonic()
        self.set_transfer(0, self._phase_total)
        self.update_timing()
        self.progress_timer.start()

    def set_progress_value(self, value):
        self.progress.setValue(value)
        self.percent.setText(f"{value}%")

    def set_transfer(self, done, total):
        self._phase_done, self._phase_total = done, total
        self.transfer.setText(f"{done / 1024:g} / {total / 1024:g} KiB")
        self.update_timing()

    def update_timing(self):
        if self._phase_started is None:
            return
        elapsed = max(0, time.monotonic() - self._phase_started)
        text = f"{elapsed:.0f} s"
        if elapsed >= 3 and 0 < self._phase_done < self._phase_total and self._phase_done >= self._phase_total * .05:
            remaining = elapsed * (self._phase_total - self._phase_done) / self._phase_done
            text += f"  ·  ~{remaining:.0f} s remaining"
        self.timing.setText(text)

    def finish_progress(self, failed=False):
        self.progress_timer.stop()
        self.update_timing()
        if self._phase_started is not None:
            self.timing.setText(f"{max(0, time.monotonic() - self._phase_started):.0f} s")
        self._phase_started = None
        self._operation_active = False
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        if failed:
            self.progress.setStyleSheet("QProgressBar::chunk { background: #dc2626; }")
            self.percent.setText("Stopped")

    def on_worker_status(self, message):
        self.note(message)
        # Transport diagnostics stay in the log; only actionable power instructions
        # replace the current preparation status. A completed result is persistent.
        if self._operation_active and self._phase_started is None:
            if "Power off detected" in message:
                self.set_status("Power off detected - reconnect target power")
            elif "Power cycle captured" in message:
                self.set_status("Power detected - connecting to EC…")
            elif "Pico is armed" in message:
                self.set_status("Waiting for target power cycle")

    def failure_summary(self, message):
        action = getattr(self.controller.worker, "action", "operation")
        title = {"connect": "Connection failed", "read": "Read failed", "write": "Write stopped",
                 "erase": "Erase stopped", "keepalive": "Connection lost"}.get(action, "Operation failed")
        lower = message.lower()
        if "after erase began" in lower:
            return f"{title} - flash may be incomplete; see log"
        if "nack" in lower or "no_device" in lower or "no ack" in lower:
            return f"{title} - EC did not respond"
        if "timeout" in lower:
            return f"{title} - communication timed out"
        if "usb" in lower:
            return f"{title} - check the USB connection"
        return f"{title} - see log for details"

    def last_directory(self, kind):
        value = self.settings.value(f"directories/{kind}", str(Path.home()))
        path = Path(str(value))
        return path if path.is_dir() else Path.home()

    def remember_directory(self, kind, filename):
        self.settings.setValue(f"directories/{kind}", str(Path(filename).resolve().parent))

    def open_saved_folder(self):
        if self.saved_path is not None:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved_path.resolve().parent))):
                self.note(f"Could not open folder: {self.saved_path.parent}")

    def discard_read(self):
        if self.pending_read is None or self.controller.busy:
            return
        if QMessageBox.question(self, "Discard unsaved read", "Discard the read held in memory?",
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                               QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.pending_read = self.pending_identity = None
        self.set_status("Read discarded")
        self.note("Unsaved read discarded.")
        self.update_buttons()

    def reset_identity(self):
        self.keepalive.stop()
        self.connected_identity = None
        self.connected_protocol = None
        if not self._operation_active and self.status.text() == "EC connected":
            self.set_status("Ready")
        self.update_identity_label()
        self.update_buttons()

    def flash_size_bytes(self):
        return self.flash_size.value() * 1024 or None

    def update_identity_label(self):
        size = self.flash_size_bytes()
        profile = self.model.currentData()
        if profile is not None and profile.fixed_flash_size is not None:
            source = "model default"
            selected = f"{size // 1024} KiB ({source})"
        elif size and profile is not None and size not in profile.flash_sizes:
            selected = f"{size // 1024} KiB (unsupported size)"
        else:
            selected = f"{size // 1024} KiB selected" if size else "Size not selected"
        if self.connected_identity is None:
            self.identity.setText(f"EC not connected  |  {selected}")
            self.identity_details.setText(" ")
            return
        chip, version = self.connected_identity
        if self.manufacturer.currentText() == "ENE":
            self.identity.setText(f"Connected  |  {self.model.currentText()}  |  {selected}")
            self.identity_details.setText(f"HW 0x{chip:02X}  /  EDI 0x{version:02X}")
        else:
            self.identity.setText(f"Connected  |  {self.model.currentText()}  |  {selected}")
            self.identity_details.setText(f"CHIP ID 0x{chip:04X}  /  REV 0x{version:02X}")

    def on_flash_size_changed(self):
        profile = self.model.currentData()
        if profile is not None and profile.fixed_flash_size is None:
            self._manual_flash_size_kib = self.flash_size.value()
        self.update_identity_label()
        self.update_buttons()

    def create_wiring_dialog(self):
        profile = self.model.currentData()
        model = ene_model(profile.name) if profile and profile.transport == "ene_edi" else None
        if model is None:
            return None
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{model.name} - Wiring diagram")
        dialog.setStyleSheet("QDialog { background: #191e26; }")
        layout = QVBoxLayout(dialog)
        diagram = WiringDiagram()
        diagram.set_model(model)
        layout.addWidget(diagram)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(900, 300)
        return dialog

    def show_wiring_diagram(self, _link=None):
        dialog = self.create_wiring_dialog()
        if dialog is not None:
            dialog.exec()
            dialog.deleteLater()

    def on_model_changed(self):
        # Known capacities are fixed by the group. Preserve the user's ITE
        # value separately so switching through ENE cannot overwrite it.
        profile = self.model.currentData()
        model = ene_model(profile.name) if profile and profile.transport == "ene_edi" else None
        self.ene_wiring.setVisible(model is not None)
        self.ene_wiring.setText(
            '<a href="wiring" style="color: #38bdf8;">View wiring diagram</a>' if model else "")
        self.ene_wiring.setToolTip(
            (f"Source: {model.source}. " if model else "") +
            "EC package pin numbers, not keyboard connector positions. "
            "Disconnect power before wiring. Connect KSO3 to ground before powering "
            "the target; use common Pico/board ground. Power the EC from its board."
        )
        fixed = profile.fixed_flash_size if profile else None
        self.flash_size.blockSignals(True)
        if fixed is not None:
            self.flash_size.setRange(fixed // 1024, fixed // 1024)
            self.flash_size.setSpecialValueText("")
            self.flash_size.setValue(fixed // 1024)
            self.flash_size.setToolTip("Flash size for the selected model.")
        else:
            self.flash_size.setRange(0, max(profile.flash_sizes) // 1024 if profile else 256)
            self.flash_size.setSpecialValueText("Set size")
            self.flash_size.setValue(self._manual_flash_size_kib if profile else 0)
            sizes = ", ".join(str(size // 1024) for size in profile.flash_sizes) if profile else ""
            self.flash_size.setToolTip(f"Enter the EC flash size in KiB. Supported sizes: {sizes}.")
        self.flash_size.blockSignals(False)
        self.reset_identity()

    def on_manufacturer_changed(self):
        families = FAMILIES_BY_MANUFACTURER.get(self.manufacturer.currentText(), ())
        ene = self.manufacturer.currentText() == "ENE"
        ite = self.manufacturer.currentText() == "ITE"
        for widget in (self.sda_field, self.scl_field):
            widget.setVisible(ite)
        self.ene_wiring.setVisible(ene)
        self.model.blockSignals(True)
        self.model.clear()
        for profile in families:
            self.model.addItem(profile.name, profile)
        self.model.setCurrentIndex(-1)
        self.model.blockSignals(False)
        self.on_model_changed()

    def start(self, action, image_path=None, confirmed=False):
        if self.controller.busy:
            if (action == "connect" and self.workspaces.currentIndex() == 0 and
                    self.battery.live_read_in_progress() and self.model.currentData() is not None and
                    self.port.currentData() is not None and self.pending_read is None):
                self._pending_operation = (action, image_path)
                self.battery.stop_monitor()
            return
        if self.workspaces.currentIndex() != 0 and action != "disconnect":
            return
        if action == "read" and self.pending_read is not None:
            self.save_read()
            return
        profile = self.model.currentData()
        if not profile or not self.port.currentData():
            return
        if action in ("connect", "read", "write", "erase"):
            self.battery.stop_monitor()
        if profile.transport == "ite":
            try:
                validate_ite_pins(self.sda.value(), self.scl.value())
            except ValueError as exc:
                QMessageBox.information(self, "Select GPIO pins", str(exc))
                return
        if action in ("read", "write", "erase") and self.connected_identity is None:
            return
        read_size = None
        if action == "read":
            try:
                read_size = resolve_read_size(self.flash_size_bytes(), profile)
            except ValueError as exc:
                QMessageBox.information(self, "Select flash size", str(exc))
                return
        if action in ("write", "erase"):
            if (self.connected_protocol is None or
                    self.flash_size_bytes() not in profile.flash_sizes):
                return
            if action == "write" and image_path is None:
                image_path, _ = QFileDialog.getOpenFileName(
                    self, "Select EC firmware image", str(self.last_directory("images")),
                    "Binary image (*.bin);;All files (*)"
                )
                if not image_path:
                    return
                self.remember_directory("images", image_path)
                try:
                    image_size = Path(image_path).stat().st_size
                except OSError as exc:
                    QMessageBox.critical(self, "Cannot open image", str(exc))
                    return
                if image_size != self.flash_size_bytes():
                    QMessageBox.critical(self, "Wrong image size",
                                         f"Expected {self.flash_size_bytes()} bytes; file has {image_size}.")
                    return
            label = "erase and write" if action == "write" else "erase"
            message = (f"This will {label} the EC flash. "
                       + ("The written image will be verified. " if action == "write" else "")
                       + "Continue?")
            if not confirmed and QMessageBox.question(self, "Confirm EC flash operation", message,
                                    QMessageBox.StandardButton.Yes |
                                    QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            # Native dialogs process Qt events. A keepalive may have acquired
            # USB while the user selected/confirmed the image. Queue behind it.
            if self.controller.busy:
                self._pending_operation = (action, image_path)
                return
            if self.connected_identity is None:
                return
        if action not in ("keepalive", "disconnect"):
            self.begin_operation(action)
            self.note("Connecting to EC..." if action == "connect" else "Checking the EC session...")
        worker = Worker(action, self.port.currentData(),
                        (self.sda.value(), self.scl.value()), profile,
                        self.connected_identity, image_path,
                        self.flash_size_bytes())
        worker.interface_generation = self.port.generation
        worker.progress.connect(self.set_progress_value)
        worker.transfer.connect(self.set_transfer)
        worker.phase.connect(self.set_progress_phase)
        worker.status.connect(self.on_worker_status)
        worker.power_cycle_needed.connect(self.show_power_cycle_prompt)
        worker.finished.connect(self.on_finished)
        worker.failed.connect(self.on_failed)
        worker.warning.connect(self.on_warning)
        self.controller.start(worker)

    def show_power_cycle_prompt(self):
        self.set_status("Waiting for target power cycle")
        continuation = ("Connection will continue automatically." if
                        self.controller.worker.action == "connect" else
                        "The operation will start automatically.")
        self.power_prompt = QMessageBox(
            QMessageBox.Icon.Information,
            "Power cycle the EC",
            "Pico is ready. If the laptop adapter is plugged in, unplug it for "
            "5 seconds, then reconnect it. If it is already unplugged, connect it now. "
            "Keep Pico and the EC wires connected. "
            + continuation, QMessageBox.StandardButton.Ok, self,
        )
        self.power_prompt.show()

    def on_finished(self, action, result):
        if self.power_prompt is not None:
            self.power_prompt.close()
            self.power_prompt.deleteLater()
            self.power_prompt = None
        if action == "keepalive":
            return
        if action == "disconnect":
            self.reset_identity()
            return
        self.finish_progress()
        current = (getattr(self.controller.worker, "interface_generation", self.port.generation)
                   == self.port.generation and self.port.currentData() is not None)
        if action == "connect":
            if not current:
                self.set_status("Pico disconnected. Connect again to identify the EC.", "warning")
                return
            (chip, version), hold_active, detected_protocol = result
            self.connected_identity = (chip, version)
            self.connected_protocol = detected_protocol
            self.update_identity_label()
            self.set_status("EC connected", "success")
            self.progress.hide()
            if detected_protocol:
                self.note(f"Flash protocol: {detected_protocol.name} ({detected_protocol.program_method})")
            if detected_protocol is not None and self.flash_size_bytes() in self.model.currentData().flash_sizes:
                self.note("EC connected. Read, Write and Erase are available.")
            elif self.model.currentData().read_protocol:
                if self.flash_size_bytes() in self.model.currentData().flash_sizes:
                    self.note("EC connected. Read is available for the selected size.")
                else:
                    self.note("EC connected. Select a flash size to enable Read.")
            else:
                self.note("EC identified. Read protocol for this family is not implemented yet.")
            if hold_active and self.model.currentData().read_protocol:
                self.keepalive.start()
            self.update_buttons()
        elif action == "read":
            identity, data = result
            self.update_identity_label()
            self.pending_read = data
            self.pending_identity = identity
            self.set_status("Read complete - not saved", "warning")
            self.update_buttons()
            self.note(f"Read complete: {len(data)} bytes. Choose where to save.")
            self.save_read()
        elif action in ("write", "erase"):
            self.set_status("Write completed - Verify OK" if action == "write" else "Erase completed", "success")
            self.note("Write complete and verified." if action == "write" else "Erase complete.")
            if current:
                self.connected_identity = result
            self.update_buttons()

    def save_read(self):
        if self.pending_read is None:
            return
        chip = self.pending_identity[0] if self.pending_identity else 0
        prefix = (f"ENE-{self.model.currentText().replace(' ', '')}-HW{chip:02X}" if self.manufacturer.currentText() == "ENE"
                  else f"ITE-{chip:04X}")
        suggested = self.last_directory("images") / (
            f"{prefix}-{len(self.pending_read) // 1024}KiB-"
            f"{datetime.now():%Y%m%d-%H%M%S}.bin"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save EC read", str(suggested), "Binary image (*.bin);;All files (*)"
        )
        if not path:
            self.note("Read is held in memory. Use Save or Discard.")
            self.set_status("Read complete - not saved", "warning")
            self.update_buttons()
            return
        try:
            digest = save_new(path, self.pending_read)
        except Exception as exc:
            QMessageBox.critical(self, "Backup not saved", str(exc))
            self.note("Read is still in memory. Use Save to choose another location.")
            self.set_status("Could not save - read is still in memory", "error")
            self.update_buttons()
            return
        self.pending_read = None
        self.pending_identity = None
        self.saved_path = Path(path)
        self.remember_directory("images", path)
        self.set_status("Read saved", "success")
        self.transfer.setText(self.saved_path.name)
        self.transfer.setToolTip(str(self.saved_path))
        self.note(f"Saved {path} | SHA-256 {digest}")
        self.update_buttons()

    def on_failed(self, message):
        if self.power_prompt is not None:
            self.power_prompt.close()
            self.power_prompt.deleteLater()
            self.power_prompt = None
        self.finish_progress(failed=True)
        self.set_status(self.failure_summary(message), "error")
        self.status.setToolTip(message)
        self.note("ERROR: " + message)
        self.reset_identity()
        if self.controller.worker.action in ("write", "erase"):
            QMessageBox.critical(self, "EC flash operation stopped", message)

    def on_warning(self, message):
        self.finish_progress(failed=True)
        self.set_status("Session cleanup failed - reconnect before continuing", "warning")
        self.status.setToolTip(message)
        self.note("WARNING: " + message)
        self.reset_identity()

    def refresh_debug_hold(self):
        if (self.workspaces.currentIndex() != 0 or self.controller.busy or self.battery.monitoring or self.connected_identity is None or
                self.manufacturer.currentText() == "ENE"):
            return
        self.start("keepalive")

    def on_workspace_changed(self, index):
        self.battery.stop_monitor()
        if index != 0:
            self.keepalive.stop()
            if self.connected_identity is not None:
                self.start("disconnect")
        self.update_buttons()

    def on_thread_finished(self):
        self.update_buttons()
        if self._close_when_idle:
            self._pending_operation = None
            self.close()
        elif self._pending_operation is not None:
            action, image_path = self._pending_operation
            self._pending_operation = None
            self.start(action, image_path, confirmed=True)

    def closeEvent(self, event):
        self.battery.stop_monitor()
        if self.controller.busy:
            if (self.controller.worker.action in ("keepalive", "disconnect", "interface_probe") or
                    self.controller.worker.action.startswith("battery_")):
                self._close_when_idle = True
                self.keepalive.stop()
                self.discovery.stop()
            else:
                QMessageBox.information(self, "Operation in progress", "Wait for it to finish.")
            event.ignore()
        elif self.pd.pending_read is not None:
            answer = QMessageBox.question(self, "Unsaved PD backup", "The PD read is not saved. Close and discard it?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
            else:
                self.pd.pending_read = None
                self.closeEvent(event)
        elif self.pending_read is not None:
            answer = QMessageBox.question(
                self, "Unsaved backup", "The read is not saved. Close and discard it?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
            else:
                self.pending_read = None
                self.pending_identity = None
                self.closeEvent(event)
        else:
            self.keepalive.stop()
            self.discovery.stop()
            if self.connected_identity is not None and not self._shutdown_complete:
                self._shutdown_complete = True
                self._close_when_idle = True
                self.start("disconnect")
                event.ignore()
            elif self.discovery.thread is not None:
                self._close_when_idle = True
                event.ignore()
            else:
                event.accept()

    def on_discovery_stopped(self):
        if self._close_when_idle and not self.controller.busy:
            self.close()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("R89 Repairs")
    app.setApplicationVersion(VERSION)
    app.setStyle("Fusion")
    smoke_test = "--smoke-test" in sys.argv
    settings_directory = QTemporaryDir() if smoke_test else None
    if settings_directory is not None and not settings_directory.isValid():
        raise RuntimeError("Could not create isolated startup-test settings")
    test_settings = (QSettings(str(Path(settings_directory.path()) / "startup.ini"), QSettings.Format.IniFormat)
                     if settings_directory is not None else None)
    window = Window(settings=test_settings, auto_discovery=not smoke_test)
    window.show()
    if smoke_test:
        # Startup checks never open USB or read/write the user's settings.
        QTimer.singleShot(300, window.close)
    result = app.exec()
    # Dispose the widget tree while QApplication and its Qt services still
    # exist. Python/Qt reference cycles otherwise survive into interpreter
    # shutdown and can tear down styles/timers in the wrong order on Windows.
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if test_settings is not None:
        test_settings.sync()
        settings_directory.remove()
    return result
