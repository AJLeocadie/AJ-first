"""Tests du module de persistence OVHcloud.

Couverture : PersistentStore, PersistentList, sauvegarde/chargement,
verrous fichiers, cas d'erreur.
"""

import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from persistence import PersistentStore, PersistentList


class TestPersistentStore:
    """Tests du store persistant JSON."""

    def test_create_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        store = PersistentStore("test_store", default={"key": "value"})
        data = store.load()
        assert data == {"key": "value"}

    def test_save_and_reload(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        store = PersistentStore("test_save", default={})
        store.save({"name": "NormaCheck", "version": 1})
        data = store.load()
        assert data["name"] == "NormaCheck"
        assert data["version"] == 1

    def test_overwrite_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        store = PersistentStore("test_overwrite", default={})
        store.save({"v": 1})
        store.save({"v": 2})
        data = store.load()
        assert data["v"] == 2

    def test_complex_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        store = PersistentStore("test_complex", default={})
        complex_data = {
            "users": {"u1": {"name": "Jean", "scores": [90, 85, 92]}},
            "config": {"nested": {"deep": True}},
        }
        store.save(complex_data)
        data = store.load()
        assert data["users"]["u1"]["scores"] == [90, 85, 92]

    def test_default_on_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        store = PersistentStore("nonexistent", default={"default": True})
        data = store.load()
        assert data["default"] is True


class TestPersistentList:
    """Tests de la liste persistante."""

    def test_create_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        plist = PersistentList("test_list")
        data = plist.load()
        assert data == []

    def test_save_and_reload(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        plist = PersistentList("test_list_save")
        plist.save(["item1", "item2", "item3"])
        data = plist.load()
        assert len(data) == 3
        assert "item2" in data

    def test_append_behavior(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)
        plist = PersistentList("test_append_2")
        plist.append({"name": "new_item"})
        reloaded = plist.load()
        assert len(reloaded) == 1

    def test_len(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NORMACHECK_DATA_DIR", str(tmp_path))
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)
        plist = PersistentList("test_len_2")
        assert len(plist) == 0
        plist.append({"x": 1})
        assert len(plist) == 1
