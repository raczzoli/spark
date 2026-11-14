"""Exercise ITE family operations through the production worker and flash engine."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.flash_protocols import protocol_for
from app.models import FAMILIES
from app.operations import Worker
from app.transport import TransportError


class MemoryBus:
    def __init__(self, identity, flash_id, size):
        self.identity, self.id = identity, flash_id
        self.memory = bytearray(b'\xa5' * size)
        self.family = None
        self.active = False
        self.events = []
        self.corrupt = False

    def capabilities(self):
        return frozenset(('ITE5', 'SESSION', 'FLASHID', 'ERASESECTOR', 'AAIV2_256', 'PAGE64'))

    def supports(self, cap): return cap in self.capabilities()
    def pins(self, *pins): pass
    def close(self): pass
    def firmware_info(self): return 'INFO simulated ITE target'
    def select_ite_family(self, family): self.family = family
    def command(self, text):
        if text == 'HOLDDBGR': return 'HOLDDBGR ACTIVE' if self.active else 'HOLDDBGR INACTIVE'
        raise AssertionError(text)

    def session(self):
        if not self.active: raise TransportError('ERR ITE_SESSION_INACTIVE')
        return self.identity

    def enter_dbgr(self):
        self.events.append('enter')
        self.active = True
        return self.identity

    def flash_id(self, port): return self.id
    def fast_aai_v2_256_available(self): return True
    def fast_page_available(self): return True

    def erase_sector(self, address, opcode):
        count = 4096 if opcode == 0x20 else 1024
        assert opcode in (0x20, 0xd7) and address % count == 0
        self.events.append(('erase', address))
        self.memory[address:address+count] = b'\xff' * count

    def program(self, address, data):
        self.events.append(('program', address))
        for offset, value in enumerate(data): self.memory[address+offset] &= value

    def program_v2_256(self, address, data): self.program(address, data)
    def program_v2_64(self, address, data, page_program=False):
        assert page_program
        self.program(address, data)

    def read_page(self, address):
        self.events.append(('read', address))
        data = bytes(self.memory[address:address+256])
        if self.corrupt and address == len(self.memory)-256:
            data = data[:-1] + bytes([data[-1] ^ 1])
        return data


class Ite5Tests(unittest.TestCase):
    def run_worker(self, action, bus, profile, size, path=None, identity=None):
        worker = Worker(action, 'SIMULATED', (7, 6), profile, identity or bus.identity,
                        str(path) if path else None, size)
        finished, errors = [], []
        worker.finished.connect(lambda name, result: finished.append((name, result)))
        worker.failed.connect(errors.append)
        with patch('app.operations.ECTransport', return_value=bus): worker.run()
        return finished, errors

    def test_legacy_and_extended_ids_choose_v2_without_revision_three(self):
        for chip in (0x5122, 0x5570, 0x51526, 0x51626):
            for revision in (0, 2, 3):
                with self.subTest(chip=chip, revision=revision):
                    aai = protocol_for((chip, revision), bytes.fromhex('FFFFFE'))
                    kgd = protocol_for((chip, revision), bytes.fromhex('EF4012'))
                    self.assertEqual((aai.program_method, aai.erase_opcode), ('aai_v2', 0xd7))
                    self.assertEqual((kgd.program_method, kgd.erase_opcode), ('page_program', 0x20))

    def test_connect_read_write_verify_and_erase_for_both_selectors(self):
        size = 128*1024
        cases = ((FAMILIES[0], (0x5122, 2), 'FFFFFE'),
                 (FAMILIES[1], (0x5570, 2), 'C84012'),
                 (FAMILIES[0], (0x51526, 2), 'FFFFFE'))
        for profile, identity, flash in cases:
            with self.subTest(family=profile.name, chip=identity[0]), tempfile.TemporaryDirectory() as directory:
                bus = MemoryBus(identity, bytes.fromhex(flash), size)
                finished, errors = self.run_worker('connect', bus, profile, size)
                self.assertEqual(errors, [])
                self.assertEqual(bus.family, profile.name)
                self.assertEqual(finished[0][1][0], identity)
                self.assertIsNotNone(finished[0][1][2])
                image = bytes((i ^ (i >> 16)) & 255 for i in range(size))
                path = Path(directory) / 'firmware.bin'
                path.write_bytes(image)
                finished, errors = self.run_worker('write', bus, profile, size, path)
                self.assertEqual(errors, [])
                self.assertEqual(finished, [('write', identity)])
                self.assertEqual(bytes(bus.memory), image)
                finished, errors = self.run_worker('read', bus, profile, size)
                self.assertEqual(errors, [])
                self.assertEqual(finished, [('read', (identity, image))])
                finished, errors = self.run_worker('erase', bus, profile, size)
                self.assertEqual(errors, [])
                self.assertEqual(finished, [('erase', identity)])
                self.assertEqual(bytes(bus.memory), b'\xff' * size)

    def test_verify_mismatch_reports_last_address_and_does_not_report_success(self):
        size = 64*1024
        bus = MemoryBus((0x5570, 2), bytes.fromhex('C84012'), size)
        bus.corrupt = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'firmware.bin'
            path.write_bytes(bytes(range(256)) * (size//256))
            finished, errors = self.run_worker('write', bus, FAMILIES[1], size, path)
        self.assertEqual(finished, [])
        self.assertIn('Verification failed at 0x00FFFF', errors[0])

    def test_changed_target_stops_before_erase(self):
        bus = MemoryBus((0x5570, 2), bytes.fromhex('C84012'), 128*1024)
        finished, errors = self.run_worker('erase', bus, FAMILIES[1], 128*1024,
                                           identity=(0x5571, 2))
        self.assertEqual(finished, [])
        self.assertIn('EC identity changed', errors[0])
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'erase' for event in bus.events))
