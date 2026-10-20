"""Local RTSP -> fragmented MP4 over WebSocket, with a private go2rtc relay.

Camera credentials never leave the backend or enter a browser URL.
"""
import atexit
import base64
import ctypes
import json
import os
import secrets
import select
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path


def validate_rtsp(value):
    if not isinstance(value,str) or any(c in value for c in '\r\n\x00'):
        raise ValueError('La fuente de video debe ser una direccion RTSP.')
    parsed=urllib.parse.urlsplit(value)
    if parsed.scheme not in ('rtsp','rtsps') or not parsed.hostname:
        raise ValueError('La fuente del juego en OBS debe usar RTSP, o configurar game_rtsp.')
    return value


class WindowsJob:
    """The relay is killed by Windows even if the Python parent is force-closed."""
    def __init__(self,process):
        self.handle=None
        if os.name!='nt':return
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_=[('processTime',ctypes.c_longlong),('jobTime',ctypes.c_longlong),('flags',w.DWORD),
                      ('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),('active',w.DWORD),
                      ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(n,ctypes.c_ulonglong) for n in ('readOps','writeOps','otherOps','readBytes','writeBytes','otherBytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('processMemory',ctypes.c_size_t),('jobMemory',ctypes.c_size_t),
                      ('peakProcess',ctypes.c_size_t),('peakJob',ctypes.c_size_t)]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];kernel.CreateJobObjectW.restype=w.HANDLE
        kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD];kernel.SetInformationJobObject.restype=w.BOOL
        kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];kernel.AssignProcessToJobObject.restype=w.BOOL
        kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
        handle=kernel.CreateJobObjectW(None,None)
        info=Extended();info.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle,int(process._handle)):
            error=ctypes.get_last_error();kernel.CloseHandle(handle);raise ctypes.WinError(error)
        self.kernel=kernel;self.handle=handle

    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


