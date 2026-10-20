"""Runs on the client's PC. OBS is local or reached over ZeroTier; only score data goes to Render."""
import argparse
import base64
import hmac
import html
import io
import ipaddress
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from core import Feed, OBS
import core
from continuous_video import ContinuousVideo
from obs_control import GraphicControl,make_bridge,make_control_server
from stream_source import NoPreview,StreamFrames,StreamPreview,srt_url
from vmix_control import VmixGraphicControl
from program_preview import ProgramPreview
from license import DEFAULT_LICENSE_URL,License,expiry_label

ROOT = Path(__file__).resolve().parent
# Shown over the local panel until the match code is validated.
LICENSE_UI = (ROOT/'license_ui.html').read_text(encoding='utf-8')
REMOTE_PORT = 8773
# Page for the technician who connects over ZeroTier: code entry, live reading and calibration only.
REMOTE_PAGE = '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Panel Go · Acceso remoto</title>
<style>body{margin:0;background:#15161a;color:#f2f3f5;font:16px system-ui,"Segoe UI",Arial,sans-serif}main{max-width:760px;margin:0 auto;padding:24px 16px}header{display:flex;gap:14px;align-items:center}header img{height:52px;border-radius:10px}h1{font-size:20px;margin:0}small{color:#a3a7b0}#status{margin:18px 0 10px;color:#a3a7b0}.vals{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.vals div{background:#202227;border:1px solid #33363e;border-radius:12px;padding:12px;font-size:13px;color:#a3a7b0}.vals strong{display:block;color:#fff;font-size:30px;margin-top:6px}.stale{opacity:.45}img#board{width:100%;max-height:320px;object-fit:contain;background:#050505;border-radius:12px;margin:16px 0}a.btn{display:block;text-align:center;padding:14px;border-radius:12px;background:#d6221e;color:#fff;font-weight:700;text-decoration:none}@media(max-width:520px){.vals{grid-template-columns:1fr 1fr}}</style></head>
<body><main><header><img src="/assets/panelgo-logo.png" alt="Panel Go"><div><h1>Acceso remoto · CLUB_PC</h1><small>Código del partido y calibración por ZeroTier</small></div></header>
<p id="status">Conectando...</p><div class="vals"><div>Reloj<strong id="clock">--:--</strong></div><div>Local<strong id="homeScore">--</strong></div><div>Visita<strong id="awayScore">--</strong></div><div>Período<strong id="period">--</strong></div></div>
<img id="board" alt="Última captura del tablero"><a class="btn" href="/calibrar">Calibrar tablero</a></main>
<script>let revision=-1;async function poll(){try{const r=await fetch('/api/state',{cache:'no-store'});const s=await r.json();for(const k of ['clock','homeScore','awayScore','period']){const e=document.getElementById(k);e.textContent=s[k];e.classList.toggle('stale',!s.fields[k].valid);}document.getElementById('status').textContent=s.status;if(s.revision!==revision){revision=s.revision;document.getElementById('board').src='/board.png?r='+revision;}}catch{document.getElementById('status').textContent='Sin conexión con el panel del club';}finally{setTimeout(poll,1000)}}poll();</script></body></html>'''
REMOTE_ROUTES = {'/','/calibrar','/api/state','/api/license','/api/calibration','/frame.jpg','/board.png','/styles.css'}


def load_config(path,local_only=False):
    config=json.loads(Path(path).read_text(encoding='utf-8-sig')) if Path(path).exists() else {}
    cloud=config.get('cloud_url','').strip().rstrip('/')
    url=urllib.parse.urlsplit(cloud)
    local=url.hostname in ('localhost','127.0.0.1')
    if not local_only and (not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/')):
        raise ValueError('Usar la URL base del panel, sin ruta, usuario ni clave.')
    if not local_only and url.scheme!='https' and not (local and url.scheme=='http'):
        raise ValueError('La URL de Render debe usar https://')
    token=config.get('ingest_token','')
    if not local_only and (not isinstance(token,str) or len(token)<32 or 'REPLACE_' in token):
        raise ValueError('Configurar la clave INGEST_TOKEN del servicio de Render.')
    switcher=str(config.get('switcher','obs')).strip().lower()
    if switcher not in ('obs','vmix'):raise ValueError('switcher debe ser "obs" o "vmix".')
    name='vMix' if switcher=='vmix' else 'OBS'
    host=str(config.get('production_host') or config.get('obs_host') or '127.0.0.1').strip()
    bridge=str(config.get('bridge_address','')).strip()
    if host=='localhost':host='127.0.0.1'
    try:production_ip=ipaddress.ip_address(host)
    except ValueError:raise ValueError(f'La IP de la PC con {name} no es valida.')
    remote=not production_ip.is_loopback and str(production_ip)!=bridge
    if remote:
        # Different IPs: the production PC is reached over ZeroTier.
        if not production_ip.is_private:raise ValueError(f'La IP de {name} debe ser una IP privada de ZeroTier, no una IP publica.')
        try:bridge_ip=ipaddress.ip_address(bridge)
        except ValueError:raise ValueError('Cargar bridge_address con la IP de ZeroTier de esta PC.')
        if bridge_ip.is_loopback or not bridge_ip.is_private:raise ValueError('bridge_address debe ser la IP de ZeroTier de esta PC.')
    else:
        # Same IP: the panel runs on the production PC.
        host='127.0.0.1';bridge=''
    port=int(config.get('obs_port',4455));vmix_port=int(config.get('vmix_port',8088))
    if not 1<=port<=65535 or not 1<=vmix_port<=65535:raise ValueError('Puerto invalido')
    board_mode=str(config.get('board_mode','stream' if switcher=='vmix' else 'obs')).strip().lower()
    if board_mode not in ('obs','stream'):raise ValueError('board_mode debe ser "obs" o "stream".')
    if switcher=='vmix' and board_mode=='obs':raise ValueError('Con vMix el tablero se lee por SRT o RTSP (board_mode "stream").')
    board_url=game_url=''
    # SRT buffer: short on this PC or the local network, longer over ZeroTier between sites.
    latency=int(config.get('srt_latency_ms') or (400 if remote else 120))
    if board_mode=='stream':
        if not config.get('board_url'):raise ValueError('Falta board_url: la salida SRT de vMix (IP:puerto) o la camara RTSP del tablero.')
        board_url=srt_url(str(config['board_url']),latency)
    if config.get('game_url'):game_url=srt_url(str(config['game_url']),latency)
    license_url=str(config.get('license_url') or DEFAULT_LICENSE_URL).strip().rstrip('/')
    parts=urllib.parse.urlsplit(license_url)
    if parts.scheme!='https' and parts.hostname not in ('localhost','127.0.0.1'):raise ValueError('license_url debe usar https://')
    remote_ip=str(config.get('remote_admin_ip') or '').strip();remote_password=str(config.get('remote_password') or '')
    zerotier=str(config.get('bridge_address','')).strip()
    if remote_ip:
        try:
            if not ipaddress.ip_address(remote_ip).is_private or not ipaddress.ip_address(zerotier).is_private:raise ValueError
        except ValueError:raise ValueError('Calibracion remota: remote_admin_ip y bridge_address tienen que ser IP de ZeroTier.')
        if len(remote_password)<8:raise ValueError('Calibracion remota: remote_password tiene que tener al menos 8 caracteres.')
    remote={'listen':zerotier,'allow':remote_ip,'password':remote_password} if remote_ip else None
    return {**config,'remote':remote,'license_url':license_url,'cloud_url':'' if local_only else cloud,'ingest_token':token,'obs_port':port,'obs_host':host,'production_host':host,
            'bridge_address':bridge,'switcher':switcher,'switcher_name':name,'vmix_port':vmix_port,'vmix_overlay':int(config.get('vmix_overlay',1)),
            'board_mode':board_mode,'board_url':board_url,'game_url':game_url}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Uplink:
    def __init__(self,feed,config):
        self.feed=feed;self.config=config;self.message='Esperando envio a Render';self.last_ok=None
        self.opener=urllib.request.build_opener(NoRedirect())

    def run(self):
        last_signature=None;last_sent=0
        while True:
            state=self.feed.snapshot()
            signature=tuple(state.get(k) for k in ('clock','homeScore','awayScore','period','connected','boardOff'))+tuple(state['fields'][k]['valid'] for k in ('clock','homeScore','awayScore','period'))
            if signature==last_signature and time.monotonic()-last_sent<1:
                with self.feed.lock:self.feed.lock.wait_for(lambda:self.feed.revision!=state['revision'],timeout=.2)
                continue
            # Keep frames, source details, PID and credentials on the client PC.
            payload={k:state[k] for k in ('clock','homeScore','awayScore','period','fields','connected','updatedAt','boardOff')}
            request=urllib.request.Request(self.config['cloud_url']+'/api/ingest',data=json.dumps(payload).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+self.config['ingest_token']},method='POST')
            try:
                with self.opener.open(request,timeout=3) as response:
                    if response.status!=200:raise RuntimeError('Respuesta inesperada de Render')
                    response.read(2048)
                self.last_ok=time.time();self.message='Datos enviados a Render'
                last_signature=signature;last_sent=time.monotonic()
            except urllib.error.HTTPError as exc:
                self.message='Clave rechazada por Render' if exc.code==401 else f'Render respondio HTTP {exc.code}'
            except Exception:
                self.message='No se pudo enviar a Render; reintentando'
            if self.message!='Datos enviados a Render':time.sleep(1)


def local_server(feed,uplink,game,port,license=None,bind='127.0.0.1',remote=None):
    page='''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Panel Go - Lector local</title><style>body{margin:32px auto;max-width:850px;padding:0 20px;background:#101620;color:#eef2f8;font:16px Arial}h1{color:#ffd348}section{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}section div{padding:20px 10px;background:#1d2939;border-radius:10px}strong{display:block;margin-top:12px;font-size:34px}img{width:100%;max-height:300px;object-fit:contain;background:#080b10;margin:20px 0}a{color:#76e4b2}.stale{opacity:.45}@media(max-width:500px){section{grid-template-columns:1fr 1fr}}</style>
<h1>Panel Go · lector local</h1><p id="status">Conectando con OBS local...</p><p id="cloud"></p>
<section><div>Reloj<strong id="clock">--:--</strong></div><div>Local<strong id="homeScore">--</strong></div><div>Visita<strong id="awayScore">--</strong></div><div>Período<strong id="period">--</strong></div></section>
<style>.monitors{display:grid;grid-template-columns:1fr 1.7fr;gap:15px;margin-top:24px}.monitors figure{margin:0;min-width:0}.monitors img{height:240px;object-fit:contain;margin:8px 0;background:#050505}figcaption{font-weight:bold}#gameStatus{font-size:12px;font-weight:normal}club-game{display:block;height:240px;background:#050505;margin:8px 0}club-game video{object-fit:contain}@media(max-width:520px){.monitors{grid-template-columns:1fr}}</style>
<div class="monitors"><figure><figcaption>Tablero</figcaption><img id="board" alt="Última captura del tablero"></figure><figure><figcaption>Juego <span id="gameStatus">Conectando video continuo</span></figcaption><club-game data-enabled="true" aria-label="Video continuo del juego"></club-game></figure></div>
<p id="videoBackend"></p><p><a href="CLOUD_URL" target="_blank" rel="noopener">Abrir panel en Render</a></p><small>OBS local o por ZeroTier · cámara en video continuo · lectura del tablero independiente</small>
<script type="module" src="/video-monitor.js"></script>
<script>let revision=-1;async function poll(){try{const r=await fetch('/api/state',{cache:'no-store',signal:AbortSignal.timeout(2500)});const s=await r.json();for(const k of ['clock','homeScore','awayScore','period']){document.getElementById(k).textContent=s[k];document.getElementById(k).classList.toggle('stale',!s.fields[k].valid);}document.getElementById('status').textContent=s.status+' · lector '+s.version;document.getElementById('cloud').textContent=s.uplink;document.getElementById('videoBackend').textContent=s.gameStatus||'';if(s.revision!==revision){revision=s.revision;document.getElementById('board').src='/board.png?r='+revision;}}catch{document.getElementById('status').textContent='Sin conexión con el lector local';}finally{setTimeout(poll,1000)}}poll();</script></html>'''.replace('CLOUD_URL',html.escape(uplink.config['cloud_url'],quote=True))
    if not uplink.config['cloud_url']:
        page=page.replace('<a href="" target="_blank" rel="noopener">Abrir panel en Render</a>','Prueba local · no se envian datos a Render')
    public=ROOT.parent/'public'
    if not public.is_dir():public=ROOT/'panel'
    if (public/'index.html').is_file():
        page=(public/'index.html').read_text(encoding='utf-8')
        monitors='<div class="camera-pair"><figure><figcaption>01 / Tablero <small>Lectura automática</small></figcaption><div class="camera-image"><img id="boardPreview" alt="Captura del tablero" hidden></div></figure><figure><figcaption><span id="gameLabel">02 / Salida de OBS</span> <small id="gameStatus">Conectando</small></figcaption><div class="camera-image"><club-game id="gameVideo" aria-label="Video continuo del juego"></club-game><img id="gamePreview" hidden alt="Cámara del juego"></div></figure></div>'
        page=re.sub(r'<div class="cloud-note">.*?</div>',monitors,page,flags=re.S)
        page=page.replace('<script src="script.js','<script type="module" src="/video-monitor.js"></script><script src="script.js')
    if license:page=page.replace('</body>',LICENSE_UI+'</body>') if '</body>' in page else page+LICENSE_UI
    cloud_origin=uplink.config.get('cloud_url','').rstrip('/')
    allowed_origins={f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
    if cloud_origin.startswith('https://'):allowed_origins.add(cloud_origin)
    own_origins={f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
    failures={'count':0,'until':0.}
    if remote:
        # Remote access: only the technician's ZeroTier IP, with password, and only code entry + calibration.
        own_origins=allowed_origins={f'http://{bind}:{port}'}
        page=REMOTE_PAGE.replace('CLUB_PC',html.escape(bind))+(LICENSE_UI if license else '')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def allowed(self):
            if not remote:return True
            if self.client_address[0]!=remote['allow']:self.send_error(403);return False
            if time.monotonic()<failures['until']:self.send_error(429,'Demasiados intentos; esperar 5 minutos');return False
            header=self.headers.get('Authorization','')
            try:password=base64.b64decode(header[6:]).decode('utf-8').split(':',1)[1] if header.startswith('Basic ') else ''
            except Exception:password=''
            if password and hmac.compare_digest(password.encode(),remote['password'].encode()):failures['count']=0;return True
            if password:
                failures['count']+=1
                if failures['count']>=10:failures['count']=0;failures['until']=time.monotonic()+300
            self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="Panel Go remoto", charset="UTF-8"');self.send_header('Content-Length','0');self.end_headers()
            return False
        def end_headers(self):
            origin=self.headers.get('Origin')
            if origin in allowed_origins:
                self.send_header('Access-Control-Allow-Origin',origin)
                self.send_header('Vary','Origin')
            super().end_headers()
        def do_OPTIONS(self):
            if remote:self.send_error(405);return
            if self.headers.get('Origin') not in allowed_origins:self.send_error(403);return
            if self.path.split('?',1)[0] not in ('/api/state','/api/events','/board.png','/game.jpg'):self.send_error(404);return
            self.send_response(204)
            self.send_header('Access-Control-Allow-Methods','GET, OPTIONS')
            self.send_header('Access-Control-Allow-Private-Network','true')
            self.end_headers()
        def do_POST(self):
            # Calibration changes only from the panel served by this same reader.
            if not self.allowed():return
            if self.headers.get('Origin') not in own_origins:self.send_error(403);return
            if self.path=='/api/license' and license:
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=2000:raise ValueError('Pedido invalido')
                    status,result=200,license.activate(json.loads(self.rfile.read(length)).get('code'))
                    print('Partido habilitado hasta '+expiry_label(result['expiresAt']),flush=True)
                except Exception as exc:status,result=400,{'error':str(exc) if isinstance(exc,ValueError) else 'No se pudo validar el codigo'}
                data=json.dumps(result).encode()
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
                return
            if self.path!='/api/calibration':self.send_error(404);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=20000 or not self.headers.get('Content-Type','').startswith('application/json'):raise ValueError('Pedido invalido')
                body=json.loads(self.rfile.read(length))
                calibration=core.reader_module.reset_calibration() if body.get('reset') else core.reader_module.save_calibration(body)
                with feed.lock:feed.confirmed.clear();feed.pending.clear();feed.last_samples.clear()
                status,result=200,{'ok':True,'calibration':calibration}
            except Exception as exc:status,result=400,{'error':str(exc) if isinstance(exc,ValueError) else 'No se pudo guardar la calibracion'}
            data=json.dumps(result).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if not self.allowed():return
            origin=self.headers.get('Origin')
            if origin and origin not in allowed_origins:self.send_error(403);return
            route=self.path.split('?',1)[0]
            if remote and route not in REMOTE_ROUTES and not (route.startswith('/assets/') and '..' not in route):self.send_error(404);return
            if route=='/video/ws':game.forward_websocket(self);return
            if route in ('/','/index.html'):data=page.encode();kind='text/html; charset=utf-8'
            elif route=='/api/state':
                state=feed.snapshot();state.update(game.snapshot());state['uplink']=uplink.message
                if license:state['license']=license.snapshot()
                data=json.dumps(state).encode();kind='application/json'
            elif route=='/api/license':
                data=json.dumps(license.snapshot() if license else {'active':True,'message':'Sin licencia'}).encode();kind='application/json'
            elif route=='/api/calibration':
                data=json.dumps({'calibration':core.reader_module.current_calibration(),'calibrated':core.reader_module.CALIBRATED}).encode();kind='application/json'
            elif route=='/frame.jpg':
                with feed.lock:frame=feed.frame
                if frame is None:self.send_error(503,'Sin imagen del tablero');return
                out=io.BytesIO();frame.save(out,format='JPEG',quality=88);data=out.getvalue();kind='image/jpeg'
            elif route=='/board.png':
                with feed.lock:data=feed.board
                kind='image/png'
            elif route=='/game.jpg' and hasattr(game,'image'):
                with game.lock:data=game.image
                kind='image/jpeg'
            elif route in ('/video-monitor.js','/vendor/video-rtc.js'):
                data=(ROOT/route.lstrip('/')).read_bytes();kind='text/javascript; charset=utf-8'
            elif route=='/api/events':
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-store');self.end_headers()
                try:
                    while True:
                        state=feed.snapshot();state.update(game.snapshot());state['uplink']=uplink.message
                        self.wfile.write(('data: '+json.dumps(state)+'\n\n').encode());self.wfile.flush()
                        with feed.lock:feed.lock.wait_for(lambda:feed.revision!=state['revision'],timeout=1)
                except (OSError,ConnectionError):pass
                return
            elif route=='/calibrar':
                data=(public/'calibrar.html').read_bytes();kind='text/html; charset=utf-8'
            elif route in ('/graphics.html','/styles.css','/script.js') or route.startswith('/assets/') and '..' not in route:
                file=(public/route.lstrip('/')).resolve()
                if not file.is_relative_to(public.resolve()) or not file.is_file():self.send_error(404);return
                data=file.read_bytes();kind={'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.png':'image/png'}.get(file.suffix,'application/octet-stream')
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer((bind,port),Handler);server.daemon_threads=True
    if remote:allowed_origins.clear();allowed_origins.add(f'http://{bind}:{server.server_port}')
    return server


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',default=str(ROOT/'config.json'));parser.add_argument('--no-browser',action='store_true');parser.add_argument('--local-only',action='store_true');args=parser.parse_args()
    try:config=load_config(args.config,args.local_only)
    except Exception as exc:raise SystemExit('Configuracion invalida: '+str(exc))
    os.environ['OBS_PASSWORD']=config.get('obs_password','')
    name=config['switcher_name']
    board_stream=StreamFrames(config['board_url'],fps=8,ffmpeg=config.get('ffmpeg_path','')) if config['board_mode']=='stream' else None
    feed=Feed(SimpleNamespace(host=config['obs_host'],obs_port=config['obs_port'],source=config.get('source','Camara 2'),game_source=config.get('game_source','camara 01'),interval=.125 if config['board_mode']=='stream' else .2,
                             game_rtsp=config.get('game_rtsp',''),video_port=int(config.get('video_port',1987)),board_stream=board_stream,board_crop=config.get('board_crop')))
    uplink=Uplink(feed,config)
    license=License(config['license_url'],ROOT/'.licencia.json')
    feed.gate=license.blocked
    threading.Thread(target=license.resume,daemon=True).start()
    if config['game_url']:game=StreamPreview(config['game_url'],f'Salida de {name}',ffmpeg=config.get('ffmpeg_path',''))
    elif config['switcher']=='vmix':game=NoPreview('Sin monitor: cargar game_url con una salida SRT del programa de vMix')
    elif config.get('monitor_mode','program')=='camera':game=ContinuousVideo(feed.args,OBS,ROOT)
    else:game=ProgramPreview(feed.args,OBS)
    port=int(config.get('local_port',8771))
    try:server=local_server(feed,uplink,game,port,license)
    except OSError:raise SystemExit(f'El puerto {port} ya esta en uso: hay otro panel o lector abierto (por ejemplo el de Club Estrella). Cerrar esa consola y volver a ejecutar INICIAR.cmd.')
    control_server=None
    if config['remote']:
        try:
            remote_server=local_server(feed,uplink,game,REMOTE_PORT,license,bind=config['remote']['listen'],remote=config['remote'])
            threading.Thread(target=remote_server.serve_forever,daemon=True).start()
            print(f"Acceso remoto para {config['remote']['allow']}: http://{config['remote']['listen']}:{REMOTE_PORT}/",flush=True)
        except OSError:print(f"No se pudo abrir el acceso remoto en {config['remote']['listen']}:{REMOTE_PORT}. Revisar ZeroTier.",flush=True)
    if config['switcher']=='vmix':control=VmixGraphicControl(config['production_host'],config['vmix_port'],config['vmix_overlay'])
    else:control=GraphicControl(config['obs_host'],config['obs_port'])
    control.local=not config['bridge_address']
    try:
        graphic_url=f'http://127.0.0.1:{port}/graphics.html'
        if config['bridge_address']:
            web=ROOT.parent/'public'
            if not web.is_dir():web=ROOT/'panel'
            try:bridge=make_bridge(config['bridge_address'],8772,config['production_host'],web,local_port=port)
            except OSError:raise SystemExit(f"No se pudo abrir {config['bridge_address']}:8772. Revisar que ZeroTier este conectado y que esa sea la IP de esta PC.")
            threading.Thread(target=bridge.serve_forever,daemon=True).start()
            graphic_url=f"http://{config['bridge_address']}:8772/graphics.html"
            print(f"{name} remoto {config['production_host']} · grafica para {name} en {graphic_url}",flush=True)
        else:print(f'{name} en esta PC',flush=True)
        if board_stream:print('Tablero por video: '+config['board_url'].split('?',1)[0],flush=True)
        control_server=make_control_server(control,graphic_url=graphic_url,cloud_origin=config.get('cloud_url',''))
        threading.Thread(target=control_server.serve_forever,daemon=True).start()
    except OSError:logging.info('El control de la grafica ya esta abierto o su puerto no esta disponible.')
    threading.Thread(target=feed.run,daemon=True).start()
    if not args.local_only:threading.Thread(target=uplink.run,daemon=True).start()
    else:uplink.message='Panel local · activo'
    threading.Thread(target=game.run,daemon=True).start()
    address=f'http://127.0.0.1:{port}/'
    print('Lector activo: '+address,flush=True)
    print('Para habilitar el partido, ingresar el codigo en el panel.',flush=True)
    if not args.no_browser:webbrowser.open(address)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        game.close();server.server_close()
        if board_stream:board_stream.close()
        if control_server:control_server.shutdown();control_server.server_close()


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    main()
