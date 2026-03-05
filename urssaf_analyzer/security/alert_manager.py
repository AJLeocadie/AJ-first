"""Systeme d'alertes de securite conforme PSSI NormaCheck §6.3.

Detecte et signale en temps reel :
- Rupture de la chaine de preuve (integrite compromise)
- Tentatives de connexion echouees excessives (brute force)
- Erreurs de dechiffrement (tentative d'acces non autorise)
- Volumes anormaux (exfiltration ou injection de donnees)

Architecture :
- AlertManager centralise la detection et la notification
- Chaque type d'alerte a son propre seuil configurable
- Les alertes sont persistees dans un journal dedie (JSON Lines)
- Callbacks optionnels pour notification externe (webhook, email)

Conformite :
- ISO/IEC 27001:2022 §A.8.16 - Surveillance des activites
- RGPD art. 33 - Notification de violation dans les 72h
- PSSI NormaCheck §6.3 - Alertes de securite
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("urssaf_analyzer.alerts")


class AlertSeverity(str, Enum):
    """Niveaux de severite des alertes (ISO 27035)."""
    CRITIQUE = "critique"
    HAUTE = "haute"
    MOYENNE = "moyenne"
    INFO = "info"


class AlertType(str, Enum):
    """Types d'alertes de securite (PSSI §6.3)."""
    PROOF_CHAIN_RUPTURE = "rupture_chaine_preuve"
    LOGIN_BRUTE_FORCE = "tentatives_login_excessives"
    DECRYPTION_ERROR = "erreur_dechiffrement"
    ANOMALOUS_VOLUME = "volume_anormal"
    INTEGRITY_VIOLATION = "violation_integrite"
    UNAUTHORIZED_ACCESS = "acces_non_autorise"


class Alert:
    """Representation d'une alerte de securite."""

    def __init__(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        message: str,
        details: Optional[dict] = None,
        source_ip: Optional[str] = None,
        user_email: Optional[str] = None,
    ):
        self.alert_type = alert_type
        self.severity = severity
        self.message = message
        self.details = details or {}
        self.source_ip = source_ip
        self.user_email = user_email
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.acknowledged = False

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "type": self.alert_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
            "source_ip": self.source_ip,
            "user_email": self.user_email,
            "acknowledged": self.acknowledged,
        }


class LoginTracker:
    """Suivi des tentatives de connexion par IP/email.

    Detecte les attaques par brute force selon la regle :
    - Plus de `max_attempts` echecs en `window_seconds` secondes
      depuis une meme IP ou pour un meme email.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts_by_ip: dict[str, list[float]] = {}
        self._attempts_by_email: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def record_failure(self, ip: str = "", email: str = "") -> bool:
        """Enregistre un echec de connexion.

        Returns:
            True si le seuil d'alerte est atteint.
        """
        now = time.time()
        triggered = False

        with self._lock:
            if ip:
                attempts = self._attempts_by_ip.setdefault(ip, [])
                attempts.append(now)
                # Nettoyer les anciennes tentatives
                cutoff = now - self.window_seconds
                self._attempts_by_ip[ip] = [t for t in attempts if t > cutoff]
                if len(self._attempts_by_ip[ip]) >= self.max_attempts:
                    triggered = True

            if email:
                attempts = self._attempts_by_email.setdefault(email, [])
                attempts.append(now)
                cutoff = now - self.window_seconds
                self._attempts_by_email[email] = [t for t in attempts if t > cutoff]
                if len(self._attempts_by_email[email]) >= self.max_attempts:
                    triggered = True

        return triggered

    def record_success(self, ip: str = "", email: str = "") -> None:
        """Reinitialise les compteurs apres une connexion reussie."""
        with self._lock:
            if ip and ip in self._attempts_by_ip:
                del self._attempts_by_ip[ip]
            if email and email in self._attempts_by_email:
                del self._attempts_by_email[email]

    def get_failed_count(self, ip: str = "", email: str = "") -> int:
        """Retourne le nombre de tentatives echouees recentes."""
        now = time.time()
        cutoff = now - self.window_seconds
        count = 0
        with self._lock:
            if ip and ip in self._attempts_by_ip:
                count = max(count, len([t for t in self._attempts_by_ip[ip] if t > cutoff]))
            if email and email in self._attempts_by_email:
                count = max(count, len([t for t in self._attempts_by_email[email] if t > cutoff]))
        return count


class VolumeTracker:
    """Suivi des volumes d'operations pour detecter les anomalies.

    Detecte :
    - Upload massif (exfiltration inversee / injection)
    - Telechargements excessifs (exfiltration)
    - Nombre anormal de requetes d'analyse
    """

    def __init__(
        self,
        max_uploads_per_hour: int = 100,
        max_downloads_per_hour: int = 200,
        max_analyses_per_hour: int = 50,
    ):
        self.thresholds = {
            "upload": max_uploads_per_hour,
            "download": max_downloads_per_hour,
            "analyse": max_analyses_per_hour,
        }
        self._counters: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def record(self, operation: str, user_email: str = "") -> bool:
        """Enregistre une operation et verifie le seuil.

        Returns:
            True si le volume est anormal.
        """
        now = time.time()
        key = f"{operation}:{user_email}" if user_email else operation
        threshold = self.thresholds.get(operation, 100)
        one_hour_ago = now - 3600

        with self._lock:
            timestamps = self._counters.setdefault(key, [])
            timestamps.append(now)
            self._counters[key] = [t for t in timestamps if t > one_hour_ago]
            return len(self._counters[key]) > threshold

    def get_count(self, operation: str, user_email: str = "") -> int:
        """Retourne le nombre d'operations dans la derniere heure."""
        now = time.time()
        one_hour_ago = now - 3600
        key = f"{operation}:{user_email}" if user_email else operation
        with self._lock:
            timestamps = self._counters.get(key, [])
            return len([t for t in timestamps if t > one_hour_ago])


