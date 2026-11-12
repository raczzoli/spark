"""Exercise real SMBus C with slave ACK/data/PEC bits and GPIO faults."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class SMBusFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=[sys.executable,"-m","ziglang","cc"] if importlib.util.find_spec("ziglang") else [os.environ.get("CC") or shutil.which("cc") or "gcc"]
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.exe=Path(cls.temp.name)/("smbus.exe" if os.name=="nt" else "smbus")
        sources=["tests/native/smbus_harness.c","firmware/smbus.c","firmware/smbus_commands.c","firmware/usb_commands.c","firmware/usb_output.c"]
        subprocess.run(compiler+["-std=c11","-Wall","-Wextra","-Werror","-Itests/native","-Ifirmware",*sources,"-o",str(cls.exe)],cwd=ROOT,check=True,capture_output=True,text=True,timeout=180)

    def run_c(self,*args):
        return subprocess.check_output([str(self.exe),*args],text=True,timeout=5).splitlines()

    def test_word_and_block_pec_match_known_packets(self):
        self.assertEqual(self.run_c("word")[0],"OK=1 VALUE=3B51 ERROR=SMB_BUS")
        self.assertEqual(self.run_c("nopec")[0],"OK=1 VALUE=3B51 ERROR=SMB_BUS")
        self.assertEqual(self.run_c("block")[:2],["OK=1 LEN=3 ERROR=SMB_BUS","DATA=ABC"])

    def test_pec_and_block_length_errors_publish_no_value(self):
        self.assertEqual(self.run_c("badpec")[0],"OK=0 VALUE=DEAD ERROR=SMB_PEC")
        self.assertEqual(self.run_c("longblock")[0],"OK=0 LEN=99 ERROR=SMB_BLOCK_LENGTH")

    def test_ti_mac_echo_extension_allows_34_but_rejects_35_bytes(self):
        self.assertEqual(self.run_c("mac34")[0],"OK=1 LEN=34 ERROR=SMB_BUS")
        self.assertEqual(self.run_c("mac35")[0],"OK=0 LEN=99 ERROR=SMB_BLOCK_LENGTH")

    def test_word_and_block_writes_have_exact_wire_order_and_pec(self):
        # CRCs independently checked by polynomial division with x^8+x^2+x+1.
        self.assertEqual(self.run_c("write")[1],"TX=16003412C0")
        self.assertEqual(self.run_c("writeblock")[1],"TX=164402010079")

    def test_open_drain_release_and_ec_pin_isolation(self):
        for scenario in ("word","nopec","block","badpec","longblock","nack","write","expire","clocklow","clockdrive","datadrive"):
            with self.subTest(scenario=scenario):
                self.assertEqual(self.run_c(scenario)[-1],"HIGH=0 RELEASED=1 PULLS=0 EC=7,6")

    def test_timeouts_and_gpio_drive_failures_are_bounded(self):
        for scenario,code in (("clocklow","SMB_CLOCK_TIMEOUT"),("clockdrive","SMB_CLOCK_DRIVE"),("datadrive","SMB_DATA_DRIVE")):
            with self.subTest(scenario=scenario):
                result=self.run_c(scenario)[0]
                self.assertIn("OK=0 ERROR="+code,result)
                self.assertLess(int(result.split("TIME=")[1]),100000)

    def test_nack_and_idle_expiry(self):
        self.assertEqual(self.run_c("nack")[0],"OK=0 ERROR=SMB_ADDRESS_NACK")
        self.assertEqual(self.run_c("expire")[0],"ACTIVE=0")

    def test_parser_rejects_bad_arguments_and_blocks_ec_while_open(self):
        for command in ("SMBRW 0B -1 1","SMBRW 80 09 1","SMBRW 0B 09 2","SMBWW 0B 00 -123 1","SMBWB 0B 44 XYZ 1","SMBOPEN 7 7 1 5","SMBOPEN 7 24 1 5","SMBOPEN 7 9 1 1"):
            with self.subTest(command=command):
                self.assertEqual(self.run_c("parser",command)[1],"ERR SMB_ARGUMENT")
        self.assertEqual(self.run_c("parser","REGREAD 00")[1],"ERR SMB_ACTIVE")
        self.assertEqual(self.run_c("parser","SMBCLOSE")[1:], ["OK","ENDS=1 CLOSES=1 ACTIVE=0"])
        self.assertEqual(self.run_c("parser","SMBCLOSE","REGREAD 00")[1:3],["OK","EC_DISPATCH"])


if __name__=="__main__":unittest.main()
