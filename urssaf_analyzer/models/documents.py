"""Modeles de donnees pour les documents et resultats d'analyse."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional

from urssaf_analyzer.config.constants import (
    ContributionType, Severity, FindingCategory,
)


# --- Document ---

class FileType(str, Enum):
    PDF = "pdf"
    CSV = "csv"
    EXCEL = "excel"
    XML = "xml"
    DSN = "dsn"
    IMAGE = "image"
    TEXTE = "texte"


@dataclass
class DateRange:
    debut: date
    fin: date


@dataclass
class Document:
    """Metadonnees d'un document importe."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    nom_fichier: str = ""
    chemin: Optional[Path] = None
    type_fichier: Optional[FileType] = None
    hash_sha256: str = ""
    taille_octets: int = 0
    importe_le: datetime = field(default_factory=datetime.now)
    periode: Optional[DateRange] = None
    metadata: dict = field(default_factory=dict)


# --- Employe / Employeur ---

@dataclass
class Employe:
    """Donnees d'un salarie."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    nir: str = ""                  # Numero de securite sociale
    nom: str = ""
    prenom: str = ""
    date_naissance: Optional[date] = None
    date_embauche: Optional[date] = None
    date_sortie: Optional[date] = None
    statut: str = ""               # cadre, non-cadre, etc.
    temps_travail: Decimal = Decimal("1.0")  # 1.0 = temps plein
    convention_collective: str = ""
    source_document_id: str = ""


@dataclass
class Employeur:
    """Donnees d'un employeur."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    siret: str = ""
    siren: str = ""
    raison_sociale: str = ""
    effectif: int = 0
    code_naf: str = ""
    taux_at: Decimal = Decimal("0")
    adresse: str = ""
    source_document_id: str = ""


# --- Cotisations ---

@dataclass
class Cotisation:
    """Une ligne de cotisation sociale."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type_cotisation: ContributionType = ContributionType.MALADIE
    base_brute: Decimal = Decimal("0")
    assiette: Decimal = Decimal("0")        # base apres plafonnement
    taux_patronal: Decimal = Decimal("0")
    taux_salarial: Decimal = Decimal("0")
    montant_patronal: Decimal = Decimal("0")
    montant_salarial: Decimal = Decimal("0")
    periode: Optional[DateRange] = None
    employe_id: str = ""
    employeur_id: str = ""
    source_document_id: str = ""


@dataclass
class Declaration:
    """Une declaration regroupant plusieurs cotisations."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type_declaration: str = ""       # DSN, DUCS, AE, etc.
    reference: str = ""
    periode: Optional[DateRange] = None
    date_envoi: Optional[datetime] = None
    employeur: Optional[Employeur] = None
    employes: list[Employe] = field(default_factory=list)
    cotisations: list[Cotisation] = field(default_factory=list)
    masse_salariale_brute: Decimal = Decimal("0")
    effectif_declare: int = 0
    source_document_id: str = ""
    metadata: dict = field(default_factory=dict)


# --- Constats (Findings) ---

@dataclass
class Finding:
    """Un constat d'anomalie, incoherence ou point d'attention."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    categorie: FindingCategory = FindingCategory.ANOMALIE
    severite: Severity = Severity.MOYENNE
    titre: str = ""
    description: str = ""
    details_technique: str = ""
    documents_concernes: list[str] = field(default_factory=list)
    montant_impact: Optional[Decimal] = None
    valeur_attendue: Optional[str] = None
    valeur_constatee: Optional[str] = None
    score_risque: int = 0          # 0-100
    recommandation: str = ""
    detecte_par: str = ""          # Nom de l'analyseur
    detecte_le: datetime = field(default_factory=datetime.now)
    reference_legale: str = ""


@dataclass
class AnalysisResult:
    """Resultat complet d'une analyse."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    date_analyse: datetime = field(default_factory=datetime.now)
    documents_analyses: list[Document] = field(default_factory=list)
    declarations: list[Declaration] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    duree_analyse_secondes: float = 0.0

    @property
    def nb_anomalies(self) -> int:
        return sum(1 for f in self.findings if f.categorie == FindingCategory.ANOMALIE)

    @property
    def nb_incoherences(self) -> int:
        return sum(1 for f in self.findings if f.categorie == FindingCategory.INCOHERENCE)

    @property
    def nb_critiques(self) -> int:
        return sum(1 for f in self.findings if f.severite == Severity.CRITIQUE)

    @property
    def impact_total(self) -> Decimal:
        return sum(
            (f.montant_impact for f in self.findings if f.montant_impact),
            Decimal("0"),
        )

    @property
    def score_risque_global(self) -> int:
        if not self.findings:
            return 0
        poids = {Severity.CRITIQUE: 4, Severity.HAUTE: 3, Severity.MOYENNE: 2, Severity.FAIBLE: 1}
        total = sum(poids.get(f.severite, 1) * f.score_risque for f in self.findings)
        max_possible = len(self.findings) * 4 * 100
        return min(100, int((total / max_possible) * 100)) if max_possible > 0 else 0
