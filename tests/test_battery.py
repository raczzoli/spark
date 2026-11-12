"""SBS units, PEC negotiation, controller gating and USB adapter boundaries."""
import unittest
from dataclasses import replace
from unittest.mock import patch, Mock
from app.battery import BatteryError, BatteryTransport, Snapshot, read_snapshot, read_ti_diagnostics, service, WORDS, TEXTS
from app.battery_operations import BatteryWorker
from app.transport import TransportError


def sample(**updates):
    words={f"{reg:02X}":0 for reg in WORDS}
    words.update({'03':0x6001,'08':2975,'09':15186,'0A':0xFC18,'0D':90,'0F':2034,'10':2282,'16':0xC0,'17':214,'18':3220,'19':15200,'1A':0x31,'1B':0x4AFC,'1C':0x7B1C})
    return replace(Snapshot('2026-11-12T17:09:44+00:00',words,{'manufacturer':'LGC','device':'AC14B8K','chemistry':'LION'},{},True),**updates)


class Gauge:
    def __init__(self):
        self.snapshot=sample();self.pec_mode='auto';self.pec=False;self._synchronized=True;self.calls=[];self.failure=None
    def read_word(self,reg,pec=None):
        self.calls.append(('word',reg,self.pec if pec is None else pec))
        if self.failure and reg==self.failure[0]:raise self.failure[1]
        return self.snapshot.raw(reg)
    def read_block(self,reg):
        self.calls.append(('block',reg,self.pec));return self.snapshot.strings[TEXTS[reg]].encode()


