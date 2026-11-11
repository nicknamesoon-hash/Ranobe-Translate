"""SQLite connection, transactions and numbered SQL migrations (PRAGMA user_version)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path


def _migrations() -> list[tuple[int, str]]:
    folder = resources.files("ranobe.storage") / "migrations"
    found = []
    for entry in folder.iterdir():
        name = entry.name
        if name.endswith(".sql") and name[:4].isdigit():
            found.append((int(name[:4]), entry.read_text(encoding="utf-8")))
    return sorted(found)


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: we control transactions explicitly with BEGIN/COMMIT.
        self.conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._depth = 0
        self.migrate()

    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        for number, sql in _migrations():
            if number <= self.version:
                continue
            with self.transaction():
                for statement in _split_sql(sql):
                    self.conn.execute(statement)
                self.conn.execute(f"PRAGMA user_version = {number}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Nested calls join the outer transaction; only the outermost commits."""
        if self._depth == 0:
            self.conn.execute("BEGIN IMMEDIATE")
        self._depth += 1
        try:
            yield self.conn
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("ROLLBACK")
            raise
        self._depth -= 1
        if self._depth == 0:
            self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()


def _split_sql(sql: str) -> list[str]:
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
