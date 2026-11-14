import unittest
from app.battery_catalog import catalog,search,connection_for,has_bus_pinout,has_pinout,pinout_summary,pico_physical,ROLE_LABELS,brands


class CatalogTests(unittest.TestCase):
    def test_brand_registry_includes_empty_brands_and_existing_catalog_manufacturers(self):
        names=brands()
        self.assertEqual(names,tuple(sorted(names,key=str.casefold)))
        self.assertEqual(len(names),len({name.casefold() for name in names}))
        self.assertTrue({'DJI','Fujifilm','Google','Honor','iRobot','Thunderobot'}.issubset(names))
        self.assertTrue({e['manufacturer'].casefold() for e in catalog()}.issubset({name.casefold() for name in names}))
        self.assertFalse(any(e['manufacturer']=='DJI' for e in catalog()))

    def test_catalog_keeps_pinout_and_model_identity_records_explicit(self):
        entries=catalog();self.assertGreaterEqual(len(entries),80)
        self.assertEqual(len(entries),len({e['id'] for e in entries}))
        for e in entries:
            with self.subTest(model=e['model']):
                self.assertEqual([p['number'] for p in e['pins']],list(range(1,len(e['pins'])+1)))
                self.assertTrue(e['sources'][0]['url'].startswith('https://'))
                self.assertTrue(e['orientation'])
                self.assertTrue(all(p['role'] in ROLE_LABELS for p in e['pins']))
                if not has_pinout(e):
                    self.assertEqual(e['verification'],'model_listed')
                    self.assertFalse(e['present_to_ground'])
                    self.assertFalse(has_bus_pinout(e))

    def test_search_finds_aliases_case_punctuation_and_brand(self):
        self.assertEqual(search('ac14-b8k')[0]['model'],'AC14B8K')
        self.assertEqual(search('916811 855')[0]['model'],'BK03XL')
        self.assertTrue(all(e['manufacturer']=='HP' for e in search('HP BK03')))
        self.assertEqual(search('no-such-battery-xyz'),[])

    def test_signal_gpio_and_pico_pad_numbers_are_separate(self):
        e=search('AC14B8K')[0]
        self.assertEqual(connection_for(e['pins'][2],e,7,9)[0],'Pico GP7')
        self.assertEqual(connection_for(e['pins'][3],e,7,9)[0],'Pico GP9')
        self.assertEqual(connection_for(e['pins'][3],e,12,13)[0],'Pico GP13')
        self.assertEqual((pico_physical(7),pico_physical(9)),(10,12))
        self.assertTrue(has_bus_pinout(e))

    def test_power_unknown_uncertain_and_unconfirmed_present_never_get_gpio(self):
        for e in catalog():
            for p in e['pins']:
                if p['role'] not in ('clock','data') or p.get('uncertain'):
                    self.assertNotRegex(connection_for(p,e)[0],r'GP\d')
                if p['role']=='present' and not e['present_to_ground']:
                    self.assertNotIn('GND',connection_for(p,e)[0])
        self.assertFalse(has_bus_pinout(search('PA3905U')[0]))

    def test_gap_and_unresolved_t_are_not_thermistor_guesses(self):
        e=next(e for e in search('45N1001') if len(e['pins'])==8)
        self.assertEqual(e['pins'][2]['role'],'gap')
        e=search('AP11D3F')[0];self.assertEqual(e['pins'][6]['role'],'unknown')

    def test_forum_corrections_distinguish_sensor_present_and_auxiliary_power(self):
        asus=search('A32-F82')[0]
        self.assertEqual(asus['pins'][2]['role'],'temperature')
        self.assertEqual(connection_for(asus['pins'][2],asus)[0],'Leave disconnected')
        for index in (5,6):
            self.assertEqual(asus['pins'][index]['role'],'present')
            self.assertEqual(connection_for(asus['pins'][index],asus)[0],'Battery B− / GND')
        apple=search('A1382')[0]
        self.assertEqual([apple['pins'][i]['role'] for i in (3,5)],['data','clock'])
        self.assertEqual(apple['pins'][4]['role'],'unknown')
        hp=search('BI03XL')[0]
        self.assertEqual(hp['pins'][6]['role'],'unknown')
        self.assertEqual(connection_for(hp['pins'][6],hp)[0],'Unidentified')

    def test_forum_sparse_contacts_and_corrected_ground_remain_distinct(self):
        dell=search('J60J5')[0]
        self.assertEqual(dell['pins'][3]['role'],'present')
        self.assertEqual(dell['pins'][4]['role'],'ground')
        self.assertTrue(dell['present_to_ground'])
        hp=search('LP03XL')[0]
        self.assertEqual(len(hp['pins']),10)
        self.assertFalse(hp['pin_count_inferred'])
        for index in (6,9):
            self.assertEqual(hp['pins'][index]['role'],'unknown')
            self.assertNotRegex(connection_for(hp['pins'][index],hp)[0],r'GP\d|GND')
        self.assertIn('Bottom',search('RR03XL')[0]['orientation'])

    def test_model_identity_has_no_invented_connector_and_searches_assembly_parts(self):
        entry=search('L22D2PG2')[0]
        self.assertEqual(entry['manufacturer'],'Lenovo')
        self.assertEqual(entry['pins'],[])
        self.assertEqual(pinout_summary(entry),'Pinout unavailable')
        for part in ('SB11K24749','5B11K24746','SB11N56337','5B11N56339'):
            self.assertEqual(search(part)[0]['id'],entry['id'])
        self.assertTrue(has_pinout(search('AC14B8K')[0]))
        self.assertEqual(pinout_summary(search('AC14B8K')[0]),'8 pins')

    def test_google_source_review_keeps_sparse_battery_maps_separate_from_cable_guesses(self):
        acer=next(e for e in search('AC14B18J') if e['model']=='AC14B18J')
        self.assertEqual([p['role'] for p in acer['pins']],
                         ['ground','unknown','data','clock','unknown','present','unknown','positive'])
        dell=next(e for e in search('WDX0R') if e['model']=='WDX0R')
        self.assertEqual(len(dell['pins']),10)
        self.assertEqual([dell['pins'][i]['role'] for i in (0,3,5,6,9)],
                         ['ground','present','data','clock','positive'])
        for record in (acer,dell):
            self.assertTrue(record['pin_count_inferred'])
            self.assertFalse(record['present_to_ground'])
        self.assertFalse(has_pinout(search('FW8KR')[0]))


if __name__=='__main__':unittest.main()