class BatteryTests(unittest.TestCase):
    def test_real_pack_units_signed_current_date_and_estimated_health(self):
        s=sample();m=s.metrics
        self.assertEqual((m['voltage'],m['current'],m['remaining_capacity'],m['capacity_unit']),(15.186,-1.0,2034,'mAh'))
        self.assertAlmostEqual(m['temperature'],24.35);self.assertAlmostEqual(m['health'],2282/3220*100)
        self.assertEqual(s.manufacture_date,'2017-07-28');self.assertIn('no controlled discharge',s.export()['capacity_note'])

    def test_energy_mode_and_specification_scaling(self):
        s=sample();s.words.update({'03':0x8000,'1A':0x2131})
        self.assertEqual(s.metrics['voltage'],151.86)
        self.assertEqual(s.metrics['current'],-100)
        self.assertEqual(s.metrics['design_capacity'],3220000)
        self.assertEqual(s.metrics['capacity_unit'],'mWh')

    def test_missing_optional_values_are_not_displayed_as_zero(self):
        s=sample()
        for reg in ('08','0A','0D','0F','10','17'):s.words.pop(reg)
        for key in ('temperature','current','soc','remaining_capacity','full_capacity','cycles','health'):
            self.assertIsNone(s.metrics[key],key)
        s.words['1B']=0;self.assertEqual(s.manufacture_date,'Not reported')

    def test_standard_read_negotiates_pec_without_manufacturer_commands(self):
        bus=Gauge();result=read_snapshot(bus)
        self.assertEqual(bus.calls[0],('word',0x1A,False));self.assertTrue(result.pec)
        self.assertTrue(all(call[2] for call in bus.calls[1:]))
        self.assertEqual({c[1] for c in bus.calls if c[0]=='block'},{0x20,0x21,0x22})
        self.assertEqual(result.identity,sample().identity)

    def test_pec_off_is_explicit_and_auto_does_not_require_unsupported_pec(self):
        for mode,spec,expected in (('auto',0x11,False),('auto',0x21,False),('on',0x11,True),('off',0x31,False)):
            bus=Gauge();bus.pec_mode=mode;bus.snapshot.words['1A']=spec
            self.assertEqual(read_snapshot(bus).pec,expected)

    def test_nack_optional_is_retained_but_pec_or_required_or_usb_failure_aborts(self):
        bus=Gauge();bus.failure=(0x17,TransportError('ERR SMB_COMMAND_NACK'))
        result=read_snapshot(bus);self.assertIn('Cycle count',result.errors);self.assertIsNone(result.metrics['cycles'])
        for reg,message,sync in ((0x17,'ERR SMB_PEC',True),(0x09,'ERR SMB_COMMAND_NACK',True),(0x17,'USB disconnected',False)):
            bus=Gauge();bus.failure=(reg,TransportError(message));bus._synchronized=sync
            with self.assertRaises(TransportError):read_snapshot(bus)

    def test_unknown_sbs_spec_is_rejected_before_reading_other_registers(self):
        bus=Gauge();bus.snapshot.words['1A']=0xFFFF
        with self.assertRaises(BatteryError):read_snapshot(bus)
        self.assertEqual(len(bus.calls),1)

    def test_ti_profile_requires_matching_device_and_firmware(self):
        bus=Mock();bus.query_ti.return_value=b'\x50\x40'
        with self.assertRaisesRegex(BatteryError,'did not identify'):read_ti_diagnostics(bus)
        self.assertEqual(bus.query_ti.call_count,1)
        bus.query_ti.side_effect=[b'\x00\x45',b'\x45\x00\x02\x08\x00\x01'+bytes(5)]
        info=read_ti_diagnostics(bus);self.assertFalse(info['service_supported']);self.assertNotIn('security',info)

    def test_ti_status_cells_decode_preserves_unused_inputs(self):
        bus=Mock();bus.query_ti.side_effect=[b'\x00\x45',b'\x45\x00\x03\x01\x00\x01'+bytes(5),b'\x00\x03\x00\x00',bytes(4),bytes(4),b'\xA0\x0F\xB4\x0F\x00\x00\x00\x00'+bytes(24)]
        info=read_ti_diagnostics(bus)
        self.assertEqual(info['security'],'Sealed');self.assertEqual(info['cells_mV'],[4000,4020,0,0]);self.assertEqual(info['imbalance_mV'],20)
        self.assertEqual(info['firmware'], '0301')
        self.assertEqual(info['firmware_display'], '3.01')

    def test_service_refuses_changed_pack_wrong_revision_or_no_pec_before_keys(self):
        original=sample();original.controller={'service_supported':True,'security':'Sealed'}
        for candidate in (replace(original,strings={'device':'OTHER'}),replace(original,pec=False),replace(original,controller={'service_supported':False})):
            bus=Mock()
            with patch('app.battery.read_snapshot',return_value=candidate),patch('app.battery.read_ti_diagnostics',return_value=candidate.controller),self.assertRaises(BatteryError):service(bus,'unseal',original,(0x1234,0x5678))
            bus._write_word.assert_not_called()

    def test_service_pair_has_no_guess_or_retry_and_rechecks_result(self):
        original=sample();original.controller={'service_supported':True,'security':'Sealed'}
        after=replace(original,controller={'service_supported':True,'security':'Unsealed'})
        bus=Mock()
        with patch('app.battery.read_snapshot',side_effect=[original,after]),patch('app.battery.read_ti_diagnostics',return_value=original.controller),patch('app.battery.time.sleep'):
            self.assertIs(service(bus,'unseal',original,(0x1234,0x5678)),after)
        self.assertEqual([c.args for c in bus._write_word.call_args_list],[(0,0x1234),(0,0x5678)])
        bus.reset_mock()
        with patch('app.battery.read_snapshot',side_effect=[original,original]),patch('app.battery.read_ti_diagnostics',return_value=original.controller),patch('app.battery.time.sleep'),self.assertRaisesRegex(BatteryError,'No key retry'):
            service(bus,'unseal',original,(0x1234,0x5678))
        self.assertEqual(bus._write_word.call_count,2)

    def test_service_state_and_missing_reference_guards(self):
        bus=Mock()
        with self.assertRaises(BatteryError):service(bus,'seal',None)
        bus.assert_not_called()
        s=sample();s.controller={'service_supported':True,'security':'Sealed'}
        with patch('app.battery.read_snapshot',return_value=s),patch('app.battery.read_ti_diagnostics',return_value=s.controller),self.assertRaisesRegex(BatteryError,'Unseal this'):service(bus,'full_access',s,(1,2))
        bus._write_word.assert_not_called()

    def test_changed_pack_is_rejected_before_any_manufacturer_selector(self):
        bus=Gauge();bus.snapshot.words['1C']+=1
        with self.assertRaisesRegex(BatteryError,'identity changed'):service(bus,'unseal',sample(),(1,2))
        self.assertNotIn(0x44,[c[1] for c in bus.calls])

    def test_worker_closes_before_result_and_forgets_keys_on_failure(self):
        worker=BatteryWorker('battery_unseal','TEST',(7,9),expected=sample(),keys=(1,2));events=[]
        bus=Mock();bus.close.side_effect=lambda:events.append('closed')
        worker.finished.connect(lambda *args:events.append('finished'));worker.failed.connect(lambda text:events.append('failed'))
        with patch('app.battery_operations.BatteryTransport',return_value=bus),patch('app.battery_operations.service',side_effect=BatteryError('Wrong device')):worker.run()
        self.assertEqual(events,['closed','failed']);self.assertIsNone(worker.keys)


