"""
Constantes reglementaires URSSAF 2026.

Sources officielles :
- urssaf.fr : Ce qu'il faut savoir au 1er janvier 2026
- staffngo.com : Taux cotisations sociales 2026
- travail-emploi.gouv.fr : Changements emploi 2026
"""

from decimal import Decimal
from enum import Enum


# --- Plafonds 2026 ---

PASS_ANNUEL = Decimal("48060.00")
PASS_MENSUEL = Decimal("4005.00")
PASS_JOURNALIER = Decimal("185.00")
PASS_HORAIRE = Decimal("27.00")

SMIC_HORAIRE_BRUT = Decimal("12.02")
SMIC_MENSUEL_BRUT = Decimal("1823.03")
SMIC_ANNUEL_BRUT = SMIC_MENSUEL_BRUT * 12

# Seuil RGDU : 3 SMIC
RGDU_SEUIL_SMIC_MULTIPLE = Decimal("3")
RGDU_SEUIL_MENSUEL = SMIC_MENSUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
RGDU_SEUIL_ANNUEL = SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE

# Abattement independants
ABATTEMENT_INDEPENDANTS = Decimal("0.26")  # 26%


class ContributionType(str, Enum):
    """Types de cotisations sociales."""
    MALADIE = "maladie"
    VIEILLESSE_PLAFONNEE = "vieillesse_plafonnee"
    VIEILLESSE_DEPLAFONNEE = "vieillesse_deplafonnee"
    ALLOCATIONS_FAMILIALES = "allocations_familiales"
    ACCIDENT_TRAVAIL = "accident_travail"
    CSG_DEDUCTIBLE = "csg_deductible"
    CSG_NON_DEDUCTIBLE = "csg_non_deductible"
    CRDS = "crds"
    FNAL = "fnal"
    FORMATION_PROFESSIONNELLE = "formation_professionnelle"
    ASSURANCE_CHOMAGE = "assurance_chomage"
    AGS = "ags"
    RETRAITE_COMPLEMENTAIRE_T1 = "retraite_complementaire_t1"
    RETRAITE_COMPLEMENTAIRE_T2 = "retraite_complementaire_t2"
    CEG_T1 = "ceg_t1"
    CEG_T2 = "ceg_t2"
    CET = "cet"
    APEC = "apec"
    PREVOYANCE_CADRE = "prevoyance_cadre"


# --- Taux de cotisations 2026 (regime general) ---

TAUX_COTISATIONS_2026 = {
    ContributionType.MALADIE: {
        "patronal": Decimal("0.13"),       # 13%
        "salarial": Decimal("0.0"),        # 0% (supprime depuis 2018)
        "patronal_reduit": Decimal("0.07"),  # 7% si < 2.5 SMIC
        "seuil_reduction_smic": Decimal("2.5"),
    },
    ContributionType.VIEILLESSE_PLAFONNEE: {
        "patronal": Decimal("0.0855"),     # 8.55%
        "salarial": Decimal("0.069"),      # 6.90%
        "plafond": PASS_MENSUEL,
    },
    ContributionType.VIEILLESSE_DEPLAFONNEE: {
        "patronal": Decimal("0.0211"),     # 2.11% (nouveau 2026)
        "salarial": Decimal("0.024"),      # 2.40%
    },
    ContributionType.ALLOCATIONS_FAMILIALES: {
        "patronal": Decimal("0.0525"),     # 5.25%
        "patronal_reduit": Decimal("0.0325"),  # 3.25% si < 3.5 SMIC
        "seuil_reduction_smic": Decimal("3.5"),
    },
    ContributionType.ACCIDENT_TRAVAIL: {
        "patronal_moyen": Decimal("0.0208"),  # 2.08% (taux moyen, variable par entreprise)
    },
    ContributionType.CSG_DEDUCTIBLE: {
        "taux": Decimal("0.068"),          # 6.8%
        "assiette_pct": Decimal("0.9825"), # 98.25% du brut
    },
    ContributionType.CSG_NON_DEDUCTIBLE: {
        "taux": Decimal("0.024"),          # 2.4%
        "assiette_pct": Decimal("0.9825"),
    },
    ContributionType.CRDS: {
        "taux": Decimal("0.005"),          # 0.5%
        "assiette_pct": Decimal("0.9825"),
    },
    ContributionType.ASSURANCE_CHOMAGE: {
        "patronal": Decimal("0.0405"),     # 4.05%
        "salarial": Decimal("0.0"),        # 0% (supprime)
        "plafond_multiple_pass": Decimal("4"),  # 4x PASS
    },
    ContributionType.AGS: {
        "patronal": Decimal("0.0015"),     # 0.15%
        "plafond_multiple_pass": Decimal("4"),
    },
    ContributionType.FNAL: {
        "patronal_moins_50": Decimal("0.001"),  # 0.10% < 50 salaries
        "patronal_50_plus": Decimal("0.005"),    # 0.50% >= 50 salaries
    },
    ContributionType.FORMATION_PROFESSIONNELLE: {
        "patronal_moins_11": Decimal("0.0055"),  # 0.55% < 11 salaries
        "patronal_11_plus": Decimal("0.01"),     # 1% >= 11 salaries
    },
    ContributionType.RETRAITE_COMPLEMENTAIRE_T1: {
        "patronal": Decimal("0.0472"),     # 4.72%
        "salarial": Decimal("0.0315"),     # 3.15%
        "plafond": PASS_MENSUEL,
    },
    ContributionType.RETRAITE_COMPLEMENTAIRE_T2: {
        "patronal": Decimal("0.1229"),     # 12.29%
        "salarial": Decimal("0.0864"),     # 8.64%
        "plancher": PASS_MENSUEL,
        "plafond_multiple_pass": Decimal("8"),
    },
}


# --- Seuils de detection d'anomalies ---

class Severity(str, Enum):
    """Niveaux de severite des anomalies."""
    CRITIQUE = "critique"
    HAUTE = "haute"
    MOYENNE = "moyenne"
    FAIBLE = "faible"


class FindingCategory(str, Enum):
    """Categories de constats."""
    ANOMALIE = "anomalie"
    INCOHERENCE = "incoherence"
    DONNEE_MANQUANTE = "donnee_manquante"
    DEPASSEMENT_SEUIL = "depassement_seuil"
    PATTERN_SUSPECT = "pattern_suspect"


# Tolerances pour les comparaisons numeriques
TOLERANCE_MONTANT = Decimal("0.01")       # 1 centime
TOLERANCE_TAUX = Decimal("0.0001")        # 0.01%
TOLERANCE_ARRONDI_PCT = Decimal("0.005")  # 0.5% d'ecart tolere

# Seuils de detection de patterns
SEUIL_NOMBRES_RONDS_PCT = Decimal("0.30")  # 30% de nombres ronds = suspect
SEUIL_BENFORD_CHI2 = Decimal("15.51")      # Chi2 critique a 5% avec 8 ddl
SEUIL_OUTLIER_IQR = Decimal("1.5")         # Coefficient IQR standard

# Formats de fichiers supportes
SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".csv": "csv",
    ".xlsx": "excel",
    ".xls": "excel",
    ".xml": "xml",
    ".dsn": "dsn",
}
