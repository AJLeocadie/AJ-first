"""Profil travailleur independant : fiscal et social.

Couvre :
- Micro-entrepreneur (ex auto-entrepreneur)
- Entreprise Individuelle (EI) / EIRL
- TNS (Travailleur Non Salarie) : gerant majoritaire SARL, EURL
- Profession liberale (CIPAV, CNAVPL)

Ref :
- CSS art. L131-6 a L131-6-4 (assiette cotisations TNS)
- CSS art. L613-1 et s. (regime TNS)
- CGI art. 50-0 (micro-BIC), art. 102 ter (micro-BNC)
- LFSS 2026 : refonte cotisations independants
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional


class TypeIndependant(str, Enum):
    """Type de statut independant."""
    MICRO_ENTREPRENEUR = "micro_entrepreneur"
    EI_IR = "entreprise_individuelle_ir"  # EI a l'IR
    EI_IS = "entreprise_individuelle_is"  # EI option IS
    GERANT_MAJORITAIRE = "gerant_majoritaire"  # SARL/EURL
    PROFESSION_LIBERALE = "profession_liberale"
    ARTISAN = "artisan"
    COMMERCANT = "commercant"


class ActiviteMicro(str, Enum):
    """Type d'activite micro-entrepreneur."""
    VENTE_MARCHANDISES = "vente_marchandises"  # BIC vente
    PRESTATIONS_BIC = "prestations_bic"  # BIC prestations
    PRESTATIONS_BNC = "prestations_bnc"  # BNC liberal
    LOCATION_MEUBLEE = "location_meublee"  # BIC location


@dataclass
class ProfilIndependant:
    """Profil complet d'un travailleur independant."""
    type_statut: TypeIndependant
    activite: str = ""
    code_naf: str = ""
    siret: str = ""

    # Fiscal
    regime_fiscal: str = ""  # micro, reel_simplifie, reel_normal
    option_is: bool = False  # EI a opte pour l'IS
    tva_franchise: bool = True  # Franchise en base de TVA

    # Social
    caisse_retraite: str = ""  # SSI (ex-RSI), CIPAV, CNAVPL
    acre: bool = False  # Aide a la Creation/Reprise d'Entreprise
    annee_creation: int = 0

    # Revenus
    chiffre_affaires_annuel: Decimal = Decimal("0")
    benefice_annuel: Decimal = Decimal("0")
    remuneration_nette: Decimal = Decimal("0")


# ===================================================================
# SEUILS MICRO-ENTREPRISE 2026
# ===================================================================

SEUILS_MICRO_2026 = {
    ActiviteMicro.VENTE_MARCHANDISES: {
        "ca_max": Decimal("188700"),
        "abattement_fiscal": Decimal("0.71"),  # 71%
        "taux_cotisations": Decimal("0.123"),  # 12.3%
        "taux_cotisations_acre": Decimal("0.0615"),  # 6.15% (1ere annee)
        "taux_prelevement_liberatoire": Decimal("0.01"),  # 1% PFL
        "cfe_minimum": Decimal("237"),
    },
    ActiviteMicro.PRESTATIONS_BIC: {
        "ca_max": Decimal("77700"),
        "abattement_fiscal": Decimal("0.50"),  # 50%
        "taux_cotisations": Decimal("0.213"),  # 21.3%
        "taux_cotisations_acre": Decimal("0.1065"),  # 10.65%
        "taux_prelevement_liberatoire": Decimal("0.017"),  # 1.7%
        "cfe_minimum": Decimal("237"),
    },
    ActiviteMicro.PRESTATIONS_BNC: {
        "ca_max": Decimal("77700"),
        "abattement_fiscal": Decimal("0.34"),  # 34%
        "taux_cotisations": Decimal("0.232"),  # 23.2%
        "taux_cotisations_acre": Decimal("0.116"),  # 11.6%
        "taux_prelevement_liberatoire": Decimal("0.022"),  # 2.2%
        "cfe_minimum": Decimal("237"),
    },
    ActiviteMicro.LOCATION_MEUBLEE: {
        "ca_max": Decimal("188700"),
        "abattement_fiscal": Decimal("0.50"),  # 50%
        "taux_cotisations": Decimal("0.213"),
        "taux_cotisations_acre": Decimal("0.1065"),
        "taux_prelevement_liberatoire": Decimal("0.017"),
        "cfe_minimum": Decimal("237"),
    },
}

