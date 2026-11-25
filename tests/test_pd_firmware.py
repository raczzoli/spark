# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the actual PD firmware parser and mailbox executor against a recording bus."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PDFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = [sys.executable, "-m", "ziglang", "cc"] if importlib.util.find_spec("ziglang") else [os.environ.get("CC") or shutil.which("cc") or "gcc"]
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.exe = Path(cls.temp.name) / "pd-native.exe"
        subprocess.run(compiler + ["-std=c11", "-Wall", "-Wextra", "-Werror", "-Itests/native", "-Ifirmware",
                       "tests/native/pd_harness.c", "firmware/pd_commands.c", "firmware/usb_output.c", "-o", str(cls.exe)],
                       cwd=ROOT, check=True, capture_output=True, text=True, timeout=180)

    def run_c(self, command, fault=""):
        return subprocess.check_output([str(self.exe), command, fault], text=True, timeout=10).splitlines()

    def test_bulk_read_preserves_all_bytes_and_reports_address(self):
        lines = self.run_c("PDREAD 38 00000100 256")
        self.assertEqual(lines[0], "PDREAD 00000100 " + bytes(range(256)).hex().upper())
        self.assertEqual(lines[1], "TASKS=16 PARAMS=4")

    def test_payload_write_nack_never_executes_task(self):
        lines = self.run_c("PDTASK 38 FLwd " + "A5" * 64 + " 1", "parameter_nack")
        self.assertEqual(lines, ["ERR INJECTED_NACK", "TASKS=0 PARAMS=0"])

    def test_atomic_task_accepts_complete_64_byte_payload(self):
        lines = self.run_c("PDTASK 38 FLwd " + "A5" * 64 + " 1")
        self.assertEqual(lines, ["PDTASK 00", "TASKS=1 PARAMS=64"])

    def test_unsupported_task_stops_bulk_read_without_success_data(self):
        lines = self.run_c("PDREAD 38 0 256", "unsupported")
        self.assertEqual(lines, ["ERR PD_COMMAND_UNSUPPORTED", "TASKS=1 PARAMS=4"])

    def test_busy_task_has_bounded_wait(self):
        lines = self.run_c("PDTASK 38 FLrd 00000000 16", "timeout")
        self.assertEqual(lines, ["ERR PD_COMMAND_TIMEOUT", "TASKS=1 PARAMS=4"])

    def test_bad_register_length_stops_before_task(self):
        self.assertEqual(self.run_c("PDREAD 38 0 256", "length"), ["ERR PD_REGISTER_LENGTH", "TASKS=0 PARAMS=0"])

    def test_invalid_arguments_cannot_touch_bus(self):
        commands = ("PDREAD 38 0 0", "PDREAD 38 0 257", "PDREAD 38 1 16", "PDREAD 38 100000000 16",
                    "PDREAD 38 FFFFFFFFFFFFFFFF 16", "PDTASK 80 FLrd 00000000 16", "PDTASK 38 FLwd GG 1",
                    "PDTASK 38 FLwd " + "00" * 65 + " 1", "PDTASK 38 FLrd - 65")
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.run_c(command), ["ERR PD_ARGUMENT", "TASKS=0 PARAMS=0"])


if __name__ == "__main__":
    unittest.main()
