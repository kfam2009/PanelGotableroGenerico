"""Local control of one dedicated OBS graphic, separate from the camera reader."""
import argparse
import json
import os
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
try:
    from core import OBS
except ImportError:
    from server import OBS

SOURCE='Panel Go - Marcador Estrella'
SETTINGS_PATH=Path(__file__).with_name('.graphic-settings.json')
SETTINGS_LOCK=threading.Lock()
SETTING_KEYS={'homeName','awayName','homeLogo','awayLogo','eventLogo','tournament','category'}

def read_graphic_settings(path=None):
    try:return json.loads((path or SETTINGS_PATH).read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}

def save_graphic_settings(values,path=None):
    if not isinstance(values,dict) or set(values)-SETTING_KEYS:raise ValueError('Ajustes no permitidos')
    clean={}
    for key,value in values.items():
        if not isinstance(value,str) or len(value)>(1500000 if key.endswith('Logo') else 120):raise ValueError('Valor invalido')
        if key.endswith('Logo') and value and not value.startswith(('assets/','http://','https://','data:image/')):raise ValueError('Imagen no permitida')
        clean[key]=value
    target=path or SETTINGS_PATH
    with SETTINGS_LOCK:
        merged={**read_graphic_settings(target),**clean}
        temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(merged,ensure_ascii=False),encoding='utf-8')
        temporary.replace(target)
    return merged
READ={'GetCurrentProgramScene','GetSceneItemList','GetInputList','GetVideoSettings','GetSceneItemEnabled','GetVirtualCamStatus'}
WRITE={'CreateInput','SetSceneItemTransform','SetSceneItemEnabled','StartVirtualCam'}

class GraphicsOBS(OBS):
    def request(self,kind,data=None):
        if kind not in READ|WRITE:raise ValueError('Operacion no permitida')
        if kind=='CreateInput' and ((data or {}).get('inputName')!=SOURCE or (data or {}).get('sceneItemEnabled') is not False):
            raise ValueError('Solo se crea el marcador desactivado')
        rid=str(time.monotonic_ns())
        self.send({'op':6,'d':{'requestType':kind,'requestId':rid,'requestData':data or {}}})
        while True:
            message=self.receive()
            if message.get('op')==7 and message['d'].get('requestId')==rid:
                response=message['d']
                if not response['requestStatus']['result']:raise RuntimeError('OBS rechazo la operacion del marcador')
                return response.get('responseData',{})

class GraphicControl:
    def __init__(self,host='127.0.0.1',port=4455,scene=''):
        self.host=host;self.port=port;self.scene=scene;self.lock=threading.Lock()
    def connect(self):return GraphicsOBS(self.host,self.port,os.environ.get('OBS_PASSWORD',''))
    def locate(self,obs):
        scene=self.scene or obs.request('GetCurrentProgramScene')['currentProgramSceneName']
        items=obs.request('GetSceneItemList',{'sceneName':scene})['sceneItems']
        return scene,next((item for item in items if item['sourceName']==SOURCE),None)
    def start_virtual_camera(self):
        with self.lock:
            obs=self.connect()
            try:
                if not obs.request('GetVirtualCamStatus')['outputActive']:obs.request('StartVirtualCam')
                return {'active':obs.request('GetVirtualCamStatus')['outputActive']}
            finally:obs.close()
    def status(self):
        with self.lock:
            obs=self.connect()
            try:
                scene,item=self.locate(obs)
                return {'ready':bool(item),'enabled':bool(item and item['sceneItemEnabled']),'scene':scene,'source':SOURCE,'safetyLocked':Path(__file__).with_name('.obs-safety-lock').exists()}
            finally:obs.close()
    def install(self,url):
        with self.lock:
            obs=self.connect()
            try:
                scene,item=self.locate(obs)
                if item:return {'ready':True,'enabled':item['sceneItemEnabled'],'scene':scene,'created':False}
                if any(x['inputName']==SOURCE for x in obs.request('GetInputList')['inputs']):
                    raise ValueError('El marcador ya existe en otra escena; revisar antes de agregarlo')
                video=obs.request('GetVideoSettings')
                result=obs.request('CreateInput',{'sceneName':scene,'inputName':SOURCE,'inputKind':'browser_source','inputSettings':{'url':url,'width':1920,'height':1080,'fps':30,'shutdown':False,'restart_when_active':False,'css':'body { margin: 0; background-color: rgba(0,0,0,0); overflow: hidden; }'},'sceneItemEnabled':False})
                item_id=result['sceneItemId']
                obs.request('SetSceneItemTransform',{'sceneName':scene,'sceneItemId':item_id,'sceneItemTransform':{'positionX':0,'positionY':0,'scaleX':video['baseWidth']/1920,'scaleY':video['baseHeight']/1080,'alignment':5}})
                enabled=obs.request('GetSceneItemEnabled',{'sceneName':scene,'sceneItemId':item_id})['sceneItemEnabled']
                return {'ready':True,'enabled':enabled,'scene':scene,'created':True}
            finally:obs.close()
    def set_enabled(self,enabled):
        if type(enabled) is not bool:raise ValueError('Se requiere un estado booleano explicito')
        if enabled and Path(__file__).with_name('.obs-safety-lock').exists():raise ValueError('Prueba pausada durante la transmision')
        with self.lock:
            obs=self.connect()
            try:
                scene,item=self.locate(obs)
                if not item:raise ValueError('Agregar primero el marcador a OBS')
                obs.request('SetSceneItemEnabled',{'sceneName':scene,'sceneItemId':item['sceneItemId'],'sceneItemEnabled':enabled})
                actual=obs.request('GetSceneItemEnabled',{'sceneName':scene,'sceneItemId':item['sceneItemId']})['sceneItemEnabled']
                return {'ready':True,'enabled':actual,'scene':scene,'source':SOURCE}
            finally:obs.close()

