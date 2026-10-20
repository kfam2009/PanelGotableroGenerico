"""Refresh only Panel Go's existing browser source after a reader update."""
import json
import base64
import io
import time
import urllib.request
from PIL import Image
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl,urlencode
import core

SOURCE='Panel Go - Marcador'

def refresh_graphic(obs,port=8771,verify=False):
    sources=obs.request('GetInputList')['inputs']
    if not any(source['inputName']==SOURCE and source['inputKind']=='browser_source' for source in sources):return False
    settings=obs.request('GetInputSettings',{'inputName':SOURCE})['inputSettings']
    url=urlsplit(settings.get('url',''))
    if settings.get('is_local_file') or url.path!='/graphics.html' or url.hostname not in ('127.0.0.1','localhost','172.27.4.221'):return False
    query=dict(parse_qsl(url.query));query['v']='clock-fast-1'
    new_url=f'http://127.0.0.1:{port}/graphics.html?'+urlencode(query)
    if settings.get('url')!=new_url:
        obs.request('SetInputSettings',{'inputName':SOURCE,'inputSettings':{'url':new_url},'overlay':True})
        if verify and obs.request('GetSourceActive',{'sourceName':SOURCE}).get('videoShowing',False):
            try:
                time.sleep(3)
                reply=obs.request('GetSourceScreenshot',{'sourceName':SOURCE,'imageFormat':'png','imageWidth':320,'imageHeight':180})
                pixels=base64.b64decode(reply['imageData'].split(',',1)[1])
                if not Image.open(io.BytesIO(pixels)).convert('RGBA').getchannel('A').getbbox():raise RuntimeError('Fuente sin imagen')
            except Exception:
                obs.request('SetInputSettings',{'inputName':SOURCE,'inputSettings':{'url':settings['url']},'overlay':True})
                raise
    return True

def main():
    config=json.loads(Path(__file__).with_name('config.json').read_text(encoding='utf-8-sig'))
    core.ALLOWLIST.add('SetInputSettings')
    core.ALLOWLIST.add('GetSourceActive')
    obs=None
    try:
        port=int(config.get('local_port',8771))
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/graphics.html',timeout=3) as response:
            if b'id="bar"' not in response.read():raise RuntimeError('La salida local no esta lista')
        obs=core.OBS('127.0.0.1',int(config.get('obs_port',4455)),config.get('obs_password',''))
        print('Marcador de OBS actualizado.' if refresh_graphic(obs,port,verify=True) else 'No se recargo ninguna fuente: revisar la fuente Panel Go en OBS.')
    except Exception:print('No se pudo recargar el marcador. Con OBS abierto, refrescar la fuente Panel Go una vez.')
    finally:
        if obs:obs.close()

if __name__=='__main__':main()