# Seuils TVA franchise en base 2026
TVA_FRANCHISE_SEUILS = {
    "vente": Decimal("91900"),
    "vente_majore": Decimal("101000"),
    "services": Decimal("36800"),
    "services_majore": Decimal("39100"),
}

# Formation professionnelle micro
FORMATION_MICRO = {
    ActiviteMicro.VENTE_MARCHANDISES: Decimal("0.001"),  # 0.10%
    ActiviteMicro.PRESTATIONS_BIC: Decimal("0.002"),  # 0.20% (artisan)
    ActiviteMicro.PRESTATIONS_BNC: Decimal("0.002"),  # 0.20%
    ActiviteMicro.LOCATION_MEUBLEE: Decimal("0.001"),
}


# ===================================================================
# COTISATIONS TNS (REGIME REEL) 2026
# ===================================================================

@dataclass
class CotisationsTNS2026:
    """Taux de cotisations TNS regime reel 2026."""
    # Maladie-maternite
    maladie_taux_1: Decimal = Decimal("0.004")   # 0.40% si revenu < 40% PASS
    maladie_taux_2: Decimal = Decimal("0.040")   # 4% si revenu < 60% PASS
    maladie_taux_3: Decimal = Decimal("0.065")   # 6.50% si revenu < 110% PASS
    maladie_taux_4: Decimal = Decimal("0.065")   # 6.50% au-dela
    maladie_supplementaire: Decimal = Decimal("0.005")  # 0.50% > 5 PASS (indemnites j.)

    # Indemnites journalieres
    ij_taux: Decimal = Decimal("0.0085")  # 0.85%
    ij_plafond_pass: Decimal = Decimal("5")  # 5 PASS

    # Allocations familiales
    af_taux_reduit: Decimal = Decimal("0.0")  # 0% si revenu < 110% PASS
    af_taux_intermediaire: Decimal = Decimal("0.0")  # progressif 110-140% PASS
    af_taux_plein: Decimal = Decimal("0.0310")  # 3.10% si revenu > 140% PASS

    # Vieillesse de base
    vieillesse_plafonnee: Decimal = Decimal("0.1775")  # 17.75% plafonne au PASS
    vieillesse_deplafonnee: Decimal = Decimal("0.0060")  # 0.60% sur totalite

    # Invalidite-deces
    invalidite_deces_1: Decimal = Decimal("0.013")  # 1.30% classe 1
    invalidite_deces_2: Decimal = Decimal("0.013")  # adaptable

    # CSG / CRDS
    csg_deductible: Decimal = Decimal("0.068")
    csg_non_deductible: Decimal = Decimal("0.024")
    crds: Decimal = Decimal("0.005")

    # Formation professionnelle
    formation: Decimal = Decimal("0.0025")  # 0.25% du PASS (commercant/artisan)
    formation_conjoint: Decimal = Decimal("0.0034")  # si conjoint collaborateur

    # Retraite complementaire (SSI)
    retraite_compl_t1: Decimal = Decimal("0.07")  # 7% <= PASS
    retraite_compl_t2: Decimal = Decimal("0.08")  # 8% PASS a 4 PASS


TNS_2026 = CotisationsTNS2026()

# ===================================================================
# CIPAV (Professions liberales non reglementees)
# ===================================================================

COTISATIONS_CIPAV_2026 = {
    "retraite_base_t1": {"taux": Decimal("0.1013"), "plafond_pass": Decimal("1")},
    "retraite_base_t2": {"taux": Decimal("0.0187"), "de_pass": Decimal("1"), "a_pass": Decimal("5")},
    "retraite_complementaire": {"forfait_classe_a": Decimal("1840"), "classes": 8},
    "invalidite_deces": {"classe_a": Decimal("76"), "classe_b": Decimal("228"), "classe_c": Decimal("380")},
}


