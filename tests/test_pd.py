# SPDX-License-Identifier: GPL-2.0-or-later
"""PD mailbox, NOR flash operations and USB error handling without hardware."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from app.pd import PDDevice, PDTransport, PDIdentity, PDConnection, PDError
from app.transport import TransportError
from app.pd_operations import PDWorker


class FlashBus:
    def __init__(self):
        self.flash = bytearray((index * 17 + index // 251) & 255 for index in range(8192))
        self.cursor = 0
        self.calls = []
        self.status = 0
        self.identity = PDIdentity(bytes(4), b"XYZ9", b"\x12\x34\x56\x78", bytes(range(16)), "APP")

    def read_register(self, register, size):
        return {0: self.identity.vendor, 1: self.identity.device, 3: b"APP ",
                5: self.identity.uid, 15: self.identity.version}[register]

    def task(self, name, data, count, timeout=3):
        self.calls.append((name, data))
        if name == "FLrd":
            address = int.from_bytes(data, "little")
            return bytes(self.flash[address:address + count])
        if self.status:
            return bytes([self.status])
        if name == "FLem":
            address = int.from_bytes(data[:4], "little")
            self.flash[address:address + data[4] * 4096] = b"\xff" * (data[4] * 4096)
        elif name == "FLad":
            self.cursor = int.from_bytes(data, "little")
        elif name == "FLwd":
            if self.cursor // 256 != (self.cursor + len(data) - 1) // 256:
                raise AssertionError("SPI page crossed")
            for byte in data:
                self.flash[self.cursor] &= byte
                self.cursor += 1
        else:
            raise AssertionError(name)
        return b"\x00"


class PDTests(unittest.TestCase):
    def setUp(self):
        self.bus = FlashBus()
        self.pd = PDDevice(self.bus)

    def test_identity_does_not_restrict_vendor_or_device_id(self):
        self.assertEqual(self.pd.identify().device_label, "XYZ9")
        self.bus.identity = PDIdentity(b"abcd", b"\x01\xff\x00\x02", bytes(4), bytes(16), "APP")
        self.assertEqual(self.pd.identify().device_label, "0x0200FF01")

    def test_read_is_one_pass_and_preserves_memory_byte_order(self):
        expected = bytes(self.bus.flash)
        progress = []
        self.assertEqual(self.pd.read_flash(8192, lambda *args: progress.append(args)), expected)
        self.assertEqual(len(self.bus.calls), 8192 // 16)
        self.assertEqual(progress[-1], (8192, 8192))
        self.assertEqual({call[0] for call in self.bus.calls}, {"FLrd"})

    def test_full_nor_erase_program_verify_cycle_across_pages_and_sectors(self):
        image = bytes((i * 73 ^ i >> 3 ^ 165) & 255 for i in range(8192))
        self.pd.erase_flash(8192)
        self.pd.verify_flash(b"\xff" * 8192)
        self.pd.write_flash(image)
        self.pd.verify_flash(image)
        self.assertEqual(bytes(self.bus.flash), image)
        self.assertEqual(sum(name == "FLem" for name, _ in self.bus.calls), 2)
        self.assertEqual(sum(name == "FLad" for name, _ in self.bus.calls), 32)

    def test_sector_range_leaves_adjacent_contents_unchanged(self):
        first = bytes(self.bus.flash[:4096])
        self.pd.erase_flash(4096, start=4096)
        self.pd.write_flash(bytes(4096), start=4096)
        self.assertEqual(bytes(self.bus.flash[:4096]), first)
        self.pd.verify_flash(bytes(4096), start=4096)

    def test_invalid_range_sends_no_task(self):
        for size, start in ((0, 0), (4097, 0), (4096, 1), (4096, -4096), (4096, 2**32)):
            with self.subTest(size=size, start=start), self.assertRaises(ValueError):
                self.pd.erase_flash(size, start=start)
        self.assertEqual(self.bus.calls, [])

    def test_geometry_accepts_larger_and_upper_address_space_ranges(self):
        self.pd.validate_range(16 * 1024 * 1024)
        self.pd.validate_range(4096, 2**32 - 4096)

    def test_blank_pages_need_no_program_task_but_keep_complete_progress(self):
        progress = []
        self.pd.write_flash(b"\xff" * 4096, lambda *args: progress.append(args))
        self.assertEqual(self.bus.calls, [])
        self.assertEqual(progress[-1], (4096, 4096))

    def test_new_pico_capability_uses_bulk_reads_and_full_mailbox_payloads(self):
        self.bus.supports = lambda capability: capability == "PD4CC1"
        self.bus.address = 0x38
        calls = []
        def command(text):
            _, _, address, count = text.split()
            offset = int(address, 16)
            calls.append(text)
            return f"PDREAD {address} " + bytes(self.bus.flash[offset:offset + int(count)]).hex().upper()
        self.bus.command = command
        pd = PDDevice(self.bus)
        self.assertEqual(pd.read_size, 256)
        self.assertEqual(pd.write_size, 64)
        self.assertEqual(pd.read_flash(8192), bytes(self.bus.flash))
        self.assertEqual(len(calls), 32)
        pd.erase_flash(8192)
        pd.write_flash(b"\xa5" * 8192)
        self.assertEqual(max(len(data) for name, data in self.bus.calls if name == "FLwd"), 64)

    def test_nonzero_task_status_stops_without_replaying_erase(self):
        self.bus.status = 0xFE
        with self.assertRaisesRegex(PDError, "0xFE"):
            self.pd.erase_flash(8192)
        self.assertEqual(len(self.bus.calls), 1)

    def test_verification_reports_first_mismatching_block(self):
        expected = bytearray(self.bus.flash)
        expected[4111] ^= 1
        with self.assertRaisesRegex(PDError, "0x00001000"):
            self.pd.verify_flash(bytes(expected))

    def test_transient_read_failure_can_repeat_only_the_same_read(self):
        task = self.bus.task
        self.bus.task = Mock(side_effect=[TransportError("ERR SDA_LOW_BEFORE_START"), task("FLrd", bytes(4), 16)])
        with patch("app.pd.time.sleep"):
            self.assertEqual(self.pd.read_block(0), bytes(self.bus.flash[:16]))
        self.assertEqual(self.pd.read_retries, 1)
        self.assertEqual(self.bus.task.call_count, 2)
        self.assertEqual(self.bus.task.call_args_list[0], self.bus.task.call_args_list[1])

    def test_unknown_outcome_or_unsupported_task_is_not_replayed(self):
        for error in (TransportError("Timeout USB CDC"), PDError("unsupported command")):
            with self.subTest(error=error):
                self.bus.task = Mock(side_effect=error)
                with self.assertRaises(type(error)):
                    self.pd.read_block(0)
                self.assertEqual(self.bus.task.call_count, 1)

    def test_persistent_read_bus_failure_has_bounded_retries(self):
        self.bus.task = Mock(side_effect=TransportError("ERR ADDRESS_NACK"))
        with patch("app.pd.time.sleep"), self.assertRaises(TransportError):
            self.pd.read_block(0)
        self.assertEqual(self.bus.task.call_count, 4)

    def test_write_failure_is_never_replayed(self):
        self.bus.task = Mock(side_effect=TransportError("ERR DATA_NACK"))
        with self.assertRaises(TransportError):
            self.pd.write_flash(bytes(4096))
        self.assertEqual(self.bus.task.call_count, 1)

    def transport(self):
        bus = PDTransport.__new__(PDTransport)
        bus.address = 0x38
        bus._read_ready = True
        bus._tagged = True
        bus._sequence = 100
        bus._synchronized = True
        bus._caps = frozenset()
        bus.port = Mock()
        return bus

    def pipeline(self, bus, error=None, pending=bytes(4)):
        responses = ["OK", "OK", "OK", "DATA 04" + pending.hex(), "OK", "DATA 40" + bytes(range(16)).hex()]
        if error:
            responses[0] = error
        bus.port.readline.side_effect = [f"@{101+i:08X} {reply}\n".encode() for i, reply in enumerate(responses)]

    def test_pipelined_read_checks_every_acknowledgement(self):
        bus = self.transport()
        self.pipeline(bus)
        self.assertEqual(bus.flash_read_block(0), bytes(range(16)))
        self.assertEqual(bus.port.readline.call_count, 6)
        self.assertIn(b"0804464C7264", bus.port.write.call_args[0][0])
        self.assertNotIn(b"464C656D", bus.port.write.call_args[0][0])

    def test_pipelined_error_drains_all_replies_and_invalidates_read_state(self):
        bus = self.transport()
        self.pipeline(bus, error="ERR DATA_NACK")
        with self.assertRaises(TransportError):
            bus.flash_read_block(0)
        self.assertFalse(bus._read_ready)
        self.assertTrue(bus._synchronized)
        self.assertEqual(bus.port.readline.call_count, 6)

    def test_pending_read_discards_early_data_without_reissuing_command(self):
        bus = self.transport()
        self.pipeline(bus, pending=b"FLrd")
        bus.read_register = Mock(side_effect=[bytes(4), b"x" * 16])
        self.assertEqual(bus.flash_read_block(0), b"x" * 16)
        self.assertEqual(bus.port.write.call_count, 1)

    def test_pipelined_usb_loss_marks_session_unsynchronized(self):
        bus = self.transport()
        bus.port.readline.return_value = b""
        with self.assertRaises(TransportError):
            bus.flash_read_block(0)
        self.assertFalse(bus._synchronized)

    def test_address_discovery_accepts_unlisted_device_id_and_firmware_override(self):
        bus = self.transport()
        def read(register, count):
            if bus.address != 0x55:
                raise TransportError("ERR ADDRESS_NACK")
            return {0: bytes(4), 1: b"XYZ9", 2: b"\x01\x00\x00\x00", 3: b"APP ",
                    5: bytes(range(16)), 15: bytes(4)}[register]
        bus.read_register = Mock(side_effect=read)
        self.assertEqual(bus.discover_address(), 0x55)
        self.assertEqual(bus.address, 0x55)
        bus.port.write.assert_not_called()

    def test_discovery_stops_on_bus_or_usb_failure(self):
        for error in ("ERR SDA_LOW_BEFORE_START", "Timeout USB CDC"):
            bus = self.transport()
            bus.read_register = Mock(side_effect=TransportError(error))
            with self.assertRaises(TransportError):
                bus.discover_address()
            self.assertEqual(bus.read_register.call_count, 1)

    def test_discovery_reports_no_interface_without_any_flash_task(self):
        bus = self.transport()
        bus.read_register = Mock(side_effect=TransportError("ERR ADDRESS_NACK"))
        with self.assertRaisesRegex(PDError, "No PD host interface"):
            bus.discover_address()
        self.assertEqual(bus.read_register.call_count, 0x78 - 8)

    def test_worker_rejects_wrong_size_image_before_opening_usb(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "image.bin"
            path.write_bytes(bytes(17))
            worker = PDWorker("pd_write", "COM0", (3, 2), 0x38, 4096, image_path=path)
            errors = []
            worker.failed.connect(errors.append)
            with patch("app.pd_operations.PDTransport") as transport:
                worker.run()
            transport.assert_not_called()
            self.assertIn("17 bytes", errors[0])

    def test_connect_worker_accepts_unknown_capacity_and_returns_discovered_address(self):
        self.bus.address = 0x55
        worker = PDWorker("pd_connect", "COM0", (3, 2), None, 0)
        results, errors = [], []
        worker.finished.connect(lambda action, result: results.append(result))
        worker.failed.connect(errors.append)
        with patch("app.pd_operations.PDTransport") as transport:
            transport.return_value.__enter__.return_value = self.bus
            worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(results, [PDConnection(self.bus.identity, 0x55)])
        self.assertIsNone(transport.call_args.args[2])

    def test_worker_identity_change_blocks_destructive_commands(self):
        expected = PDIdentity(bytes(4), b"OLD1", bytes(4), b"o" * 16, "APP")
        worker = PDWorker("pd_erase", "COM0", (3, 2), 0x38, 4096, expected=expected)
        errors = []
        worker.failed.connect(errors.append)
        with patch("app.pd_operations.PDTransport") as transport:
            transport.return_value.__enter__.return_value = self.bus
            worker.run()
        self.assertIn("changed", errors[0])
        self.assertEqual(self.bus.calls, [])

    def test_worker_erases_and_verifies_blank_before_success_after_cleanup(self):
        worker = PDWorker("pd_erase", "COM0", (3, 2), 0x38, 8192)
        results = []
        with patch("app.pd_operations.PDTransport") as transport:
            transport.return_value.__enter__.return_value = self.bus
            worker.finished.connect(lambda *args: results.append(transport.return_value.__exit__.called))
            worker.run()
        self.assertEqual(results, [True])
        self.assertEqual(bytes(self.bus.flash), b"\xff" * 8192)


if __name__ == "__main__":
    unittest.main()