class ContinuousVideo:
    def __init__(self,args,obs_factory,root):
        self.args=args;self.obs_factory=obs_factory;self.root=Path(root).resolve()
        self.port=int(getattr(args,'video_port',1987));self.source=getattr(args,'game_source','camara 01')
        self.lock=threading.RLock();self.stopped=threading.Event();self.process=None;self.job=None
        self.ready=False;self.connected=False;self.message='Preparando video continuo'
        self.bytes_received=0;self.last_activity=0.;self.auth='';self.config_path=None
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        atexit.register(self.close)

    def snapshot(self):
        with self.lock:
            fresh=self.connected and time.monotonic()-self.last_activity<5
            return {'gameMode':'continuous','gameReady':self.ready,'gameConnected':fresh,
                    'gameWebsocket':'/video/ws','gameStatus':self.message,'gameImage':'',
                    'gameRevision':0,'gameAge':None}

    def discover_source(self):
        explicit=getattr(self.args,'game_rtsp','')
        if explicit:return validate_rtsp(explicit)
        obs=self.obs_factory(self.args.host,self.args.obs_port,os.environ.get('OBS_PASSWORD',''))
        try:
            result=obs.request('GetInputSettings',{'inputName':self.source})
            settings=result.get('inputSettings',{})
            return validate_rtsp(settings.get('input',''))
        finally:obs.close()

    def _get(self,route):
        request=urllib.request.Request(f'http://127.0.0.1:{self.port}'+route,headers={'Authorization':self.auth})
        with self.opener.open(request,timeout=2) as response:return json.load(response)

    def start(self):
        configured=getattr(self.args,'video_binary','')
        binary=Path(configured) if configured else self.root/'tools'/('go2rtc.exe' if os.name=='nt' else 'go2rtc')
        if not binary.is_file():
            found=shutil.which('go2rtc')
            if not found:raise FileNotFoundError('Falta go2rtc. Ejecutar INSTALAR-VIDEO.ps1.')
            binary=Path(found)
        if not 1024<=self.port<=65535:raise ValueError('Puerto de video invalido.')
        with socket.socket() as check:
            check.bind(('127.0.0.1',self.port))
        source=self.discover_source()
        password=secrets.token_urlsafe(32)
        self.auth='Basic '+base64.b64encode(('panelgo:'+password).encode()).decode()
        config={'api':{'listen':f'127.0.0.1:{self.port}','username':'panelgo','password':password,'local_auth':True,
                       'allow_paths':['/api','/api/ws','/api/streams']},
                'rtsp':{'listen':''},'webrtc':{'listen':''},'log':{'level':'error'},'streams':{'game':[source]}}
        runtime=self.root/'.runtime';runtime.mkdir(exist_ok=True)
        self.config_path=runtime/f'video-{self.port}.json'
        self.config_path.write_text(json.dumps(config),encoding='utf-8')
        kwargs={'cwd':str(self.root),'stdin':subprocess.DEVNULL,'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL}
        if os.name=='nt':kwargs['creationflags']=subprocess.CREATE_NO_WINDOW
        self.process=subprocess.Popen([str(binary.resolve()),'-config',str(self.config_path)],**kwargs)
        try:self.job=WindowsJob(self.process)
        except Exception:self._stop_process();raise RuntimeError('No se pudo asociar el video al lector.')
        for _ in range(30):
            if self.stopped.is_set():raise RuntimeError('Lector detenido')
            if self.process.poll() is not None:raise RuntimeError('El servicio de video no inicio.')
            try:
                self._get('/api')
                with self.lock:self.ready=True;self.message='Conectando con la camara del juego'
                return
            except Exception:self.stopped.wait(.1)
        raise RuntimeError('El servicio de video no responde.')

    def _stop_process(self):
        process=self.process;self.process=None
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        if self.job:self.job.close();self.job=None
        if self.config_path:
            try:self.config_path.unlink(missing_ok=True)
            except OSError:pass

    def close(self):
        self.stopped.set()
        with self.lock:self.ready=False;self.connected=False
        self._stop_process()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.start()
                while not self.stopped.is_set():
                    if self.process is None or self.process.poll() is not None:raise RuntimeError('El video se detuvo.')
                    state=self._get('/api/streams?src=game')
                    if 'game' in state:state=state['game']
                    total=sum(int(p.get('bytes_recv',0)) for p in (state.get('producers') or []))
                    with self.lock:
                        if total!=self.bytes_received:
                            self.bytes_received=total;self.last_activity=time.monotonic()
                        self.connected=bool(total and time.monotonic()-self.last_activity<5)
                        self.message='Video continuo activo' if self.connected else 'Esperando señal de la camara; verificar acceso desde esta PC'
                    self.stopped.wait(1)
            except FileNotFoundError:
                with self.lock:self.ready=False;self.connected=False;self.message='Falta instalar el componente de video continuo'
            except ValueError:
                with self.lock:self.ready=False;self.connected=False;self.message='La fuente del juego debe ser una camara RTSP'
            except OSError:
                with self.lock:self.ready=False;self.connected=False;self.message='No se pudo iniciar el video; revisar puerto y acceso a OBS'
            except Exception:
                with self.lock:self.ready=False;self.connected=False;self.message='Video sin conexion; reintentando'
            finally:self._stop_process()
            self.stopped.wait(3)

    def forward_websocket(self,handler):
        """Only proxy the fixed game stream. Never expose the relay administration API."""
        port=handler.server.server_address[1]
        origins={f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
        if handler.headers.get('Origin') not in origins or handler.headers.get('Upgrade','').lower()!='websocket':
            handler.send_error(403,'Origen de video no permitido');return
        key=handler.headers.get('Sec-WebSocket-Key','')
        try:
            if len(base64.b64decode(key,validate=True))!=16:raise ValueError()
        except Exception:handler.send_error(400,'WebSocket invalido');return
        with self.lock:ready=self.ready;auth=self.auth
        if not ready:handler.send_error(503,'Video iniciando');return
        upstream=None
        try:
            upstream=socket.create_connection(('127.0.0.1',self.port),timeout=4)
            request=(f'GET /api/ws?src=game HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                     f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nAuthorization: {auth}\r\n\r\n')
            upstream.sendall(request.encode('ascii'));header=bytearray()
            while b'\r\n\r\n' not in header:
                data=upstream.recv(4096)
                if not data or len(header)>65536:raise ConnectionError()
                header.extend(data)
            if b' 101 ' not in header.split(b'\r\n',1)[0]:raise ConnectionError()
            handler.close_connection=True;handler.connection.sendall(header)
            upstream.settimeout(5);handler.connection.settimeout(5)
            sockets=[upstream,handler.connection];active=time.monotonic()
            while not self.stopped.is_set():
                readable,_,_=select.select(sockets,[],[],2)
                if not readable and time.monotonic()-active>30:return
                for source in readable:
                    data=source.recv(65536)
                    if not data:return
                    (handler.connection if source is upstream else upstream).sendall(data)
                    active=time.monotonic()
        except OSError:pass
        finally:
            if upstream:upstream.close()
