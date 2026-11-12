# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Device ownership must outlive a result signal and worker cleanup."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import time
import unittest
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication
from app.controller import OperationController


class BlockingWorker(QObject):
    finished = Signal(str, object)
    failed = Signal(str)

    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail
        self.reported = threading.Event()
        self.release = threading.Event()
        self.cleaned = threading.Event()
        self.on_gui_thread = None

    @Slot()
    def run(self):
        self.on_gui_thread = QThread.currentThread() == QApplication.instance().thread()
        if self.fail:
            self.failed.emit("simulated failure")
        else:
            self.finished.emit("tool operation", None)
        self.reported.set()
        # Deliberately remain inside run() after reporting a terminal result.
        # No other tool may acquire the device while the worker is unwinding.
        self.release.wait(5)
        self.cleaned.set()


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_idle(self, controller):
        deadline = time.monotonic() + 5
        while controller.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertFalse(controller.busy)

    def test_result_or_failure_does_not_release_device_before_worker_exits(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                controller = OperationController()
                worker = BlockingWorker(fail)
                rejected = BlockingWorker()
                idle_cleanup = []
                controller.idle.connect(lambda: idle_cleanup.append(worker.cleaned.is_set()))
                try:
                    self.assertTrue(controller.start(worker))
                    self.assertTrue(worker.reported.wait(3))
                    self.app.processEvents()
                    self.assertTrue(controller.busy)
                    self.assertFalse(controller.start(rejected))
                    self.assertIs(controller.worker, worker)
                    self.assertFalse(worker.on_gui_thread)
                finally:
                    worker.release.set()
                    self.wait_idle(controller)
                    rejected.deleteLater()
                self.assertEqual(idle_cleanup, [True])
                next_worker = BlockingWorker()
                next_worker.release.set()
                self.assertTrue(controller.start(next_worker))
                self.wait_idle(controller)
                controller.deleteLater()


if __name__ == "__main__":
    unittest.main()
