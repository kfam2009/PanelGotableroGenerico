import base64
import threading
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from agent import local_server
from core import Feed


class Game:
    def snapshot(self): return {}


class RemoteAccessTests(unittest.TestCase):
    def setUp(self):
        feed = Feed(SimpleNamespace(source='x', board_crop=None))
        uplink = SimpleNamespace(config={'cloud_url': ''}, message='')
        self.server = local_server(feed, uplink, Game(), 0, bind='127.0.0.1', remote={'allow': '127.0.0.1', 'password': 'clave-segura'})
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self): self.server.shutdown(); self.server.server_close()

    def get(self, path, password=None, method='GET', origin=None):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', method=method, data=b'{}' if method == 'POST' else None)
        if password is not None: request.add_header('Authorization', 'Basic ' + base64.b64encode(f'tecnico:{password}'.encode()).decode())
        if origin: request.add_header('Origin', origin); request.add_header('Content-Type', 'application/json')
        try:
            with self.opener.open(request, timeout=3) as response: return response.status, response.read().decode()
        except urllib.error.HTTPError as exc: return exc.code, ''

    def test_password_is_required(self):
        self.assertEqual(self.get('/')[0], 401)
        self.assertEqual(self.get('/', 'otra')[0], 401)
        status, body = self.get('/', 'clave-segura')
        self.assertEqual(status, 200); self.assertIn('Acceso remoto', body)

    def test_only_calibration_and_code_routes_are_exposed(self):
        self.assertEqual(self.get('/calibrar', 'clave-segura')[0], 200)
        for path in ('/graphics.html', '/game.jpg', '/video/ws', '/script.js'):
            self.assertEqual(self.get(path, 'clave-segura')[0], 404, path)

    def test_writes_need_the_remote_origin(self):
        self.assertEqual(self.get('/api/calibration', 'clave-segura', 'POST', origin='http://evil.example')[0], 403)
        status, _ = self.get('/api/calibration', 'clave-segura', 'POST', origin=f'http://127.0.0.1:{self.port}')
        self.assertEqual(status, 400)  # reached the handler; empty calibration is rejected

    def test_repeated_wrong_passwords_lock_out(self):
        for _ in range(10): self.get('/', 'mal')
        self.assertEqual(self.get('/', 'clave-segura')[0], 429)


if __name__ == '__main__':
    unittest.main()
