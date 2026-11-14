"""Model-source boundaries: only battery identities, no guessed wiring."""
import unittest
import json
import tempfile
from pathlib import Path

from devtools.import_battery_models import Models, hp_part, lenovo_models, forum_models
from devtools.import_battery_catalog import model_entries


class BatteryModelImportTests(unittest.TestCase):
    def test_adding_a_pinout_preserves_other_identity_codes_without_copying_wiring(self):
        listing={'schema':1,'entries':[{'manufacturer':'Dell','model':'WDX0R','aliases':['FW8KR'],
            'sources':[{'url':'https://example.com/identity-list'}],'notes':'Listed models'}]}
        connectors=[{'manufacturer':'Dell','model':'WDX0R','aliases':[],
                     'pins':[{'role':'data'}]}]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'models.json';path.write_text(json.dumps(listing),encoding='utf8')
            records=list(model_entries(path,connectors))
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['model'],'FW8KR')
        self.assertEqual(records[0]['pins'],[])
        self.assertEqual(records[0]['verification'],'model_listed')
        self.assertIn('not transferred',records[0]['notes'])

    def test_notebook_rows_merge_real_models_and_part_aliases_but_exclude_other_batteries(self):
        def row(number, model, asm, fru, category):
            return {"_row":number,"Battery Model":model,"ASSM PN":asm,"FRU PN":fru,
                    "SDS Link":"https://example.com/"+category+"/battery.pdf"}
        rows=[row(2,"L22D2PG2","SB11K24749","5B11K24746","notebooks---ultrabooks"),
              row(3," L22D2PG2 ","SB11N56337","5B11N56339","notebooks---ultrabooks"),
              row(4,"N/A","SB11K24749","5B11K24746","notebooks---ultrabooks"),
              row(5,"DJW12-5","00FP780","00FP780","ups"),
              row(6,"CR2032","00RY543","00RY543","coin-cell"),
              row(7,"NONE","SB12345678","5B12345678","notebooks---ultrabooks")]
        models=Models();lenovo_models(models,rows)
        entries=list(models.entries.values())
        self.assertEqual(len(entries),2)
        named=next(e for e in entries if e['model']=='L22D2PG2')
        self.assertEqual(set(named['aliases']),{'SB11K24749','5B11K24746','SB11N56337','5B11N56339'})
        self.assertEqual(len(named['sources']),2)
        self.assertNotIn('pins',named)
        self.assertEqual(next(e for e in entries if e['model']=='SB12345678')['identity_kind'],'part_number')

    def test_hp_number_normalization_does_not_import_cell_or_laptop_names(self):
        self.assertEqual(hp_part(' N69453 - 271 '),'N69453-271')
        self.assertEqual(hp_part('852527221\n-'),'852527-221')
        self.assertEqual(hp_part('HSTNNDB7L\n-'),'HSTNN-DB7L')
        self.assertEqual(hp_part('SANYOLI-IONUR18650F'),'')
        self.assertEqual(hp_part('HP Engage Go 10 Mobile System'),'')

    def test_forum_requests_do_not_replace_official_identities_or_supply_pinouts(self):
        models=Models()
        models.add('Lenovo','L22D2PG2',['SB11K24749'],{'url':'https://example.com/official'},'Official model')
        data={'schema':1,'entries':[
            {'manufacturer':'Lenovo','model':'SB11K24749','aliases':[],
             'sources':[{'url':'https://example.com/request'}],'notes':'Unsolved request'},
            {'manufacturer':'Asus','model':'C21N1818-1','aliases':[],
             'sources':[{'url':'https://example.com/another-request'}],'notes':'No confirmed wiring',
             'pins':['-','D','C','+']}]}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'forum.json';path.write_text(json.dumps(data),encoding='utf8')
            forum_models(models,path)
        entries=list(models.entries.values())
        self.assertEqual(len(entries),2)
        self.assertEqual(next(e for e in entries if e['manufacturer']=='Lenovo')['sources'],[{'url':'https://example.com/official'}])
        asus=next(e for e in entries if e['manufacturer']=='Asus')
        self.assertEqual(asus['identity_kind'],'forum_reference')
        self.assertNotIn('pins',asus)


if __name__=='__main__':
    unittest.main()
