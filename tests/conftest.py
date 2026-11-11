import pytest

from ranobe.storage.db import Database
from ranobe.storage.repositories import Repositories


@pytest.fixture
def repos(tmp_path):
    db = Database(tmp_path / "test.db")
    yield Repositories(db)
    db.close()
