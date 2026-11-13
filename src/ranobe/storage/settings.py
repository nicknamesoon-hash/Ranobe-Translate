"""Device settings stored as JSON. Contains no secrets."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class AppSettings:
    ui_locale: str = "uk"
    theme: str = "system"  # "light" | "dark" | "system"
    reduce_motion: bool = False
    default_target_lang: str = "uk"
    default_provider: str = ""  # provider preselected when adding an account
    secret_backend: str = "auto"  # "auto" | "keyring" | "fernet"

    @classmethod
    def load(cls, path: Path) -> AppSettings:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
