"""Frames from an SRT or RTSP stream through ffmpeg (vMix outputs, IP cameras).

ffmpeg decodes only a few frames per second; the reader always gets the latest one.
"""
import io
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

from PIL import Image

ROOT=Path(__file__).resolve().parent


def validate_stream(value):
    if not isinstance(value,str) or any(c in value for c in '\r\n\x00 '):
        raise ValueError('La fuente de video debe ser una direccion srt:// o rtsp://')
    parsed=urllib.parse.urlsplit(value)
    if parsed.scheme not in ('srt','rtsp','rtsps') or not parsed.hostname or not parsed.port and parsed.scheme=='srt':
        raise ValueError('La fuente de video debe ser srt://IP:PUERTO o rtsp://...')
    return value


IMAGE_TYPES={'.jpg','.jpeg','.png','.bmp','.webp'}
VIDEO_TYPES={'.mp4','.mov','.mkv','.avi','.ts','.m4v','.webm','.mxf','.wmv'}


def media_file(value):
    """A local photo or video used to test the reader (looped)."""
    if not isinstance(value,str) or '://' in value:return None
    path=Path(value.strip().strip('"'))
    if path.suffix.lower() in IMAGE_TYPES|VIDEO_TYPES and path.is_file():return str(path.resolve())
    return None


def srt_url(value,latency_ms=400):
    """Accepts IP:PORT or a full srt:// URL and adds caller mode and latency."""
    value=value.strip()
    local=media_file(value)
    if local:return local
    if '://' not in value:value='srt://'+value
    parsed=urllib.parse.urlsplit(value)
    if parsed.scheme!='srt':return validate_stream(value)
    query=dict(urllib.parse.parse_qsl(parsed.query))
    query.setdefault('mode','caller')
    query.setdefault('latency',str(int(latency_ms)*1000))  # ffmpeg uses microseconds
    return validate_stream(parsed._replace(query=urllib.parse.urlencode(query)).geturl())


def find_ffmpeg(configured=''):
    candidates=[configured] if configured else []
    exe='ffmpeg.exe' if os.name=='nt' else 'ffmpeg'
    candidates.append(str(ROOT/'tools'/exe))
    found=shutil.which('ffmpeg')
    if found:candidates.append(found)
    if os.name=='nt':
        local=os.environ.get('LOCALAPPDATA','')
        if local:candidates.append(os.path.join(local,'Microsoft','WinGet','Links','ffmpeg.exe'))
        candidates+=[r'C:\ffmpeg\bin\ffmpeg.exe',r'C:\Program Files\ffmpeg\bin\ffmpeg.exe']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():return str(Path(candidate))
    raise FileNotFoundError('Falta ffmpeg. Ejecutar INSTALAR.cmd o instalar ffmpeg con: winget install Gyan.FFmpeg')


class StreamFrames:
    """Keeps the latest decoded frame of one stream; reconnects on its own."""
    def __init__(self,url,width=1920,height=1080,fps=5,ffmpeg=''):
        self.url=url;self.width=width;self.height=height;self.fps=fps;self.ffmpeg=ffmpeg
        self.lock=threading.Condition();self.frame=None;self.updated=0.;self.count=0
        self.stopped=threading.Event();self.process=None;self.message='Conectando video'
        self.thread=None

    def command(self,binary):
        options=['-hide_banner','-loglevel','error','-nostdin','-probesize','1000000','-analyzeduration','1000000','-fflags','nobuffer','-flags','low_delay']
        source=Path(self.url)
        if source.suffix.lower() in IMAGE_TYPES and source.is_file():options+=['-loop','1','-framerate',str(self.fps)]
        elif source.suffix.lower() in VIDEO_TYPES and source.is_file():options+=['-re','-stream_loop','-1']
        elif self.url.startswith('rtsp'):options+=['-rtsp_transport','tcp']
        options+=['-i',self.url,'-an','-sn','-vf',f'fps={self.fps},scale={self.width}:{self.height}',
                  '-pix_fmt','rgb24','-f','rawvideo','pipe:1']
        return [binary]+options

    def start(self):
        if not self.thread:
            self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
        return self

    def run(self):
        size=self.width*self.height*3
        while not self.stopped.is_set():
            try:
                binary=find_ffmpeg(self.ffmpeg)
                kwargs={'stdin':subprocess.DEVNULL,'stdout':subprocess.PIPE,'stderr':subprocess.PIPE}
                if os.name=='nt':kwargs['creationflags']=subprocess.CREATE_NO_WINDOW
                self.process=subprocess.Popen(self.command(binary),**kwargs)
                with self.lock:self.message='Esperando video'
                while not self.stopped.is_set():
                    data=self.process.stdout.read(size)
                    if len(data)<size:break
                    image=Image.frombuffer('RGB',(self.width,self.height),data,'raw','RGB',0,1)
                    with self.lock:
                        self.frame=image;self.updated=time.time();self.count+=1;self.message='Video activo'
                        self.lock.notify_all()
                error=b''
                try:error=self.process.stderr.read(400) if self.process.poll() is not None else b''
                except Exception:pass
                with self.lock:self.message='Sin video; reintentando'+(': '+error.decode('utf-8','replace').strip().splitlines()[-1] if error.strip() else '')
            except FileNotFoundError as exc:
                with self.lock:self.message=str(exc)
            except Exception as exc:
                with self.lock:self.message=f'Error de video: {exc}'
            finally:self.stop_process()
            self.stopped.wait(2)

    def latest(self,timeout=3,newer_than=0):
        with self.lock:
            self.lock.wait_for(lambda:self.count>newer_than or self.stopped.is_set(),timeout=timeout)
            if self.frame is None or time.time()-self.updated>4:raise ConnectionError(self.message)
            return self.frame,self.count

    def stop_process(self):
        process=self.process;self.process=None
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill()

    def close(self):
        self.stopped.set()
        with self.lock:self.lock.notify_all()
        self.stop_process()


class StreamPreview:
    """Monitor snapshots (960x540 JPEG) from a stream, same contract as ProgramPreview."""
    def __init__(self,url,label,ffmpeg=''):
        self.frames=StreamFrames(url,960,540,fps=1,ffmpeg=ffmpeg);self.label=label
        self.lock=threading.Lock();self.image=b'';self.updated=0.;self.revision=0;self.stopped=threading.Event()
    def snapshot(self):
        with self.lock:
            age=time.time()-self.updated if self.updated else None
            return {'gameMode':'snapshots','gameView':'program','gameLabel':self.label,'gameImage':'game.jpg',
                    'gameConnected':bool(age is not None and age<5),'gameRevision':self.revision,
                    'gameAge':round(age,1) if age is not None else None,'gameStatus':self.frames.message}
    def run(self):
        self.frames.start();seen=0
        while not self.stopped.is_set():
            try:
                frame,seen=self.frames.latest(timeout=3,newer_than=seen)
                out=io.BytesIO();frame.save(out,format='JPEG',quality=75)
                with self.lock:self.image=out.getvalue();self.updated=time.time();self.revision+=1
            except Exception:self.stopped.wait(1)
    def close(self):self.stopped.set();self.frames.close()


class NoPreview:
    def __init__(self,message):self.message=message;self.lock=threading.Lock();self.image=b''
    def snapshot(self):
        return {'gameMode':'snapshots','gameView':'program','gameLabel':'Programa','gameImage':'game.jpg',
                'gameConnected':False,'gameRevision':0,'gameAge':None,'gameStatus':self.message}
    def run(self):pass
    def close(self):pass
