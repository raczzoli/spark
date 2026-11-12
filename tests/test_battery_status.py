"""Battery fault lockout must never be inferred from memory sealing."""
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
from app.battery_status import battery_status, recovery_unavailable
from app.battery import BatteryError, service
from tests.test_battery import sample


def chip(security="Sealed", pf=0, operation=0x387, safety=0):
    return {"device_type": "4500", "firmware": "0301", "security": security,
            "status_layout": "ti_bq40", "permanent_failure": pf, "operation": operation,
            "safety": safety, "service_supported": True, "recovery_supported": True}


class BatteryStatusTests(unittest.TestCase):
    def test_healthy_pack_is_unlocked_for_every_memory_access_state(self):
        for security, sec_bits in (("Sealed", 0x300), ("Unsealed", 0x200), ("Full access", 0x100)):
            state = battery_status(chip(security, operation=sec_bits | 0x87))
            self.assertEqual(state["state"], "unlocked")
            self.assertTrue(state["charge_fet"])
            self.assertTrue(state["discharge_fet"])

    def test_pf_lockout_is_reported_even_if_controller_is_unsealed(self):
        for security in ("Sealed", "Unsealed", "Full access"):
            self.assertEqual(battery_status(chip(security, pf=1))["state"], "locked")
        self.assertEqual(battery_status(chip(operation=0x7381))["state"], "locked")

    def test_fuse_activation_has_its_own_lockout_reason(self):
        state = battery_status(chip(operation=0x3A7))
        self.assertEqual(state["state"], "locked")
        self.assertIn("fuse", state["reason"])

    def test_temporary_protection_and_disabled_outputs_are_not_pf_lockout(self):
        self.assertEqual(battery_status(chip(safety=1))["state"], "protected")
        self.assertEqual(battery_status(chip(operation=0xB87))["state"], "protected")
        for bit in (6, 10, 16, 29, 30, 31):
            self.assertEqual(battery_status(chip(operation=0x387 | (1 << bit)))["state"], "inhibited")
        for operation in (0x4387, 0x2387, 0x381, 0x385):
            self.assertEqual(battery_status(chip(operation=operation))["state"], "inhibited")

    def test_missing_malformed_or_unverified_diagnostics_stay_unknown(self):
        self.assertEqual(battery_status({"security": "Sealed"})["state"], "unknown")
        for key in ("status_layout", "operation", "safety", "permanent_failure"):
            value = chip()
            value.pop(key)
            self.assertEqual(battery_status(value)["state"], "unknown")
        for invalid in (True, -1, 1 << 32, "0"):
            value = chip()
            value["operation"] = invalid
            self.assertEqual(battery_status(value)["state"], "unknown")

    def test_report_preserves_operational_and_memory_access_states_separately(self):
        report = sample(controller=chip()).export()
        self.assertEqual(report["battery_status"]["state"], "unlocked")
        self.assertEqual(report["controller"]["security"], "Sealed")


