# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Serialize device operations independently of the active tool and its widgets."""
from PySide6.QtCore import QObject, QThread, Signal, Slot


class OperationController(QObject):
    started = Signal()
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.worker = None

    @property
    def busy(self):
        return self.thread is not None

    def start(self, worker):
        """Own one worker until its thread exits, including target cleanup.

        Workers expose run(), finished and failed. Tool-specific progress and
        result handlers are connected by the caller before starting.
        """
        if self.busy:
            return False
        self.worker = worker
        self.thread = QThread(self)
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.finished.connect(self.thread.quit)
        worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(worker.deleteLater)
        self.thread.finished.connect(self._on_thread_finished)
        self.started.emit()
        self.thread.start()
        return True

    @Slot()
    def _on_thread_finished(self):
        # finished() precedes deferred worker deletion and thread-local cleanup.
        # Keep its Python wrapper alive until C++ destruction has completed.
        self.thread.wait()
        self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.idle.emit()
