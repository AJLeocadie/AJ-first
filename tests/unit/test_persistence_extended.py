"""Tests etendus de persistence et auth pour combler les gaps de couverture."""

import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from persistence import PersistentStore, PersistentList


class TestPersistentStoreExtended:
    """Tests etendus du PersistentStore."""

    def test_update_atomic(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        store = PersistentStore("test_update", default={"count": 0})
        store.update(lambda data: data.update({"count": 1}))
        data = store.load()
        assert data["count"] == 1

    def test_update_multiple(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        store = PersistentStore("test_multi_update", default={"count": 0})
        for i in range(5):
            store.update(lambda data: data.update({"count": data["count"] + 1}))
        data = store.load()
        assert data["count"] == 5

    def test_corrupt_json_returns_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        store = PersistentStore("test_corrupt", default={"fallback": True})
        # Corrupt the file
        store.path.write_text("{invalid json")
        data = store.load()
        assert data == {"fallback": True}

    def test_save_complex_types(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        store = PersistentStore("test_complex_types", default={})
        from datetime import datetime
        store.save({"timestamp": datetime.now(), "items": [1, 2, 3]})
        data = store.load()
        assert "timestamp" in data
        assert data["items"] == [1, 2, 3]


class TestPersistentListExtended:
    """Tests etendus de la PersistentList."""

    def test_load_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        plist = PersistentList("test_empty_list")
        assert plist.load() == []

    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        plist = PersistentList("test_save_load")
        plist.save(["a", "b", "c"])
        assert plist.load() == ["a", "b", "c"]

    def test_multiple_appends(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        plist = PersistentList("test_multi_append")
        plist.append("item1")
        plist.append("item2")
        plist.append("item3")
        assert len(plist) == 3
        data = plist.load()
        assert data == ["item1", "item2", "item3"]
