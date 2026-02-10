"""Configuration globale de l'application."""

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class SecurityConfig:
    """Configuration securite."""
    encryption_algorithm: str = "AES-256-GCM"
    key_derivation: str = "pbkdf2"
    pbkdf2_iterations: int = 100_000
    salt_length: int = 32
    iv_length: int = 16
    secure_delete_passes: int = 3


@dataclass
class AnalysisConfig:
    """Configuration analyse."""
    annee_reference: int = 2026
    tolerance_montant: float = 0.01
    tolerance_taux: float = 0.0001
    seuil_nombres_ronds: float = 0.30
    seuil_benford_chi2: float = 15.51
    seuil_outlier_iqr: float = 1.5
    max_file_size_mb: int = 100


@dataclass
class ReportConfig:
    """Configuration rapports."""
    format_defaut: str = "html"
    inclure_graphiques: bool = True
    langue: str = "fr"


@dataclass
class AppConfig:
    """Configuration principale de l'application."""
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)
    data_dir: Path = field(default=None)
    encrypted_dir: Path = field(default=None)
    temp_dir: Path = field(default=None)
    reports_dir: Path = field(default=None)
    audit_log_path: Path = field(default=None)

    security: SecurityConfig = field(default_factory=SecurityConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    report: ReportConfig = field(default_factory=ReportConfig)

    def __post_init__(self):
        if self.data_dir is None:
            self.data_dir = self.base_dir / "data"
        if self.encrypted_dir is None:
            self.encrypted_dir = self.data_dir / "encrypted"
        if self.temp_dir is None:
            self.temp_dir = self.data_dir / "temp"
        if self.reports_dir is None:
            self.reports_dir = self.data_dir / "reports"
        if self.audit_log_path is None:
            self.audit_log_path = self.data_dir / "audit.log"

        # Creer les repertoires si necessaire
        for d in [self.data_dir, self.encrypted_dir, self.temp_dir, self.reports_dir]:
            d.mkdir(parents=True, exist_ok=True)
