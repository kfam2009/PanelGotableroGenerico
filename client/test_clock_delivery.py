import json
import base64
import io
import threading
import time
import unittest
import urllib.request
from types import SimpleNamespace
from agent import Uplink,local_server
from core import Feed,KEYS
from refresh_graphic import refresh_graphic,SOURCE
from PIL import Image
from unittest.mock import patch

class ClockDeliveryTests(unittest.TestCase):
    def test_uplink_sends_each_confirmed_second_without_fixed_delay(self):
        class Finished(BaseException):pass
        values=iter(['09:03','09:02','09:01'])
        def snapshot():
            try:clock=next(values)
            except StopIteration:raise Finished()
            return {'clock':clock,'homeScore':'12','awayScore':'10','period':'1','connected':True,'boardOff':False,'updatedAt':'2026-10-17T12:00:00Z','fields':{key:{'valid':True,'age':0} for key in KEYS}}
        sent=[]
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b''
        def post(request,timeout):sent.append(json.loads(request.data)['clock']);return Response()
        uplink=Uplink(SimpleNamespace(snapshot=snapshot),{'cloud_url':'https://example.com','ingest_token':'x'*40})
        uplink.opener=SimpleNamespace(open=post)
        started=time.monotonic()
        with self.assertRaises(Finished):uplink.run()
        self.assertEqual(sent,['09:03','09:02','09:01'])
        self.assertLess(time.monotonic()-started,.5)

    def test_local_events_deliver_ticks_without_waiting_for_one_second(self):
        feed=Feed(SimpleNamespace(source='Camara 2'))
        feed.values['clock']='09:03'
        uplink=SimpleNamespace(config={'cloud_url':'https://panelgo-tablero.onrender.com'},message='ok')
        server=local_server(feed,uplink,SimpleNamespace(snapshot=lambda:{}),0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        response=None
        try:
            response=opener.open(f'http://127.0.0.1:{server.server_port}/api/events',timeout=.7)
            def next_clock():
                while True:
                    line=response.readline().decode()
                    if line.startswith('data: '):return json.loads(line[6:])['clock']
            self.assertEqual(next_clock(),'09:03')
            started=time.monotonic()
            for clock in ['09:02','09:01']:
                with feed.lock:feed.values['clock']=clock;feed.revision+=1;feed.lock.notify_all()
                self.assertEqual(next_clock(),clock)
            self.assertLess(time.monotonic()-started,.5)
        finally:
            if response:response.close()
            server.shutdown();server.server_close();thread.join(timeout=2)

    def test_refresh_changes_only_the_owned_browser_url(self):
        calls=[]
        def request(kind,data=None):
            calls.append((kind,data))
            if kind=='GetInputList':return {'inputs':[{'inputName':SOURCE,'inputKind':'browser_source'}]}
            if kind=='GetInputSettings':return {'inputSettings':{'url':'http://172.27.4.221:8772/graphics.html?v=old','width':1280,'height':720}}
            return {}
        self.assertTrue(refresh_graphic(SimpleNamespace(request=request)))
        writes=[(kind,data) for kind,data in calls if kind.startswith('Set')]
        self.assertEqual(writes,[('SetInputSettings',{'inputName':SOURCE,'inputSettings':{'url':'http://127.0.0.1:8771/graphics.html?v=clock-fast-1'},'overlay':True})])
    def test_blank_source_restores_the_previous_url(self):
        calls=[];old='http://172.27.4.221:8772/graphics.html?v=old'
        raw=io.BytesIO();Image.new('RGBA',(4,4)).save(raw,format='PNG')
        def request(kind,data=None):
            calls.append((kind,data))
            if kind=='GetInputList':return {'inputs':[{'inputName':SOURCE,'inputKind':'browser_source'}]}
            if kind=='GetInputSettings':return {'inputSettings':{'url':old}}
            if kind=='GetSourceActive':return {'videoShowing':True}
            if kind=='GetSourceScreenshot':return {'imageData':'data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode()}
            return {}
        with patch('refresh_graphic.time.sleep'),self.assertRaises(RuntimeError):refresh_graphic(SimpleNamespace(request=request),verify=True)
        self.assertEqual(calls[-1],('SetInputSettings',{'inputName':SOURCE,'inputSettings':{'url':old},'overlay':True}))

if __name__=='__main__':unittest.main()
