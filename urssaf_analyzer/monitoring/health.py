"""Health checks, alertes et metriques pour URSSAF Analyzer.

Ce module fournit trois classes principales :
- HealthCheck : diagnostique l'etat de sante de chaque sous-systeme
- AlertManager : centralise les alertes applicatives par severite
- MetricsCollector : collecte les durees d'analyse et les erreurs

Usage::

    from urssaf_analyzer.monitoring import HealthCheck, AlertManager, MetricsCollector

    hc = HealthCheck()
    status = hc.check_all()

    alerts = AlertManager()
    alerts.add_alert("warning", "Bareme 2026 manquant", "config")

    metrics = MetricsCollector()
    metrics.record_analysis_duration(1.23)
"""

import logging
import os
import platform
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HealthCheck
# ---------------------------------------------------------------------------

class HealthCheck:
    """Verification de l'etat de sante des sous-systemes."""

    def check_all(self) -> dict:
        """Execute tous les health checks et retourne un rapport global.

        Returns:
            dict avec le statut de chaque sous-systeme et un statut global.
        """
        logger.info("Execution de tous les health checks")

        baremes_ok = self.check_baremes_loaded()
        coherence_issues = self.check_constants_coherence()
        parsers = self.check_parsers_available()
        system_info = self.get_system_info()

        all_ok = baremes_ok and len(coherence_issues) == 0

        return {
            "status": "healthy" if all_ok else "degraded",
            "timestamp": datetime.now().isoformat(),
            "checks": {
                "baremes_loaded": baremes_ok,
                "constants_coherence": {
                    "ok": len(coherence_issues) == 0,
                    "issues": coherence_issues,
                },
                "parsers": parsers,
            },
            "system": system_info,
        }

    # -- Sous-systemes individuels ------------------------------------------

    def check_database(self, db_path: str) -> bool:
        """Verifie que la base de donnees est accessible et valide.

        Args:
            db_path: chemin vers le fichier SQLite.

        Returns:
            True si la base est accessible, False sinon.
        """
        db_file = Path(db_path)
        if not db_file.exists():
            logger.warning("Base de donnees introuvable : %s", db_path)
            return False

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            conn.close()
            logger.debug("Base de donnees OK : %s", db_path)
            return True
        except Exception as exc:
            logger.error("Erreur d'acces a la base de donnees : %s", exc)
            return False

    def check_baremes_loaded(self) -> bool:
        """Verifie que BAREMES_PAR_ANNEE contient l'annee en cours.

        Returns:
            True si le bareme de l'annee courante est present.
        """
        try:
            from urssaf_analyzer.veille.urssaf_client import BAREMES_PAR_ANNEE

            current_year = datetime.now().year
            if current_year in BAREMES_PAR_ANNEE:
                logger.debug("Bareme %d present dans BAREMES_PAR_ANNEE", current_year)
                return True
            else:
                logger.warning(
                    "Bareme %d absent de BAREMES_PAR_ANNEE (annees disponibles : %s)",
                    current_year,
                    sorted(BAREMES_PAR_ANNEE.keys()),
                )
                return False
        except ImportError as exc:
            logger.error("Impossible d'importer BAREMES_PAR_ANNEE : %s", exc)
            return False

    def check_constants_coherence(self) -> list:
        """Valide la coherence entre TAUX_COTISATIONS_2026 et BAREMES_PAR_ANNEE[2026].

        Compare les valeurs cles (pass_mensuel, smic_mensuel, taux de vieillesse, etc.)
        entre les deux sources de reference.

        Returns:
            Liste de messages decrivant les incoherences detectees.
        """
        issues: list[str] = []

        try:
            from urssaf_analyzer.config.constants import (
                TAUX_COTISATIONS_2026,
                ContributionType,
                PASS_MENSUEL,
                SMIC_MENSUEL_BRUT,
            )
            from urssaf_analyzer.veille.urssaf_client import BAREMES_PAR_ANNEE
        except ImportError as exc:
            issues.append(f"Impossible d'importer les modules de reference : {exc}")
            return issues

        baremes_2026 = BAREMES_PAR_ANNEE.get(2026)
        if baremes_2026 is None:
            issues.append("Bareme 2026 absent de BAREMES_PAR_ANNEE")
            return issues

        # --- PASS mensuel ---
        if float(PASS_MENSUEL) != baremes_2026.get("pass_mensuel", 0):
            issues.append(
                f"PASS_MENSUEL diverge : constants={PASS_MENSUEL}, "
                f"baremes={baremes_2026.get('pass_mensuel')}"
            )

        # --- SMIC mensuel ---
        if float(SMIC_MENSUEL_BRUT) != baremes_2026.get("smic_mensuel", 0):
            issues.append(
                f"SMIC_MENSUEL_BRUT diverge : constants={SMIC_MENSUEL_BRUT}, "
                f"baremes={baremes_2026.get('smic_mensuel')}"
            )

        # --- Taux vieillesse plafonnee ---
        vieillesse_p = TAUX_COTISATIONS_2026.get(ContributionType.VIEILLESSE_PLAFONNEE, {})
        if vieillesse_p:
            patronal = float(vieillesse_p.get("patronal", 0))
            salarial = float(vieillesse_p.get("salarial", 0))
            b_patronal = baremes_2026.get("taux_vieillesse_plafonnee_patronal", 0)
            b_salarial = baremes_2026.get("taux_vieillesse_plafonnee_salarial", 0)
            if patronal != b_patronal:
                issues.append(
                    f"Vieillesse plafonnee patronal diverge : constants={patronal}, "
                    f"baremes={b_patronal}"
                )
            if salarial != b_salarial:
                issues.append(
                    f"Vieillesse plafonnee salarial diverge : constants={salarial}, "
                    f"baremes={b_salarial}"
                )

        # --- Taux vieillesse deplafonnee ---
        vieillesse_d = TAUX_COTISATIONS_2026.get(ContributionType.VIEILLESSE_DEPLAFONNEE, {})
        if vieillesse_d:
            patronal = float(vieillesse_d.get("patronal", 0))
            salarial = float(vieillesse_d.get("salarial", 0))
            b_patronal = baremes_2026.get("taux_vieillesse_deplafonnee_patronal", 0)
            b_salarial = baremes_2026.get("taux_vieillesse_deplafonnee_salarial", 0)
            if patronal != b_patronal:
                issues.append(
                    f"Vieillesse deplafonnee patronal diverge : constants={patronal}, "
                    f"baremes={b_patronal}"
                )
            if salarial != b_salarial:
                issues.append(
                    f"Vieillesse deplafonnee salarial diverge : constants={salarial}, "
                    f"baremes={b_salarial}"
                )

        # --- Taux maladie ---
        maladie = TAUX_COTISATIONS_2026.get(ContributionType.MALADIE, {})
        if maladie:
            patronal = float(maladie.get("patronal", 0))
            patronal_reduit = float(maladie.get("patronal_reduit", 0))
            b_patronal = baremes_2026.get("taux_maladie_patronal", 0)
            b_reduit = baremes_2026.get("taux_maladie_patronal_reduit", 0)
            if patronal != b_patronal:
                issues.append(
                    f"Maladie patronal diverge : constants={patronal}, "
                    f"baremes={b_patronal}"
                )
            if patronal_reduit != b_reduit:
                issues.append(
                    f"Maladie patronal reduit diverge : constants={patronal_reduit}, "
                    f"baremes={b_reduit}"
                )

        # --- Taux allocations familiales ---
        af = TAUX_COTISATIONS_2026.get(ContributionType.ALLOCATIONS_FAMILIALES, {})
        if af:
            patronal = float(af.get("patronal", 0))
            b_patronal = baremes_2026.get("taux_af_patronal", 0)
            if patronal != b_patronal:
                issues.append(
                    f"Allocations familiales patronal diverge : constants={patronal}, "
                    f"baremes={b_patronal}"
                )

        # --- CSG / CRDS (stockees avec cle "taux" et non "salarial") ---
        csg_ded = TAUX_COTISATIONS_2026.get(ContributionType.CSG_DEDUCTIBLE, {})
        if csg_ded:
            taux = float(csg_ded.get("taux", csg_ded.get("salarial", 0)))
            b_taux = baremes_2026.get("taux_csg_deductible", 0)
            if taux != b_taux:
                issues.append(
                    f"CSG deductible diverge : constants={taux}, baremes={b_taux}"
                )

        csg_nded = TAUX_COTISATIONS_2026.get(ContributionType.CSG_NON_DEDUCTIBLE, {})
        if csg_nded:
            taux = float(csg_nded.get("taux", csg_nded.get("salarial", 0)))
            b_taux = baremes_2026.get("taux_csg_non_deductible", 0)
            if taux != b_taux:
                issues.append(
                    f"CSG non deductible diverge : constants={taux}, baremes={b_taux}"
                )

        crds = TAUX_COTISATIONS_2026.get(ContributionType.CRDS, {})
        if crds:
            taux = float(crds.get("taux", crds.get("salarial", 0)))
            b_taux = baremes_2026.get("taux_crds", 0)
            if taux != b_taux:
                issues.append(
                    f"CRDS diverge : constants={taux}, baremes={b_taux}"
                )

        if issues:
            logger.warning(
                "Incoherences detectees entre constants et baremes : %s", issues
            )
        else:
            logger.debug("Coherence constants/baremes OK pour 2026")

        return issues

    def check_parsers_available(self) -> dict:
        """Verifie la disponibilite de chaque parser.

        Returns:
            dict de nom_parser -> bool indiquant si le parser est importable.
        """
        parsers = {
            "PDFParser": "urssaf_analyzer.parsers.pdf_parser",
            "ExcelParser": "urssaf_analyzer.parsers.excel_parser",
            "CSVParser": "urssaf_analyzer.parsers.csv_parser",
            "DocxParser": "urssaf_analyzer.parsers.docx_parser",
            "XMLParser": "urssaf_analyzer.parsers.xml_parser",
            "TextParser": "urssaf_analyzer.parsers.text_parser",
            "DSNParser": "urssaf_analyzer.parsers.dsn_parser",
            "FECParser": "urssaf_analyzer.parsers.fec_parser",
            "ImageParser": "urssaf_analyzer.parsers.image_parser",
            "FixedWidthParser": "urssaf_analyzer.parsers.fixedwidth_parser",
        }

        result = {}
        for class_name, module_path in parsers.items():
            try:
                module = __import__(module_path, fromlist=[class_name])
                getattr(module, class_name)
                result[class_name] = True
                logger.debug("Parser disponible : %s", class_name)
            except (ImportError, AttributeError) as exc:
                result[class_name] = False
                logger.warning("Parser indisponible : %s (%s)", class_name, exc)

        return result

    def check_disk_space(self, path: str = ".") -> dict:
        """Retourne l'espace disque disponible et total pour le chemin donne.

        Args:
            path: chemin du systeme de fichiers a verifier.

        Returns:
            dict avec cles 'free_bytes', 'total_bytes', 'free_gb', 'total_gb',
            'usage_percent'.
        """
        try:
            stat = os.statvfs(path)
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bavail * stat.f_frsize
            usage_percent = ((total - free) / total * 100) if total > 0 else 0.0

            return {
                "free_bytes": free,
                "total_bytes": total,
                "free_gb": round(free / (1024 ** 3), 2),
                "total_gb": round(total / (1024 ** 3), 2),
                "usage_percent": round(usage_percent, 1),
                "path": str(Path(path).resolve()),
            }
        except OSError as exc:
            logger.error("Impossible de lire l'espace disque pour %s : %s", path, exc)
            return {
                "free_bytes": 0,
                "total_bytes": 0,
                "free_gb": 0.0,
                "total_gb": 0.0,
                "usage_percent": 0.0,
                "path": path,
                "error": str(exc),
            }

    def get_system_info(self) -> dict:
        """Retourne les informations systeme de l'environnement d'execution.

        Returns:
            dict avec version Python, plateforme, memoire, etc.
        """
        info = {
            "python_version": sys.version,
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "hostname": platform.node(),
            "pid": os.getpid(),
        }

        # Memoire via /proc/meminfo (Linux)
        try:
            meminfo_path = Path("/proc/meminfo")
            if meminfo_path.exists():
                meminfo = meminfo_path.read_text()
                mem_total = None
                mem_available = None
                for line in meminfo.splitlines():
                    if line.startswith("MemTotal:"):
                        mem_total = int(line.split()[1]) * 1024  # kB -> bytes
                    elif line.startswith("MemAvailable:"):
                        mem_available = int(line.split()[1]) * 1024
                if mem_total is not None:
                    info["memory_total_gb"] = round(mem_total / (1024 ** 3), 2)
                if mem_available is not None:
                    info["memory_available_gb"] = round(mem_available / (1024 ** 3), 2)
        except Exception:
            pass

        return info


