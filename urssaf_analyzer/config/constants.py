"""
Constantes reglementaires URSSAF 2026 - Couverture complete.

Sources officielles :
- urssaf.fr : Taux et baremes 2026 secteur prive
- boss.gouv.fr : Bulletin Officiel Securite Sociale
- legifrance.gouv.fr : CSS art. L241-1 a L241-18, L136-1 a L136-8
- agirc-arrco.fr : Taux retraite complementaire 2026
- opco-atlas.fr / France Competences : Formation professionnelle
"""

from decimal import Decimal
from enum import Enum


# ===================================================================
# PLAFONDS DE SECURITE SOCIALE 2026
# Ref: Arrete du 19/12/2025, CSS art. D242-17
# ===================================================================

PASS_ANNUEL = Decimal("48060.00")
PASS_MENSUEL = Decimal("4005.00")
PASS_TRIMESTRIEL = Decimal("12015.00")
PASS_JOURNALIER = Decimal("185.00")
PASS_HORAIRE = Decimal("27.00")

# Plafonds specifiques
PLAFOND_4_PASS = PASS_ANNUEL * 4     # 192 240 EUR - chomage, AGS
PLAFOND_8_PASS = PASS_ANNUEL * 8     # 384 480 EUR - retraite T2

# ===================================================================
# SMIC 2026
# Ref: Decret n° 2025-xxx, CSS art. D241-7
# ===================================================================

SMIC_HORAIRE_BRUT = Decimal("12.02")
SMIC_MENSUEL_BRUT = Decimal("1823.03")  # 151.67h x 12.02
SMIC_ANNUEL_BRUT = SMIC_MENSUEL_BRUT * 12
HEURES_MENSUELLES_LEGALES = Decimal("151.67")

# ===================================================================
# SEUILS RGDU (Reduction Generale Degressive Unique) 2026
# Ref: CSS art. L241-13 (refonte), decret d'application 2026
# ===================================================================

RGDU_SEUIL_SMIC_MULTIPLE = Decimal("3")
RGDU_SEUIL_MENSUEL = SMIC_MENSUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
RGDU_SEUIL_ANNUEL = SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
RGDU_TAUX_MAX_MOINS_50 = Decimal("0.3194")
RGDU_TAUX_MAX_50_PLUS = Decimal("0.3234")

# ===================================================================
# ABATTEMENT INDEPENDANTS
# Ref: CSS art. L131-6, LFSS 2025/2026
# ===================================================================

ABATTEMENT_INDEPENDANTS = Decimal("0.26")  # 26%

# ===================================================================
# SEUILS D'EFFECTIF
# Ref: CSS art. L130-1, Code du travail art. L5422-13
# ===================================================================

SEUIL_EFFECTIF_11 = 11   # Formation pro, taxe apprentissage
SEUIL_EFFECTIF_20 = 20   # PEEC (effort construction)
SEUIL_EFFECTIF_50 = 50   # FNAL deplafonne, forfait social
SEUIL_EFFECTIF_250 = 250  # Taxe apprentissage solde, bonus-malus