def make_control_server(control,port=8774,graphic_url='http://127.0.0.1:8771/graphics.html',cloud_origin=''):
    token=secrets.token_urlsafe(32)
    origins={'http://127.0.0.1:8771','http://localhost:8771'}
    if cloud_origin=='https://clubestrella-panel.onrender.com':origins.add(cloud_origin)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,data):
            raw=json.dumps(data).encode();self.send_response(status)
            origin=self.headers.get('Origin')
            if origin in origins:self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_OPTIONS(self):
            if self.headers.get('Origin') not in origins:self.reply(403,{'error':'Origen no permitido'});return
            self.send_response(204);self.send_header('Access-Control-Allow-Origin',self.headers['Origin']);self.send_header('Access-Control-Allow-Methods','GET, POST');self.send_header('Access-Control-Allow-Headers','Content-Type, X-Panel-Token');self.send_header('Access-Control-Allow-Private-Network','true');self.end_headers()
        def do_GET(self):
            if self.path not in ('/state','/settings'):self.reply(404,{});return
            if self.headers.get('Origin') and self.headers['Origin'] not in origins:self.reply(403,{});return
            if self.path=='/settings':self.reply(200,read_graphic_settings());return
            try:self.reply(200,{**control.status(),'token':token})
            except Exception:self.reply(503,{'ready':False,'enabled':False,'error':'Sin conexion con OBS'})
        def do_POST(self):
            if self.headers.get('Origin') not in origins or not secrets.compare_digest(self.headers.get('X-Panel-Token',''),token):self.reply(403,{'error':'Origen no permitido'});return
            if self.path not in ('/visibility','/install','/settings','/virtual-camera'):self.reply(404,{});return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=(3100000 if self.path=='/settings' else 512) or self.headers.get('Content-Type')!='application/json':raise ValueError()
                data=json.loads(self.rfile.read(length))
                if self.path=='/virtual-camera':self.reply(200,control.start_virtual_camera());return
                if self.path=='/settings':self.reply(200,{'ok':True,'settings':save_graphic_settings(data)});return
                result=control.install(graphic_url) if self.path=='/install' else control.set_enabled(data.get('enabled'))
                self.reply(200,result)
            except Exception:self.reply(400,{'error':'No se pudo cambiar el marcador en OBS'})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server

def make_bridge(address,port,peer,root,local_port=8771):
    """Only the OBS peer can read the graphic and score feed; no cameras or control."""
    root=Path(root).resolve()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def state():
        with opener.open(f'http://127.0.0.1:{local_port}/api/state',timeout=3) as response:data=json.load(response)
        return {**{k:v for k,v in data.items() if k in {'service','clock','homeScore','awayScore','period','fields','connected','ocrStatus','status','updatedAt','revision','boardOff'}},'graphicSettings':read_graphic_settings()}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.client_address[0] not in (peer,address):self.send_error(403);return
            route=self.path.split('?',1)[0]
            if route=='/api/events':
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-cache');self.end_headers()
                try:
                    while True:
                        self.wfile.write(('data: '+json.dumps(state())+'\n\n').encode());self.wfile.flush();time.sleep(1)
                except Exception:pass
                return
            try:
                if route=='/api/state':data=json.dumps(state()).encode();kind='application/json'
                elif route in ('/graphics.html','/styles.css','/script.js') or route.startswith('/assets/') and '..' not in route:
                    file=(root/route.lstrip('/')).resolve()
                    if not file.is_relative_to(root):raise ValueError()
                    data=file.read_bytes();kind={'.html':'text/html','.css':'text/css','.js':'text/javascript','.png':'image/png'}.get(file.suffix,'application/octet-stream')
                else:self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            except Exception:self.send_error(503)
    server=ThreadingHTTPServer((address,port),Handler);server.daemon_threads=True;return server

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--scene',default='');parser.add_argument('--bridge-address',default='');parser.add_argument('--root',default=str(Path(__file__).parent));parser.add_argument('--install',action='store_true');args=parser.parse_args()
    control=GraphicControl(args.host,scene=args.scene)
    url='http://127.0.0.1:8771/graphics.html'
    if args.bridge_address:
        bridge=make_bridge(args.bridge_address,8772,args.host,args.root)
        threading.Thread(target=bridge.serve_forever,daemon=True).start()
        url=f'http://{args.bridge_address}:8772/graphics.html'
    server=make_control_server(control,graphic_url=url)
    if args.install:print(json.dumps(control.install(url)),flush=True)
    print('Control del marcador en http://127.0.0.1:8774',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
