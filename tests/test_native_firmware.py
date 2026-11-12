# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute production C against a recording bus; never open USB hardware."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec("ziglang"):
            compiler = [sys.executable, "-m", "ziglang", "cc"]
        else:
            cc = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
            if not cc:
                raise RuntimeError("Native C tests need a C compiler (or pip install ziglang==0.13.0)")
            compiler = [cc]
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.exe = Path(cls.temp.name) / ("firmware-test.exe" if os.name == "nt" else "firmware-test")
        sources = ["tests/native/flash_harness.c", "firmware/ite_flash.c",
                   "firmware/ite_session.c", "firmware/ite_bus.c",
                   "firmware/usb_commands.c", "firmware/usb_output.c",
                   "firmware/ec_commands.c", "firmware/ite_commands.c",
                   "firmware/ene_commands.c", "firmware/device_runtime.c"]
        subprocess.run(compiler + ["-std=c11", "-Wall", "-Wextra", "-Werror",
                       "-Itests/native", "-Ifirmware", *sources, "-o", str(cls.exe)],
                       cwd=ROOT, check=True, capture_output=True, text=True, timeout=180)

    def run_c(self, *args):
        return subprocess.check_output([str(self.exe), *args], text=True, timeout=10).splitlines()

    def test_existing_read_and_write_command_traces(self):
        fixture = json.loads((ROOT / "tests/fixtures/ite_flash_traces.json").read_text())
        for args, expected in fixture["traces"].items():
            with self.subTest(command=args):
                self.assertEqual(self.run_c(*args.split()), expected)

    def test_watchdog_restores_register_cursor(self):
        trace = self.run_c("hold")
        self.assertEqual(trace[-2:], ["W 5A 08", "CURSOR=08 HOLD=1"])

    def test_failed_cursor_restore_invalidates_hold(self):
        self.assertTrue(self.run_c("hold", "7")[-1].endswith("HOLD=0"))

    def test_ite_cursor_is_isolated_from_generic_transfers_and_pin_changes(self):
        trace = self.run_c("cursor")
        self.assertIn("GENERIC_CURSOR=08", trace)
        self.assertIn("FAILED_CURSOR=08", trace)
        self.assertEqual(trace[-2:], ["SAME_PINS_VALID=1", "NEW_PINS_VALID=0"])

    def test_legacy_split_write_still_restores_cursor_during_runtime_tick(self):
        self.assertEqual(self.run_c("legacycursor")[-2:],
                         ["W 5A 08", "CURSOR=08 HOLD=1"])

    def test_release_keeps_debug_hold_and_end_session_stops_it(self):
        self.assertEqual(self.run_c("lifecycle"), [
            "RELEASE HOLD=1 BUS=1 ENE_CLOSE=1", "END HOLD=0 BUS=2 ENE_CLOSE=2"])

    def test_ene_session_blocks_ite_commands_but_allows_common_commands(self):
        for command in ("REGREAD 00", "PINS 7 6", "WRITE 5A 08"):
            with self.subTest(command=command):
                self.assertEqual(self.run_c("eneactive", command), ["ERR ENE_ACTIVE"])
        self.assertEqual(self.run_c("eneactive", "HELLO"), ["OK PICO_ITE_EC_PROGRAMMER 2"])
        for command in ("RELEASE", "ENECLOSE", "ENDSESSION"):
            with self.subTest(command=command):
                self.assertEqual(self.run_c("eneactive", command), ["OK"])

    def test_overlong_line_discards_tail_until_newline(self):
        self.assertEqual(self.run_c("overflow"), ["OVERFLOW", "OK PICO_ITE_EC_PROGRAMMER 2"])

    def test_tagged_multifragment_reply(self):
        trace = self.run_c("command", "@1234ABCD READPAGE 000100")
        reply = trace[-1]
        self.assertEqual(reply, "@1234ABCD PAGE 000100 " + bytes(range(256)).hex().upper())
        self.assertEqual(reply.count("@1234ABCD"), 1)

    def test_reject_bad_commands_before_bus_access(self):
        commands = ["REGREAD 00 garbage", "REGWRITE 100 20", "READ 35 65",
                    "WRITE 35 " + "FF" * 65, "ERASESECTOR 000001 D7",
                    "ERASESECTOR 000000 1D7", "READPAGE 040000",
                    "AAI64 000000 " + "00" * 65, "AAI256 000000 " + "00" * 257,
                    "PINS 6 6", "REGWRITE 00 01 WRITE 35 FF", "READPAGE 100000000",
                    "@Z234ABCD HELLO", "PAGE64 000001 " + "00" * 64,
                    "ENEOPEN KB901X EXTRA", "ENEOPEN " + "X"*30,
                    "ENEREADPAGE 100000000", "ENEERASEPAGE 00000 garbage",
                    "ENEWRITEPAGE 00000 " + "00"*129]
        for command in commands:
            with self.subTest(command=command[:50]):
                trace = self.run_c("command", command)
                self.assertEqual(len(trace), 1, trace)
                self.assertTrue(trace[0].startswith("ERR "), trace)

    def test_atomic_sector_erase_addresses_and_write_disable(self):
        for name, address, opcode in (("erase1k", "000400", "D7"), ("erase4k", "001000", "20")):
            trace = self.run_c(name)
            index = trace.index("W 35 " + opcode)
            address_writes = [part for byte in bytes.fromhex(address) for part in ("W 5A 08", f"W 35 {byte:02X}")]
            self.assertEqual(trace[index+1:index+7], address_writes)
            self.assertEqual(trace[-2:], ["W 35 04", f"ERASESECTOR {address} OK"])

    def test_default_timing_and_build_metadata(self):
        self.assertEqual(self.run_c("command", "INFO"),
                         ["INFO VERSION=test BUILD=native BOARD=simulated I2C_DELAY_US=5"])


if __name__ == "__main__":
    unittest.main()
