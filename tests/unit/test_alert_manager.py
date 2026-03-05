"""Tests du systeme d'alertes de securite (PSSI §6.3).

Couvre les 4 types d'alertes requis :
1. Rupture de la chaine de preuve
2. Tentatives de connexion echouees excessives (brute force)
3. Erreurs de dechiffrement
4. Volumes anormaux d'operations
"""

import json
import time
import pytest
from pathlib import Path

from urssaf_analyzer.security.alert_manager import (
    Alert,
    AlertManager,
    AlertSeverity,
    AlertType,
    LoginTracker,
    VolumeTracker,
)


@pytest.fixture
def alert_log(tmp_path):
    return tmp_path / "alerts.jsonl"


@pytest.fixture
def manager(alert_log):
    return AlertManager(alert_log_path=alert_log)


# === Tests Alert ===

class TestAlert:
    def test_alert_creation(self):
        alert = Alert(
            alert_type=AlertType.PROOF_CHAIN_RUPTURE,
            severity=AlertSeverity.CRITIQUE,
            message="Test rupture",
        )
        assert alert.alert_type == AlertType.PROOF_CHAIN_RUPTURE
        assert alert.severity == AlertSeverity.CRITIQUE
        assert alert.message == "Test rupture"
        assert alert.acknowledged is False

    def test_alert_to_dict(self):
        alert = Alert(
            alert_type=AlertType.LOGIN_BRUTE_FORCE,
            severity=AlertSeverity.HAUTE,
            message="5 echecs",
            source_ip="192.168.1.1",
            user_email="test@example.com",
        )
        d = alert.to_dict()
        assert d["type"] == "tentatives_login_excessives"
        assert d["severity"] == "haute"
        assert d["source_ip"] == "192.168.1.1"
        assert d["user_email"] == "test@example.com"
        assert "timestamp" in d

    def test_alert_with_details(self):
        alert = Alert(
            alert_type=AlertType.DECRYPTION_ERROR,
            severity=AlertSeverity.HAUTE,
            message="Erreur",
            details={"context": "test_file.enc", "count": 3},
        )
        d = alert.to_dict()
        assert d["details"]["context"] == "test_file.enc"
        assert d["details"]["count"] == 3


# === Tests LoginTracker ===

class TestLoginTracker:
    def test_no_alert_under_threshold(self):
        tracker = LoginTracker(max_attempts=5, window_seconds=300)
        for _ in range(4):
            triggered = tracker.record_failure(ip="1.2.3.4")
        assert not triggered

    def test_alert_at_threshold(self):
        tracker = LoginTracker(max_attempts=3, window_seconds=300)
        for _ in range(2):
            tracker.record_failure(ip="1.2.3.4")
        triggered = tracker.record_failure(ip="1.2.3.4")
        assert triggered

    def test_alert_by_email(self):
        tracker = LoginTracker(max_attempts=3, window_seconds=300)
        for _ in range(2):
            tracker.record_failure(email="user@test.com")
        triggered = tracker.record_failure(email="user@test.com")
        assert triggered

    def test_reset_after_success(self):
        tracker = LoginTracker(max_attempts=3, window_seconds=300)
        for _ in range(2):
            tracker.record_failure(ip="1.2.3.4")
        tracker.record_success(ip="1.2.3.4")
        triggered = tracker.record_failure(ip="1.2.3.4")
        assert not triggered

    def test_different_ips_independent(self):
        tracker = LoginTracker(max_attempts=3, window_seconds=300)
        for _ in range(2):
            tracker.record_failure(ip="1.2.3.4")
        triggered = tracker.record_failure(ip="5.6.7.8")
        assert not triggered

    def test_get_failed_count(self):
        tracker = LoginTracker(max_attempts=5, window_seconds=300)
        for _ in range(3):
            tracker.record_failure(ip="1.2.3.4")
        assert tracker.get_failed_count(ip="1.2.3.4") == 3
        assert tracker.get_failed_count(ip="other") == 0


# === Tests VolumeTracker ===

class TestVolumeTracker:
    def test_no_alert_under_threshold(self):
        tracker = VolumeTracker(max_uploads_per_hour=5)
        for _ in range(4):
            triggered = tracker.record("upload")
        assert not triggered

    def test_alert_over_threshold(self):
        tracker = VolumeTracker(max_uploads_per_hour=3)
        for _ in range(3):
            tracker.record("upload")
        triggered = tracker.record("upload")
        assert triggered

    def test_per_user_tracking(self):
        tracker = VolumeTracker(max_uploads_per_hour=3)
        for _ in range(3):
            tracker.record("upload", user_email="user1@test.com")
        # Different user should not trigger
        triggered = tracker.record("upload", user_email="user2@test.com")
        assert not triggered

    def test_get_count(self):
        tracker = VolumeTracker()
        for _ in range(5):
            tracker.record("download")
        assert tracker.get_count("download") == 5


