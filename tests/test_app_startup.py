"""Real Qt process startup/shutdown; enumerates ports but never opens USB."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


class AppStartupTests(unittest.TestCase):
    def test_widget_tree_is_disposed_before_main_returns(self):
        script="""
import json,sys
from pathlib import Path
from app import gui
events=[]
settings_files=[]
OriginalWindow=gui.Window
class ObservedWindow(OriginalWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        assert self.settings.format() == gui.QSettings.Format.IniFormat
        settings_files.append(self.settings.fileName())
        self.destroyed.connect(lambda:events.append('disposed'))
gui.Window=ObservedWindow
sys.argv=['startup-test','--smoke-test']
result=gui.main()
events.append('returned')
print(json.dumps({'result':result,'events':events,'temporary_settings_removed':
                  bool(settings_files) and all(not Path(p).exists() for p in settings_files)}),flush=True)
"""
        result=subprocess.run([sys.executable,'-X','faulthandler','-c',script],
                              cwd=Path(__file__).resolve().parents[1],
                              env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()),{'result':0,'events':['disposed','returned'],
                                                            'temporary_settings_removed':True})


if __name__=='__main__':unittest.main()