def calculer_cotisations_micro(
    chiffre_affaires: Decimal,
    activite: ActiviteMicro,
    acre: bool = False,
    prelevement_liberatoire: bool = False,
) -> dict:
    """Calcule les cotisations et impots d'un micro-entrepreneur.

    Args:
        chiffre_affaires: CA sur la periode
        activite: Type d'activite
        acre: Beneficie de l'ACRE
        prelevement_liberatoire: Option pour le versement liberatoire IR
    """
    params = SEUILS_MICRO_2026.get(activite)
    if not params:
        return {"erreur": f"Activite non reconnue : {activite}"}

    # Verifier le seuil
    depassement = chiffre_affaires > params["ca_max"]

    # Taux de cotisations
    taux_cotis = params["taux_cotisations_acre"] if acre else params["taux_cotisations"]
    cotisations = (chiffre_affaires * taux_cotis).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Formation professionnelle (CFP)
    taux_formation = FORMATION_MICRO.get(activite, Decimal("0.002"))
    formation = (chiffre_affaires * taux_formation).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Impot sur le revenu
    abattement = params["abattement_fiscal"]
    revenu_imposable = (chiffre_affaires * (1 - abattement)).quantize(Decimal("0.01"), ROUND_HALF_UP)

    impot_ir = Decimal("0")
    if prelevement_liberatoire:
        taux_pfl = params["taux_prelevement_liberatoire"]
        impot_ir = (chiffre_affaires * taux_pfl).quantize(Decimal("0.01"), ROUND_HALF_UP)

    total_prelevements = cotisations + formation + impot_ir
    net = chiffre_affaires - total_prelevements

    return {
        "regime": "Micro-entrepreneur",
        "activite": activite.value,
        "chiffre_affaires": float(chiffre_affaires),
        "seuil_ca": float(params["ca_max"]),
        "depassement_seuil": depassement,
        "acre": acre,
        "cotisations_sociales": {
            "taux": float(taux_cotis),
            "montant": float(cotisations),
        },
        "formation_professionnelle": {
            "taux": float(taux_formation),
            "montant": float(formation),
        },
        "fiscal": {
            "abattement_forfaitaire_pct": float(abattement * 100),
            "revenu_imposable": float(revenu_imposable),
            "prelevement_liberatoire": prelevement_liberatoire,
            "montant_ir": float(impot_ir) if prelevement_liberatoire else None,
        },
        "total_prelevements": float(total_prelevements),
        "net_apres_prelevements": float(net),
        "taux_prelevement_global_pct": float(total_prelevements / chiffre_affaires * 100) if chiffre_affaires else 0,
        "avertissements": [
            f"ATTENTION : Le CA ({chiffre_affaires} EUR) depasse le seuil micro ({params['ca_max']} EUR). "
            "Passage au regime reel obligatoire au 1er janvier N+1."
        ] if depassement else [],
    }


