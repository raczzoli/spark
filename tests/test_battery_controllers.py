"""Real diagnostic layout, access states and cell positions, without service IO."""
import unittest
from unittest.mock import Mock, patch
from app.battery import BatteryTransport, BatteryError, read_snapshot
from app.battery_controllers import identify_controller
from app.transport import TransportError
from tests.test_battery import Gauge, sample


class TiGauge(Gauge):
    def __init__(self):
        super().__init__()
        self.queries = []
        self.responses = {1: bytes.fromhex("5545"), 2: bytes.fromhex("4555000300030003850200"),
                          0x54: bytes.fromhex("87030000"), 0x51: bytes(4), 0x53: bytes(4)}
        self.cells = {0x3F: 3797, 0x3E: 3792, 0x3D: 3794, 0x3C: 3803}

    def query_ti_legacy(self, selector):
        self.queries.append(selector)
        data = self.responses[selector]
        if isinstance(data, Exception):
            raise data
        return data

    def read_word(self, reg, pec=None):
        if reg in self.cells:
            self.calls.append(("cell", reg, self.pec))
            value = self.cells[reg]
            if isinstance(value, Exception):
                raise value
            return value
        return super().read_word(reg, pec)


class ControllerDiagnosticsTests(unittest.TestCase):
    def test_read_battery_auto_identifies_live_pack_access_and_all_four_cells(self):
        bus = TiGauge()
        result = read_snapshot(bus, "auto")
        chip = result.controller
        self.assertEqual(chip["device_type"], "4555")
        self.assertEqual(chip["firmware_display"], "0.03")
        self.assertEqual(chip["security"], "Sealed")
        self.assertEqual(chip["cells_mV"], [3797, 3792, 3794, 3803])
        self.assertEqual(chip["imbalance_mV"], 11)
        self.assertFalse(chip["service_supported"])
        self.assertEqual(bus.queries, [1, 2, 0x54, 0x51, 0x53])
        self.assertNotIn(0x30, bus.queries)

    def test_sbs_only_profile_does_not_query_manufacturer_extensions(self):
        bus = TiGauge()
        self.assertEqual(read_snapshot(bus, "sbs").controller, {})
        self.assertEqual(bus.queries, [])
        self.assertFalse(any(call[0] == "cell" for call in bus.calls))

    def test_unsupported_live_identity_is_not_guessed_from_an_acer_reference(self):
        bus = TiGauge()
        for identity in ({"manufacturer": "Other", "device": "AC14B8K"},
                         {"manufacturer": "LGC", "device": "Different battery"}):
            result = identify_controller(bus, sample(strings=identity))
            self.assertIn("No verified", result["note"])
        self.assertEqual(bus.queries, [])

    def test_wrong_controller_stops_after_identity_without_status_or_cells(self):
        bus = TiGauge()
        bus.responses[1] = bytes.fromhex("0045")
        result = identify_controller(bus, sample())
        self.assertIn("differs", result["note"])
        self.assertEqual(bus.queries, [1])
        self.assertNotIn("security", result)
        self.assertEqual(bus.calls, [])

    def test_wrong_or_unverified_firmware_does_not_decode_access_bits(self):
        for fw in (bytes.fromhex("4555000400030003850200"),
                   bytes.fromhex("4500000300030003850200"), bytes(3)):
            bus = TiGauge()
            bus.responses[2] = fw
            result = identify_controller(bus, sample())
            self.assertNotIn("security", result)
            self.assertNotIn("cells_mV", result)
            self.assertEqual(bus.queries, [1, 2])

    def test_sealed_unsealed_full_access_and_invalid_states_are_distinct(self):
        for bits, security in ((0x300, "Sealed"), (0x200, "Unsealed"),
                               (0x100, "Full access"), (0, "Unknown")):
            bus = TiGauge()
            bus.responses[0x54] = bits.to_bytes(4, "little")
            self.assertEqual(identify_controller(bus, sample())["security"], security)

    def test_invalid_status_does_not_hide_valid_cell_readings(self):
        bus = TiGauge()
        bus.responses[0x54] = bytes(2)
        result = identify_controller(bus, sample())
        self.assertNotIn("security", result)
        self.assertIn("operation", result["diagnostic_errors"])
        self.assertEqual(result["cells_mV"], [3797, 3792, 3794, 3803])

    def test_implausible_cells_do_not_appear_as_measured_cell_voltages(self):
        for voltage in (65535, 0, 2000):
            bus = TiGauge()
            bus.cells[0x3F] = voltage
            result = identify_controller(bus, sample())
            self.assertNotIn("cells_mV", result)
            self.assertIn("cells", result["diagnostic_errors"])
            self.assertEqual(result["security"], "Sealed")

    def test_checksum_failure_or_usb_loss_invalidates_the_read(self):
        for error, synchronized in ((TransportError("ERR SMB_PEC"), True),
                                     (TransportError("USB lost"), False)):
            bus = TiGauge()
            bus._synchronized = synchronized
            bus.responses[0x54] = error
            with self.assertRaises(TransportError):
                identify_controller(bus, sample())

    def test_explicit_ti_profile_can_identify_an_unsupported_device_without_decoding_it(self):
        bus = TiGauge()
        bus.responses[1] = bytes.fromhex("3412")
        result = identify_controller(bus, sample(strings={}), explicit=True)
        self.assertEqual(result["device_type"], "1234")
        self.assertNotIn("security", result)
        self.assertEqual(bus.queries, [1])

    def test_legacy_diagnostic_adapter_is_allowlisted_and_uses_manufacturer_data(self):
        bus = BatteryTransport.__new__(BatteryTransport)
        bus._write_word = Mock()
        bus.read_block = Mock(return_value=bytes.fromhex("5545"))
        with patch("app.battery.time.sleep"):
            self.assertEqual(bus.query_ti_legacy(1), bytes.fromhex("5545"))
            bus._write_word.assert_called_once_with(0, 1)
            bus.read_block.assert_called_once_with(0x23)
            for unsafe in (0x12, 0x30, 0x35, 0x41, 0x26):
                with self.assertRaises(BatteryError):
                    bus.query_ti_legacy(unsafe)
        self.assertEqual(bus._write_word.call_count, 1)


if __name__ == "__main__":
    unittest.main()
