"""Battery UX checks: compact workflow, truthful states, keyboard input and feedback."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QPlainTextEdit

from app.gui import Window
from app.interface import DetectedInterface, UsbCandidate
from app.battery_catalog import search
from tests.test_battery import sample


class BatteryGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = QSettings(str(Path(self.temp.name) / "ui.ini"), QSettings.Format.IniFormat)
        self.w = Window(settings, auto_discovery=False)
        self.w.port.set_device(DetectedInterface(UsbCandidate("TEST"), "pico_w"))
        self.w.workspaces.setCurrentIndex(2)
        self.b = self.w.battery

    def tearDown(self):
        self.b.stop_monitor()
        self.w.connected_identity = None
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()

    def choose(self, query):
        entry = search(query)[0]
        self.b.battery_choice.select_id(entry["id"])
        return entry

    def test_battery_header_has_only_model_and_read_action(self):
        self.assertEqual(
            sorted(control.text() for control in self.b.header.findChildren(QPushButton)),
            ["Read battery"],
        )
        self.assertEqual(self.b.port.currentData(), "TEST")
        self.assertIs(self.b.port, self.w.port)
        self.assertFalse(self.b.header.isAncestorOf(self.w.interface_bar))
        self.assertEqual(self.b.sections.currentIndex(), 0)
        self.assertEqual(
            [self.b.sections.tabText(i) for i in range(self.b.sections.count())],
            ["General info", "Measurements", "Controller"],
        )
        self.assertEqual(self.b.findChildren(QPlainTextEdit), [])
        self.assertTrue(self.b.export_button.isHidden())
        self.assertTrue(self.b.advanced.isHidden())
        self.assertFalse(self.b.battery_choice.lineEdit().isClearButtonEnabled())

    def test_battery_selection_is_not_restored_or_saved_between_sessions(self):
        from app.battery_gui import BatteryPage
        settings = QSettings(str(Path(self.temp.name) / "old-settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("battery/reference", search("AC14B8K")[0]["id"])
        settings.setValue("battery/scl", 13)
        page = BatteryPage(self.w.controller, settings, self.w.interface_bar)
        try:
            self.assertEqual(page.battery_choice.currentText(), "")
            self.assertIsNone(page.entry)
            self.assertIsNone(page.diagram.entry)
            self.assertFalse(settings.contains("battery/reference"))
            self.assertEqual(page.scl.value(), 13)
            page.battery_choice.select_id(search("AC14B8K")[0]["id"])
            self.assertFalse(settings.contains("battery/reference"))
        finally:
            page.deleteLater()

    def test_brand_filters_both_popups_and_preserves_alias_search_and_selection(self):
        brand=self.b.brand_choice
        combo=self.b.battery_choice
        self.assertEqual(brand.currentData(), "")
        self.assertEqual(combo.currentText(), "")
        self.assertLessEqual(brand.maximumWidth(),150)
        self.w.show();self.app.processEvents()
        brand.showPopup();self.app.processEvents()
        self.assertLessEqual(brand.view().height(),350)
        brand.hidePopup()
        brand.setCurrentIndex(brand.findData("HP"))
        self.assertGreater(combo.count(),0)
        self.assertTrue(all(combo.itemData(i)['manufacturer']=='HP' for i in range(combo.count())))
        self.assertFalse(combo.select_id(search('AC14B8K')[0]['id']))
        combo.lineEdit().setText('916811855')
        combo._edited('916811855')
        self.assertEqual(combo.filtered.rowCount(),1)
        QTest.keyClick(combo.lineEdit(),Qt.Key.Key_Return)
        self.assertEqual(self.b.entry['model'],'BK03XL')
        self.assertEqual(combo.currentData()['id'],self.b.entry['id'])
        brand.setCurrentIndex(brand.findData("Lenovo"))
        self.assertEqual(combo.currentText(), "")
        self.assertIsNone(self.b.entry)
        self.assertIsNone(self.b.diagram.entry)
        self.assertTrue(all(combo.itemData(i)['manufacturer']=='Lenovo' for i in range(combo.count())))
        combo._combo_selected(0)
        self.assertEqual(self.b.entry['id'],combo.itemData(0)['id'])

    def test_empty_brand_clears_wiring_and_cannot_select_another_brands_first_model(self):
        self.choose('AC14B8K')
        self.b.brand_choice.setCurrentIndex(self.b.brand_choice.findData('DJI'))
        combo=self.b.battery_choice
        self.assertEqual(combo.count(),0)
        self.assertEqual(combo.filtered.rowCount(),0)
        self.assertIn('No models',combo.lineEdit().placeholderText())
        self.assertEqual(combo.currentText(),'')
        self.assertIsNone(self.b.entry)
        self.assertIsNone(self.b.diagram.entry)
        QTest.keyClick(combo.lineEdit(),Qt.Key.Key_Return)
        self.assertIsNone(self.b.entry)
        self.b.brand_choice.setCurrentIndex(0)
        self.assertGreater(combo.count(),0)
        self.assertEqual(combo.currentText(),'')
        self.assertIn('Search battery',combo.lineEdit().placeholderText())
        self.assertIsNone(self.b.entry)

    def test_catalog_combo_filters_aliases_and_accepts_keyboard_selection(self):
        self.w.show()
        self.w.activateWindow()
        self.app.processEvents()
        combo = self.b.battery_choice
        edit = combo.lineEdit()
        for query, model in (("ac14-b8k", "AC14B8K"), ("916811855", "BK03XL")):
            edit.setFocus()
            edit.selectAll()
            QTest.keyClicks(edit, query)
            self.app.processEvents()
            self.assertEqual(combo.filtered.rowCount(), 1)
            self.assertIsNone(self.b.entry)
            self.assertTrue(combo.completer().popup().isVisible())
            QTest.keyClick(edit, Qt.Key.Key_Down)
            QTest.keyClick(edit, Qt.Key.Key_Return)
            self.assertEqual(self.b.entry["model"], model)
            self.assertFalse(combo.completer().popup().isVisible())
        edit.selectAll()
        QTest.keyClicks(edit, "unlisted-model")
        self.app.processEvents()
        self.assertEqual(combo.filtered.rowCount(), 0)
        self.assertIsNone(self.b.entry)
        self.assertIsNone(self.b.diagram.entry)
        edit.selectAll()
        QTest.keyClick(edit, Qt.Key.Key_Backspace)
        self.assertEqual(combo.currentText(), "")
        self.assertIsNone(self.b.entry)
        QTest.keyClick(edit, Qt.Key.Key_Return)
        self.assertEqual(combo.currentText(), "")
        self.assertIsNone(self.b.entry)

    def test_all_connector_positions_and_gpio_changes_remain_available(self):
        entry = self.choose("AC14B8K")
        self.assertEqual(len(self.b.diagram.entry["pins"]), 8)
        self.assertEqual(self.b.diagram.entry["pins"][5]["role"], "present")
        self.assertLessEqual(self.b.diagram.height(), 80)
        self.b.scl.setValue(13)
        self.assertEqual(self.b.diagram.scl, 13)
        self.assertIn("CLOCK GP13", self.b.connection_hint.text())
        self.assertNotIn("physical", self.b.connection_hint.text().lower())
        self.b.mirror_view()
        self.assertTrue(self.b.diagram.mirrored)
        self.assertEqual(entry["pins"][0]["number"], 1)

    def test_model_without_pinout_clears_previous_wiring_and_stays_readable(self):
        from app.battery_widgets import BatteryResultDelegate
        self.w.show()
        self.choose("AC14B8K")
        self.app.processEvents()
        self.assertTrue(self.b.diagram.rects)
        entry=self.choose("L22D2PG2")
        self.app.processEvents()
        self.assertEqual(entry["pins"],[])
        self.assertEqual(self.b.diagram.rects,[])
        self.assertIn("pinout unavailable",self.b.wiring_meta.text().lower())
        self.assertNotIn("GP",self.b.connection_hint.text())
        subtitle=self.b.battery_choice.currentData(BatteryResultDelegate.SUBTITLE_ROLE)
        self.assertEqual(subtitle,"Lenovo · Pinout unavailable")
        self.assertNotIn("0 pins",subtitle)
        self.assertTrue(self.b.read_button.isEnabled())
        self.b.mirror_view()
        self.assertFalse(self.b.diagram.mirrored)
        self.assertFalse(self.b.settings.contains("battery/reference"))
        self.choose("AC14B8K")
        self.app.processEvents()
        self.assertEqual(len(self.b.diagram.rects),8)
        self.assertIn("CLOCK GP9",self.b.connection_hint.text())

    def test_saved_gpio_settings_update_header_without_an_extra_settings_button(self):
        settings = QSettings(str(Path(self.temp.name) / "other.ini"), QSettings.Format.IniFormat)
        settings.setValue("battery/sda", 12)
        settings.setValue("battery/scl", 13)
        from app.battery_gui import BatteryPage
        page = BatteryPage(self.w.controller, settings, self.w.interface_bar)
        self.assertIn("GP12", page.connection_hint.text())
        self.assertIn("GP13", page.connection_hint.text())
        page.deleteLater()

    def test_scrolling_over_connection_fields_never_changes_wiring_or_address(self):
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtGui import QWheelEvent
        self.b.sections.setCurrentIndex(2)
        self.b.connection_options.click()
        self.w.show()
        self.app.processEvents()
        for control in (self.b.sda, self.b.scl, self.b.address):
            before = control.value()
            for focused in (False, True):
                if focused:
                    control.setFocus()
                else:
                    self.b.profile.setFocus()
                self.app.processEvents()
                for delta in (-120, 120):
                    event = QWheelEvent(QPointF(control.rect().center()),
                                        QPointF(control.mapToGlobal(control.rect().center())),
                                        QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
                    self.app.sendEvent(control, event)
                    self.assertEqual(control.value(), before)
            QTest.keyClick(control, Qt.Key.Key_Up)
            self.assertEqual(control.value(), before + control.singleStep())
            control.setValue(before)

    def test_connection_error_identifies_selected_gpio_or_address(self):
        self.b.scl.setValue(8)
        self.b.on_failed("TransportError: ERR SMB_CLOCK_DRIVE")
        self.assertIn("CLOCK GP8", self.b.status.text())
        self.b.address.setValue(0x0D)
        self.b.on_failed("TransportError: ERR SMB_ADDRESS_NACK")
        self.assertIn("0x0D", self.b.status.text())

    def test_overview_fits_normal_window_and_feedback_stays_fixed_at_small_size(self):
        self.choose("AC14B8K")
        self.b.on_finished("battery_read", sample())
        self.w.resize(1040, 790)
        self.w.show()
        for _ in range(3):
            self.app.processEvents()
        self.assertLessEqual(self.b.header.height(), 180)
        self.assertEqual(self.b.general_scroll.verticalScrollBar().maximum(), 0)
        self.w.resize(840, 560)
        self.b.on_failed("ERR SMB_PEC")
        self.app.processEvents()
        self.assertTrue(self.b.status.isVisible())
        self.assertTrue(self.b.feedback_details.isVisible())
        self.assertGreater(self.b.status.geometry().top(), self.b.sections.geometry().bottom())
        self.assertLessEqual(self.b.status.geometry().bottom(), self.b.height())
        self.assertIn("rejected", self.b.status.text())

    def test_basic_read_stays_on_overview_and_does_not_guess_security_or_cells(self):
        self.b.on_finished("battery_read", sample())
        self.assertEqual(self.b.sections.currentIndex(), 0)
        self.assertEqual(self.b.summary.text(), "AC14B8K")
        self.assertEqual(self.b.cards["voltage"].value.text(), "15.186")
        self.assertEqual(self.b.access_value.text(), "Unknown")
        self.assertEqual(self.b.balance_value.text(), "Unknown")
        self.assertIsNone(self.b.cells.voltages)
        self.assertTrue(self.b.access_button.isHidden())
        self.assertTrue(self.b.identify_link.isVisibleTo(self.b.general_scroll.widget()))

    def test_controller_memory_access_uses_seal_unseal_without_changing_battery_lock_status(self):
        self.b.profile.setCurrentIndex(1)
        for security, label, action in (
            ("Sealed", "Unseal", "unseal"),
            ("Unsealed", "Seal", "seal"),
            ("Full access", "Seal", "seal"),
        ):
            snapshot = sample(profile="ti_bq40z50")
            snapshot.controller = {
                "name": "TI bq40z50", "firmware": "0301",
                "service_supported": True, "security": security,
                "status_layout": "ti_bq40", "operation": 0x387, "safety": 0, "permanent_failure": 0,
            }
            self.b.on_finished("battery_read", snapshot)
            self.assertEqual(self.b.access_value.text(), "Unlocked")
            self.assertEqual(self.b.security_value.text(), security)
            self.assertTrue(self.b.access_button.isHidden())
            self.assertTrue(self.b.controller_access_button.isHidden())
            self.assertEqual(self.b.security_button.text(), label)
            self.assertFalse(self.b.security_button.isHidden())
            self.assertTrue(self.b.security_button.isEnabled())
            with patch.object(self.b, "start_service") as start:
                self.b.security_button.click()
                start.assert_called_once_with(action)
        self.b.address.setValue(0x0C)
        self.assertFalse(self.b.latest_valid)
        self.assertEqual(self.b.access_value.text(), "Unknown")
        self.assertTrue(self.b.access_button.isHidden())
        self.assertTrue(self.b.controller_access_button.isHidden())

    def test_automatic_read_displays_detected_access_and_cells_without_enabling_unverified_service(self):
        from tests.test_battery_controllers import TiGauge
        from app.battery import read_snapshot
        self.assertEqual(self.b.profile.currentData(), "auto")
        snapshot = read_snapshot(TiGauge(), "auto")
        self.b.on_finished("battery_read", snapshot)
        self.assertEqual(self.b.access_value.text(), "Unlocked")
        self.assertEqual(self.b.cells.voltages, [3797, 3792, 3794, 3803])
        self.assertIn("11 mV", self.b.balance_value.text())
        self.assertIn("0x4555", self.b.controller_details.text())
        self.assertIn("firmware 0.03", self.b.controller_details.text())
        self.assertTrue(self.b.identify_link.isHidden())
        self.assertTrue(self.b.access_button.isHidden())
        self.assertFalse(self.b.service_permitted("unseal"))
        self.assertEqual(self.b.controller_access_value.text(), "Unlocked")
        self.assertEqual(self.b.security_value.text(), "Sealed")
        self.assertTrue(self.b.controller_service_note.isHidden())
        self.assertIn("4 cells", self.b.controller_cells.text())
        self.assertIn("11 mV", self.b.controller_cells.text())
        self.assertEqual(self.b.controller_protection.text(), "No faults reported")

    def test_controller_keeps_profiles_and_raw_data_inside_advanced(self):
        self.w.show()
        self.b.sections.setCurrentIndex(2)
        self.app.processEvents()
        self.assertEqual(self.b.connection_options.text(), "Advanced")
        self.assertFalse(self.b.profile.isVisible())
        self.assertFalse(self.b.details.isVisible())
        self.assertTrue(self.b.controller_details.isVisible())
        self.assertTrue(self.b.controller_access_value.isVisible())
        self.b.connection_options.click()
        self.assertTrue(self.b.profile.isVisible())
        self.assertTrue(self.b.details.isVisible())
        self.b.connection_options.click()
        self.assertFalse(self.b.profile.isVisible())
        self.assertFalse(self.b.details.isVisible())

    def test_controller_checks_distinguish_missing_partial_and_active_protections(self):
        for chip, text in (({}, "Not available"), ({"safety": 0}, "Partially checked"),
                           ({"safety": 1}, "Output blocked"),
                           ({"safety": 0, "permanent_failure": 2}, "Permanent fault reported")):
            self.b.on_finished("battery_read", sample(controller=chip))
            self.assertEqual(self.b.controller_protection.text(), text)

    def test_pf_locked_unsealed_battery_offers_pf_recovery_not_memory_unseal(self):
        from tests.test_battery_status import chip
        snapshot = sample(profile="ti_bq40z50", controller=chip("Unsealed", pf=1, operation=0x7201))
        self.b.on_finished("battery_read", snapshot)
        self.assertEqual(self.b.access_value.text(), "Locked")
        self.assertEqual(self.b.security_value.text(), "Unsealed")
        self.assertEqual(self.b.access_button.text(), "Unlock battery")
        self.assertTrue(self.b.access_button.isEnabled())
        with patch.object(self.b, "start_service") as start:
            self.b.access_button.click()
            start.assert_called_once_with("clear_pf")
        self.w.controller.thread = Mock()
        try:
            self.b.update_controls()
            self.assertFalse(self.b.access_button.isEnabled())
        finally:
            self.w.controller.thread = None

    def test_unsupported_pf_recovery_is_explicit_and_cannot_send_a_service_command(self):
        from tests.test_battery_status import chip
        snapshot = sample(profile="auto", controller=dict(chip(pf=1), device_type="4555",
                                                          recovery_supported=False, service_supported=False))
        self.b.on_finished("battery_read", snapshot)
        self.assertEqual(self.b.access_value.text(), "Locked")
        self.assertFalse(self.b.access_button.isHidden())
        self.assertFalse(self.b.access_button.isEnabled())
        self.assertIn("not implemented", self.b.access_button.toolTip())
        with patch.object(self.b, "start") as start:
            self.b.start_service("clear_pf")
            start.assert_not_called()

    def test_unverified_or_unsupported_controller_cannot_change_access(self):
        self.b.profile.setCurrentIndex(1)
        for pec, supported in ((False, True), (True, False)):
            snapshot = sample(pec=pec)
            snapshot.controller = {
                "name": "TI bq40z50", "firmware": "0301",
                "service_supported": supported, "security": "Sealed",
            }
            self.b.on_finished("battery_read", snapshot)
            self.assertFalse(self.b.service_permitted("unseal"))
            with patch.object(self.b, "start") as start:
                self.b.start_service("unseal")
                start.assert_not_called()

    def test_different_reference_or_port_does_not_inherit_oem_queries(self):
        self.b.profile.setCurrentIndex(1)
        self.choose("AC14B8K")
        self.assertEqual(self.b.profile.currentData(), "auto")
        self.b.profile.setCurrentIndex(1)
        self.b.port.set_device(DetectedInterface(UsbCandidate("OTHER"), "pico_w"))
        self.assertEqual(self.b.profile.currentData(), "auto")
        self.assertFalse(self.b.latest_valid)

    def test_cells_preserve_positions_and_show_an_explicit_comparison_reference(self):
        snapshot = sample()
        snapshot.controller = {
            "name": "TI bq40z50", "firmware": "0301",
            "cells_mV": [4000, 4020, 0, 0],
        }
        self.b.on_finished("battery_read", snapshot)
        self.assertEqual(self.b.cells.voltages, [4000, 4020, 0, 0])
        self.assertIn("20 mV", self.b.balance_value.text())
        self.assertIn("within", self.b.balance_value.text())
        self.assertIn("not the manufacturer", self.b.balance_value.toolTip())
        snapshot.controller["cells_mV"] = [3800, 4100, 0, 0]
        self.b.on_finished("battery_read", snapshot)
        self.assertIn("300 mV", self.b.balance_value.text())
        self.assertIn("over", self.b.balance_value.text())
        self.b.on_failed("USB disconnected")
        self.assertIsNone(self.b.cells.voltages)
        self.assertEqual(self.b.balance_value.text(), "Unknown")

    def test_shared_owner_blocks_mode_switch_and_battery_actions(self):
        self.w.controller.thread = Mock()
        try:
            self.w.update_buttons()
            self.b.update_controls()
            self.assertFalse(self.w.workspaces.tabBar().isEnabled())
            self.assertFalse(self.b.read_button.isEnabled())
            self.assertFalse(self.b.profile.isEnabled())
            with patch("app.battery_gui.BatteryWorker") as worker:
                self.b.start("battery_read")
                worker.assert_not_called()
        finally:
            self.w.controller.thread = None

    def test_ec_keepalive_cannot_run_in_battery_mode_and_switch_ends_session(self):
        self.w.connected_identity = (0x8227, 3)
        with patch.object(self.w, "start") as start:
            self.w.refresh_debug_hold()
            start.assert_not_called()
        self.w.workspaces.setCurrentIndex(0)
        self.w.connected_identity = (0x8227, 3)
        with patch.object(self.w, "start") as start:
            self.w.workspaces.setCurrentIndex(2)
            start.assert_called_once_with("disconnect")
        self.assertFalse(self.w.keepalive.isActive())

    def test_unsaved_ec_read_prevents_selecting_battery_tab(self):
        self.w.workspaces.setCurrentIndex(0)
        self.w.pending_read = b"dump"
        self.w.update_buttons()
        self.assertFalse(self.w.workspaces.isTabEnabled(2))
        self.w.pending_read = None
        self.w.update_buttons()
        self.assertTrue(self.w.workspaces.isTabEnabled(2))

    def test_tab_changes_stop_live_reading_without_restarting_on_return(self):
        self.assertFalse(self.b.header.isAncestorOf(self.b.monitor_button))
        self.w.show()
        for section in (0, 2):
            self.b.sections.setCurrentIndex(1)
            with patch.object(self.b, "start"):
                self.b.toggle_monitor()
            self.assertTrue(self.b.monitoring)
            QTest.mouseClick(self.b.sections.tabBar(), Qt.MouseButton.LeftButton,
                             pos=self.b.sections.tabBar().tabRect(section).center())
            self.assertEqual(self.b.sections.currentIndex(), section)
            self.assertFalse(self.b.monitoring)
            self.assertFalse(self.b.timer.isActive())
            self.b.sections.setCurrentIndex(1)
            self.assertFalse(self.b.monitoring)
        with patch.object(self.b, "start"):
            self.b.toggle_monitor()
        tabs = self.w.workspaces.tabBar()
        QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(0).center())
        self.assertEqual(self.w.workspaces.currentIndex(), 0)
        self.assertFalse(self.b.isVisible())
        self.assertFalse(self.b.monitoring)
        self.assertFalse(self.b.timer.isActive())
        QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(1).center())
        self.assertEqual(self.w.workspaces.currentIndex(), 1)
        self.assertFalse(self.b.monitoring)
        self.assertFalse(self.b.timer.isActive())
        with patch.object(self.b, "start") as start:
            self.b.poll()
            start.assert_not_called()

    def test_live_stop_works_during_initial_read_and_poll_without_header_flicker(self):
        import threading
        import time
        from itertools import product
        self.w.show()
        for previous_read, stop_via in product((False, True), ("button", "section", "workspace")):
            with self.subTest(previous_read=previous_read, stop_via=stop_via):
                self.w.workspaces.setCurrentIndex(2)
                self.b.sections.setCurrentIndex(1)
                if previous_read:
                    self.b.on_finished("battery_read", sample())
                else:
                    self.b.latest_valid = False
                entered, release = threading.Event(), threading.Event()

                def slow_read(*args):
                    entered.set()
                    release.wait(5)
                    return sample()

                with patch("app.battery_operations.BatteryTransport", return_value=Mock()), \
                     patch("app.battery_operations.read_snapshot", side_effect=slow_read):
                    try:
                        self.b.monitor_button.click()
                        self.assertTrue(entered.wait(3))
                        self.app.processEvents()
                        self.assertTrue(self.w.controller.busy)
                        self.assertEqual(self.w.controller.worker.action,
                                         "battery_poll" if previous_read else "battery_read")
                        self.assertEqual(self.b.read_button.text(), "Read battery")
                        self.assertEqual(self.b.monitor_button.text(), "Stop")
                        self.assertTrue(self.b.monitor_button.isEnabled())
                        self.assertTrue(self.w.workspaces.tabBar().isEnabled())
                        self.assertTrue(self.b.battery_choice.isEnabled())
                        self.assertTrue(self.b.profile.isEnabled())
                        # Poll ticks while a read is running cannot acquire USB again.
                        with patch.object(self.b, "start") as start:
                            self.b.poll()
                            start.assert_not_called()
                        if previous_read:
                            self.assertTrue(self.b.export_button.isEnabled())
                        if stop_via == "button":
                            self.b.monitor_button.click()
                        elif stop_via == "section":
                            tabs = self.b.sections.tabBar()
                            QTest.mouseClick(tabs, Qt.MouseButton.LeftButton,
                                             pos=tabs.tabRect(0).center())
                            self.assertEqual(self.b.sections.currentIndex(), 0)
                        else:
                            tabs = self.w.workspaces.tabBar()
                            QTest.mouseClick(tabs, Qt.MouseButton.LeftButton,
                                             pos=tabs.tabRect(0).center())
                            self.assertEqual(self.w.workspaces.currentIndex(), 0)
                        self.assertFalse(self.b.monitoring)
                        self.assertFalse(self.b.timer.isActive())
                        self.assertTrue(self.w.controller.busy)
                        self.assertEqual(self.b.monitor_button.text(), "Stopping…")
                        self.assertEqual(self.b.read_button.text(), "Read battery")
                        self.assertTrue(self.w.workspaces.tabBar().isEnabled())
                        self.w.workspaces.setCurrentIndex(2)
                        self.b.sections.setCurrentIndex(1)
                        self.assertFalse(self.b.monitoring)
                    finally:
                        release.set()
                        deadline = time.monotonic() + 3
                        while self.w.controller.busy and time.monotonic() < deadline:
                            self.app.processEvents()
                            time.sleep(.001)
                self.assertFalse(self.w.controller.busy)
                self.assertIsNotNone(self.b.snapshot)
                self.assertFalse(self.b.monitoring)
                self.assertFalse(self.b.timer.isActive())
                self.assertEqual(self.b.monitor_button.text(), "Live readings")
                self.assertTrue(self.b.monitor_button.isEnabled())
                self.assertEqual(self.b.read_button.text(), "Read battery")
                self.assertIn("Live readings stopped", self.b.status.text())
                with patch.object(self.b, "start") as start:
                    self.b.poll()
                    start.assert_not_called()

    def test_edit_during_live_read_retains_original_reference_and_invalidates_late_result(self):
        import threading
        import time
        for change in ("reference", "gpio", "address", "profile"):
            with self.subTest(change=change):
                original = self.choose("AC14B8K")
                entered, release = threading.Event(), threading.Event()

                def slow_read(*args):
                    entered.set()
                    release.wait(5)
                    return sample()

                with patch("app.battery_operations.BatteryTransport", return_value=Mock()), \
                     patch("app.battery_operations.read_snapshot", side_effect=slow_read):
                    try:
                        self.b.toggle_monitor()
                        self.assertTrue(entered.wait(3))
                        self.app.processEvents()
                        for control in (self.b.battery_choice, self.b.scl,
                                        self.b.address, self.b.profile):
                            self.assertTrue(control.isEnabled())
                        if change == "reference":
                            self.choose("BK03XL")
                        elif change == "gpio":
                            self.b.scl.setValue(self.b.scl.value() + 1)
                        elif change == "address":
                            self.b.address.setValue(self.b.address.value() + 1)
                        else:
                            self.b.profile.setCurrentIndex(1)
                        self.assertFalse(self.b.monitoring)
                        self.assertFalse(self.b.timer.isActive())
                        self.assertTrue(self.w.controller.busy)
                    finally:
                        release.set()
                        deadline = time.monotonic() + 3
                        while self.w.controller.busy and time.monotonic() < deadline:
                            self.app.processEvents()
                            time.sleep(.001)
                self.assertFalse(self.w.controller.busy)
                self.assertIsNotNone(self.b.snapshot)
                self.assertEqual(self.b.snapshot_reference, original)
                self.assertFalse(self.b.latest_valid)
                self.assertIn("settings changed", self.b.status.text())
                self.assertFalse(self.b.access_button.isEnabled())

    def test_ec_connect_waits_for_live_battery_cleanup_and_stops_polling(self):
        import threading
        import time
        from types import SimpleNamespace
        self.w.manufacturer.setCurrentText("ITE")
        self.w.model.setCurrentText("IT8xxx")
        self.w.flash_size.setValue(256)
        entered, release = threading.Event(), threading.Event()
        calls = []

        def slow_read(*args):
            entered.set()
            release.wait(5)
            return sample()

        bus = Mock()
        bus.close.side_effect = lambda: calls.append("battery closed")
        session = Mock(ene=False)
        session.connect.return_value = (0x8227, 3)
        session.ec.flash_protocol.return_value = SimpleNamespace(name="test", program_method="aai_v2")
        session.bus.command.return_value = "HOLDDBGR INACTIVE"
        session.bus.firmware_info.return_value = "Simulated firmware"

        def ec_session(*args):
            calls.append("EC opened")
            return session

        with patch("app.battery_operations.BatteryTransport", return_value=bus), \
             patch("app.battery_operations.read_snapshot", side_effect=slow_read), \
             patch("app.operations.DeviceSession", side_effect=ec_session):
            try:
                self.b.toggle_monitor()
                self.assertTrue(entered.wait(3))
                self.app.processEvents()
                self.w.workspaces.setCurrentIndex(0)
                self.assertTrue(self.w.detect.isEnabled())
                self.w.detect.click()
                self.assertFalse(self.b.monitoring)
                self.assertFalse(self.b.timer.isActive())
                self.assertEqual(self.w._pending_operation, ("connect", None))
                self.assertEqual(calls, [])
                self.assertEqual(self.w.controller.worker.action, "battery_read")
                with patch.object(self.b, "start") as start:
                    self.b.poll()
                    start.assert_not_called()
            finally:
                release.set()
                deadline = time.monotonic() + 3
                while self.w.controller.busy and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.001)
        self.assertFalse(self.w.controller.busy)
        self.assertEqual(calls, ["battery closed", "EC opened"])
        self.assertEqual(self.w.connected_identity, (0x8227, 3))
        self.assertTrue(self.w.read.isEnabled())
        self.assertTrue(self.w.write.isEnabled())
        self.assertTrue(self.w.erase.isEnabled())
        self.assertIsNone(self.w._pending_operation)
        self.assertFalse(self.b.monitoring)

    def test_failed_live_read_reports_the_connection_used_before_an_edit(self):
        self.w.controller.worker = Mock(battery_context={"pins": (7, 9), "address": 0x0B})
        self.b.sda.setValue(12)
        self.b.scl.setValue(13)
        self.b.address.setValue(0x0C)
        for error, expected in (("SMB_CLOCK_DRIVE", "CLOCK GP9"),
                                ("SMB_DATA_DRIVE", "DATA GP7"),
                                ("SMB_ADDRESS_NACK", "at 0x0B")):
            self.b.on_failed("ERR " + error)
            self.assertIn(expected, self.b.status.text())
        self.w.controller.worker = None

    def test_manual_read_keeps_its_progress_label_and_cannot_start_live_simultaneously(self):
        self.w.controller.thread = Mock()
        self.w.controller.worker = Mock(action="battery_read", live_read=False)
        try:
            self.b.update_controls()
            self.assertEqual(self.b.read_button.text(), "Reading…")
            self.assertFalse(self.b.monitor_button.isEnabled())
        finally:
            self.w.controller.thread = None
            self.w.controller.worker = None
            self.b.update_controls()

    def test_chart_cells_and_pinout_render_at_two_window_sizes(self):
        self.choose("AC14B8K")
        self.b.on_finished("battery_read", sample())
        self.w.show()
        for width, height in ((1040, 790), (840, 560)):
            self.w.resize(width, height)
            for i in range(self.b.plot_metric.count()):
                self.b.plot_metric.setCurrentIndex(i)
                self.app.processEvents()
                self.assertFalse(self.b.plot.grab().isNull())
            self.assertFalse(self.b.diagram.grab().isNull())
            self.assertFalse(self.b.cells.grab().isNull())

    def test_normal_ec_heading_and_compact_log_remain_unchanged(self):
        self.w.workspaces.setCurrentIndex(0)
        self.w.resize(1040, 790)
        self.w.show()
        self.app.processEvents()
        self.assertFalse(any(l.text() in ("EC Programmer", "v0.4.0") for l in self.w.findChildren(QLabel)))
        layout = self.w.journal.layout()
        caption = layout.itemAt(0).widget()
        self.assertLess(self.w.log.y() - caption.geometry().bottom(), 12)
        self.assertLess(self.w.journal.height() - caption.height() - self.w.log.height(), 15)

    def test_report_menu_exports_real_snapshot_and_history_in_each_format(self):
        self.b.on_finished("battery_read", sample())
        for extension, name in (
            ("pdf", "PDF report (*.pdf)"),
            ("json", "JSON diagnostic snapshot (*.json)"),
            ("csv", "CSV measurement history (*.csv)"),
        ):
            target = Path(self.temp.name) / ("report." + extension)
            with patch("app.battery_gui.QFileDialog.getSaveFileName", return_value=(str(target), name)) as dialog:
                self.b.export_report(extension)
            self.assertTrue(dialog.call_args.args[2].endswith("." + extension))
            if extension == "pdf":
                self.assertTrue(target.read_bytes().startswith(b"%PDF"))
            elif extension == "json":
                self.assertEqual(json.loads(target.read_text(encoding="utf8"))["metrics"]["voltage"], 15.186)
            else:
                with target.open(encoding="utf-8-sig", newline="") as f:
                    rows = list(csv.reader(f))
                self.assertEqual(rows[1][1], "15.186")
                self.assertEqual(len(rows), 2)

    def test_export_keeps_reference_from_read_not_a_later_catalog_lookup(self):
        self.choose("AC14B8K")
        self.b.on_finished("battery_read", sample())
        self.choose("BK03XL")
        self.assertIn("Previous reading", self.b.identity_subtitle.text())
        target = Path(self.temp.name) / "previous.json"
        with patch("app.battery_gui.QFileDialog.getSaveFileName", return_value=(str(target), "JSON diagnostic snapshot (*.json)")):
            self.b.export_report("json")
        data = json.loads(target.read_text(encoding="utf8"))
        self.assertEqual(data["connector_reference"]["model"], "AC14B8K")

    def test_model_only_report_does_not_claim_a_connector_pinout(self):
        self.choose("L22D2PG2")
        self.b.on_finished("battery_read",sample())
        target=Path(self.temp.name)/"model-only.json"
        with patch("app.battery_gui.QFileDialog.getSaveFileName",return_value=(str(target),"JSON diagnostic snapshot (*.json)")):
            self.b.export_report("json")
        data=json.loads(target.read_text(encoding="utf8"))
        self.assertFalse(data["connector_reference"]["pinout_available"])
        self.assertEqual(data["connector_reference"]["verification"],"model_listed")


if __name__ == "__main__":
    unittest.main()

