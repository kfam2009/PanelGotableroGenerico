import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image,ImageDraw
import reader
from core import Feed,read_values

SEGMENTS={'0':'abcdef','1':'bc','2':'abdeg','3':'abcdg','4':'bcfg','5':'acdfg','6':'acdefg','7':'abc','8':'abcdefg','9':'abcdfg'}

def draw_digit(draw,x,y,w,h,digit,color=(255,40,30)):
    t=max(3,w//4+1);boxes={'a':(x+t,y,x+w-t,y+t),'b':(x+w-t,y+t,x+w,y+h//2),'c':(x+w-t,y+h//2,x+w,y+h-t),'d':(x+t,y+h-t,x+w-t,y+h),
                         'e':(x,y+h//2,x+t,y+h-t),'f':(x,y+t,x+t,y+h//2),'g':(x+t,y+h//2-t//2,x+w-t,y+h//2+t//2)}
    for segment in SEGMENTS[digit]:draw.rectangle(boxes[segment],fill=color)

def board(clock='0945',home=' 7',away='12',period='3',color=(255,40,30)):
    """A synthetic 7-segment board placed somewhere else than the default calibration."""
    frame=Image.new('RGB',(1920,1080),(25,25,30));draw=ImageDraw.Draw(frame)
    for i,d in enumerate(clock):draw_digit(draw,400+i*60,200,40,70,d,color)
    for i,d in enumerate(home):
        if d!=' ':draw_digit(draw,400+i*60,320,40,70,d,color)
    for i,d in enumerate(away):draw_digit(draw,580+i*60,320,40,70,d,color)
    draw_digit(draw,500,440,40,70,period,color)
    return frame

CALIBRATION={'view':[350,150,800,560],'color':'red','threshold':180,'groups':{
    'clock':{'quad':[[390,190],[630,190],[630,280],[390,280]],'digits':4},
    'homeScore':{'quad':[[390,310],[510,310],[510,400],[390,400]],'digits':2},
    'awayScore':{'quad':[[570,310],[690,310],[690,400],[570,400]],'digits':2},
    'period':{'quad':[[490,430],[550,430],[550,520],[490,520]],'digits':1}}}

class CalibrationTests(unittest.TestCase):
    def tearDown(self):reader.apply_calibration(None)
    def test_default_reads_nothing_on_another_board(self):
        reader.apply_calibration(None)
        self.assertEqual(read_values(board())[0],{})
    def test_calibrated_board_is_read_with_unlit_leading_digit(self):
        with tempfile.TemporaryDirectory() as folder:
            saved=reader.save_calibration(CALIBRATION,Path(folder)/'calibration.json')
            self.assertEqual(reader.load_calibration(Path(folder)/'calibration.json'),saved)
        values,_=read_values(board())
        self.assertEqual(values,{'clock':'09:45','homeScore':'7','awayScore':'12','period':'3'})
        self.assertEqual(reader.VIEW,(350,150,800,560))
    def test_three_digit_scores_and_other_led_colors(self):
        calibration={**CALIBRATION,'color':'green','groups':{**CALIBRATION['groups'],'awayScore':{'quad':[[570,310],[750,310],[750,400],[570,400]],'digits':3}}}
        reader.apply_calibration(calibration)
        values,_=read_values(board(away='104',color=(40,255,60)))
        self.assertEqual(values['awayScore'],'104')
        self.assertEqual(values['clock'],'09:45')
    def test_split_quad_follows_perspective(self):
        cells=reader.split_quad([(0,0),(100,10),(100,60),(0,50)],2)
        self.assertEqual(cells[0][1],(50.0,5.0));self.assertEqual(cells[1][2],(100.0,60.0))
    def test_invalid_calibrations_are_rejected(self):
        for bad in ({},{**CALIBRATION,'color':'blue'},{**CALIBRATION,'threshold':10},
                    {**CALIBRATION,'groups':{**CALIBRATION['groups'],'clock':{'quad':[[0,0]],'digits':4}}},
                    {**CALIBRATION,'groups':{**CALIBRATION['groups'],'period':{'quad':CALIBRATION['groups']['period']['quad'],'digits':2}}},
                    {**CALIBRATION,'groups':{**CALIBRATION['groups'],'clock':{'quad':[[0,0],[5000,0],[5000,10],[0,10]],'digits':4}}}):
            with self.assertRaises(ValueError):reader.validate_calibration(bad)
    def test_board_preview_uses_the_calibrated_zone(self):
        reader.apply_calibration(CALIBRATION)
        feed=Feed(SimpleNamespace(source='x'));feed.process(board(),100)
        import io;self.assertEqual(Image.open(io.BytesIO(feed.board)).size,(450,410))
    def test_zone_is_widened_to_contain_the_marked_groups(self):
        view=reader.validate_calibration({**CALIBRATION,'view':[1360,350,1700,610]})['view']
        self.assertTrue(view[0]<=390 and view[1]<=190 and view[2]>=690 and view[3]>=520)
        self.assertEqual(reader.validate_calibration(CALIBRATION)['view'],[350,150,800,560])
    def test_default_calibration_round_trips(self):
        default=reader.default_calibration()
        self.assertEqual(reader.validate_calibration(default)['groups']['clock']['digits'],4)

if __name__=='__main__':unittest.main()
