"""vMix control of one dedicated Web Browser input, through the vMix Web API (port 8088).

Only that input is created, renamed, navigated and put on/off one overlay channel.
Never changes Program, Preview, recording or streaming.
"""
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE='Panel Go - Marcador'
FUNCTIONS={'AddInput','SetInputName','BrowserNavigate'}
OVERLAY_FUNCTIONS={'In','Out'}


class VmixAPI:
    def __init__(self,host='127.0.0.1',port=8088,timeout=4):
        self.base=f'http://{host}:{int(port)}/api/'
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.timeout=timeout

    def state(self):
        with self.opener.open(self.base,timeout=self.timeout) as response:
            return ET.fromstring(response.read())

    def call(self,function,**params):
        allowed=function in FUNCTIONS or (function.startswith('OverlayInput') and function[12:13].isdigit() and function[13:] in OVERLAY_FUNCTIONS)
        if not allowed:raise ValueError('Operacion vMix no permitida')
        query=urllib.parse.urlencode({'Function':function,**params})
        with self.opener.open(self.base+'?'+query,timeout=self.timeout) as response:
            response.read(4096)
            if response.status!=200:raise RuntimeError('vMix rechazo la operacion')


def find_input(root):
    for item in root.iter('input'):
        if item.get('title')==SOURCE:return item
    return None


def overlay_input(root,channel):
    for item in root.iter('overlay'):
        if item.get('number')==str(channel):return (item.text or '').strip()
    return ''


class VmixGraphicControl:
    name='vMix'
    def __init__(self,host='127.0.0.1',port=8088,overlay=1,api=None):
        if not 1<=int(overlay)<=4:raise ValueError('Overlay de vMix invalido (1 a 4)')
        self.api=api or VmixAPI(host,port);self.overlay=int(overlay);self.lock=threading.Lock();self.sleep=time.sleep

    def locked(self):return Path(__file__).with_name('.obs-safety-lock').exists()

    def status(self):
        with self.lock:
            root=self.api.state();item=find_input(root)
            enabled=bool(item is not None and overlay_input(root,self.overlay)==item.get('number'))
            return {'ready':item is not None,'enabled':enabled,'scene':f'Overlay {self.overlay}','source':SOURCE,
                    'safetyLocked':self.locked(),'switcher':self.name}

    def install(self,url):
        with self.lock:
            root=self.api.state();item=find_input(root)
            if item is not None:return {'ready':True,'enabled':overlay_input(root,self.overlay)==item.get('number'),'scene':f'Overlay {self.overlay}','created':False}
            before={i.get('key') for i in root.iter('input')}
            self.api.call('AddInput',Value='Browser|'+url)
            for _ in range(20):
                self.sleep(.25)
                new=[i for i in self.api.state().iter('input') if i.get('key') not in before]
                if new:break
            else:raise RuntimeError('vMix no agrego la entrada del marcador')
            self.api.call('SetInputName',Input=new[0].get('key'),Value=SOURCE)
            return {'ready':True,'enabled':False,'scene':f'Overlay {self.overlay}','created':True}

    def set_enabled(self,enabled,url=''):
        if type(enabled) is not bool:raise ValueError('Se requiere un estado booleano explicito')
        if enabled and self.locked():raise ValueError('Prueba pausada durante la transmision')
        with self.lock:
            root=self.api.state();item=find_input(root)
            if item is None:raise ValueError('Agregar primero el marcador a vMix')
            key=item.get('key');showing=overlay_input(root,self.overlay)==item.get('number')
            if enabled and not showing:
                # The panel that shows the graphic also becomes its data source.
                if url:self.api.call('BrowserNavigate',Input=key,Value=url);self.sleep(1.5)
                self.api.call(f'OverlayInput{self.overlay}In',Input=key)
            elif not enabled and showing:
                self.api.call(f'OverlayInput{self.overlay}Out',Input=key)
            for _ in range(8):
                root=self.api.state()
                actual=overlay_input(root,self.overlay)==item.get('number')
                if actual==enabled:break
                self.sleep(.25)
            return {'ready':True,'enabled':actual,'scene':f'Overlay {self.overlay}','source':SOURCE}

    def start_virtual_camera(self):raise ValueError('La vista fluida solo esta disponible con OBS en esta PC')
