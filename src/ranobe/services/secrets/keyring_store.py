"""OS keychain: Windows Credential Manager, Linux Secret Service, macOS Keychain."""

from __future__ import annotations

import contextlib

SERVICE = "ranobe-translator"


class KeyringStore:
    name = "keyring"

    def available(self) -> bool:
        try:
            import keyring
            from keyring.backends import fail
        except ImportError:
            return False
        backend = keyring.get_keyring()
        return not isinstance(backend, fail.Keyring) and getattr(backend, "priority", 0) > 0

    def get(self, ref: str) -> str | None:
        import keyring

        return keyring.get_password(SERVICE, ref)

    def set(self, ref: str, secret: str) -> None:
        import keyring

        keyring.set_password(SERVICE, ref, secret)

    def delete(self, ref: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        with contextlib.suppress(PasswordDeleteError):
            keyring.delete_password(SERVICE, ref)
