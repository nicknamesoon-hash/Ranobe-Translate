"""Fallback store: one file encrypted with Fernet, key derived from a master password (scrypt).

"Remember on this device" (opt-in) writes the derived key to `device.key` with owner-only
permissions, so the password is not asked again on this device. `forget()` removes it.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ranobe.services.secrets.base import SecretStoreLocked

SCRYPT_N = 2**15


class WrongPassword(Exception):
    pass


def derive_key(password: str, salt: bytes, n: int = SCRYPT_N) -> bytes:
    raw = Scrypt(salt=salt, length=32, n=n, r=8, p=1).derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


class FernetStore:
    name = "fernet"

    def __init__(self, folder: Path, scrypt_n: int = SCRYPT_N):
        self.file = folder / "secrets.enc"
        self.device_key_file = folder / "device.key"
        self._n = scrypt_n
        self._fernet: Fernet | None = None
        self._data: dict[str, str] = {}
        if self.device_key_file.exists() and self.file.exists():
            self._open(self.device_key_file.read_bytes().strip())

    def available(self) -> bool:
        return True

    @property
    def initialized(self) -> bool:
        return self.file.exists()

    @property
    def unlocked(self) -> bool:
        return self._fernet is not None

    def unlock(self, password: str, remember: bool = False) -> None:
        """Open the store (or create it on first use). Raises WrongPassword."""
        if self.initialized:
            salt = base64.b64decode(json.loads(self.file.read_text("utf-8"))["salt"])
        else:
            salt = secrets.token_bytes(16)
        key = derive_key(password, salt, self._n)
        if self.initialized:
            self._open(key)
        else:
            self._fernet, self._data = Fernet(key), {}
            self._salt = salt
            self._write()
        if remember:
            self._write_private(self.device_key_file, key)

    def forget(self) -> None:
        self.device_key_file.unlink(missing_ok=True)

    def lock(self) -> None:
        self._fernet, self._data = None, {}

    def get(self, ref: str) -> str | None:
        self._require_unlocked()
        return self._data.get(ref)

    def set(self, ref: str, secret: str) -> None:
        self._require_unlocked()
        self._data[ref] = secret
        self._write()

    def delete(self, ref: str) -> None:
        self._require_unlocked()
        if self._data.pop(ref, None) is not None:
            self._write()

    def _open(self, key: bytes) -> None:
        payload = json.loads(self.file.read_text("utf-8"))
        fernet = Fernet(key)
        try:
            data = json.loads(fernet.decrypt(payload["data"].encode()))
        except InvalidToken as e:
            raise WrongPassword from e
        self._fernet, self._data = fernet, data
        self._salt = base64.b64decode(payload["salt"])

    def _require_unlocked(self) -> None:
        if self._fernet is None:
            raise SecretStoreLocked

    def _write(self) -> None:
        assert self._fernet is not None
        token = self._fernet.encrypt(json.dumps(self._data).encode()).decode()
        payload = {"v": 1, "salt": base64.b64encode(self._salt).decode(), "data": token}
        self._write_private(self.file, json.dumps(payload).encode())

    @staticmethod
    def _write_private(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, path)
