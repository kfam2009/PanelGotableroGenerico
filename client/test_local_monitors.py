import threading
import unittest
import urllib.request
import urllib.error
from types import SimpleNamespace
from agent import local_server
from obs_control import make_control_server

class LocalMonitorTests(unittest.TestCase):
    def test_hosted_controls_require_the_trusted_origin_and_token(self):
        control=SimpleNamespace(status=lambda:{'ready':True,'enabled':False})
        server=make_control_server(control,port=0,cloud_origin='https://panelgo-tablero.onrender.com')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        address=f'http://127.0.0.1:{server.server_port}'
        try:
            request=urllib.request.Request(address+'/state',headers={'Origin':'https://panelgo-tablero.onrender.com'})
            with opener.open(request,timeout=3) as response:
                self.assertEqual(response.headers['Access-Control-Allow-Origin'],'https://panelgo-tablero.onrender.com')
            request=urllib.request.Request(address+'/visibility',data=b'{"enabled":true}',headers={'Origin':'https://panelgo-tablero.onrender.com','Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as error:opener.open(request,timeout=3)
            self.assertEqual(error.exception.code,403)
            request=urllib.request.Request(address+'/state',headers={'Origin':'https://unrelated.example'})
            with self.assertRaises(urllib.error.HTTPError) as error:opener.open(request,timeout=3)
            self.assertEqual(error.exception.code,403)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

    def test_only_configured_render_origin_can_read_monitors(self):
        feed=SimpleNamespace(snapshot=lambda:{'service':'panelgo-tablero'},lock=threading.Lock(),board=b'board')
        game=SimpleNamespace(snapshot=lambda:{})
        uplink=SimpleNamespace(config={'cloud_url':'https://panelgo-tablero.onrender.com'},message='ok')
        server=local_server(feed,uplink,game,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='https://panelgo-tablero.onrender.com'
        address=f'http://127.0.0.1:{server.server_port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            for method,path in [('GET','/api/state'),('GET','/board.png'),('OPTIONS','/api/state')]:
                request=urllib.request.Request(address+path,method=method,headers={'Origin':origin,'Access-Control-Request-Private-Network':'true'})
                with opener.open(request,timeout=3) as response:
                    self.assertEqual(response.headers['Access-Control-Allow-Origin'],origin)
                    if method=='OPTIONS':self.assertEqual(response.headers['Access-Control-Allow-Private-Network'],'true')
            for method in ('GET','OPTIONS'):
                request=urllib.request.Request(address+'/api/state',method=method,headers={'Origin':'https://unrelated.example'})
                with self.assertRaises(urllib.error.HTTPError) as error:opener.open(request,timeout=3)
                self.assertEqual(error.exception.code,403)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

if __name__=='__main__':unittest.main()