class RecoveryTests(unittest.TestCase):
    def locked(self, security="Full access"):
        return sample(profile="ti_bq40z50", controller=chip(security, pf=1, operation=0x7101))

    def test_no_recovery_for_healthy_pack_active_safety_fuse_or_unknown_profile(self):
        for value in (chip(), chip(pf=1, safety=1), chip(pf=1, operation=0x73A1),
                      dict(chip(pf=1), recovery_supported=False)):
            self.assertTrue(recovery_unavailable(value))

    def test_unsupported_controller_refuses_before_any_manufacturer_command(self):
        expected = self.locked()
        expected.controller["device_type"] = "4555"
        bus = Mock()
        with patch("app.battery.read_snapshot") as read, self.assertRaises(BatteryError):
            service(bus, "clear_pf", expected)
        read.assert_not_called()
        bus._write_word.assert_not_called()

    def test_clear_pf_uses_distinct_reset_commands_and_checks_actual_operation(self):
        current, after = self.locked(), sample(profile="ti_bq40z50", controller=chip())
        bus = Mock()
        with patch("app.battery.read_snapshot", side_effect=[current, deepcopy(current), after]), \
             patch("app.battery.read_ti_diagnostics", return_value=current.controller), \
             patch("app.battery.time.sleep"):
            self.assertIs(service(bus, "clear_pf", deepcopy(current)), after)
        self.assertEqual([c.args for c in bus._write_word.call_args_list], [(0, 0x29), (0, 0x41)])
        self.assertTrue(after.controller["recovery"]["verified"])
        self.assertEqual(after.controller["recovery"]["before"]["controller"]["permanent_failure"], 1)
        self.assertEqual(after.controller["security"], "Sealed")

    def test_recovery_validates_all_keys_before_any_access_change(self):
        current = self.locked("Sealed")
        bus = Mock()
        with patch("app.battery.read_snapshot", return_value=current), \
             patch("app.battery.read_ti_diagnostics", return_value=current.controller), self.assertRaises(BatteryError):
            service(bus, "clear_pf", deepcopy(current), {"unseal": (0x1234, 0x5678)})
        bus._write_word.assert_not_called()

    def test_one_button_recovery_verifies_each_access_stage_before_pf_reset(self):
        current, after = self.locked("Sealed"), sample(profile="ti_bq40z50", controller=chip())
        unsealed, full = dict(current.controller, security="Unsealed"), dict(current.controller, security="Full access")
        bus = Mock()
        keys = {"unseal": (0x1234, 0x5678), "full_access": (0x1111, 0x2222)}
        with patch("app.battery.read_snapshot", side_effect=[current, deepcopy(current), after]), \
             patch("app.battery.read_ti_diagnostics", side_effect=[current.controller, unsealed, full, full]), \
             patch("app.battery.time.sleep"):
            service(bus, "clear_pf", deepcopy(current), keys)
        self.assertEqual([c.args for c in bus._write_word.call_args_list],
                         [(0, 0x1234), (0, 0x5678), (0, 0x1111), (0, 0x2222), (0, 0x29), (0, 0x41)])

    def test_wrong_keys_stop_recovery_without_reset_or_retry(self):
        current = self.locked("Sealed")
        bus = Mock()
        with patch("app.battery.read_snapshot", return_value=current), \
             patch("app.battery.read_ti_diagnostics", return_value=current.controller), \
             patch("app.battery.time.sleep"), self.assertRaisesRegex(BatteryError, "No PF reset"):
            service(bus, "clear_pf", deepcopy(current), {"unseal": (1, 2), "full_access": (3, 4)})
        self.assertEqual([c.args for c in bus._write_word.call_args_list], [(0, 1), (0, 2)])

    def test_changed_battery_stops_before_reset(self):
        current = self.locked()
        other = deepcopy(current)
        other.words["1C"] += 1
        bus = Mock()
        with patch("app.battery.read_snapshot", side_effect=[current, other]), \
             patch("app.battery.read_ti_diagnostics", return_value=current.controller), self.assertRaises(BatteryError):
            service(bus, "clear_pf", deepcopy(current))
        bus._write_word.assert_not_called()

    def test_pf_clear_without_restored_output_is_not_reported_as_unlocked(self):
        for after in (self.locked(), sample(profile="ti_bq40z50", controller=chip(operation=0x381))):
            current, bus = self.locked(), Mock()
            with patch("app.battery.read_snapshot", side_effect=[current, deepcopy(current), after]), \
                 patch("app.battery.read_ti_diagnostics", return_value=current.controller), \
                 patch("app.battery.time.sleep"), self.assertRaisesRegex(BatteryError, "not confirmed"):
                service(bus, "clear_pf", deepcopy(current))
            self.assertEqual([c.args for c in bus._write_word.call_args_list], [(0, 0x29), (0, 0x41)])


if __name__ == "__main__":
    unittest.main()
