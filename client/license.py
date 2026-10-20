"""Per-match activation: the reader works only with a code validated by the Panel Go server on Render."""
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_LICENSE_URL = 'https://panelgo-tablero.onrender.com'
LOCKED = 'Panel sin habilitar: ingresar el código del partido'


class License:
    def __init__(self, server, saved_path, opener=None, clock=time.monotonic, timeout=75):
        self.server = server.rstrip('/'); self.saved_path = Path(saved_path); self.clock = clock; self.timeout = timeout
        self.opener = opener or urllib.request.build_opener()
        self.lock = threading.Lock(); self.until = None; self.expires_at = None; self.busy = False
        self.message = LOCKED

    def remaining(self):
        with self.lock:
            return max(0, int(self.until - self.clock())) if self.until is not None else 0

    def blocked(self):
        """None when the reader may run, otherwise the reason shown in the panel."""
        with self.lock:
            if self.until is not None and self.clock() < self.until: return None
            if self.until is not None:
                self.until = None; self.message = 'El código del partido venció. Pedir uno nuevo.'
            return self.message

    def snapshot(self):
        active = self.blocked() is None
        return {'active': active, 'busy': self.busy, 'expiresAt': self.expires_at if active else None,
                'remaining': self.remaining(), 'message': 'Habilitado' if active else self.message}

    def activate(self, code, save=True):
        code = str(code or '').strip()
        if not code: raise ValueError('Ingresar el código del partido')
        request = urllib.request.Request(self.server + '/api/license/activate', data=json.dumps({'code': code}).encode(),
                                         headers={'Content-Type': 'application/json'}, method='POST')
        self.busy = True
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = json.loads(response.read(4096))
        except urllib.error.HTTPError as exc:
            try: error = json.loads(exc.read(4096)).get('error')
            except Exception: error = None
            self.message = error or f'El servidor de licencias respondió HTTP {exc.code}'
            if exc.code == 403 and save and self.saved_code() == code: self.forget()
            raise ValueError(self.message)
        except (urllib.error.URLError, OSError, ValueError):
            self.message = 'Sin conexión con el servidor de licencias. Revisar internet y reintentar.'
            raise ValueError(self.message)
        finally:
            self.busy = False
        remaining = int(data.get('remaining', 0))
        if not data.get('ok') or remaining <= 0:
            self.message = 'Código vencido'; raise ValueError(self.message)
        with self.lock:
            # The local clock only counts the time Render granted; changing the PC date does not extend it.
            self.until = self.clock() + remaining; self.expires_at = data.get('expiresAt'); self.message = 'Habilitado'
        if save:
            try: self.saved_path.write_text(json.dumps({'code': code}), encoding='utf-8')
            except OSError: pass
        return self.snapshot()

    def saved_code(self):
        try: return json.loads(self.saved_path.read_text(encoding='utf-8')).get('code')
        except (OSError, ValueError, AttributeError): return None

    def forget(self):
        try: self.saved_path.unlink()
        except OSError: pass

    def resume(self):
        """After a restart, re-validate the last code automatically (needs internet once)."""
        code = self.saved_code()
        if not code: return
        self.message = 'Validando el código guardado...'
        try: self.activate(code)
        except ValueError: pass


def expiry_label(iso):
    try: return datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone().strftime('%d/%m %H:%M')
    except (AttributeError, ValueError): return ''
