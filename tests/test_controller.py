# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Device ownership must outlive a result signal and worker cleanup."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import time
import unittest
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
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

    def test_finished_signal_does_not_release_worker_before_native_cleanup(self):
        controller = OperationController()
        finish_entered = threading.Event()
        finish_release = threading.Event()
        tail_done = threading.Event()
        run_ready = threading.Event()
        observations = []
        gui_thread = self.app.thread()

        class GatedWorker(QObject):
            finished = Signal(str, object)
            failed = Signal(str)

            @Slot()
            def run(self):
                run_ready.wait(3)
                self.finished.emit("read", None)

        def finish_tail():
            finish_entered.set()
            finish_release.wait(3)
            tail_done.set()

        def destroyed():
            observations.append(("destroyed_on_gui", QThread.currentThread() == gui_thread))

        worker = GatedWorker()
        worker.destroyed.connect(destroyed, Qt.ConnectionType.DirectConnection)
        controller.start(worker)
        thread = controller.thread
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(finish_tail, Qt.ConnectionType.DirectConnection)
        controller.idle.connect(lambda: observations.append(("idle_after_tail", tail_done.is_set())))
        # The controller must hold the only Python reference through native
        # cleanup, just as it does between consecutive application operations.
        del worker
        run_ready.set()
        release_timer = threading.Timer(.1, finish_release.set)
        try:
            self.assertTrue(finish_entered.wait(3))
            release_timer.start()
            self.wait_idle(controller)
            self.assertIn(("idle_after_tail", True), observations)
            self.assertIn(("destroyed_on_gui", False), observations)
        finally:
            finish_release.set()
            if release_timer.ident is not None:
                release_timer.join()
            thread.wait(3000)
            self.wait_idle(controller)
            controller.deleteLater()


if __name__ == "__main__":
    unittest.main()
