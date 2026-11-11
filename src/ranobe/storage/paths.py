"""Per-platform data directory. Never inside the app folder, so updates do not touch user data."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "RanobeTranslator"


def data_dir() -> Path:
    override = os.environ.get("RANOBE_DATA_DIR")
    if override:
        return Path(override)
    flet_storage = os.environ.get("FLET_APP_STORAGE_DATA")  # set by Flet on Android
    if flet_storage:
        return Path(flet_storage)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "ranobe-translator"


def db_path() -> Path:
    return data_dir() / "library.db"


def settings_path() -> Path:
    return data_dir() / "settings.json"
