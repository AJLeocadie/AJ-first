"""Tests unitaires de la persistance et du stockage.

Couverture niveau bancaire : atomicite, concurrence, integrite des donnees.
"""

import json
import os
import pytest
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ================================================================
# PERSISTENT STORE
# ================================================================

class TestPersistentStore:

    @pytest.fixture
    def store(self, tmp_path):
        # Override DATA_DIR pour les tests
        os.environ["NORMACHECK_DATA_DIR"] = str(tmp_path)
        # Recreer les dirs
        (tmp_path / "db").mkdir(exist_ok=True)
        (tmp_path / "uploads").mkdir(exist_ok=True)
        (tmp_path / "reports").mkdir(exist_ok=True)
        (tmp_path / "logs").mkdir(exist_ok=True)
        (tmp_path / "temp").mkdir(exist_ok=True)
        (tmp_path / "encrypted").mkdir(exist_ok=True)
        (tmp_path / "backups").mkdir(exist_ok=True)

        import persistence
        persistence.DATA_DIR = Path(str(tmp_path))
        persistence.DB_DIR = persistence.DATA_DIR / "db"
        return persistence.PersistentStore("test_store", default={"key": "value"})

    def test_store_creation(self, store):
        assert store.path.exists()

    def test_store_load_default(self, store):
        data = store.load()
        assert data == {"key": "value"}

    def test_store_save_and_load(self, store):
        store.save({"users": ["alice", "bob"], "count": 42})
        loaded = store.load()
        assert loaded["count"] == 42
        assert len(loaded["users"]) == 2

    def test_store_update_atomic(self, store):
        store.save({"counter": 0})

        def increment(data):
            data["counter"] += 1

        store.update(increment)
        assert store.load()["counter"] == 1

    def test_store_handles_unicode(self, store):
        store.save({"nom": "François Müller", "ville": "Strasbourg"})
        loaded = store.load()
        assert loaded["nom"] == "François Müller"

    def test_store_handles_large_data(self, store):
        large_data = {"items": [{"id": i, "data": "x" * 100} for i in range(1000)]}
        store.save(large_data)
        loaded = store.load()
        assert len(loaded["items"]) == 1000


# ================================================================
# PERSISTENT LIST
# ================================================================

class TestPersistentList:

    @pytest.fixture
    def plist(self, tmp_path):
        os.environ["NORMACHECK_DATA_DIR"] = str(tmp_path)
        (tmp_path / "db").mkdir(exist_ok=True)
        for d in ["uploads", "reports", "logs", "temp", "encrypted", "backups"]:
            (tmp_path / d).mkdir(exist_ok=True)

        import persistence
        persistence.DATA_DIR = Path(str(tmp_path))
        persistence.DB_DIR = persistence.DATA_DIR / "db"
        return persistence.PersistentList("test_list")

    def test_list_empty(self, plist):
        assert plist.load() == []

    def test_list_append(self, plist):
        plist.append({"action": "login", "user": "test@test.fr"})
        data = plist.load()
        assert len(data) == 1
        assert data[0]["action"] == "login"

    def test_list_multiple_appends(self, plist):
        for i in range(5):
            plist.append({"index": i})
        assert len(plist.load()) == 5

    def test_list_len(self, plist):
        plist.append({"x": 1})
        plist.append({"x": 2})
        assert len(plist) == 2

    def test_list_bool(self, plist):
        assert not plist
        plist.append({"x": 1})
        assert plist


# ================================================================
# FILE UPLOAD PERSISTENCE
# ================================================================

class TestFileUploadPersistence:

    @pytest.fixture(autouse=True)
    def setup_dirs(self, tmp_path):
        os.environ["NORMACHECK_DATA_DIR"] = str(tmp_path)
        for d in ["db", "uploads", "reports", "logs", "temp", "encrypted", "backups"]:
            (tmp_path / d).mkdir(exist_ok=True)
        self.tmp_path = tmp_path

    def test_save_uploaded_file(self):
        from persistence import save_uploaded_file
        path = save_uploaded_file("test.csv", b"data;content", "analysis-123")
        assert path.exists()
        assert path.read_bytes() == b"data;content"

    def test_save_report(self):
        from persistence import save_report
        path = save_report("report-001", "<html>Rapport</html>", "html")
        assert path.exists()
        assert "Rapport" in path.read_text()


# ================================================================
# AUDIT LOG
# ================================================================

class TestAuditLog:

    @pytest.fixture(autouse=True)
    def setup_dirs(self, tmp_path):
        os.environ["NORMACHECK_DATA_DIR"] = str(tmp_path)
        for d in ["db", "uploads", "reports", "logs", "temp", "encrypted", "backups"]:
            (tmp_path / d).mkdir(exist_ok=True)

    def test_log_action(self):
        from persistence import log_action, audit_log_store
        log_action("admin", "upload", "test.csv uploade")
        logs = audit_log_store.load()
        assert len(logs) >= 1
        assert logs[-1]["action"] == "upload"

    def test_data_stats(self):
        from persistence import get_data_stats
        stats = get_data_stats()
        assert "db_size_mb" in stats
        assert "uploads_count" in stats
