// favorites.js -- server-side storage for the "Favorites" feature on the
// connect screen (public/index.html): saved IP/Port/SID/password so a
// known DB can be connected to with one click instead of retyping its
// details every time.
//
// This used to live entirely in the browser (localStorage), which meant
// the password sat in plain text in the browser's storage for that
// origin. It's now a small encrypted file on disk instead
// (data/favorites.enc), same reasoning and same approach as
// report.js's snapshot-history.jsonl target encryption: AES-256-GCM with a
// key generated once into its own file (data/.favorites-key) the first
// time this module needs it. This doesn't defend against someone who
// already has full access to this app's own data/ folder, but it does mean
// the favorites file on its own (copied out, attached to a support ticket,
// backed up alongside other files, etc.) doesn't hand over a working DB
// password.
//
// There's no login gate on the /api/favorites* routes in main.js (same as
// everywhere else in this app -- see the top-of-file comment in main.js):
// this whole feature only exists to be usable from the connect screen,
// before any DB connection/session exists yet.

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DATA_DIR = path.join(__dirname, 'data');
const FAVORITES_FILE = path.join(DATA_DIR, 'favorites.enc');
const KEY_FILE = path.join(DATA_DIR, '.favorites-key');

function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
}

let cachedKey = null;
function getEncryptionKey() {
  if (cachedKey) return cachedKey;
  ensureDataDir();
  if (fs.existsSync(KEY_FILE)) {
    cachedKey = Buffer.from(fs.readFileSync(KEY_FILE, 'utf8').trim(), 'hex');
  } else {
    cachedKey = crypto.randomBytes(32);
    fs.writeFileSync(KEY_FILE, cachedKey.toString('hex'), { mode: 0o600 });
  }
  return cachedKey;
}

// AES-256-GCM: a random IV per write plus an auth tag, so a corrupted/
// tampered file is detected (decrypt throws) rather than silently handing
// back garbage favorites.
function encrypt(value) {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', getEncryptionKey(), iv);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(value), 'utf8'), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), ciphertext]).toString('base64');
}

function decrypt(base64) {
  const raw = Buffer.from(base64, 'base64');
  const iv = raw.subarray(0, 12);
  const authTag = raw.subarray(12, 28);
  const ciphertext = raw.subarray(28);
  const decipher = crypto.createDecipheriv('aes-256-gcm', getEncryptionKey(), iv);
  decipher.setAuthTag(authTag);
  const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return JSON.parse(plaintext.toString('utf8'));
}

// The whole list is stored as one encrypted blob (rather than encrypting
// individual fields within a plain-JSON array) -- simplest way to
// guarantee nothing about a favorite (name, IP, port, SID, password) ever
// touches disk unencrypted.
function readAll() {
  ensureDataDir();
  if (!fs.existsSync(FAVORITES_FILE)) return [];
  const raw = fs.readFileSync(FAVORITES_FILE, 'utf8').trim();
  if (!raw) return [];
  try {
    const list = decrypt(raw);
    return Array.isArray(list) ? list : [];
  } catch (err) {
    // Wrong/rotated key or a corrupted file -- treated as "no favorites"
    // rather than crashing the connect screen over it.
    console.error('[favorites] could not decrypt favorites.enc, treating as empty:', err.message);
    return [];
  }
}

function writeAll(list) {
  ensureDataDir();
  fs.writeFileSync(FAVORITES_FILE, encrypt(list), 'utf8');
}

function listFavorites() {
  return readAll();
}

// Upserts by id: a new favorite gets a generated id, an existing one
// (same id passed back in, e.g. when the user chose to overwrite an
// existing name) is replaced in place.
function saveFavorite({ id, name, ip, port, sid, account, password }) {
  const list = readAll();
  const resolvedId = id && list.some(f => f.id === id) ? id : `fav_${Date.now()}_${crypto.randomBytes(4).toString('hex')}`;
  const record = { id: resolvedId, name, ip, port, sid, account, password };
  const idx = list.findIndex(f => f.id === resolvedId);
  const next = idx >= 0 ? list.map(f => (f.id === resolvedId ? record : f)) : [...list, record];
  writeAll(next);
  return record;
}

function deleteFavorite(id) {
  writeAll(readAll().filter(f => f.id !== id));
}

module.exports = { listFavorites, saveFavorite, deleteFavorite };
