import unittest
from app.battery_catalog import catalog,search,connection_for,has_bus_pinout,pico_physical,ROLE_LABELS


class CatalogTests(unittest.TestCase):
    def test_catalog_has_complete_position_lists_sources_and_unique_ids(self):
        entries=catalog();self.assertGreaterEqual(len(entries),80)
        self.assertEqual(len(entries),len({e['id'] for e in entries}))
        for e in entries:
            with self.subTest(model=e['model']):
                self.assertEqual([p['number'] for p in e['pins']],list(range(1,len(e['pins'])+1)))
                self.assertTrue(e['sources'][0]['url'].startswith('https://'))
                self.assertTrue(e['orientation'])
                self.assertTrue(all(p['role'] in ROLE_LABELS for p in e['pins']))

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


if __name__=='__main__':unittest.main()
