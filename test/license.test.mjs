import test from 'node:test';
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { issueCode, verifyCode, Attempts } from '../license.mjs';
import { createHandler } from '../server.mjs';

const secret = 's'.repeat(40), adminKey = 'a'.repeat(24), token = 'x'.repeat(40);
const NOW = Date.parse('2026-10-20T18:00:00Z');

async function call(app, { method = 'POST', url, body = {}, authorization = null, ip = '1.2.3.4' }) {
  const req = Readable.from([JSON.stringify(body)]);
  req.method = method; req.url = url; req.headers = { 'content-type': 'application/json', authorization, 'x-forwarded-for': ip };
  const res = { headers: {}, status: null, body: '', headersSent: false, setHeader(k, v) { this.headers[k] = v; },
    writeHead(s) { this.status = s; this.headersSent = true; }, end(d) { if (d) this.body += d; } };
  await app.handler(req, res); return { status: res.status, data: JSON.parse(res.body || '{}') };
}

test('a code is valid until its expiry and tolerant to typing', () => {
  const code = issueCode(secret, NOW + 4 * 3600e3);
  assert.match(code, /^[A-Z2-7]{5}(-[A-Z2-7]{5}){3}$/);
  assert.equal(verifyCode(secret, code, NOW).ok, true);
  assert.equal(verifyCode(secret, ` ${code.toLowerCase().replace(/-/g, ' ')} `, NOW).ok, true);
  assert.equal(verifyCode(secret, code, NOW + 5 * 3600e3).error, 'Código vencido');
});

test('a forged or altered code is rejected', () => {
  const code = issueCode(secret, NOW + 3600e3);
  assert.equal(verifyCode('otro'.repeat(10), code, NOW).ok, false);
  const altered = (code[0] === 'A' ? 'B' : 'A') + code.slice(1);
  assert.equal(verifyCode(secret, altered, NOW).ok, false);
  for (const bad of ['', null, 'ABC', '<script>']) assert.equal(verifyCode(secret, bad, NOW).ok, false);
});

test('admin issues codes only with the key and within 31 days', async () => {
  const app = createHandler({ token, licenseSecret: secret, adminKey, now: () => NOW });
  const until = new Date(NOW + 4 * 3600e3).toISOString();
  assert.equal((await call(app, { url: '/api/admin/code', body: { expiresAt: until } })).status, 401);
  assert.equal((await call(app, { url: '/api/admin/code', authorization: `Bearer ${adminKey}`, body: { expiresAt: new Date(NOW - 1).toISOString() } })).status, 400);
  assert.equal((await call(app, { url: '/api/admin/code', authorization: `Bearer ${adminKey}`, body: { expiresAt: new Date(NOW + 40 * 86400e3).toISOString() } })).status, 400);
  const issued = await call(app, { url: '/api/admin/code', authorization: `Bearer ${adminKey}`, body: { club: 'Club Estrella', expiresAt: until } });
  assert.equal(issued.status, 200); assert.equal(issued.data.club, 'Club Estrella');
  const activated = await call(app, { url: '/api/license/activate', body: { code: issued.data.code } });
  assert.equal(activated.status, 200); assert.equal(activated.data.remaining, 4 * 3600);
});

test('activation fails clearly when expired, unconfigured or brute-forced', async () => {
  const code = issueCode(secret, NOW + 60e3);
  const later = createHandler({ token, licenseSecret: secret, adminKey, now: () => NOW + 120e3 });
  assert.equal((await call(later, { url: '/api/license/activate', body: { code } })).data.error, 'Código vencido');
  const off = createHandler({ token });
  assert.equal((await call(off, { url: '/api/license/activate', body: { code } })).status, 503);
  const app = createHandler({ token, licenseSecret: secret, adminKey, now: () => NOW, attempts: new Attempts(3, 60000, () => NOW) });
  const statuses = [];
  for (let i = 0; i < 4; i++) statuses.push((await call(app, { url: '/api/license/activate', body: { code: 'AAAAA-AAAAA-AAAAA-AAAAA' } })).status);
  assert.deepEqual(statuses, [403, 403, 403, 429]);
  assert.equal((await call(app, { url: '/api/license/activate', body: { code }, ip: '5.6.7.8' })).status, 200);
});

test('the admin page is served', async () => {
  const app = createHandler({ token });
  const req = Readable.from([]); req.method = 'GET'; req.url = '/admin'; req.headers = {};
  const res = { status: null, setHeader() {}, writeHead(s) { this.status = s; }, end() {} };
  await app.handler(req, res); assert.equal(res.status, 200);
});
