import http from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { EventEmitter } from 'node:events';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(ROOT, 'public');
const KEYS = ['clock', 'homeScore', 'awayScore', 'period'];
const DEFAULTS = { clock: '--:--', homeScore: '--', awayScore: '--', period: '--' };
const ASSETS = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ...['index.html', 'graphics.html'].map(n => ['/' + n, [n, 'text/html; charset=utf-8']]),
  ['/script.js', ['script.js', 'text/javascript; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
  ['/assets/panelgo-logo.png', ['assets/panelgo-logo.png', 'image/png']],
  ...[1, 2, 3, 4].map(n => [`/assets/page-04-image-0${n}.png`, [`assets/page-04-image-0${n}.png`, 'image/png']]),
]);

export function authorized(header, token) {
  if (!token || typeof header !== 'string' || !header.startsWith('Bearer ')) return false;
  const actual = Buffer.from(header.slice(7));
  const expected = Buffer.from(token);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

function validValue(key, value) {
  if (typeof value !== 'string') return false;
  if (value === DEFAULTS[key]) return true;
  if (key === 'clock') return (/^\d{2}:[0-5]\d$/.test(value) && Number(value.slice(0, 2)) <= 20) || /^[0-5]\d\.\d$/.test(value);
  if (key === 'period') return /^[1-9]$/.test(value);
  return /^\d{1,2}$/.test(value);
}

export function normalize(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Datos invalidos');
  const values = {}, fields = {};
  for (const key of KEYS) {
    if (!validValue(key, input[key])) throw new Error(`Valor invalido: ${key}`);
    values[key] = input[key];
    const field = input.fields?.[key];
    const age = typeof field?.age === 'number' && Number.isFinite(field.age) && field.age >= 0 ? field.age : null;
    fields[key] = { age, valid: field?.valid === true && age !== null && input[key] !== DEFAULTS[key] };
  }
  const captured = typeof input.updatedAt === 'string' && Number.isFinite(Date.parse(input.updatedAt)) ? input.updatedAt : null;
  const boardOff = input.boardOff === true && values.clock === '10:00' && values.homeScore === '0' && values.awayScore === '0';
  return { ...values, fields, connected: input.connected === true, updatedAt: captured, boardOff };
}

export class ScoreStore extends EventEmitter {
  constructor(now = () => Date.now()) { super(); this.now = now; this.latest = null; this.receivedAt = null; this.revision = 0; }
  accept(input) { this.latest = normalize(input); this.receivedAt = this.now(); this.revision++; this.emit('update'); }
  snapshot() {
    const elapsed = this.receivedAt === null ? Infinity : Math.max(0, (this.now() - this.receivedAt) / 1000);
    const latest = this.latest;
    const connected = Boolean(latest?.connected && elapsed < 6);
    const fields = Object.fromEntries(KEYS.map(key => {
      const previous = latest?.fields[key];
      const age = previous?.age === null || !previous ? null : Math.round((previous.age + elapsed) * 10) / 10;
      return [key, { age, valid: connected && previous.valid && age !== null && age < 5 }];
    }));
    const good = connected && Object.values(fields).every(field => field.valid);
    const standby = connected && latest?.boardOff === true;
    return { ...DEFAULTS, ...(latest || {}), fields, connected,
      service: 'panelgo-tablero', version: '1.0.0', source: 'OBS local del cliente',
      revision: this.revision, ocrStatus: standby ? 'standby' : good ? 'ok' : 'waiting',
      status: !latest ? 'Esperando lector de la PC del cliente' : standby ? 'Tablero apagado · listo para iniciar' : good ? 'Lectura automatica activa' : connected ? 'Verificando lectura del tablero' : 'Lector sin conexion · ultimo dato recibido',
      boardImage: '',
    };
  }
}

async function jsonBody(req) {
  let bytes = 0; const chunks = [];
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > 16384) throw Object.assign(new Error('Peticion demasiado grande'), { status: 413 });
    chunks.push(Buffer.from(chunk));
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw Object.assign(new Error('JSON invalido'), { status: 400 }); }
}

function json(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(data));
}

export function createHandler({ token, store = new ScoreStore() }) {
  const streams = new Set();
  const handler = async (req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    const url = new URL(req.url, 'http://localhost');
    try {
      if (req.method === 'GET' && url.pathname === '/healthz') return json(res, 200, { ok: true, service: 'panelgo-tablero' });
      if (req.method === 'POST' && url.pathname === '/api/ingest') {
        if (!authorized(req.headers.authorization, token)) return json(res, 401, { error: 'No autorizado' });
        if (!req.headers['content-type']?.startsWith('application/json')) return json(res, 415, { error: 'Se requiere JSON' });
        const body = await jsonBody(req);
        try { store.accept(body); } catch (e) { return json(res, 400, { error: e.message }); }
        return json(res, 200, { ok: true, revision: store.revision });
      }
      if (req.method === 'GET' && ['/api/state', '/live-state.json'].includes(url.pathname)) return json(res, 200, store.snapshot());
      if (req.method === 'GET' && url.pathname === '/api/events') {
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no' });
        const send = () => { if (!res.writableEnded) res.write(`data: ${JSON.stringify(store.snapshot())}\n\n`); };
        send();
        const interval = setInterval(send, 1000); interval.unref();
        store.on('update', send); streams.add(res);
        res.once('close', () => { clearInterval(interval); store.off('update', send); streams.delete(res); });
        return;
      }
      const asset = ASSETS.get(url.pathname);
      if (req.method === 'GET' && asset) {
        const data = await readFile(path.join(PUBLIC, asset[0]));
        res.writeHead(200, { 'Content-Type': asset[1], 'Content-Length': data.length, 'Cache-Control': 'no-cache' });
        return res.end(data);
      }
      return json(res, 404, { error: 'No encontrado' });
    } catch (e) {
      if (!res.headersSent) json(res, e.status || 500, { error: e.status ? e.message : 'Error interno' });
      else res.end();
    }
  };
  return { handler, close: () => { for (const stream of streams) stream.end(); } };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const token = process.env.INGEST_TOKEN || '';
  if (token.length < 32 || token.includes('REPLACE_')) {
    console.error('Configurar INGEST_TOKEN con una clave privada de al menos 32 caracteres.');
    process.exitCode = 1;
  } else {
    const app = createHandler({ token });
    const server = http.createServer(app.handler);
    server.requestTimeout = 15000; server.headersTimeout = 10000;
    const port = Number(process.env.PORT || 10000);
    server.listen(port, '0.0.0.0', () => console.log(`Panel Go en puerto ${port}`));
    const stop = () => { app.close(); server.close(() => process.exit(0)); server.closeIdleConnections(); setTimeout(() => process.exit(1), 10000).unref(); };
    process.on('SIGTERM', stop); process.on('SIGINT', stop);
  }
}