def calculer_cotisations_tns(
    revenu_net: Decimal,
    type_independant: TypeIndependant = TypeIndependant.GERANT_MAJORITAIRE,
    conjoint_collaborateur: bool = False,
    acre: bool = False,
    pass_annuel: Decimal = Decimal("48060"),
) -> dict:
    """Calcule les cotisations TNS au regime reel.

    Args:
        revenu_net: Revenu net de l'activite (benefice ou remuneration gerant)
        type_independant: Type de statut
        conjoint_collaborateur: Si le conjoint est collaborateur
        acre: Beneficie de l'ACRE (premiere annee)
        pass_annuel: Plafond annuel de securite sociale
    """
    t = TNS_2026
    r = revenu_net

    lignes = []

    # --- Maladie-maternite ---
    # Taux progressif selon le revenu
    if r <= pass_annuel * Decimal("0.40"):
        taux_maladie = t.maladie_taux_1
    elif r <= pass_annuel * Decimal("0.60"):
        taux_maladie = t.maladie_taux_2
    elif r <= pass_annuel * Decimal("1.10"):
        taux_maladie = t.maladie_taux_3
    else:
        taux_maladie = t.maladie_taux_4

    maladie = (r * taux_maladie).quantize(Decimal("0.01"), ROUND_HALF_UP)
    lignes.append({
        "libelle": "Maladie-maternite",
        "assiette": float(r),
        "taux": float(taux_maladie),
        "montant": float(maladie),
    })

    # Indemnites journalieres
    assiette_ij = min(r, pass_annuel * t.ij_plafond_pass)
    ij = (assiette_ij * t.ij_taux).quantize(Decimal("0.01"), ROUND_HALF_UP)
    lignes.append({
        "libelle": "Indemnites journalieres",
        "assiette": float(assiette_ij),
        "taux": float(t.ij_taux),
        "montant": float(ij),
    })

    # --- Allocations familiales ---
    seuil_110 = pass_annuel * Decimal("1.10")
    seuil_140 = pass_annuel * Decimal("1.40")
    if r <= seuil_110:
        taux_af = t.af_taux_reduit
    elif r >= seuil_140:
        taux_af = t.af_taux_plein
    else:
        # Progressif entre 110% et 140% PASS
        ratio = (r - seuil_110) / (seuil_140 - seuil_110)
        taux_af = t.af_taux_plein * ratio

    af = (r * taux_af).quantize(Decimal("0.01"), ROUND_HALF_UP)
    lignes.append({
        "libelle": "Allocations familiales",
        "assiette": float(r),
        "taux": float(taux_af),
        "montant": float(af),
    })

    # --- Retraite de base ---
    assiette_plafonnee = min(r, pass_annuel)
    vieillesse_p = (assiette_plafonnee * t.vieillesse_plafonnee).quantize(Decimal("0.01"), ROUND_HALF_UP)
    lignes.append({
        "libelle": "Retraite de base plafonnee",
        "assiette": float(assiette_plafonnee),
        "taux": float(t.vieillesse_plafonnee),
        "montant": float(vieillesse_p),
    })

    vieillesse_d = (r * t.vieillesse_deplafonnee).quantize(Decimal("0.01"), ROUND_HALF_UP)
    lignes.append({
        "libelle": "Retraite de base deplafonnee",
        "assiette": float(r),
        "taux": float(t.vieillesse_deplafonnee),
        "montant": float(vieillesse_d),
    })

    # --- Retraite complementaire ---
    rc_t1 = (assiette_plafonnee * t.retraite_compl_t1).quantize(Decimal("0.01"), ROUND_HALF_UP)
    lignes.append({
        "libelle": "Retraite complementaire T1",
        "assiette": float(assiette_plafonnee),
        "taux": float(t.retraite_compl_t1),
        "montant": float(rc_t1),
    })

    if r > pass_annuel:
        assiette_t2 = min(r, pass_annuel * 4) - pass_annuel
        rc_t2 = (assiette_t2 * t.retraite_compl_t2).quantize(Decimal("0.01"), ROUND_HALF_UP)
        lignes.append({
            "libelle": "Retraite complementaire T2",
            "assiette": float(assiette_t2),
            "taux": float(t.retraite_compl_t2),
            "montant": float(rc_t2),
        })

    # --- Invalidite-deces ---
    inv_dec = (r * t.invalidite_deces_1).quantize(Decimal("0.01"), ROUND_HALF_UP)
    lignes.append({
        "libelle": "Invalidite-deces",
        "assiette": float(r),
        "taux": float(t.invalidite_deces_1),
        "montant": float(inv_dec),
    })

    # --- CSG / CRDS ---
    assiette_csg = r + sum(l["montant"] for l in lignes)  # R + cotisations obligatoires
    csg_ded = (Decimal(str(assiette_csg)) * t.csg_deductible).quantize(Decimal("0.01"), ROUND_HALF_UP)
    csg_nd = (Decimal(str(assiette_csg)) * t.csg_non_deductible).quantize(Decimal("0.01"), ROUND_HALF_UP)
    crds_m = (Decimal(str(assiette_csg)) * t.crds).quantize(Decimal("0.01"), ROUND_HALF_UP)

    lignes.append({"libelle": "CSG deductible", "assiette": float(assiette_csg),
                    "taux": float(t.csg_deductible), "montant": float(csg_ded)})
    lignes.append({"libelle": "CSG non deductible", "assiette": float(assiette_csg),
                    "taux": float(t.csg_non_deductible), "montant": float(csg_nd)})
    lignes.append({"libelle": "CRDS", "assiette": float(assiette_csg),
                    "taux": float(t.crds), "montant": float(crds_m)})

    # --- Formation professionnelle ---
    taux_form = t.formation_conjoint if conjoint_collaborateur else t.formation
    formation = (pass_annuel * taux_form).quantize(Decimal("0.01"), ROUND_HALF_UP)
    lignes.append({
        "libelle": "Formation professionnelle",
        "assiette": float(pass_annuel),
        "taux": float(taux_form),
        "montant": float(formation),
    })

    total = sum(Decimal(str(l["montant"])) for l in lignes)

    # ACRE : reduction 50% premiere annee
    reduction_acre = Decimal("0")
    if acre:
        reduction_acre = (total * Decimal("0.50")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        total = total - reduction_acre

    net_apres_cotisations = r - total

    return {
        "regime": "TNS - Regime reel",
        "type_statut": type_independant.value,
        "revenu_net": float(r),
        "lignes": lignes,
        "total_cotisations": float(total),
        "acre": acre,
        "reduction_acre": float(reduction_acre) if acre else 0,
        "net_apres_cotisations": float(net_apres_cotisations),
        "taux_cotisations_global_pct": float(total / r * 100) if r else 0,
        "protection_sociale": {
            "maladie": True,
            "indemnites_journalieres": True,
            "maternite": True,
            "retraite_base": True,
            "retraite_complementaire": True,
            "invalidite_deces": True,
            "allocations_familiales": True,
            "chomage": False,  # TNS pas de chomage sauf ATI
        },
    }


def calculer_impot_independant(
    benefice: Decimal,
    type_statut: TypeIndependant,
    autres_revenus_foyer: Decimal = Decimal("0"),
    nb_parts: Decimal = Decimal("1"),
) -> dict:
    """Calcule l'impot sur le revenu pour un independant (bareme progressif).

    Bareme IR 2026 (revenus 2025) :
    - 0% : 0 a 11 497 EUR
    - 11% : 11 497 a 29 315 EUR
    - 30% : 29 315 a 83 823 EUR
    - 41% : 83 823 a 180 294 EUR
    - 45% : > 180 294 EUR
    """
    TRANCHES_IR = [
        (Decimal("11497"), Decimal("0")),
        (Decimal("29315"), Decimal("0.11")),
        (Decimal("83823"), Decimal("0.30")),
        (Decimal("180294"), Decimal("0.41")),
        (Decimal("999999999"), Decimal("0.45")),
    ]

    revenu_imposable = benefice + autres_revenus_foyer
    quotient = revenu_imposable / nb_parts

    impot_par_part = Decimal("0")
    precedent = Decimal("0")
    detail_tranches = []

    for plafond, taux in TRANCHES_IR:
        if quotient <= precedent:
            break
        tranche = min(quotient, plafond) - precedent
        if tranche > 0:
            montant = (tranche * taux).quantize(Decimal("0.01"), ROUND_HALF_UP)
            impot_par_part += montant
            detail_tranches.append({
                "de": float(precedent),
                "a": float(min(quotient, plafond)),
                "taux_pct": float(taux * 100),
                "montant": float(montant),
            })
        precedent = plafond

    impot_total = (impot_par_part * nb_parts).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Taux marginal d'imposition
    tmi = Decimal("0")
    for plafond, taux in TRANCHES_IR:
        if quotient <= plafond:
            tmi = taux
            break

    return {
        "revenu_imposable": float(revenu_imposable),
        "nb_parts": float(nb_parts),
        "quotient_familial": float(quotient),
        "tranches": detail_tranches,
        "impot_brut": float(impot_total),
        "taux_marginal_pct": float(tmi * 100),
        "taux_moyen_pct": float(impot_total / revenu_imposable * 100) if revenu_imposable else 0,
    }
