import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image,ImageDraw
from core import Feed
from reader import board_power_state

def dark_board():
    frame=Image.new('RGB',(1920,1080),(60,60,60))
    draw=ImageDraw.Draw(frame)
    for y in range(360,600,20):draw.line((1365,y,1695,y),fill=(180,180,180),width=5)
    return frame

class StandbyTests(unittest.TestCase):
    def test_visible_unlit_board_is_distinct_from_black_camera(self):
        self.assertEqual(board_power_state(dark_board()),'off')
        self.assertEqual(board_power_state(Image.new('RGB',(1920,1080))),'unknown')
        self.assertEqual(board_power_state(Image.new('RGB',(960,540))),'unknown')
        self.assertEqual(board_power_state(dark_board(),{'h1':'0'}),'on')
    def test_only_sustained_darkness_resets_the_three_requested_values(self):
        feed=Feed(SimpleNamespace(source='Camara 2'))
        feed.values.update(homeScore='55',awayScore='66',clock='00:00',period='4')
        frame=dark_board()
        feed.process(frame,100);feed.process(frame,101)
        self.assertEqual(feed.values['homeScore'],'55')
        feed.process(frame,102.1)
        self.assertTrue(feed.board_off)
        self.assertEqual((feed.values['homeScore'],feed.values['awayScore'],feed.values['clock']),('0','0','10:00'))
        self.assertEqual(feed.values['period'],'4')
    def test_black_or_unreadable_camera_keeps_the_previous_score(self):
        feed=Feed(SimpleNamespace(source='Camara 2'));feed.values['awayScore']='66'
        for now in (100,103,110):feed.process(Image.new('RGB',(1920,1080)),now)
        self.assertFalse(feed.board_off);self.assertEqual(feed.values['awayScore'],'66')
    def test_powering_on_requires_confirmed_readings_again(self):
        feed=Feed(SimpleNamespace(source='Camara 2'));frame=dark_board()
        feed.process(frame,100);feed.process(frame,103)
        readings={'homeScore':'12','awayScore':'8','clock':'09:50','period':'1'}
        with patch('core.read_values',return_value=(readings,{'h1':'1'})):
            feed.process(frame,104);self.assertEqual(feed.values['homeScore'],'0')
            feed.process(frame,105);feed.process(frame,105.1);feed.process(frame,105.2)
        self.assertFalse(feed.board_off);self.assertEqual(feed.values['homeScore'],'12');self.assertEqual(feed.values['clock'],'09:50')
    def test_connection_loss_does_not_turn_the_standby_into_a_live_reading(self):
        feed=Feed(SimpleNamespace(source='Camara 2'));frame=dark_board();now=time.time()
        feed.process(frame,now-3);feed.process(frame,now)
        self.assertEqual(feed.snapshot()['ocrStatus'],'standby')
        feed.connected=False
        self.assertFalse(feed.snapshot()['boardOff']);self.assertEqual(feed.snapshot()['ocrStatus'],'waiting')

if __name__=='__main__':unittest.main()
