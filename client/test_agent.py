import math
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
        same=self.config(**{**remote,'bridge_address':'172.27.4.10'})
        self.assertEqual((same['obs_host'],same['bridge_address']),('127.0.0.1',''))
        with self.assertRaises(ValueError):self.config(**{**remote,'obs_host':'8.8.8.8'})
        with self.assertRaises(ValueError):self.config(**{**remote,'obs_host':'obs.example.com'})

    def test_vmix_reads_the_board_over_srt(self):
        vmix=dict(switcher='vmix',production_host='172.27.4.10',bridge_address='172.27.4.221',board_url='172.27.4.10:9000')
        config=self.config(**vmix)
        self.assertEqual((config['switcher'],config['board_mode'],config['production_host']),('vmix','stream','172.27.4.10'))
        self.assertEqual(config['board_url'],'srt://172.27.4.10:9000?mode=caller&latency=400000')
        self.assertIn('latency=120000',self.config(**{**vmix,'production_host':'127.0.0.1','board_url':'127.0.0.1:9000'})['board_url'])
        self.assertEqual(self.config(**{**vmix,'board_url':'srt://172.27.4.10:9000?latency=800000'})['board_url'],'srt://172.27.4.10:9000?latency=800000&mode=caller')
        self.assertEqual(self.config(**{**vmix,'board_url':'rtsp://172.27.4.50/stream'})['board_url'],'rtsp://172.27.4.50/stream')
        with self.assertRaises(ValueError):self.config(**{**vmix,'board_url':''})
        with self.assertRaises(ValueError):self.config(**{**vmix,'board_mode':'obs'})
        with self.assertRaises(ValueError):self.config(**{**vmix,'board_url':'http://172.27.4.10:9000'})
        with self.assertRaises(ValueError):self.config(**{**vmix,'switcher':'tricaster'})
        self.assertEqual(self.config(**{**vmix,'bridge_address':'172.27.4.10'})['production_host'],'127.0.0.1')

    def test_blank_frame_is_not_a_score(self):
        self.assertEqual(read_values(Image.new('RGB',(1920,1080)))[0],{})

    def test_confirmed_countdown_switches_to_tenths(self):
        feed=Feed(SimpleNamespace(source='Camara 2'));frame=Image.new('RGB',(1920,1080))
        for when,value in [(100,'01:00'),(101,'01:00'),(102,'59.8'),(103,'58.9')]:
            with patch('core.read_values',return_value=({'clock':value},{})):feed.process(frame,when)
        self.assertEqual(feed.values['clock'],'58.9')

    def test_score_change_survives_one_bad_frame(self):
        feed=Feed(SimpleNamespace(source='Camara 2'));frame=Image.new('RGB',(1920,1080))
        for when,value in [(100,'38'),(100.1,'38'),(100.2,'38'),(100.3,'38'),(102,'40'),(102.1,'40'),(103,None),(104,'40'),(104.1,'40')]:
            with patch('core.read_values',return_value=({'awayScore':value} if value else {},{})):feed.process(frame,when)
        self.assertEqual(feed.values['awayScore'],'40')
        for when,value in [(105,'42'),(105.1,'42'),(106,'48'),(107,'42'),(107.1,'42')]:
            with patch('core.read_values',return_value=({'awayScore':value},{})):feed.process(frame,when)
        self.assertEqual(feed.values['awayScore'],'42')

    def test_implausible_jumps_need_a_long_streak(self):
        feed=Feed(SimpleNamespace(source='Camara 2'));frame=Image.new('RGB',(1920,1080))
        for when,value in [(100,'0'),(100.1,'0'),(100.2,'0'),(100.3,'0'),(102,'81'),(103,'81'),(104,'0'),(105,'81'),(106,'81')]:
            with patch('core.read_values',return_value=({'awayScore':value},{})):feed.process(frame,when)
        self.assertEqual(feed.values['awayScore'],'0')
        for when in range(107,112):
            with patch('core.read_values',return_value=({'awayScore':'81'},{})):feed.process(frame,when)
        self.assertEqual(feed.values['awayScore'],'81')

    def test_unconfirmed_score_change_is_ignored(self):
        feed=Feed(SimpleNamespace(source='Camara 2'));frame=Image.new('RGB',(1920,1080))
        for when,value in [(100,'38'),(100.1,'38'),(100.2,'38'),(100.3,'38'),(102,'18'),(102.1,'18'),(103,'38')]:
            with patch('core.read_values',return_value=({'awayScore':value},{})):feed.process(frame,when)
        self.assertEqual(feed.values['awayScore'],'38')

    def run_clock(self,feed,readings):
        frame=Image.new('RGB',(1920,1080))
        for when,value in readings:
            with patch('core.read_values',return_value=({'clock':value},{})):feed.process(frame,when)

    def test_running_clock_ignores_misread_frames(self):
        feed=Feed(SimpleNamespace(source='Camara 2'))
        readings=[(100,'13:10'),(100.2,'13:10'),(100.4,'13:10')]
        # The board starts at 101 and counts down; some frames read the units wrong.
        bad={102.4:'13:01',103.6:'13:06',104.2:'13:09',105.0:'13:00'}
        t=101.0
        while t<107:
            shown=13*60+10-math.floor(t-101+1e-9)-1
            value=bad.get(round(t,1),f'{shown//60:02d}:{shown%60:02d}')
            readings.append((round(t,1),value));t+=.2
        self.run_clock(feed,readings)
        self.assertTrue(feed.clock.running)
        seen=[]
        for t in [103.3,104.3,105.1,106.5]:seen.append(feed.clock.text(t))
        self.assertEqual(seen,['13:07','13:06','13:05','13:04'])

    def test_clock_stops_when_board_stops(self):
        feed=Feed(SimpleNamespace(source='Camara 2'))
        readings=[(100,'05:00'),(100.2,'05:00'),(100.4,'05:00')]
        t=101.0
        while t<104:
            shown=300-math.floor(t-101+1e-9)-1;readings.append((round(t,1),f'{shown//60:02d}:{shown%60:02d}'));t+=.2
        while t<107:readings.append((round(t,1),'04:57'));t+=.2
        self.run_clock(feed,readings)
        self.assertFalse(feed.clock.running);self.assertEqual(feed.values['clock'],'04:57')
        self.assertEqual(feed.snapshot()['clock'],'04:57')
        # It starts again when the board goes down.
        self.run_clock(feed,[(107.2,'04:56'),(107.4,'04:56'),(107.6,'04:56')])
        self.assertTrue(feed.clock.running)

    def test_free_throw_stop_is_seen_quickly_and_holds(self):
        feed=Feed(SimpleNamespace(source='Camara 2'))
        readings=[(100,'06:00'),(100.125,'06:00')]
        t=101.0
        while t<104.6:
            shown=360-math.floor(t-101+1e-9)-1;readings.append((round(t,3),f'{shown//60:02d}:{shown%60:02d}'));t+=.125
        self.run_clock(feed,readings)
        stopped_at=readings[-1][1]  # board stops at 104.5 showing 05:56
        t=104.625;seen=None
        while t<110:
            self.run_clock(feed,[(round(t,3),stopped_at)])
            if seen is None and not feed.clock.running:seen=t
            t+=.125
        self.assertIsNotNone(seen);self.assertLessEqual(seen,104.0+1.35)
        self.assertFalse(feed.clock.running);self.assertEqual(feed.values['clock'],stopped_at)
        self.run_clock(feed,[(110.1,'05:55'),(110.2,'05:55')])
        self.assertTrue(feed.clock.running);self.assertEqual(feed.clock.text(110.3),'05:55')

    def test_last_minute_stop_with_tenths(self):
        feed=Feed(SimpleNamespace(source='Camara 2'))
        readings=[];t=100.0
        while t<102:
            readings.append((round(t,3),f'{math.ceil((45-(t-100))*10-1e-6)/10:04.1f}'));t+=.125
        self.run_clock(feed,readings)
        self.assertTrue(feed.clock.running)
        held=readings[-1][1];t=102.125
        while t<102.7:self.run_clock(feed,[(round(t,3),held)]);t+=.125
        self.assertFalse(feed.clock.running);self.assertEqual(feed.values['clock'],held)

    def test_clock_set_by_operator_is_followed(self):
        feed=Feed(SimpleNamespace(source='Camara 2'))
        readings=[(100,'05:00'),(100.2,'05:00')]
        t=101.0
        while t<103:
            shown=300-math.floor(t-101+1e-9)-1;readings.append((round(t,1),f'{shown//60:02d}:{shown%60:02d}'));t+=.2
        readings+=[(round(103.2+i*.2,1),'08:00') for i in range(12)]
        self.run_clock(feed,readings)
        self.assertEqual(feed.values['clock'],'08:00')

    def test_short_run_of_misreads_does_not_reset_the_clock(self):
        feed=Feed(SimpleNamespace(source='Camara 2'))
        readings=[(100,'04:20'),(100.2,'04:20')]
        t=101.0
        while t<103:
            shown=260-math.floor(t-101+1e-9)-1;readings.append((round(t,1),f'{shown//60:02d}:{shown%60:02d}'));t+=.2
        readings+=[(103.2,'00:48'),(103.4,'00:48'),(103.6,'00:48'),(103.8,'00:48'),(104.0,'04:16')]
        self.run_clock(feed,readings)
        self.assertTrue(feed.clock.running);self.assertEqual(feed.clock.text(104.1),'04:16')


if __name__=='__main__':unittest.main()