class BatteryAdapterTests(unittest.TestCase):
    def adapter(self):
        bus=BatteryTransport.__new__(BatteryTransport);bus.address=0x0B;bus.pec=True;bus._synchronized=True;return bus

    def test_bad_echo_or_pec_claim_invalidates_usb_session(self):
        for reply in ('SMBWORD 08 3B51 PEC=OK','SMBWORD 09 3B51 PEC=OFF','SMBWORD 09 FFFFFF PEC=OK'):
            bus=self.adapter();bus.command=Mock(return_value=reply)
            with self.assertRaises(TransportError):bus.read_word(9)
            self.assertFalse(bus._synchronized)

    def test_mac_can_return_34_bytes_but_standard_strings_cannot(self):
        bus=self.adapter();data=bytes(range(34));bus.command=Mock(return_value='SMBBLOCK 44 '+data.hex().upper()+' PEC=OK')
        self.assertEqual(bus.read_block(0x44),data)
        bus.command.return_value='SMBBLOCK 20 '+data.hex().upper()+' PEC=OK'
        with self.assertRaises(TransportError):bus.read_block(0x20)

    def test_odd_hex_block_is_rejected_and_only_readonly_mac_queries_allowed(self):
        bus=self.adapter();bus.command=Mock(return_value='SMBBLOCK 20 ABC PEC=OK')
        with self.assertRaises(TransportError):bus.read_block(0x20)
        with self.assertRaises(BatteryError):bus.query_ti(0x29)

    def test_open_validates_lines_and_closes_with_no_ec_release(self):
        def init(bus,*args,**kwargs):
            bus.port=Mock(is_open=True);bus._synchronized=True
        for answer in ('SMBOPEN SDA=7 SCL=9 DATA=1 CLOCK=1','SMBOPEN SDA=7 SCL=9 DATA=0 CLOCK=1'):
            calls=[]
            def command(bus,text):
                calls.append(text);return answer if text.startswith('SMBOPEN') else 'OK'
            with patch('app.battery.PicoTransport.__init__',init),patch.object(BatteryTransport,'supports',return_value=True),patch.object(BatteryTransport,'command',command):
                if 'DATA=0' in answer:
                    with self.assertRaisesRegex(BatteryError,'idle HIGH'):BatteryTransport('TEST')
                else:BatteryTransport('TEST').close()
            self.assertEqual(calls,['SMBOPEN 7 9 1 5','SMBCLOSE'])


if __name__=='__main__':unittest.main()