# === Tests AlertManager ===

class TestAlertManagerProofChain:
    def test_no_alert_on_valid_chain(self, manager):
        result = manager.check_proof_chain({"valid": True, "entries": 10})
        assert result is None

    def test_alert_on_chain_rupture(self, manager):
        result = manager.check_proof_chain({
            "valid": False,
            "entries": 5,
            "first_invalid": 3,
            "detail": "Ligne 3: rupture de chainage",
        })
        assert result is not None
        assert result.alert_type == AlertType.PROOF_CHAIN_RUPTURE
        assert result.severity == AlertSeverity.CRITIQUE
        assert "rupture" in result.message.lower()

    def test_chain_rupture_persisted(self, manager, alert_log):
        manager.check_proof_chain({
            "valid": False, "entries": 1, "first_invalid": 1,
            "detail": "hash invalide",
        })
        assert alert_log.exists()
        with open(alert_log) as f:
            entry = json.loads(f.readline())
        assert entry["type"] == "rupture_chaine_preuve"
        assert entry["severity"] == "critique"


class TestAlertManagerLogin:
    def test_no_alert_on_few_failures(self, manager):
        for _ in range(3):
            result = manager.on_login_failure("user@test.com", "1.2.3.4")
        assert result is None

    def test_alert_on_brute_force(self, manager):
        result = None
        for _ in range(6):
            result = manager.on_login_failure("user@test.com", "1.2.3.4")
        assert result is not None
        assert result.alert_type == AlertType.LOGIN_BRUTE_FORCE
        assert result.severity == AlertSeverity.HAUTE

    def test_login_success_resets(self, manager):
        for _ in range(4):
            manager.on_login_failure("user@test.com", "1.2.3.4")
        manager.on_login_success("user@test.com", "1.2.3.4")
        result = manager.on_login_failure("user@test.com", "1.2.3.4")
        assert result is None


class TestAlertManagerDecryption:
    def test_no_alert_on_single_error(self, manager):
        result = manager.on_decryption_error("fichier.enc", user_email="u@t.com")
        assert result is None

    def test_alert_on_repeated_errors(self, manager):
        result = None
        for _ in range(4):
            result = manager.on_decryption_error("fichier.enc", user_email="u@t.com")
        assert result is not None
        assert result.alert_type == AlertType.DECRYPTION_ERROR
        assert result.severity == AlertSeverity.HAUTE


class TestAlertManagerVolume:
    def test_no_alert_normal_volume(self, manager):
        for _ in range(5):
            result = manager.on_operation("upload", "u@t.com")
        assert result is None

    def test_alert_excessive_volume(self, manager):
        manager.volume_tracker = VolumeTracker(max_uploads_per_hour=3)
        result = None
        for _ in range(5):
            result = manager.on_operation("upload", "u@t.com")
        assert result is not None
        assert result.alert_type == AlertType.ANOMALOUS_VOLUME


class TestAlertManagerPersistence:
    def test_get_alerts_empty(self, manager):
        alerts = manager.get_alerts()
        assert alerts == []

    def test_get_alerts_with_filter(self, manager):
        manager.check_proof_chain({"valid": False, "entries": 1,
                                    "first_invalid": 1, "detail": "test"})
        # Add a login alert too
        manager.login_tracker = LoginTracker(max_attempts=1, window_seconds=300)
        manager.on_login_failure("u@t.com", "1.2.3.4")

        all_alerts = manager.get_alerts()
        assert len(all_alerts) == 2

        proof_only = manager.get_alerts(alert_type=AlertType.PROOF_CHAIN_RUPTURE)
        assert len(proof_only) == 1
        assert proof_only[0]["type"] == "rupture_chaine_preuve"

    def test_count_alerts(self, manager):
        manager.check_proof_chain({"valid": False, "entries": 1,
                                    "first_invalid": 1, "detail": "test"})
        assert manager.count_alerts() == 1
        assert manager.count_alerts(alert_type=AlertType.PROOF_CHAIN_RUPTURE) == 1
        assert manager.count_alerts(alert_type=AlertType.LOGIN_BRUTE_FORCE) == 0

    def test_callback_invoked(self, alert_log):
        received = []
        mgr = AlertManager(alert_log_path=alert_log, on_alert=lambda a: received.append(a))
        mgr.check_proof_chain({"valid": False, "entries": 1,
                                "first_invalid": 1, "detail": "test"})
        assert len(received) == 1
        assert received[0].alert_type == AlertType.PROOF_CHAIN_RUPTURE
