"""crypto_store.py -- small encrypted-JSON-file helper, generalized from
OraPulse's favorites.py (same AES-256-GCM scheme: iv(12) + GCM tag(16) +
ciphertext, base64-encoded, one key file next to the data file). OraPulse
used this for one thing (saved connections); OraVault Backup uses the same
mechanism for two independent stores -- registered DBs (registered_dbs.py)
and, later, any other secret-bearing list -- so it's pulled out into a
reusable {filename, key filename} -> encrypted list store instead of two
copies of the same code.

Not shared code with OraPulse itself (that project isn't a dependency of
this one), just the same, deliberately-unchanged approach.
"""

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from paths import ensure_data_dir


class EncryptedListStore:
    def __init__(self, filename: str, key_filename: str):
        self._file = filename
        self._key_file = key_filename
        self._cached_key: Optional[bytes] = None

    def _paths(self) -> tuple[Path, Path]:
        data_dir = ensure_data_dir()
        return data_dir / self._file, data_dir / self._key_file

    def _get_key(self) -> bytes:
        if self._cached_key is not None:
            return self._cached_key
        _, key_path = self._paths()
        if key_path.exists():
            self._cached_key = bytes.fromhex(key_path.read_text().strip())
        else:
            self._cached_key = secrets.token_bytes(32)
            key_path.write_text(self._cached_key.hex())
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
        return self._cached_key

    def _encrypt(self, value) -> str:
        iv = secrets.token_bytes(12)
        combined = AESGCM(self._get_key()).encrypt(iv, json.dumps(value).encode("utf-8"), None)
        ciphertext, tag = combined[:-16], combined[-16:]
        return base64.b64encode(iv + tag + ciphertext).decode("ascii")

    def _decrypt(self, b64: str):
        raw = base64.b64decode(b64)
        iv, tag, ciphertext = raw[:12], raw[12:28], raw[28:]
        plaintext = AESGCM(self._get_key()).decrypt(iv, ciphertext + tag, None)
        return json.loads(plaintext.decode("utf-8"))

    def read_all(self) -> list:
        data_path, _ = self._paths()
        if not data_path.exists():
            return []
        raw = data_path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        try:
            data = self._decrypt(raw)
            return data if isinstance(data, list) else []
        except Exception as err:
            print(f"[crypto_store] could not decrypt {self._file}, treating as empty: {err}")
            return []

    def write_all(self, records: list) -> None:
        data_path, _ = self._paths()
        data_path.write_text(self._encrypt(records), encoding="utf-8")
