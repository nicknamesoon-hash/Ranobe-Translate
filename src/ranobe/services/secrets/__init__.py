"""Pick the best available secret store for this platform."""

from __future__ import annotations

from pathlib import Path

from ranobe.services.secrets.base import MemorySecretStore, SecretStore, SecretStoreLocked
from ranobe.services.secrets.fernet_store import FernetStore, WrongPassword
from ranobe.services.secrets.keyring_store import KeyringStore


def select_store(data_dir: Path, preference: str = "auto") -> SecretStore:
    """OS keyring first; Fernet with a master password if the keyring is missing.
    An Android Keystore backend is added after the phase 1 Android spike."""
    if preference in ("auto", "keyring"):
        keyring_store = KeyringStore()
        if keyring_store.available():
            return keyring_store
    return FernetStore(data_dir)


__all__ = [
    "FernetStore",
    "KeyringStore",
    "MemorySecretStore",
    "SecretStore",
    "SecretStoreLocked",
    "WrongPassword",
    "select_store",
]
