import tempfile
import unittest
from pathlib import Path
from obs_control import read_graphic_settings,save_graphic_settings

class SettingsTests(unittest.TestCase):
    def test_names_and_logos_persist_without_live_score_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            self.assertEqual(read_graphic_settings(path),{})
            save_graphic_settings({'homeName':'LOCAL','awayName':'INDEPENDIENTE','homeLogo':'assets/logo.png'},path)
            save_graphic_settings({'tournament':'Liga'},path)
            self.assertEqual(read_graphic_settings(path)['awayName'],'INDEPENDIENTE')
            self.assertEqual(read_graphic_settings(path)['tournament'],'Liga')
            for values in ({'obs_password':'secret'},{'homeScore':'99'},{'homeLogo':'file:///private'},{'homeName':'x'*121}):
                with self.assertRaises(ValueError):save_graphic_settings(values,path)
    def test_empty_value_removes_a_logo(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            save_graphic_settings({'homeLogo':'assets/logo.png'},path)
            self.assertEqual(save_graphic_settings({'homeLogo':''},path)['homeLogo'],'')

if __name__=='__main__':unittest.main()