class ContributionType(str, Enum):
    """Types de cotisations sociales - couverture exhaustive."""

    # --- Cotisations securite sociale (URSSAF) ---
    MALADIE = "maladie"
    MALADIE_ALSACE_MOSELLE = "maladie_alsace_moselle"
    VIEILLESSE_PLAFONNEE = "vieillesse_plafonnee"
    VIEILLESSE_DEPLAFONNEE = "vieillesse_deplafonnee"
    ALLOCATIONS_FAMILIALES = "allocations_familiales"
    ACCIDENT_TRAVAIL = "accident_travail"

    # --- CSG / CRDS ---
    CSG_DEDUCTIBLE = "csg_deductible"
    CSG_NON_DEDUCTIBLE = "csg_non_deductible"
    CRDS = "crds"

    # --- Contributions URSSAF ---
    FNAL = "fnal"
    VERSEMENT_MOBILITE = "versement_mobilite"
    CONTRIBUTION_SOLIDARITE_AUTONOMIE = "csa"
    CONTRIBUTION_DIALOGUE_SOCIAL = "dialogue_social"

    # --- Chomage et garantie des salaires ---
    ASSURANCE_CHOMAGE = "assurance_chomage"
    AGS = "ags"

    # --- Formation et apprentissage ---
    FORMATION_PROFESSIONNELLE = "formation_professionnelle"
    TAXE_APPRENTISSAGE = "taxe_apprentissage"
    CONTRIBUTION_CPF_CDD = "cpf_cdd"
    CONTRIBUTION_SUPPLEMENTAIRE_APPRENTISSAGE = "csa_apprentissage"

    # --- Construction ---
    PEEC = "peec"  # Participation Effort Construction (1% logement)

    # --- Retraite complementaire AGIRC-ARRCO ---
    RETRAITE_COMPLEMENTAIRE_T1 = "retraite_complementaire_t1"
    RETRAITE_COMPLEMENTAIRE_T2 = "retraite_complementaire_t2"
    CEG_T1 = "ceg_t1"
    CEG_T2 = "ceg_t2"
    CET = "cet"
    APEC = "apec"

    # --- Prevoyance ---
    PREVOYANCE_CADRE = "prevoyance_cadre"
    PREVOYANCE_NON_CADRE = "prevoyance_non_cadre"
    MUTUELLE_OBLIGATOIRE = "mutuelle_obligatoire"

    # --- Forfait social ---
    FORFAIT_SOCIAL = "forfait_social"
    FORFAIT_SOCIAL_REDUIT = "forfait_social_reduit"

    # --- Taxes sur les salaires (employeurs non assujettis TVA) ---
    TAXE_SUR_SALAIRES = "taxe_sur_salaires"

    # --- Reduction / Exoneration ---
    RGDU = "rgdu"
    ACRE = "acre"
    EXONERATION_ZRR = "exoneration_zrr"
    EXONERATION_ZFU = "exoneration_zfu"
    LOI_FILLON = "loi_fillon"

    # --- Avantages en nature / Divers ---
    AVANTAGE_NATURE = "avantage_nature"
    AUTRE = "autre"


# ===================================================================
# TAUX DE COTISATIONS 2026 (REGIME GENERAL)
# Ref: urssaf.fr/taux-baremes/taux-cotisations-secteur-prive
# boss.gouv.fr rubrique cotisations
# ===================================================================