class AlertManager:
    """Gestionnaire central des alertes de securite.

    Centralise la detection, la persistance et la notification
    des evenements de securite conformement a la PSSI §6.3.
    """

    def __init__(
        self,
        alert_log_path: Path,
        on_alert: Optional[Callable[[Alert], None]] = None,
    ):
        self.alert_log_path = alert_log_path
        self.alert_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._on_alert = on_alert
        self._lock = threading.Lock()

        # Sous-systemes de detection
        self.login_tracker = LoginTracker()
        self.volume_tracker = VolumeTracker()

        # Compteur d'erreurs de dechiffrement
        self._decryption_errors: dict[str, list[float]] = {}
        self._decryption_threshold = 3  # alerter apres 3 erreurs en 10 min
        self._decryption_window = 600  # 10 minutes

    def _persist_alert(self, alert: Alert) -> None:
        """Persiste une alerte dans le journal JSON Lines."""
        line = json.dumps(alert.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            try:
                with open(self.alert_log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError as e:
                logger.error("Impossible de persister l'alerte: %s", e)

    def _emit(self, alert: Alert) -> Alert:
        """Persiste et notifie une alerte."""
        self._persist_alert(alert)
        logger.warning(
            "ALERTE [%s] %s: %s",
            alert.severity.value.upper(),
            alert.alert_type.value,
            alert.message,
        )
        if self._on_alert:
            try:
                self._on_alert(alert)
            except Exception as e:
                logger.error("Erreur dans le callback d'alerte: %s", e)
        return alert

    # --- Detection : Chaine de preuve ---

    def check_proof_chain(self, verification_result: dict) -> Optional[Alert]:
        """Verifie le resultat de ProofChain.verify() et alerte si rupture.

        Args:
            verification_result: Dict retourne par ProofChain.verify()

        Returns:
            Alert si rupture detectee, None sinon.
        """
        if verification_result.get("valid", True):
            return None

        alert = Alert(
            alert_type=AlertType.PROOF_CHAIN_RUPTURE,
            severity=AlertSeverity.CRITIQUE,
            message=(
                f"Rupture de la chaine de preuve detectee : "
                f"{verification_result.get('detail', 'raison inconnue')}"
            ),
            details={
                "entries_count": verification_result.get("entries", 0),
                "first_invalid": verification_result.get("first_invalid"),
                "detail": verification_result.get("detail", ""),
            },
        )
        return self._emit(alert)

    # --- Detection : Tentatives de connexion ---

    def on_login_failure(
        self, email: str, source_ip: str = ""
    ) -> Optional[Alert]:
        """Enregistre un echec de connexion et alerte si brute force.

        Returns:
            Alert si seuil atteint, None sinon.
        """
        triggered = self.login_tracker.record_failure(ip=source_ip, email=email)
        if not triggered:
            return None

        count = self.login_tracker.get_failed_count(ip=source_ip, email=email)
        alert = Alert(
            alert_type=AlertType.LOGIN_BRUTE_FORCE,
            severity=AlertSeverity.HAUTE,
            message=(
                f"{count} tentatives de connexion echouees en "
                f"{self.login_tracker.window_seconds}s "
                f"(IP={source_ip or 'inconnue'}, email={email})"
            ),
            details={
                "attempts": count,
                "window_seconds": self.login_tracker.window_seconds,
                "threshold": self.login_tracker.max_attempts,
            },
            source_ip=source_ip,
            user_email=email,
        )
        return self._emit(alert)

    def on_login_success(self, email: str, source_ip: str = "") -> None:
        """Reinitialise les compteurs apres connexion reussie."""
        self.login_tracker.record_success(ip=source_ip, email=email)

    # --- Detection : Erreurs de dechiffrement ---

    def on_decryption_error(
        self, context: str = "", source_ip: str = "", user_email: str = ""
    ) -> Optional[Alert]:
        """Enregistre une erreur de dechiffrement et alerte si excessif.

        Returns:
            Alert si seuil atteint, None sinon.
        """
        now = time.time()
        key = user_email or source_ip or "unknown"
        cutoff = now - self._decryption_window

        with self._lock:
            errors = self._decryption_errors.setdefault(key, [])
            errors.append(now)
            self._decryption_errors[key] = [t for t in errors if t > cutoff]
            count = len(self._decryption_errors[key])

        if count < self._decryption_threshold:
            return None

        alert = Alert(
            alert_type=AlertType.DECRYPTION_ERROR,
            severity=AlertSeverity.HAUTE,
            message=(
                f"{count} erreurs de dechiffrement en "
                f"{self._decryption_window}s pour {key} "
                f"(contexte: {context or 'non specifie'})"
            ),
            details={
                "count": count,
                "window_seconds": self._decryption_window,
                "threshold": self._decryption_threshold,
                "context": context,
            },
            source_ip=source_ip,
            user_email=user_email,
        )
        return self._emit(alert)

    # --- Detection : Volumes anormaux ---

    def on_operation(
        self, operation: str, user_email: str = ""
    ) -> Optional[Alert]:
        """Enregistre une operation et alerte si volume anormal.

        Args:
            operation: Type d'operation ("upload", "download", "analyse")
            user_email: Email de l'utilisateur

        Returns:
            Alert si volume anormal, None sinon.
        """
        triggered = self.volume_tracker.record(operation, user_email)
        if not triggered:
            return None

        count = self.volume_tracker.get_count(operation, user_email)
        threshold = self.volume_tracker.thresholds.get(operation, 100)
        alert = Alert(
            alert_type=AlertType.ANOMALOUS_VOLUME,
            severity=AlertSeverity.MOYENNE,
            message=(
                f"Volume anormal detecte : {count} {operation}(s) en 1h "
                f"(seuil: {threshold}) pour {user_email or 'anonyme'}"
            ),
            details={
                "operation": operation,
                "count": count,
                "threshold": threshold,
            },
            user_email=user_email,
        )
        return self._emit(alert)

    # --- Lecture des alertes ---

    def get_alerts(
        self,
        alert_type: Optional[AlertType] = None,
        severity: Optional[AlertSeverity] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Lit les alertes persistees, optionnellement filtrees."""
        if not self.alert_log_path.exists():
            return []

        alerts = []
        with open(self.alert_log_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if alert_type and entry.get("type") != alert_type.value:
                    continue
                if severity and entry.get("severity") != severity.value:
                    continue
                alerts.append(entry)

        return alerts[-limit:]

    def count_alerts(
        self,
        alert_type: Optional[AlertType] = None,
        since_hours: int = 24,
    ) -> int:
        """Compte les alertes recentes."""
        if not self.alert_log_path.exists():
            return 0

        cutoff = datetime.now(timezone.utc).timestamp() - (since_hours * 3600)
        count = 0

        with open(self.alert_log_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if alert_type and entry.get("type") != alert_type.value:
                    continue
                # Verifier le timestamp
                ts = entry.get("timestamp", "")
                try:
                    alert_time = datetime.fromisoformat(ts).timestamp()
                    if alert_time >= cutoff:
                        count += 1
                except (ValueError, TypeError):
                    count += 1  # Compter par defaut si timestamp invalide

        return count
