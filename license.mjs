// Per-match activation codes. Stateless: a code carries its own expiry and an HMAC,
// so Render needs no database and a restart does not lose issued codes.
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
export const MAX_DAYS = 31;

function base32(bytes) {
  let bits = 0, value = 0, out = '';
  for (const byte of bytes) {
    value = (value << 8) | byte; bits += 8;
    while (bits >= 5) { out += ALPHABET[(value >>> (bits - 5)) & 31]; bits -= 5; }
  }
  if (bits > 0) out += ALPHABET[(value << (5 - bits)) & 31];
  return out;
}

function unbase32(text) {
  let bits = 0, value = 0; const out = [];
  for (const char of text) {
    const index = ALPHABET.indexOf(char);
    if (index < 0) return null;
    value = ((value << 5) | index) & 0xffff; bits += 5;
    if (bits >= 8) { out.push((value >>> (bits - 8)) & 255); bits -= 8; }
  }
  return Buffer.from(out);
}

const mac = (secret, body) => createHmac('sha256', secret).update('panelgo-licencia-1').update(body).digest().subarray(0, 6);

/** 12 bytes: expiry in minutes (4) + random (2) + HMAC (6) → 20 characters in groups of 5. */
export function issueCode(secret, expiresAt, nonce = randomBytes(2)) {
  const body = Buffer.alloc(6);
  body.writeUInt32BE(Math.ceil(expiresAt / 60000)); nonce.copy(body, 4, 0, 2);
  return base32(Buffer.concat([body, mac(secret, body)])).match(/.{5}/g).join('-');
}

export function verifyCode(secret, code, now = Date.now()) {
  const clean = String(code ?? '').toUpperCase().replace(/[\s-]/g, '').replace(/0/g, 'O').replace(/1/g, 'I');
  if (!/^[A-Z2-7]{20}$/.test(clean)) return { ok: false, error: 'El código no tiene el formato correcto' };
  const bytes = unbase32(clean);
  const body = bytes.subarray(0, 6), signature = bytes.subarray(6, 12);
  if (!timingSafeEqual(signature, mac(secret, body))) return { ok: false, error: 'Código inválido' };
  const expiresAt = body.readUInt32BE(0) * 60000;
  if (expiresAt <= now) return { ok: false, error: 'Código vencido', expiresAt };
  return { ok: true, expiresAt };
}

/** Small per-IP limit so codes cannot be guessed by brute force. */
export class Attempts {
  constructor(limit = 10, windowMs = 60000, now = () => Date.now()) { this.limit = limit; this.windowMs = windowMs; this.now = now; this.seen = new Map(); }
  allow(key) {
    const now = this.now(); const entry = this.seen.get(key);
    if (!entry || now >= entry.reset) { this.seen.set(key, { count: 1, reset: now + this.windowMs }); return true; }
    if (this.seen.size > 5000) for (const [k, v] of this.seen) if (now >= v.reset) this.seen.delete(k);
    return ++entry.count <= this.limit;
  }
}
