"""Regimes speciaux de securite sociale.

Ref:
- CSS art. L711-1 a L711-13 (regimes speciaux)
- CSS art. L741-1 a L741-21 (regime agricole MSA)
- CSS art. L242-4-4 (Alsace-Moselle)
- Loi du 1er juin 1924 (regime local Alsace-Moselle)
- Decret 2004-174 (regime des mines)

Regimes couverts :
1. MSA (Mutualite Sociale Agricole)
2. Alsace-Moselle (regime local complementaire)
3. Mines (regime minier)
4. SNCF (regime ferroviaire)
5. RATP
6. EDF/GDF (industries electriques et gazieres)
7. CRPCEN (clercs et employes de notaires)
8. Marins (ENIM)
9. Banque de France
10. Fonction publique (CNRACL/SRE) - contractuels uniquement
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


# ===================================================================
# MSA - MUTUALITE SOCIALE AGRICOLE
# Ref: CSS art. L741-1 a L741-21, L741-16 (ATEXA)
# ===================================================================

REGIME_MSA = {
    "code": "msa",
    "nom": "Mutualite Sociale Agricole",
    "description": "Regime de protection sociale des salaries et exploitants agricoles",
    "cotisations": {
        # Cotisations patronales (taux specifiques MSA)
        "maladie_maternite": {
            "patronal": Decimal("0.13"),      # 13.00% (vs 13.00% RG)
            "patronal_reduit": Decimal("0.07"), # 7.00% si <= 2.5 SMIC
            "salarial": Decimal("0"),           # 0% (supprime depuis 2018)
            "assiette": "totalite",
        },
        "vieillesse_plafonnee": {
            "patronal": Decimal("0.0855"),     # 8.55% (identique RG)
            "salarial": Decimal("0.0690"),     # 6.90% (identique RG)
            "assiette": "plafonnee",
        },
        "vieillesse_deplafonnee": {
            "patronal": Decimal("0.0202"),     # 2.02% (identique RG)
            "salarial": Decimal("0.004"),      # 0.40% (identique RG)
            "assiette": "totalite",
        },
        "allocations_familiales": {
            "patronal": Decimal("0.0525"),     # 5.25% (identique RG)
            "patronal_reduit": Decimal("0.0325"), # 3.25% si <= 3.5 SMIC
            "assiette": "totalite",
        },
        "atexa": {
            # Remplacement de AT/MP general par ATEXA (forfaitaire)
            "patronal": Decimal("0.0300"),     # Variable selon activite - moyenne
            "assiette": "totalite",
            "note": "ATEXA: cotisation forfaitaire selon categorie de risque agricole",
        },
        "chomage_agricole": {
            "patronal": Decimal("0.0405"),     # 4.05% (identique RG)
            "salarial": Decimal("0"),           # 0% (supprime 2019)
            "assiette": "4_pass",
        },
        "ags_agricole": {
            "patronal": Decimal("0.0015"),     # 0.15% (identique RG)
            "assiette": "4_pass",
        },
        "retraite_complementaire": {
            "patronal_t1": Decimal("0.0487"),  # AGIRC-ARRCO T1 (identique)
            "salarial_t1": Decimal("0.0315"),
            "patronal_t2": Decimal("0.1292"),  # AGIRC-ARRCO T2 (identique)
            "salarial_t2": Decimal("0.0864"),
        },
        "formation_professionnelle": {
            "patronal_moins_11": Decimal("0.0055"),
            "patronal_11_plus": Decimal("0.01"),
            "note": "Meme taux que RG, verse a OCAPIAT (OPCO agricole)",
        },
        "taxe_apprentissage": {
            "patronal": Decimal("0.0068"),     # Identique RG
        },
        "csg_crds": {
            "taux_csg_deductible": Decimal("0.068"),
            "taux_csg_non_deductible": Decimal("0.024"),
            "taux_crds": Decimal("0.005"),
            "assiette_pct": Decimal("0.9825"),
        },
        # Cotisation specifique MSA
        "contribution_camarca": {
            "patronal": Decimal("0.0050"),     # 0.50% complementaire retraite supplementaire
            "note": "Regime complementaire obligatoire MSA (CAMARCA/AGRICA)",
        },
    },
    "specificites": [
        "ATEXA (Assurance contre les accidents du travail des exploitants agricoles) au lieu de AT/MP",
        "Cotisation CAMARCA/AGRICA complementaire retraite",
        "OCAPIAT comme OPCO de branche (formation)",
        "Exoneration travailleurs occasionnels demandeurs d emploi (TO-DE) si <= 1.2 SMIC",
        "Avantages en nature repas: 5.35 EUR/repas (valeur 2026)",
        "Hebergement: 78.00 EUR/mois (valeur 2026)",
    ],
}


# ===================================================================
# ALSACE-MOSELLE - REGIME LOCAL COMPLEMENTAIRE
# Ref: Loi du 1er juin 1924, CSS art. L242-4-4, L325-1
# Departements: 57 (Moselle), 67 (Bas-Rhin), 68 (Haut-Rhin)
# ===================================================================

REGIME_ALSACE_MOSELLE = {
    "code": "alsace_moselle",
    "nom": "Regime local complementaire Alsace-Moselle",
    "description": "Regime complementaire maladie obligatoire pour les salaries des departements 57, 67 et 68",
    "departements": ["57", "67", "68"],
    "cotisations_supplementaires": {
        "maladie_regime_local": {
            "salarial": Decimal("0.013"),      # 1.30% salarial supplementaire
            "patronal": Decimal("0"),
            "assiette": "totalite",
            "ref": "CSS art. L242-4-4 / Instance de gestion du regime local",
        },
    },
    "avantages": [
        "Remboursement 90% des frais medicaux (vs 70% regime general)",
        "Tiers payant integral chez les medecins conventionnes",
        "Remboursement 100% frais hospitaliers (vs 80%)",
        "Pas de forfait journalier hospitalier",
        "Dispense d avance de frais pour les soins courants",
    ],
    "conditions": [
        "Le salarie doit travailler dans les departements 57, 67 ou 68",
        "Ou avoir son siege social dans ces departements",
        "Les frontaliers travaillant en Alsace-Moselle en beneficient",
        "Le regime est obligatoire (pas de choix d adhesion)",
    ],
    "jours_feries_supplementaires": [
        "Vendredi Saint (vendredi precedant Paques)",
        "26 decembre (Saint Etienne)",
    ],
    "droit_local_travail": {
        "preavis_specifique": True,
        "clause_non_concurrence": "Plus encadree que droit general",
        "repos_dominical": "Obligatoire (peu de derogations)",
        "maintien_salaire_maladie": "Des le 1er jour (pas de delai de carence)",
    },
}


# ===================================================================
# REGIME MINIER
# Ref: CSS art. L711-1, Decret 2004-174
# ===================================================================

REGIME_MINES = {
    "code": "mines",
    "nom": "Regime minier (CANSSM)",
    "description": "Regime special des mines, en extinction progressive depuis 2012",
    "cotisations": {
        "maladie": {
            "patronal": Decimal("0.1280"),     # 12.80%
            "salarial": Decimal("0"),
        },
        "vieillesse": {
            "patronal": Decimal("0.1195"),     # 11.95%
            "salarial": Decimal("0.0890"),     # 8.90%
            "note": "Pension calculee selon duree de service souterrain/jour",
        },
        "at_mp": {
            "patronal": Decimal("0.0450"),     # Taux moyen forfaitaire
        },
    },
    "specificites": [
        "Regime en extinction (plus de nouveaux affilies depuis 2012)",
        "Les anciens mineurs conservent leurs droits acquis",
        "Pension de retraite des le 50 ans (services souterrains) ou 55 ans (services jour)",
        "Prise en charge a 100% des soins de sante sans avance de frais",
        "Les salaries d anciens sites miniers reconvertis restent au regime general",
    ],
}


# ===================================================================
# REGIME SNCF
# Ref: Decret 2008-639, loi 2018 portant nouveau pacte ferroviaire
# ===================================================================

REGIME_SNCF = {
    "code": "sncf",
    "nom": "Regime special SNCF (CPRPSNCF)",
    "description": "Regime special des cheminots, ferme aux nouveaux entrants depuis 2020",
    "cotisations": {
        "maladie": {
            "salarial": Decimal("0"),
            "note": "Prise en charge par le regime special",
        },
        "vieillesse_specifique": {
            "patronal": Decimal("0.2310"),     # T1 : 23.10%
            "salarial": Decimal("0.0890"),     # 8.90%
            "note": "Taux eleve car pension = 75% du salaire des 6 derniers mois",
        },
    },
    "specificites": [
        "Ferme aux nouveaux entrants depuis le 1er janvier 2020",
        "Les agents recrutes apres 2020 relevent du regime general",
        "Age legal de depart : 52 ans (agents de conduite) / 57 ans (autres)",
        "Pension : 75% du salaire des 6 derniers mois",
        "Gratuite des voyages SNCF pour le salarie et sa famille",
    ],
}


# ===================================================================
# REGIME RATP
# Ref: Decret 2005-1635
# ===================================================================

REGIME_RATP = {
    "code": "ratp",
    "nom": "Regime special RATP (CRP RATP)",
    "description": "Regime special des agents de la RATP, ferme aux nouveaux entrants depuis 2020",
    "cotisations": {
        "vieillesse_specifique": {
            "patronal": Decimal("0.2100"),     # ~21.00%
            "salarial": Decimal("0.0890"),     # 8.90%
        },
    },
    "specificites": [
        "Ferme aux nouveaux entrants depuis le 1er janvier 2020",
        "Age legal : 52 ans (agents d exploitation) / 57 ans (autres)",
        "Pension : 75% du salaire des 6 derniers mois",
    ],
}


# ===================================================================
# REGIME EDF/GDF (INDUSTRIES ELECTRIQUES ET GAZIERES - IEG)
# Ref: Decret 46-1541, statut national du personnel IEG
# ===================================================================

REGIME_IEG = {
    "code": "ieg",
    "nom": "Regime IEG (Industries Electriques et Gazieres)",
    "description": "Regime special des agents sous statut IEG (EDF, Engie, RTE, GRDF, etc.)",
    "cotisations": {
        "vieillesse_specifique": {
            "patronal": Decimal("0.1600"),     # ~16.00% (CNIEG)
            "salarial": Decimal("0.0890"),
        },
        "complementaire_ieg": {
            "patronal": Decimal("0.0380"),     # Regime complementaire specifique
            "salarial": Decimal("0.0250"),
        },
    },
    "specificites": [
        "Regime en cours d alignement progressif sur le regime general",
        "Pension : 75% du salaire des 6 derniers mois",
        "Tarif preferentiel electricite/gaz pour les agents",
        "Nouveaux embauches depuis 2020 : reforme progressive",
    ],
}


# ===================================================================
# CRPCEN - CLERCS ET EMPLOYES DE NOTAIRES
# Ref: Decret 90-1215
# ===================================================================

REGIME_CRPCEN = {
    "code": "crpcen",
    "nom": "CRPCEN (Caisse de Retraite des Clercs et Employes de Notaires)",
    "description": "Regime special de retraite et de prevoyance des offices notariaux",
    "cotisations": {
        "vieillesse_crpcen": {
            "patronal": Decimal("0.0400"),     # ~4.00%
            "salarial": Decimal("0.0400"),     # ~4.00%
            "note": "S ajoute aux cotisations regime general",
        },
        "prevoyance_crpcen": {
            "patronal": Decimal("0.0120"),     # 1.20%
            "salarial": Decimal("0.0080"),     # 0.80%
        },
        "maladie_crpcen": {
            "patronal": Decimal("0.0500"),     # Complementaire sante specifique
        },
    },
    "specificites": [
        "Cotisation supplementaire au regime general (pas de substitution)",
        "Retraite complementaire specifique en plus d AGIRC-ARRCO",
        "Prevoyance obligatoire de branche",
        "Les salaries des etudes notariales relevent aussi du regime general",
    ],
}


# ===================================================================
# ENIM - REGIME DES MARINS
# Ref: Code des transports art. L5551-1, Decret 52-540
# ===================================================================

REGIME_MARINS = {
    "code": "enim",
    "nom": "ENIM (Etablissement National des Invalides de la Marine)",
    "description": "Regime de securite sociale des gens de mer",
    "cotisations": {
        "pension_vieillesse": {
            "patronal": Decimal("0.1320"),     # 13.20%
            "salarial": Decimal("0.1070"),     # 10.70%
            "note": "Taux incluant retraite de base + complementaire",
        },
        "maladie_accident": {
            "patronal": Decimal("0.0900"),     # 9.00%
            "salarial": Decimal("0"),
        },
        "prevoyance_enim": {
            "patronal": Decimal("0.0350"),     # 3.50%
            "salarial": Decimal("0.0200"),     # 2.00%
        },
    },
    "specificites": [
        "Age de depart en retraite : 50 a 55 ans selon navigation",
        "Annuites calculees par trimestres de navigation",
        "Couverture AT specifique (risques maritimes)",
        "Les armateurs francais sont l employeur cotisant",
        "Applicable aux marins du commerce, de la peche et de plaisance professionnelle",
    ],
}


# ===================================================================
# BANQUE DE FRANCE
# ===================================================================

REGIME_BANQUE_DE_FRANCE = {
    "code": "bdf",
    "nom": "Regime de la Banque de France",
    "description": "Regime special des agents de la Banque de France",
    "cotisations": {
        "retraite_bdf": {
            "salarial": Decimal("0.0890"),
            "note": "Regime adosse au regime general depuis 2007, cotisations supplementaires",
        },
    },
    "specificites": [
        "Regime adosse au regime general depuis 2007",
        "Complementaire specifique financee par la Banque de France",
        "Age de depart : 60 ans (categories sedentaires)",
    ],
}


# ===================================================================
# DICTIONNAIRE GLOBAL DES REGIMES
# ===================================================================

REGIMES_SPECIAUX = {
    "msa": REGIME_MSA,
    "alsace_moselle": REGIME_ALSACE_MOSELLE,
    "mines": REGIME_MINES,
    "sncf": REGIME_SNCF,
    "ratp": REGIME_RATP,
    "ieg": REGIME_IEG,
    "crpcen": REGIME_CRPCEN,
    "enim": REGIME_MARINS,
    "bdf": REGIME_BANQUE_DE_FRANCE,
}


def get_regime(code: str) -> Optional[dict]:
    """Retourne les donnees d un regime special."""
    return REGIMES_SPECIAUX.get(code.lower())


def lister_regimes() -> list[dict]:
    """Liste tous les regimes speciaux disponibles."""
    return [
        {"code": k, "nom": v["nom"], "description": v["description"]}
        for k, v in REGIMES_SPECIAUX.items()
    ]


def detecter_regime(
    code_naf: str = "",
    departement: str = "",
    idcc: str = "",
    texte: str = "",
) -> list[str]:
    """Detecte le ou les regimes applicables selon les donnees connues.

    Retourne une liste de codes de regimes applicables.
    Le regime general n est pas inclus (il est toujours le defaut).
    """
    regimes = []

    # Alsace-Moselle
    if departement in ("57", "67", "68"):
        regimes.append("alsace_moselle")

    # MSA
    naf_2 = code_naf.replace(".", "")[:2] if code_naf else ""
    if naf_2 in ("01", "02", "03"):
        regimes.append("msa")

    # CRPCEN (notariat)
    if idcc in ("2205",):
        regimes.append("crpcen")

    # Detection par texte
    texte_lower = texte.lower()
    if any(kw in texte_lower for kw in ["msa", "mutualite sociale agricole", "agricole", "atexa"]):
        if "msa" not in regimes:
            regimes.append("msa")
    if any(kw in texte_lower for kw in ["regime minier", "canssm", "mines"]):
        regimes.append("mines")
    if any(kw in texte_lower for kw in ["sncf", "cheminot", "ferroviaire", "cprpsncf"]):
        regimes.append("sncf")
    if any(kw in texte_lower for kw in ["ratp", "crp ratp"]):
        regimes.append("ratp")
    if any(kw in texte_lower for kw in ["edf", "gdf", "engie", "rte", "grdf", "ieg", "industries electriques"]):
        regimes.append("ieg")
    if any(kw in texte_lower for kw in ["enim", "marins", "gens de mer", "navigation"]):
        regimes.append("enim")
    if any(kw in texte_lower for kw in ["banque de france", "bdf"]):
        regimes.append("bdf")
    if any(kw in texte_lower for kw in ["alsace", "moselle", "bas-rhin", "haut-rhin", "regime local"]):
        if "alsace_moselle" not in regimes:
            regimes.append("alsace_moselle")

    return list(set(regimes))


def calculer_supplement_alsace_moselle(brut_mensuel: Decimal) -> dict:
    """Calcule la cotisation supplementaire Alsace-Moselle."""
    taux = REGIME_ALSACE_MOSELLE["cotisations_supplementaires"]["maladie_regime_local"]["salarial"]
    montant = (brut_mensuel * taux).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return {
        "taux_salarial": float(taux),
        "montant_salarial_mensuel": float(montant),
        "montant_salarial_annuel": float(montant * 12),
        "ref": "CSS art. L242-4-4",
    }


def calculer_cotisations_msa(brut_mensuel: Decimal, effectif: int = 0) -> dict:
    """Calcule les cotisations specifiques MSA."""
    cots = REGIME_MSA["cotisations"]
    resultat = {"regime": "msa", "brut_mensuel": float(brut_mensuel), "lignes": []}

    from urssaf_analyzer.config.constants import SMIC_MENSUEL_BRUT, PASS_MENSUEL

    for nom, params in cots.items():
        if nom == "csg_crds":
            continue  # Identique regime general
        if nom == "retraite_complementaire":
            continue  # Identique regime general
        if nom == "formation_professionnelle":
            continue  # Identique regime general
        if nom == "taxe_apprentissage":
            continue  # Identique regime general

        pat = params.get("patronal", Decimal("0"))
        sal = params.get("salarial", Decimal("0"))

        # Taux reduit maladie si <= 2.5 SMIC
        if nom == "maladie_maternite" and brut_mensuel <= SMIC_MENSUEL_BRUT * Decimal("2.5"):
            pat = params.get("patronal_reduit", pat)
        # Taux reduit AF si <= 3.5 SMIC
        if nom == "allocations_familiales" and brut_mensuel <= SMIC_MENSUEL_BRUT * Decimal("3.5"):
            pat = params.get("patronal_reduit", pat)

        assiette = brut_mensuel
        if params.get("assiette") == "plafonnee":
            assiette = min(brut_mensuel, PASS_MENSUEL)
        elif params.get("assiette") == "4_pass":
            assiette = min(brut_mensuel, PASS_MENSUEL * 4)

        montant_pat = (assiette * pat).quantize(Decimal("0.01"), ROUND_HALF_UP)
        montant_sal = (assiette * sal).quantize(Decimal("0.01"), ROUND_HALF_UP)

        resultat["lignes"].append({
            "cotisation": nom,
            "assiette": float(assiette),
            "taux_patronal": float(pat),
            "taux_salarial": float(sal),
            "montant_patronal": float(montant_pat),
            "montant_salarial": float(montant_sal),
        })

    total_pat = sum(l["montant_patronal"] for l in resultat["lignes"])
    total_sal = sum(l["montant_salarial"] for l in resultat["lignes"])
    resultat["total_patronal"] = round(total_pat, 2)
    resultat["total_salarial"] = round(total_sal, 2)
    resultat["cout_total"] = round(float(brut_mensuel) + total_pat, 2)

    return resultat
