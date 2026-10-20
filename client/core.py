"""Panel Go: scoreboard reader and local graphics server.

The OBS allowlist below contains only queries. No scene, source or stream changes.
"""
import base64
import hashlib
import io
import importlib
import json
import logging
import os
import socket
import struct
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
import reader as reader_module

ROOT = Path(__file__).resolve().parent
KEYS = ('clock', 'homeScore', 'awayScore', 'period')
ALLOWLIST = {'GetSourceScreenshot', 'GetInputList', 'GetSceneList', 'GetInputSettings', 'GetCurrentProgramScene'}
READER_MTIME = Path(reader_module.__file__).stat().st_mtime_ns


def reload_reader_if_changed():
    global READER_MTIME
    current=Path(reader_module.__file__).stat().st_mtime_ns
    if current != READER_MTIME:
        importlib.invalidate_caches()
        importlib.reload(reader_module)
        READER_MTIME=current
        logging.info('Lector actualizado: %s',reader_module.READER_VERSION)


class OBS:
    def __init__(self, host, port, password=''):
        self.sock = socket.create_connection((host,port),timeout=6)
        self.sock.settimeout(12)
        self.buffer = bytearray()
        try:
            key=base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall((f'GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
            header=bytearray()
            while b'\r\n\r\n' not in header:
                chunk=self.sock.recv(4096)
                if not chunk: raise ConnectionError('OBS cerro el handshake')
                header.extend(chunk)
                if len(header)>65536: raise ConnectionError('Handshake demasiado grande')
            head,tail=bytes(header).split(b'\r\n\r\n',1)
            expected=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
            headers={k.strip().lower():v.strip() for k,v in (line.split(b':',1) for line in head.split(b'\r\n')[1:] if b':' in line)}
            if b' 101 ' not in head.split(b'\r\n',1)[0] or headers.get(b'sec-websocket-accept') != expected:
                raise ConnectionError('Respuesta WebSocket no valida')
            self.buffer.extend(tail)
            hello=self.receive()
            identify={'rpcVersion':1,'eventSubscriptions':0}
            auth=hello.get('d',{}).get('authentication')
            if auth:
                if not password: raise ConnectionError('OBS requiere OBS_PASSWORD')
                secret=base64.b64encode(hashlib.sha256((password+auth['salt']).encode()).digest()).decode()
                identify['authentication']=base64.b64encode(hashlib.sha256((secret+auth['challenge']).encode()).digest()).decode()
            self.send({'op':1,'d':identify})
            if self.receive().get('op') != 2: raise ConnectionError('OBS no identifico la sesion')
        except Exception:
            self.close()
            raise

    def exact(self,n):
        while len(self.buffer)<n:
            chunk=self.sock.recv(max(4096,n-len(self.buffer)))
            if not chunk: raise ConnectionError('OBS desconectado')
            self.buffer.extend(chunk)
        result=bytes(self.buffer[:n]);del self.buffer[:n]
        return result

    def frame(self,data,opcode=1):
        key=os.urandom(4);n=len(data);header=bytearray([0x80|opcode])
        if n<126: header.append(0x80|n)
        elif n<65536: header.extend(bytes([0x80|126])+struct.pack('!H',n))
        else: header.extend(bytes([0x80|127])+struct.pack('!Q',n))
        header.extend(key)
        self.sock.sendall(header+bytes(v^key[i%4] for i,v in enumerate(data)))

    def send(self,obj): self.frame(json.dumps(obj,separators=(',',':')).encode())

    def receive(self):
        message=bytearray()
        while True:
            first,second=self.exact(2);opcode=first&15;n=second&127
            if n==126:n=struct.unpack('!H',self.exact(2))[0]
            elif n==127:n=struct.unpack('!Q',self.exact(8))[0]
            if n>32*1024*1024: raise ConnectionError('Imagen OBS demasiado grande')
            key=self.exact(4) if second&128 else None
            payload=self.exact(n)
            if key:payload=bytes(v^key[i%4] for i,v in enumerate(payload))
            if opcode==8: raise ConnectionError('OBS cerro la sesion')
            if opcode==9:self.frame(payload,10);continue
            if opcode==10:continue
            message.extend(payload)
            if first&0x80:return json.loads(message)

    def request(self,kind,data=None):
        if kind not in ALLOWLIST:raise ValueError('Operacion OBS no permitida')
        rid=str(time.monotonic_ns())
        self.send({'op':6,'d':{'requestType':kind,'requestId':rid,'requestData':data or {}}})
        while True:
            msg=self.receive()
            if msg.get('op')==7 and msg['d'].get('requestId')==rid:
                reply=msg['d']
                if not reply['requestStatus']['result']:raise RuntimeError(str(reply['requestStatus']))
                return reply.get('responseData',{})

    def capture(self,source):
        r=self.request('GetSourceScreenshot',{'sourceName':source,'imageFormat':'png','imageWidth':1920,'imageHeight':1080})
        return Image.open(io.BytesIO(base64.b64decode(r['imageData'].split(',',1)[1]))).convert('RGB')

    def close(self):self.sock.close()


def read_values(im):
    r=reader_module
    if r.CALIBRATED:return r.read_calibrated(im)
    results={k:r.recognize(im,k) for k in r.QUADS}
    digits={k:v[0] for k,v in results.items()}
    dark={k for k,v in results.items() if v[0] is None and not v[1]}
    values={}
    for key,names in r.GROUPS.items():
        if key in ('homeScore','awayScore'):
            # Scores may leave leading digits unlit (e.g. " 7").
            lead=0
            while lead<len(names)-1 and names[lead] in dark:lead+=1
            names=names[lead:]
        if any(digits[n] is None for n in names):continue
        text=''.join(digits[n] for n in names)
        if key=='clock':
            if int(text[2:])>59 or int(text[:2])>20:continue
            text=text[:2]+':'+text[2:]
        if key=='period' and not 1<=int(text)<=9:continue
        if key in ('homeScore','awayScore'):text=str(int(text))
        values[key]=text
    # The board uses SS:T below one minute and leaves the fourth digit dark.
    # Only accept this layout when the fourth position has no illuminated LED;
    # an unreadable but lit digit must not be mistaken for decimal mode.
    if 'clock' not in values and all(digits.get(k) is not None for k in ('m1','m2','s1')) and 's2' in r.QUADS:
        fourth_pixels=int(r.mask(r.warp(im,r.QUADS['s2'])).sum())
        seconds=int(digits['m1']+digits['m2'])
        if fourth_pixels<50 and seconds<60:
            values['clock']=f"{seconds:02d}.{digits['s1']}"
    return values,digits


def clock_seconds(value):
    if ':' in value:
        minutes,seconds=value.split(':')
        return int(minutes)*60+int(seconds)
    return float(value)


class GamePreview:
    """Independent low-bandwidth monitor; never delays the scoreboard reader."""
    def __init__(self,args):
        self.args=args;self.lock=threading.Lock();self.image=b'';self.updated=0.;self.revision=0;self.connected=False

    def snapshot(self):
        with self.lock:
            age=time.time()-self.updated if self.updated else None
            return {'gameImage':'game.jpg','gameConnected':self.connected and age is not None and age<4,
                    'gameRevision':self.revision,'gameAge':round(age,1) if age is not None else None}

    def run(self):
        obs=None
        while True:
            try:
                if obs is None:obs=OBS(self.args.host,self.args.obs_port,os.environ.get('OBS_PASSWORD',''))
                reply=obs.request('GetSourceScreenshot',{'sourceName':getattr(self.args,'game_source','camara 01'),'imageFormat':'jpg','imageWidth':960,'imageHeight':540})
                data=base64.b64decode(reply['imageData'].split(',',1)[1])
                with self.lock:
                    self.image=data;self.updated=time.time();self.revision+=1;self.connected=True
                time.sleep(.75)
            except Exception:
                if obs:
                    try:obs.close()
                    except OSError:pass
                obs=None
                with self.lock:self.connected=False
                time.sleep(2)


class Feed:
    def __init__(self,args):
        self.args=args;self.lock=threading.Condition();self.revision=0
        self.values={'clock':'--:--','homeScore':'--','awayScore':'--','period':'--'}
        self.confirmed={};self.pending={};self.connected=False;self.captured=0.;self.board=b'';self.error='Esperando el tablero'
        self.last_samples={};self.digits={};self.frame=None
        self.board_off=False;self.dark_since=None
        self.gate=None;self.locked=False

    def held(self):
        """True while the license gate blocks reading; the graphic then shows no score."""
        reason=self.gate() if self.gate else None
        if reason is None:
            if self.locked:
                with self.lock:self.locked=False;self.error='Esperando el tablero';self.revision+=1;self.lock.notify_all()
            return False
        with self.lock:
            if not self.locked or self.error!=reason:
                self.locked=True;self.connected=False;self.error=reason
                self.values={k:'--:--' if k=='clock' else '--' for k in KEYS}
                self.confirmed.clear();self.pending.clear();self.last_samples.clear();self.board_off=False;self.dark_since=None
                self.revision+=1;self.lock.notify_all()
        return True

    def snapshot(self):
        now=time.time()
        with self.lock:
            fields={k:{'age':round(now-self.confirmed[k],1) if k in self.confirmed else None,
                       'valid':k in self.confirmed and now-self.confirmed[k]<4} for k in KEYS}
            fresh=self.connected and now-self.captured<4
            good=fresh and all(v['valid'] for v in fields.values())
            return {**self.values,'service':'panelgo-tablero','version':reader_module.READER_VERSION,'pid':os.getpid(),'connected':fresh,'ocrStatus':'standby' if fresh and self.board_off else 'ok' if good else 'waiting','boardOff':fresh and self.board_off,
                    'status':'Tablero apagado · listo para iniciar' if fresh and self.board_off else 'Lectura automatica activa' if good else ('Verificando lectura del tablero' if fresh else self.error),
                    'fields':fields,'updatedAt':datetime.fromtimestamp(self.captured,timezone.utc).isoformat() if self.captured else None,
                    'boardImage':'board.png','source':self.args.source,'revision':self.revision,'digits':self.digits}

    def process(self,im,now=None):
        now=now or time.time();raw,digits=read_values(im)
        power=reader_module.board_power_state(im,digits)
        crop=getattr(self.args,'board_crop',None) or (reader_module.VIEW if reader_module.CALIBRATED else None)
        view=im.crop(tuple(crop)) if crop else im.resize((640,360))
        self.frame=im
        out=io.BytesIO();view.save(out,format='PNG')
        with self.lock:
            self.board=out.getvalue();self.connected=True;self.captured=now;self.digits=digits
            self.error='Sin capturas recientes del tablero'
            if power=='off':
                if self.dark_since is None:self.dark_since=now
                if now-self.dark_since>=2:
                    self.board_off=True
                    self.values.update(clock='10:00',homeScore='0',awayScore='0')
                    self.pending.clear();self.last_samples.clear()
                    for key in ('clock','homeScore','awayScore'):self.confirmed[key]=now
                    self.revision+=1;self.lock.notify_all();return
            else:
                self.dark_since=None
                if self.board_off:
                    self.board_off=False;self.confirmed.clear();self.pending.clear();self.last_samples.clear()
            for key in KEYS:
                value=raw.get(key)
                if value is None:
                    self.pending.pop(key,None);continue
                prior,count=self.pending.get(key,(None,0))
                count=count+1 if value==prior else 1
                if key=='clock' and prior is not None:
                    elapsed=now-self.last_samples.get(key,now)
                    delta=clock_seconds(prior)-clock_seconds(value)
                    # A running clock need not repeat the same second on two screenshots.
                    if 0<=delta<=max(2,elapsed*1.7+1) and elapsed<10:count=2
                self.last_samples[key]=now
                self.pending[key]=(value,count)
                # Previously confirmed values can refresh immediately. Changes require two frames.
                if (value==self.values[key] and key in self.confirmed) or count>=2:
                    self.values[key]=value;self.confirmed[key]=now
            self.revision+=1;self.lock.notify_all()

    def run(self):
        stream=getattr(self.args,'board_stream',None)
        if stream:return self.run_stream(stream)
        obs=None
        while True:
            try:
                if self.held():time.sleep(1);continue
                cycle_started=time.monotonic()
                reload_reader_if_changed()
                if obs is None:obs=OBS(self.args.host,self.args.obs_port,os.environ.get('OBS_PASSWORD',''))
                self.process(obs.capture(self.args.source))
                time.sleep(max(0,self.args.interval-(time.monotonic()-cycle_started)))
            except Exception as exc:
                logging.warning('OBS: %s',exc)
                if obs:
                    try:obs.close()
                    except OSError:pass
                obs=None
                with self.lock:
                    self.connected=False;self.dark_since=None;self.pending.clear();self.error='Sin conexion con OBS; reintentando'
                    self.revision+=1;self.lock.notify_all()
                time.sleep(2)

    def run_stream(self,stream):
        """Board read from an SRT/RTSP stream (vMix output or IP camera)."""
        stream.start();seen=0
        while True:
            try:
                if self.held():time.sleep(1);continue
                cycle_started=time.monotonic()
                reload_reader_if_changed()
                frame,seen=stream.latest(timeout=3,newer_than=seen)
                self.process(frame)
                time.sleep(max(0,self.args.interval-(time.monotonic()-cycle_started)))
            except Exception as exc:
                logging.warning('Video del tablero: %s',exc)
                with self.lock:
                    self.connected=False;self.dark_since=None;self.pending.clear();self.error='Sin video del tablero; reintentando'
                    self.revision+=1;self.lock.notify_all()
                time.sleep(1)
