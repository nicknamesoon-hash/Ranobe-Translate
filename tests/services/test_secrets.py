import logging
import os
import sys

import pytest

from ranobe.core.redact import RedactingFilter, redact
from ranobe.services.secrets import FernetStore, SecretStoreLocked, WrongPassword

KEY = "AIzaSyD-THIS-IS-A-FAKE-KEY-1234567890"
FAST_N = 2**10  # keep scrypt cheap in tests


def test_fernet_round_trip(tmp_path):
    store = FernetStore(tmp_path, scrypt_n=FAST_N)
    store.unlock("pass")
    store.set("account:1", KEY)
    assert KEY not in (tmp_path / "secrets.enc").read_text()

    reopened = FernetStore(tmp_path, scrypt_n=FAST_N)
    assert not reopened.unlocked
    with pytest.raises(SecretStoreLocked):
        reopened.get("account:1")
    reopened.unlock("pass")
    assert reopened.get("account:1") == KEY


def test_fernet_wrong_password(tmp_path):
    FernetStore(tmp_path, scrypt_n=FAST_N).unlock("right")
    with pytest.raises(WrongPassword):
        FernetStore(tmp_path, scrypt_n=FAST_N).unlock("wrong")


def test_fernet_remember_and_forget(tmp_path):
    store = FernetStore(tmp_path, scrypt_n=FAST_N)
    store.unlock("pass", remember=True)
    store.set("k", "v")
    assert FernetStore(tmp_path, scrypt_n=FAST_N).get("k") == "v"  # no password needed
    if sys.platform != "win32":
        assert (os.stat(tmp_path / "device.key").st_mode & 0o777) == 0o600
    store.forget()
    assert not FernetStore(tmp_path, scrypt_n=FAST_N).unlocked


def test_redact_known_key_formats():
    text = f"401 for key {KEY} and sk-abcdefghijklmnop1234 via ?key=abcdefghijklmnopqrstu"
    out = redact(text)
    assert KEY not in out and "sk-abcdefghijklmnop1234" not in out
    assert "?key=***" in out


def test_redact_explicit_secret():
    assert redact("token=plainsecret", extra=["plainsecret"]) == "token=***"


def test_log_filter_masks_keys(caplog):
    logger = logging.getLogger("ranobe.test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="ranobe.test"):
        logger.info("calling with %s", KEY)
    assert KEY not in caplog.text
