import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from agent import load_config
from core import Feed, read_values


class ClientTests(unittest.TestCase):
    def config(self, **changes):
        values=dict(cloud_url='https://example.onrender.com',ingest_token='x'*40,obs_host='127.0.0.1')
        values.update(changes)
        with tempfile.TemporaryDirectory(prefix='.test-',dir=Path(__file__).resolve().parent) as folder:
            path=Path(folder)/'config.json';path.write_text(json.dumps(values),encoding='utf-8')
            return load_config(path)

    def test_local_obs_and_https_cloud(self):
        self.assertEqual(self.config()['obs_host'],'127.0.0.1')
        with self.assertRaises(ValueError):self.config(obs_host='192.0.2.1')
        with self.assertRaises(ValueError):self.config(cloud_url='http://example.com')
        with self.assertRaises(ValueError):self.config(cloud_url='https://example.com?token=private')
        with self.assertRaises(ValueError):self.config(ingest_token='short')

    def test_remote_obs_over_zerotier(self):
        remote=dict(obs_host='172.27.4.10',obs_password='clave-obs',bridge_address='172.27.4.221')
        config=self.config(**remote)
        self.assertEqual((config['obs_host'],config['bridge_address']),('172.27.4.10','172.27.4.221'))
        self.assertEqual(self.config()['bridge_address'],'')
        self.assertEqual(self.config(**{**remote,'obs_password':''})['obs_host'],'172.27.4.10')
        with self.assertRaises(ValueError):self.config(**{**remote,'bridge_address':''})
        with self.assertRaises(ValueError):self.config(**{**remote,'bridge_address':'172.27.4.10'})
        with self.assertRaises(ValueError):self.config(**{**remote,'obs_host':'8.8.8.8'})
        with self.assertRaises(ValueError):self.config(**{**remote,'obs_host':'obs.example.com'})

    def test_blank_frame_is_not_a_score(self):
        self.assertEqual(read_values(Image.new('RGB',(1920,1080)))[0],{})

    def test_confirmed_countdown_switches_to_tenths(self):
        feed=Feed(SimpleNamespace(source='Camara 2'));frame=Image.new('RGB',(1920,1080))
        for when,value in [(100,'01:00'),(101,'01:00'),(102,'59.8'),(103,'58.9')]:
            with patch('core.read_values',return_value=({'clock':value},{})):feed.process(frame,when)
        self.assertEqual(feed.values['clock'],'58.9')

    def test_unconfirmed_score_change_is_ignored(self):
        feed=Feed(SimpleNamespace(source='Camara 2'));frame=Image.new('RGB',(1920,1080))
        for when,value in [(100,'38'),(101,'38'),(102,'18'),(103,'38')]:
            with patch('core.read_values',return_value=({'awayScore':value},{})):feed.process(frame,when)
        self.assertEqual(feed.values['awayScore'],'38')


if __name__=='__main__':unittest.main()
