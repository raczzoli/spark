# SPDX-License-Identifier: GPL-2.0-or-later
"""PD Controller workspace using the shared Pico interface and operation owner."""
from datetime import datetime
from pathlib import Path
import json
import time

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QSignalBlocker
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QComboBox, QSpinBox,
    QProgressBar, QPlainTextEdit, QFileDialog, QMessageBox,
)
from .gui_layout import label, panel, field, button
from .ec import save_new
from .pd_operations import PDWorker
from .pd_models import MODELS, FLASH_CAPACITIES, valid_capacity


class PDPage(QScrollArea):
    state_changed = Signal()

    def __init__(self, controller, settings, interface, parent=None):
        super().__init__(parent)
        self.controller, self.settings, self.port = controller, settings, interface.port
        self.identity = None
        self._address = None
        self._capacity = None
        self._read_uid = None
        self.pending_read = None
        self.saved_path = None
        self._context = None
        self._started = None
        self._done = self._total = 0
        self.setWidgetResizable(True)
        root = QWidget()
        root.setObjectName("root")
        self.setWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 12, 18, 10)
        outer.setSpacing(10)
        target = panel(outer)
        row = QHBoxLayout()
        row.addWidget(label("PROGRAMMER & TARGET", "sectionLabel"))
        row.addStretch()
        self.badge = label("Disconnected", "badge")
        row.addWidget(self.badge)
        target.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.model = QComboBox()
        for model in MODELS:
            self.model.addItem(model.name, model)
        self.model.setPlaceholderText("Select model")
        self.model.setCurrentIndex(-1)
        self.model.setMinimumWidth(215)
        self.model.setFixedHeight(40)
        field(row, "Model", self.model)
        for name, default in (("sda", 3), ("scl", 2)):
            spin = QSpinBox()
            spin.setKeyboardTracking(False)
            spin.setRange(0, 28)
            spin.setValue(settings.value(f"pd/{name}", default, type=int))
            spin.setFixedWidth(80)
            spin.setFixedHeight(40)
            spin.lineEdit().setTextMargins(8, 0, 0, 0)
            setattr(self, name, spin)
            field(row, name.upper(), spin)
            spin.valueChanged.connect(self.configuration_changed)
        self.model.currentIndexChanged.connect(self.configuration_changed)
        self.size = QComboBox()
        self.size.setEditable(True)
        self.size.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for capacity in FLASH_CAPACITIES:
            self.size.addItem(f"{capacity // 1024} KiB", capacity)
        self.size.setCurrentIndex(-1)
        self.size.lineEdit().setPlaceholderText("Select size")
        self.size.setFixedWidth(160)
        self.size.setFixedHeight(40)
        self.size.editTextChanged.connect(self.confirm_capacity)
        self.size_field, _ = field(row, "Size", self.size)
        row.addStretch()
        target.addLayout(row)
        self.memory_note = label("", "muted")
        self.memory_note.setWordWrap(True)
        target.addWidget(self.memory_note)
        row = QHBoxLayout()
        row.addStretch()
        self.connect_button = button("Connect to PD", lambda: self.start("pd_connect"), "primary")
        self.connect_button.setMinimumWidth(160)
        row.addWidget(self.connect_button)
        row.addStretch()
        target.addLayout(row)
        self.identity_label = label("PD controller not connected", "identity")
        target.addWidget(self.identity_label)
        self.identity_details = label("", "technical")
        self.identity_details.setWordWrap(True)
        self.identity_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        target.addWidget(self.identity_details)
        operations = panel(outer)
        row = QHBoxLayout()
        row.addWidget(label("OPERATIONS", "sectionLabel"))
        row.addStretch()
        row.addWidget(label("Write includes erase and verification", "muted"))
        operations.addLayout(row)
        row = QHBoxLayout()
        self.read_button = button("↓  Read", lambda: self.start("pd_read"), "action")
        self.write_button = button("↑  Write", lambda: self.start("pd_write"), "action")
        self.erase_button = button("×  Erase", lambda: self.start("pd_erase"), "danger")
        for control in (self.read_button, self.write_button, self.erase_button):
            row.addWidget(control, 1)
        operations.addLayout(row)
        self.hint = label("Select the controller model, then connect to PD.", "hint")
        self.hint.setWordWrap(True)
        operations.addWidget(self.hint)
        row = QHBoxLayout()
        self.status = label("Ready", "operationStatus")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.percent = label("", "percent")
        row.addWidget(self.percent)
        operations.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        operations.addWidget(self.progress)
        row = QHBoxLayout()
        self.transfer = label("", "technical")
        self.timing = label("", "technical")
        row.addWidget(self.transfer, 1)
        row.addWidget(self.timing)
        operations.addLayout(row)
        self.results = QWidget()
        row = QHBoxLayout(self.results)
        row.setContentsMargins(0, 0, 0, 0)
        self.save_button = button("Save…", self.save_read, "primary")
        self.discard_button = button("Discard", self.discard_read, "quiet")
        self.folder_button = button("Open folder", self.open_folder, "quiet")
        for control in (self.save_button, self.discard_button, self.folder_button):
            row.addWidget(control)
        row.addStretch()
        operations.addWidget(self.results)
        outer.addWidget(label("LOG", "sectionLabel"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(54)
        self.log.setMaximumHeight(76)
        outer.addWidget(self.log)
        outer.addStretch()
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.update_timing)
        controller.started.connect(self.update_controls)
        controller.idle.connect(self.update_controls)
        self.reset_capacity()
        self.note("Select the controller model, then connect to PD.")
        self.update_controls()

    def note(self, text):
        self.log.appendPlainText(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}")

    def context(self):
        return self.port.generation, self.sda.value(), self.scl.value(), self.model.currentText()

    def configuration_changed(self):
        self.identity = None
        self._address = None
        self.reset_capacity()
        self.identity_label.setText("PD controller not connected")
        self.identity_details.clear()
        for name in ("sda", "scl"):
            self.settings.setValue(f"pd/{name}", getattr(self, name).value())
        self.update_controls()
        self.state_changed.emit()

    def port_changed(self):
        self.identity = None
        self._address = None
        self.reset_capacity()
        self.identity_label.setText("PD controller not connected")
        self.identity_details.clear()
        self.update_controls()

    def reset_capacity(self):
        model = self.model.currentData()
        self._capacity = model.capacity if model is not None and not model.external_spi else None
        with QSignalBlocker(self.size):
            self.size.setCurrentIndex(-1)
            self.size.clearEditText()
            if valid_capacity(self._capacity):
                index = self.size.findData(self._capacity)
                if index < 0:
                    self.size.addItem(f"{self._capacity // 1024} KiB", self._capacity)
                    index = self.size.count() - 1
                self.size.setCurrentIndex(index)
        self.memory_note.setVisible(model is not None)
        if model is None:
            self.memory_note.clear()
            return
        self.memory_note.setText(
            f"{model.name} uses external SPI flash. Before reading, locate the flash chip on the board, "
            "determine its capacity from its marking or datasheet, and select Size."
            if model.external_spi else
            f"{model.name} stores firmware in internal flash. The memory size is set automatically for this model.")

    def show_identity(self):
        if self.identity is None:
            return
        self.identity_label.setText(f"PD controller · {self.model.currentText()}")
        storage = "External SPI flash" if self.model.currentData().external_spi else "Internal flash"
        memory = (f"{storage} {self._capacity // 1024:g} KiB" if self._capacity else
                  f"{storage} size required")
        self.identity_details.setText(f"Firmware {self.identity.version_label} · {memory}")

    def confirm_capacity(self, *_args):
        model = self.model.currentData()
        if (model is None or not model.external_spi or self.controller.busy
                or self.pending_read is not None):
            return
        text = self.size.currentText().strip()
        try:
            size = int(text.removesuffix("KiB").strip()) * 1024
        except ValueError:
            size = None
        self._capacity = size if valid_capacity(size) else None
        self.show_identity()
        self.update_controls()
        if text and self._capacity is None:
            self.hint.setText("Enter a flash size in KiB, in multiples of 4.")
        self.state_changed.emit()

    def update_controls(self):
        idle = not self.controller.busy
        model = self.model.currentData()
        pins = (self.sda.value(), self.scl.value())
        configured = (self.port.currentData() is not None and pins[0] != pins[1]
                      and all(p <= 22 or 26 <= p <= 28 for p in pins) and self.model.currentIndex() >= 0)
        pending = self.pending_read is not None
        for control in (self.model, self.sda, self.scl):
            control.setEnabled(idle and not pending)
        self.size.setEnabled(idle and not pending and model is not None and model.external_spi)
        self.connect_button.setEnabled(idle and configured and not pending)
        for control in (self.read_button, self.write_button, self.erase_button):
            control.setEnabled(idle and configured and self.identity is not None
                               and valid_capacity(self._capacity) and not pending)
        self.results.setVisible(pending or self.saved_path is not None)
        self.save_button.setVisible(pending)
        self.discard_button.setVisible(pending)
        self.folder_button.setVisible(not pending and self.saved_path is not None)
        self.results.setEnabled(idle)
        active = self.controller.busy and getattr(self.controller.worker, "action", "").startswith("pd_")
        self.badge.setText("Busy" if active else "Connected" if self.identity else "Disconnected")
        self.badge.setProperty("state", "busy" if active else "connected" if self.identity else "idle")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.hint.setText("Save the read or discard it to continue." if pending else
                          "Select the capacity of the external SPI flash on this board."
                          if self.identity is not None and self._capacity is None else
                          "Ready to read, write or erase the selected flash range." if self.identity else
                          "Select the controller model, check the wiring, then connect to PD.")

    def start(self, action):
        self.update_controls()
        control = {"pd_connect": self.connect_button, "pd_read": self.read_button,
                   "pd_write": self.write_button, "pd_erase": self.erase_button}[action]
        if not control.isEnabled():
            return
        launch_context, expected = self.context(), self.identity
        capacity, address = self._capacity, self._address
        image_path = None
        if action == "pd_write":
            image_path, _ = QFileDialog.getOpenFileName(self, "Select PD flash image", self.settings.value("pd/image_dir", ""), "Binary images (*.bin *.rom);;All files (*)")
            if not image_path:
                return
            try:
                image_size = Path(image_path).stat().st_size
            except OSError as exc:
                QMessageBox.warning(self, "Cannot open image", str(exc))
                return
            if image_size != capacity:
                QMessageBox.warning(self, "Image size", "Image size must match the selected flash capacity.")
                return
            self.settings.setValue("pd/image_dir", str(Path(image_path).parent))
        if action in ("pd_write", "pd_erase"):
            message = ("Erase the selected flash range, write the image and verify every byte?" if image_path else
                       "Erase the entire selected flash range and verify that it is blank?")
            if QMessageBox.question(self, "Write PD flash" if image_path else "Erase PD flash", message) != QMessageBox.StandardButton.Yes:
                return
        if (self.controller.busy or self.context() != launch_context or self.port.currentData() is None
                or (action != "pd_connect" and (self.identity is None or self.identity != expected
                    or self._capacity != capacity or self._address != address))):
            self.status.setText("Interface changed or busy · connect again before continuing")
            return
        self._context = launch_context
        worker = PDWorker(action, self.port.currentData(), (self.sda.value(), self.scl.value()),
                          None if action == "pd_connect" else address,
                          0 if action == "pd_connect" else capacity,
                          expected=expected, image_path=image_path)
        worker.phase.connect(self.set_phase)
        worker.transfer.connect(self.set_transfer)
        worker.status.connect(self.note)
        worker.finished.connect(self.on_finished)
        worker.failed.connect(self.on_failed)
        self.saved_path = None
        self._started = time.monotonic()
        self._done = self._total = 0
        self.progress.setRange(0, 0)
        self.progress.setStyleSheet("QProgressBar::chunk { background: #226db4; }")
        self.status.setText("Connecting to PD controller…" if action == "pd_connect" else "Preparing operation…")
        self.percent.clear()
        self.transfer.clear()
        self.timer.start()
        if not self.controller.start(worker):
            self.timer.stop()
            worker.deleteLater()

    def set_phase(self, phase):
        self._started = time.monotonic()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status.setText({"Read": "Reading", "Programming": "Writing", "Erase": "Erasing", "Verification": "Verifying"}[phase])
        color = {"Erase": "#dc2626", "Programming": "#ea580c"}.get(phase, "#15803d")
        self.progress.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")
        self.note(phase + " started")

    def set_transfer(self, done, total):
        self._done, self._total = done, total
        value = done * 100 // total if total else 0
        self.progress.setValue(value)
        self.percent.setText(f"{value}%")
        self.transfer.setText(f"{done // 1024} / {total // 1024} KiB")
        self.update_timing()

    def update_timing(self):
        if self._started is None:
            return
        elapsed = time.monotonic() - self._started
        text = f"{elapsed:.0f} s"
        if elapsed >= 3 and self._total * .05 <= self._done < self._total:
            text += f" · ~{elapsed * (self._total - self._done) / self._done:.0f} s remaining"
        self.timing.setText(text)

    def on_finished(self, action, result):
        self.update_timing()
        self.timer.stop()
        self._started = None
        current = self._context is None or self.context() == self._context
        identity = result.identity if action == "pd_connect" else result[0] if action == "pd_read" else result
        previous_identity = self.identity
        self.identity = identity if current else None
        if self.identity:
            if action == "pd_connect":
                self._address = result.address
                if previous_identity is not None and previous_identity.fingerprint != identity.fingerprint:
                    self.reset_capacity()
                self.note(f"I²C 0x{result.address:02X} · Device {identity.device_label} · UID {identity.uid.hex().upper()}")
            self.show_identity()
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.percent.setText("100%")
        text = {"pd_connect": "PD controller connected" if current else "Interface changed · connect again",
                "pd_read": "Read complete", "pd_write": "Write complete · full image verified",
                "pd_erase": "Erase complete · blank contents verified"}[action]
        self.status.setText(text)
        self.note(text)
        if action == "pd_read":
            self.pending_read = result[1]
            self._read_uid = identity.uid.hex()
        self.update_controls()
        self.state_changed.emit()
        if action == "pd_read":
            self.save_read()

    def on_failed(self, message):
        self.update_timing()
        self.timer.stop()
        self._started = None
        self.identity = None
        self._address = None
        self.reset_capacity()
        self.identity_label.setText("PD controller not connected")
        self.identity_details.clear()
        self.progress.setRange(0, 100)
        self.progress.setStyleSheet("QProgressBar::chunk { background: #dc2626; }")
        self.status.setText(message)
        self.percent.setText("Stopped")
        self.note("ERROR: " + message)
        self.update_controls()
        self.state_changed.emit()

    def save_read(self):
        if self.pending_read is None:
            return
        name = f"pd-flash-{len(self.pending_read)//1024}KiB-{datetime.now():%Y%m%d-%H%M%S}.bin"
        directory = self.settings.value("pd/backup_dir", str(Path.home()))
        path, _ = QFileDialog.getSaveFileName(self, "Save PD flash", str(Path(directory) / name), "Binary image (*.bin)")
        if not path:
            return
        try:
            digest = save_new(path, self.pending_read)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save PD flash", str(exc))
            return
        metadata = {"format": "spark-pd-backup-1", "image": Path(path).name,
                    "size": len(self.pending_read), "sha256": digest,
                    "uid": self._read_uid or (self.identity.uid.hex() if self.identity else None)}
        try:
            with Path(path + ".pd.json").open("x", encoding="utf-8") as stream:
                json.dump(metadata, stream, indent=2)
                stream.write("\n")
        except OSError as exc:
            self.note(f"Image saved; backup metadata could not be saved: {exc}")
        self.pending_read = None
        self.saved_path = Path(path)
        self.settings.setValue("pd/backup_dir", str(self.saved_path.parent))
        self.note(f"Saved {path} · SHA-256 {digest}")
        self.update_controls()
        self.state_changed.emit()

    def discard_read(self):
        if self.controller.busy:
            return
        self.pending_read = None
        self.update_controls()
        self.state_changed.emit()

    def open_folder(self):
        if self.saved_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved_path.parent)))