TAUX_COTISATIONS_2026 = {

    # --- SECURITE SOCIALE ---

    ContributionType.MALADIE: {
        "patronal": Decimal("0.13"),              # 13%
        "salarial": Decimal("0.0"),               # 0% (supprime depuis 01/2018)
        "patronal_reduit": Decimal("0.07"),       # 7% si remuneration <= 2.5 SMIC
        "seuil_reduction_smic": Decimal("2.5"),
        "assiette": "totalite",                   # Totalite du salaire brut
        "ref": "CSS art. L241-1, D242-3",
    },

    ContributionType.MALADIE_ALSACE_MOSELLE: {
        "salarial": Decimal("0.013"),             # 1.30% cotisation supplementaire
        "assiette": "totalite",
        "ref": "CSS art. L242-13",
    },

    ContributionType.VIEILLESSE_PLAFONNEE: {
        "patronal": Decimal("0.0855"),            # 8.55%
        "salarial": Decimal("0.069"),             # 6.90%
        "plafond": PASS_MENSUEL,                  # Plafonnee au PASS
        "assiette": "plafonnee_pass",
        "ref": "CSS art. L241-3, D242-4",
    },

    ContributionType.VIEILLESSE_DEPLAFONNEE: {
        "patronal": Decimal("0.0211"),            # 2.11% (hausse 2026 vs 2.02%)
        "salarial": Decimal("0.024"),             # 2.40%
        "assiette": "totalite",
        "ref": "CSS art. L241-3, hausse LFSS 2026",
    },

    ContributionType.ALLOCATIONS_FAMILIALES: {
        "patronal": Decimal("0.0525"),            # 5.25%
        "patronal_reduit": Decimal("0.0325"),     # 3.25% si <= 3.5 SMIC
        "seuil_reduction_smic": Decimal("3.5"),
        "assiette": "totalite",
        "ref": "CSS art. L241-6, D241-3-1",
    },

    ContributionType.ACCIDENT_TRAVAIL: {
        "patronal_moyen": Decimal("0.0208"),      # 2.08% taux moyen national 2026
        "patronal_min": Decimal("0.0090"),        # Taux plancher
        "patronal_max": Decimal("0.0600"),        # Taux plafond
        "assiette": "totalite",
        "ref": "CSS art. L242-5, D242-6-1; arrete taux AT/MP 2026",
        "note": "Taux variable par entreprise selon sinistralite (taux collectif, mixte ou individuel)",
    },

    # --- CSG / CRDS ---
    # Ref: CSS art. L136-1-1 a L136-8, CGI art. 154 quinquies

    ContributionType.CSG_DEDUCTIBLE: {
        "taux": Decimal("0.068"),                 # 6.80%
        "assiette_pct": Decimal("0.9825"),        # 98.25% du brut (abattement 1.75%)
        "assiette": "98.25% brut + prevoyance/mutuelle patronale (sans abattement)",
        "ref": "CSS art. L136-1-1, L136-2, CGI art. 154 quinquies II",
    },

    ContributionType.CSG_NON_DEDUCTIBLE: {
        "taux": Decimal("0.024"),                 # 2.40%
        "assiette_pct": Decimal("0.9825"),
        "assiette": "98.25% brut + prevoyance/mutuelle patronale (sans abattement)",
        "ref": "CSS art. L136-1-1, L136-8",
    },

    ContributionType.CRDS: {
        "taux": Decimal("0.005"),                 # 0.50%
        "assiette_pct": Decimal("0.9825"),
        "assiette": "98.25% brut + prevoyance/mutuelle patronale (sans abattement)",
        "ref": "CSS art. L136-1-1, Ordonnance 96-50 art. 14",
    },

    # --- CONTRIBUTIONS URSSAF ---

    ContributionType.CONTRIBUTION_SOLIDARITE_AUTONOMIE: {
        "patronal": Decimal("0.003"),             # 0.30%
        "assiette": "totalite",
        "ref": "CSS art. L137-40 (ex-CNSA), loi 2004-626",
    },

    ContributionType.FNAL: {
        "patronal_moins_50": Decimal("0.001"),    # 0.10% < 50 salaries (plafonnee PASS)
        "patronal_50_plus": Decimal("0.005"),     # 0.50% >= 50 salaries (deplafonnee)
        "assiette_moins_50": "plafonnee_pass",
        "assiette_50_plus": "totalite",
        "ref": "CSS art. L834-1, D834-1",
    },

    ContributionType.VERSEMENT_MOBILITE: {
        "taux_variable": True,                    # Variable selon commune / AOM
        "taux_ile_de_france": Decimal("0.0320"),  # 3.20% max IDF (zone 1)
        "taux_province_max": Decimal("0.0200"),   # 2% max hors IDF
        "taux_moyen_national": Decimal("0.0175"), # ~1.75% moyenne
        "seuil_effectif": 11,                     # >= 11 salaries
        "assiette": "totalite",
        "ref": "Code general des collectivites territoriales art. L2333-64 et s.",
        "note": "Taux fixe par deliberation de l'autorite organisatrice de la mobilite (AOM)",
    },

    ContributionType.CONTRIBUTION_DIALOGUE_SOCIAL: {
        "patronal": Decimal("0.00016"),           # 0.016%
        "assiette": "totalite",
        "ref": "CSS art. L2135-10, loi Rebsamen 2015",
    },

    # --- CHOMAGE ET GARANTIE ---

    ContributionType.ASSURANCE_CHOMAGE: {
        "patronal": Decimal("0.0405"),            # 4.05%
        "salarial": Decimal("0.0"),               # 0% (supprime depuis 10/2018)
        "plafond_multiple_pass": Decimal("4"),     # 4 PASS
        "assiette": "plafonnee_4pass",
        "ref": "Code du travail art. L5422-9, convention Unedic",
        "note": "Bonus-malus applicable entreprises >= 11 salaries dans 7 secteurs (taux 3% a 5.05%)",
        "bonus_malus_min": Decimal("0.0300"),
        "bonus_malus_max": Decimal("0.0505"),
    },

    ContributionType.AGS: {
        "patronal": Decimal("0.0015"),            # 0.15%
        "plafond_multiple_pass": Decimal("4"),     # 4 PASS
        "assiette": "plafonnee_4pass",
        "ref": "Code du travail art. L3253-18, decision conseil AGS",
    },

    # --- FORMATION PROFESSIONNELLE ET APPRENTISSAGE ---
    # Ref: Code du travail art. L6131-1 et s., collecte France Competences via OPCO

    ContributionType.FORMATION_PROFESSIONNELLE: {
        "patronal_moins_11": Decimal("0.0055"),   # 0.55% < 11 salaries
        "patronal_11_plus": Decimal("0.01"),      # 1.00% >= 11 salaries
        "assiette": "totalite",
        "ref": "Code du travail art. L6331-1",
    },

    ContributionType.TAXE_APPRENTISSAGE: {
        "patronal": Decimal("0.0068"),            # 0.68% (part principale)
        "solde_250_plus": Decimal("0.0009"),      # 0.09% solde (>= 250 salaries, quota alternants < 5%)
        "assiette": "totalite",
        "ref": "CGI art. 1599 ter A, Code du travail art. L6241-1",
        "note": "Part principale 0.68% versee URSSAF mensuellement. Solde 0.09% verse en mai N+1.",
    },

    ContributionType.CONTRIBUTION_CPF_CDD: {
        "patronal": Decimal("0.01"),              # 1% sur masse salariale CDD
        "assiette": "brut_cdd_uniquement",
        "ref": "Code du travail art. L6331-6",
        "note": "Applicable sur la masse salariale des CDD hors remplacement, saisonnier, aidee",
    },

    ContributionType.CONTRIBUTION_SUPPLEMENTAIRE_APPRENTISSAGE: {
        "patronal_250_plus": Decimal("0.0005"),   # 0.05% a 0.60% selon % alternants
        "seuil_effectif": 250,
        "assiette": "totalite",
        "ref": "CGI art. 1609 quinvicies",
        "note": "Due si effectif >= 250 et quota alternants < 5%",
    },

    # --- PEEC - PARTICIPATION EFFORT CONSTRUCTION ---

    ContributionType.PEEC: {
        "patronal": Decimal("0.0045"),            # 0.45%
        "seuil_effectif": 20,                     # >= 20 salaries
        "assiette": "totalite",
        "ref": "Code de la construction art. L313-1",
        "note": "Action Logement. Investissement direct ou versement a un CIL.",
    },

    # --- RETRAITE COMPLEMENTAIRE AGIRC-ARRCO ---
    # Ref: ANI du 17/11/2017, accord AGIRC-ARRCO

    ContributionType.RETRAITE_COMPLEMENTAIRE_T1: {
        "patronal": Decimal("0.0472"),            # 4.72% (60% de 7.87%)
        "salarial": Decimal("0.0315"),            # 3.15% (40% de 7.87%)
        "total": Decimal("0.0787"),               # 7.87%
        "plafond": PASS_MENSUEL,
        "assiette": "tranche_1_pass",
        "ref": "ANI AGIRC-ARRCO, art. 36",
    },

    ContributionType.RETRAITE_COMPLEMENTAIRE_T2: {
        "patronal": Decimal("0.1229"),            # 12.29% (60% de 21.59%)
        "salarial": Decimal("0.0864"),            # 8.64% (40% de 21.59%)
        "total": Decimal("0.2159"),               # 21.59%
        "plancher": PASS_MENSUEL,
        "plafond_multiple_pass": Decimal("8"),     # 8 PASS
        "assiette": "tranche_2_1a8pass",
        "ref": "ANI AGIRC-ARRCO, art. 36",
    },

    ContributionType.CEG_T1: {
        "patronal": Decimal("0.0129"),            # 1.29%
        "salarial": Decimal("0.0086"),            # 0.86%
        "total": Decimal("0.0215"),               # 2.15%
        "plafond": PASS_MENSUEL,
        "assiette": "tranche_1_pass",
        "ref": "ANI AGIRC-ARRCO - Contribution d'equilibre general T1",
    },

    ContributionType.CEG_T2: {
        "patronal": Decimal("0.0162"),            # 1.62%
        "salarial": Decimal("0.0108"),            # 1.08%
        "total": Decimal("0.0270"),               # 2.70%
        "plancher": PASS_MENSUEL,
        "plafond_multiple_pass": Decimal("8"),
        "assiette": "tranche_2_1a8pass",
        "ref": "ANI AGIRC-ARRCO - Contribution d'equilibre general T2",
    },

    ContributionType.CET: {
        "patronal": Decimal("0.0021"),            # 0.21% (integ. de 0.35%)
        "salarial": Decimal("0.0014"),            # 0.14%
        "total": Decimal("0.0035"),               # 0.35%
        "plafond_multiple_pass": Decimal("8"),
        "assiette": "tranche_1_et_2",
        "ref": "ANI AGIRC-ARRCO - Contribution d'equilibre technique",
    },

    ContributionType.APEC: {
        "patronal": Decimal("0.00036"),           # 0.036%
        "salarial": Decimal("0.00024"),           # 0.024%
        "total": Decimal("0.0006"),               # 0.060%
        "plafond_multiple_pass": Decimal("4"),
        "assiette": "tranche_a_b",
        "ref": "Convention collective nationale des cadres",
        "note": "Cadres uniquement",
    },

    # --- PREVOYANCE ---

    ContributionType.PREVOYANCE_CADRE: {
        "patronal_minimum": Decimal("0.015"),     # 1.50% minimum obligatoire
        "plafond": PASS_MENSUEL,
        "assiette": "tranche_1_pass",
        "ref": "Convention collective nationale des cadres art. 7, ANI prevoyance",
    },

    ContributionType.PREVOYANCE_NON_CADRE: {
        "note": "Taux variable selon convention collective et contrat",
        "ref": "ANI du 11/01/2013",
    },

    ContributionType.MUTUELLE_OBLIGATOIRE: {
        "patronal_minimum_pct": Decimal("0.50"),  # 50% minimum a charge employeur
        "panier_soins_minimum": Decimal("35.00"), # Panier de soins ANI 2016
        "ref": "Code de la Securite Sociale art. L911-7, ANI 11/01/2013",
    },

    # --- FORFAIT SOCIAL ---

    ContributionType.FORFAIT_SOCIAL: {
        "taux_droit_commun": Decimal("0.20"),     # 20%
        "taux_prevoyance": Decimal("0.08"),       # 8% sur prevoyance complementaire
        "taux_pere": Decimal("0.10"),             # 10% PERE (plan epargne retraite)
        "taux_actionnariat": Decimal("0.10"),     # 10% abondement actionnariat salarie
        "seuil_effectif": 11,
        "ref": "CSS art. L137-15 a L137-17",
        "note": "Assiette: interessement, participation, abondements PEE/PERCO",
    },

    ContributionType.FORFAIT_SOCIAL_REDUIT: {
        "taux": Decimal("0.16"),                  # 16% PERECO avec gestion pilotee
        "ref": "CSS art. L137-16",
    },

    # --- TAXE SUR LES SALAIRES ---

    ContributionType.TAXE_SUR_SALAIRES: {
        "taux_normal": Decimal("0.0420"),         # 4.25%
        "taux_majore_1": Decimal("0.0850"),       # 8.50% (8 573 a 17 114 EUR annuel)
        "taux_majore_2": Decimal("0.1360"),       # 13.60% (> 17 114 EUR annuel)
        "seuil_1": Decimal("8573.00"),
        "seuil_2": Decimal("17114.00"),
        "abattement_associations": Decimal("23616.00"),
        "ref": "CGI art. 231 et s.",
        "note": "Due par employeurs non assujettis TVA (< 10% activite taxable)",
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
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".bmp": "image",
    ".tiff": "image",
    ".tif": "image",
    ".gif": "image",
    ".webp": "image",
    ".heic": "image",
    ".heif": "image",
    ".txt": "texte",
    ".docx": "word",
    ".doc": "word",
}
