import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from core import Feed
from license import License


class FakeOpener:
    def __init__(self, status=200, body=None, error=None): self.status = status; self.body = body or {}; self.error = error; self.sent = []
    def open(self, request, timeout=None):
        self.sent.append(json.loads(request.data))
        if self.error: raise self.error
        if self.status != 200:
            raise urllib.error.HTTPError(request.full_url, self.status, 'x', {}, io.BytesIO(json.dumps(self.body).encode()))
        response = io.BytesIO(json.dumps(self.body).encode()); response.status = 200
        return _Ctx(response)


class _Ctx:
    def __init__(self, r): self.r = r
    def __enter__(self): return self.r
    def __exit__(self, *a): return False


class LicenseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='.test-', dir=Path(__file__).resolve().parent)
        self.saved = Path(self.folder.name) / 'licencia.json'; self.now = 1000.0

    def tearDown(self): self.folder.cleanup()

    def make(self, opener):
        return License('https://panel.example', self.saved, opener=opener, clock=lambda: self.now)

    def test_valid_code_unlocks_for_the_granted_time_and_is_saved(self):
        license = self.make(FakeOpener(body={'ok': True, 'remaining': 3600, 'expiresAt': '2026-10-21T02:59:00Z'}))
        self.assertIsNotNone(license.blocked())
        license.activate('abcde-fghij')
        self.assertIsNone(license.blocked()); self.assertTrue(license.snapshot()['active'])
        self.assertEqual(json.loads(self.saved.read_text())['code'], 'abcde-fghij')
        self.now += 3601
        self.assertIn('venció', license.blocked())

    def test_rejected_code_explains_why_and_forgets_saved_code(self):
        self.saved.write_text(json.dumps({'code': 'viejo'}))
        license = self.make(FakeOpener(status=403, body={'error': 'Código vencido'}))
        with self.assertRaisesRegex(ValueError, 'Código vencido'): license.activate('viejo')
        self.assertFalse(self.saved.exists()); self.assertIsNotNone(license.blocked())

    def test_offline_keeps_saved_code_for_a_later_retry(self):
        self.saved.write_text(json.dumps({'code': 'guardado'}))
        license = self.make(FakeOpener(error=urllib.error.URLError('offline')))
        license.resume()
        self.assertIn('Sin conexión', license.blocked()); self.assertTrue(self.saved.exists())

    def test_locked_feed_blanks_the_score_until_unlocked(self):
        feed = Feed(SimpleNamespace(source='x', board_crop=None)); reason = ['Panel sin habilitar']
        feed.values.update(homeScore='33', awayScore='38'); feed.connected = True
        feed.gate = lambda: reason[0]
        self.assertTrue(feed.held())
        state = feed.snapshot()
        self.assertEqual((state['homeScore'], state['connected'], state['status']), ('--', False, 'Panel sin habilitar'))
        reason[0] = None
        self.assertFalse(feed.held()); self.assertFalse(feed.locked)


if __name__ == '__main__':
    unittest.main()