# ---------------------------------------------------------------------------
# AlertManager
# ---------------------------------------------------------------------------

class AlertManager:
    """Gestionnaire d'alertes centralise.

    Stocke les alertes en memoire avec severite, message, categorie et horodatage.
    """

    SEVERITIES = ("info", "warning", "error", "critical")

    def __init__(self):
        self._alerts: list[dict] = []

    def add_alert(self, severity: str, message: str, category: str = "general") -> None:
        """Ajoute une alerte.

        Args:
            severity: niveau de severite (info, warning, error, critical).
            message: description de l'alerte.
            category: categorie fonctionnelle (config, parsing, database, etc.).
        """
        if severity not in self.SEVERITIES:
            logger.warning(
                "Severite inconnue '%s', utilisation de 'warning' par defaut", severity
            )
            severity = "warning"

        alert = {
            "timestamp": datetime.now().isoformat(),
            "severity": severity,
            "message": message,
            "category": category,
        }
        self._alerts.append(alert)
        logger.log(
            self._severity_to_level(severity),
            "[%s][%s] %s",
            severity.upper(),
            category,
            message,
        )

    def get_alerts(
        self,
        since: Optional[datetime] = None,
        severity: Optional[str] = None,
    ) -> list:
        """Retourne les alertes filtrees.

        Args:
            since: ne retourner que les alertes apres cette date.
            severity: filtrer par niveau de severite.

        Returns:
            Liste d'alertes correspondant aux criteres.
        """
        result = self._alerts

        if since is not None:
            since_iso = since.isoformat()
            result = [a for a in result if a["timestamp"] >= since_iso]

        if severity is not None:
            result = [a for a in result if a["severity"] == severity]

        return list(result)

    def clear_alerts(self, before: Optional[datetime] = None) -> int:
        """Supprime les alertes.

        Args:
            before: si fourni, ne supprime que les alertes anterieures a cette date.
                    Si None, supprime toutes les alertes.

        Returns:
            Nombre d'alertes supprimees.
        """
        if before is None:
            count = len(self._alerts)
            self._alerts.clear()
            logger.info("Toutes les alertes supprimees (%d)", count)
            return count

        before_iso = before.isoformat()
        original_count = len(self._alerts)
        self._alerts = [a for a in self._alerts if a["timestamp"] >= before_iso]
        removed = original_count - len(self._alerts)
        logger.info("%d alertes supprimees (avant %s)", removed, before_iso)
        return removed

    def get_alert_summary(self) -> dict:
        """Retourne un resume du nombre d'alertes par severite.

        Returns:
            dict avec cles = severites, valeurs = nombre d'alertes.
        """
        summary = {sev: 0 for sev in self.SEVERITIES}
        summary["total"] = len(self._alerts)
        for alert in self._alerts:
            sev = alert["severity"]
            if sev in summary:
                summary[sev] += 1
        return summary

    @staticmethod
    def _severity_to_level(severity: str) -> int:
        """Convertit une severite en niveau de logging Python."""
        mapping = {
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }
        return mapping.get(severity, logging.WARNING)


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Collecteur de metriques de performance.

    Enregistre les durees d'analyse, de parsing et les erreurs survenues.
    """

    def __init__(self):
        self._analysis_durations: list[float] = []
        self._parsing_durations: dict[str, list[float]] = {}
        self._errors: list[dict] = []

    def record_analysis_duration(self, seconds: float) -> None:
        """Enregistre la duree d'une analyse complete.

        Args:
            seconds: duree en secondes.
        """
        self._analysis_durations.append(seconds)
        logger.debug("Duree d'analyse enregistree : %.3f s", seconds)

    def record_parsing_duration(self, format_name: str, seconds: float) -> None:
        """Enregistre la duree de parsing pour un format donne.

        Args:
            format_name: nom du format (pdf, excel, csv, etc.).
            seconds: duree en secondes.
        """
        if format_name not in self._parsing_durations:
            self._parsing_durations[format_name] = []
        self._parsing_durations[format_name].append(seconds)
        logger.debug("Duree de parsing '%s' enregistree : %.3f s", format_name, seconds)

    def record_error(self, module: str, error_type: str) -> None:
        """Enregistre une erreur survenue dans un module.

        Args:
            module: nom du module source de l'erreur.
            error_type: type ou classe de l'erreur.
        """
        self._errors.append({
            "timestamp": datetime.now().isoformat(),
            "module": module,
            "error_type": error_type,
        })
        logger.debug("Erreur enregistree : module=%s, type=%s", module, error_type)

    def get_metrics_summary(self) -> dict:
        """Retourne un resume agrege de toutes les metriques collectees.

        Returns:
            dict contenant les statistiques d'analyse, de parsing et d'erreurs.
        """
        summary: dict = {
            "analysis": self._compute_stats(self._analysis_durations),
            "parsing": {},
            "errors": {
                "total": len(self._errors),
                "by_module": {},
                "by_type": {},
            },
        }

        # Statistiques de parsing par format
        for fmt, durations in self._parsing_durations.items():
            summary["parsing"][fmt] = self._compute_stats(durations)

        # Repartition des erreurs
        for err in self._errors:
            mod = err["module"]
            etype = err["error_type"]
            summary["errors"]["by_module"][mod] = (
                summary["errors"]["by_module"].get(mod, 0) + 1
            )
            summary["errors"]["by_type"][etype] = (
                summary["errors"]["by_type"].get(etype, 0) + 1
            )

        return summary

    @staticmethod
    def _compute_stats(values: list[float]) -> dict:
        """Calcule les statistiques descriptives d'une liste de valeurs.

        Args:
            values: liste de valeurs numeriques.

        Returns:
            dict avec count, total, mean, min, max.
        """
        if not values:
            return {"count": 0, "total": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0}

        return {
            "count": len(values),
            "total": round(sum(values), 3),
            "mean": round(sum(values) / len(values), 3),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
        }
