"""Routes Simulation.

Simulations de bulletins de paie, micro-entrepreneur, TNS, GUSO,
exonerations, cout employeur, epargne salariale, etc.
"""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Form, Query, Request

from api.state import (
    log_action, safe_json, get_moteur,
)
from urssaf_analyzer.config.constants import SMIC_MENSUEL_BRUT as _SMIC_MENSUEL, PASS_MENSUEL as _PASS_MENSUEL
from urssaf_analyzer.veille.urssaf_client import get_baremes_annee

router = APIRouter(prefix="/api", tags=["Simulation"])

# ==============================
# SIMULATION
# ==============================


def _get_baremes_pour_annee(annee: int) -> dict:
    """Retourne les baremes applicables pour une annee donnee.

    Permet aux simulations d'appliquer les regles de la bonne periode :
    un document 2024 utilise les taux 2024, un document 2025 les taux 2025, etc.
    """
    b = get_baremes_annee(annee)
    if not b:
        b = get_baremes_annee(2026)  # fallback
    return {
        "annee": annee,
        "smic_mensuel": b.get("smic_mensuel", float(_SMIC_MENSUEL)),
        "smic_horaire": b.get("smic_horaire", 11.88),
        "pass_mensuel": b.get("pass_mensuel", float(_PASS_MENSUEL)),
        "pass_annuel": b.get("pass_annuel", 47100.00),
        "taux_maladie": b.get("taux_maladie_patronal", 0.13),
        "taux_maladie_reduit": b.get("taux_maladie_patronal_reduit", 0.07),
        "seuil_maladie_smic": b.get("seuil_maladie_reduit_smic", 2.5),
        "taux_vieillesse_plaf": b.get("taux_vieillesse_plafonnee_patronal", 0.0855),
        "taux_vieillesse_deplaf": b.get("taux_vieillesse_deplafonnee_patronal", 0.0202),
        "taux_af": b.get("taux_af_patronal", 0.0525),
        "taux_af_reduit": b.get("taux_af_patronal_reduit", 0.0345),
        "seuil_af_smic": b.get("seuil_af_reduit_smic", 3.5),
        "taux_at_moyen": b.get("taux_at_moyen", 0.0208),
        "taux_fnal_moins_50": b.get("taux_fnal_moins_50", 0.001),
        "taux_fnal_50_plus": b.get("taux_fnal_50_plus", 0.005),
        "taux_csa": b.get("taux_csa", 0.003),
        "taux_chomage": b.get("taux_chomage_patronal", 0.0405),
        "taux_ags": b.get("taux_ags", 0.0015),
        "taux_dialogue_social": b.get("taux_dialogue_social", 0.00016),
        "taux_rc_t1_patronal": b.get("taux_rc_t1_patronal", 0.0472),
        "taux_rc_t1_salarial": b.get("taux_rc_t1_salarial", 0.0315),
        "taux_rc_t2_patronal": b.get("taux_rc_t2_patronal", 0.1229),
        "taux_rc_t2_salarial": b.get("taux_rc_t2_salarial", 0.0864),
        "taux_ceg_t1_patronal": b.get("taux_ceg_t1_patronal", 0.0129),
        "taux_ceg_t1_salarial": b.get("taux_ceg_t1_salarial", 0.0086),
        "taux_ceg_t2_patronal": b.get("taux_ceg_t2_patronal", 0.0162),
        "taux_ceg_t2_salarial": b.get("taux_ceg_t2_salarial", 0.0108),
        "taux_cet_patronal": b.get("taux_cet_patronal", 0.0021),
        "taux_cet_salarial": b.get("taux_cet_salarial", 0.0014),
        "taux_formation_moins_11": b.get("taux_formation_moins_11", 0.0055),
        "taux_formation_11_plus": b.get("taux_formation_11_plus", 0.01),
        "taux_taxe_apprentissage": b.get("taux_taxe_apprentissage", 0.0068),
        "taux_prevoyance_cadre_min": b.get("taux_prevoyance_cadre_min", 0.015),
        # Reduction generale : Fillon (<=2024: 1.6 SMIC) ou RGDU (2026: 3.0 SMIC)
        "seuil_rgd_smic": b.get("seuil_rgdu_smic", b.get("seuil_rgd_smic", 1.6)),
        "rgdu_taux_max_moins_50": b.get("rgdu_taux_max_moins_50", 0.3194),
        "rgdu_taux_max_50_plus": b.get("rgdu_taux_max_50_plus", 0.3234),
        # Nom de la reduction selon l'epoque
        "nom_reduction": "Reduction generale (RGDU 2026)" if annee >= 2026 else f"Reduction generale Fillon ({annee})",
        "ref_reduction": "Art. L.241-13 CSS (refonte LFSS 2026)" if annee >= 2026 else "Art. L.241-13 CSS",
    }


@router.get("/api/simulation/bulletin")
async def sim_bulletin(
    brut_mensuel: float = Query(2500, description="Salaire brut mensuel du salarie simule (EUR)"),
    effectif: int = Query(10, description="Effectif total de l entreprise (pour seuils FNAL, versement mobilite)"),
    est_cadre: bool = Query(False, description="Le salarie simule est-il cadre ?"),
    annee: int = Query(2026, description="Annee de reference pour les baremes (2020-2026)"),
    jours_absence: float = Query(0, description="Nombre de jours d absence dans le mois"),
    type_absence: str = Query("", description="Type d absence : maladie, at_mp, maternite, conge_sans_solde"),
):
    bar = _get_baremes_pour_annee(annee)
    from urssaf_analyzer.rules.contribution_rules import ContributionRules

    # Gestion des absences
    jours_ouvres_mois = 21.67
    retenue_absences = round(brut_mensuel / jours_ouvres_mois * jours_absence, 2) if jours_absence > 0 else 0.0
    brut_effectif = round(brut_mensuel - retenue_absences, 2)

    # IJSS estimees selon le type d absence
    info_absences = None
    if jours_absence > 0:
        smic_mensuel_ref = bar["smic_mensuel"]
        ijss = 0.0
        complement_employeur = 0.0
        if type_absence == "maladie":
            ijss = round(min(brut_mensuel / 30.42, smic_mensuel_ref / 30.42 * 1.8) * 0.5 * jours_absence, 2)
            jours_complement = max(0, jours_absence - 7)
            complement_employeur = round(brut_mensuel / 30.42 * 0.9 * min(jours_complement, 30), 2)
        elif type_absence == "maternite":
            ijss = round(min(brut_mensuel / 30.42, smic_mensuel_ref / 30.42 * 1.8) * jours_absence, 2)
        elif type_absence == "at_mp":
            ijss = round((brut_mensuel / 30.42) * 0.6 * min(jours_absence, 28) + (brut_mensuel / 30.42) * 0.8 * max(0, jours_absence - 28), 2)
        info_absences = {
            "type": type_absence or "non_precise",
            "jours": jours_absence,
            "retenue_brut": retenue_absences,
            "brut_contractuel": brut_mensuel,
            "brut_apres_absences": brut_effectif,
            "ijss_estimees": ijss,
            "complement_employeur": complement_employeur,
        }

    calc = ContributionRules(effectif_entreprise=effectif)
    res = calc.calculer_bulletin_complet(Decimal(str(brut_effectif)), est_cadre=est_cadre)
    lignes = []
    for l in res.get("lignes", []):
        lignes.append({
            "libelle": l["libelle"],
            "montant_patronal": float(l["montant_patronal"]),
            "montant_salarial": float(l["montant_salarial"]),
        })

    # Alertes SMIC
    alertes = []
    smic_mensuel = bar["smic_mensuel"]
    if brut_mensuel > 0 and brut_mensuel < smic_mensuel:
        alertes.append({
            "niveau": "haute",
            "message": f"ALERTE SMIC : Le salaire brut ({brut_mensuel:.2f} EUR) est inferieur au SMIC mensuel ({smic_mensuel:.2f} EUR). Ref: Art. L.3231-2 CT.",
        })

    return {
        "annee_baremes": annee,
        "smic_mensuel_ref": bar["smic_mensuel"],
        "pass_mensuel_ref": bar["pass_mensuel"],
        "brut_mensuel": brut_mensuel,
        "brut_effectif": brut_effectif,
        "retenue_absences": retenue_absences,
        "net_a_payer": float(res["net_avant_impot"]),
        "cout_total_employeur": float(res["cout_total_employeur"]),
        "total_patronal": float(res["total_patronal"]),
        "total_salarial": float(res["total_salarial"]),
        "lignes": lignes,
        "info_absences": info_absences,
        "alertes": alertes,
    }


@router.get("/api/simulation/micro-entrepreneur")
async def sim_micro(
    chiffre_affaires: float = Query(50000),
    activite: str = Query("prestations_bnc"),
    acre: bool = Query(False),
    nb_parts: float = Query(1, description="Nombre de parts fiscales du foyer"),
):
    ca = Decimal(str(chiffre_affaires))
    taux = {"vente_marchandises": Decimal("0.128"), "prestations_bic": Decimal("0.220"),
            "prestations_bnc": Decimal("0.224"), "liberal_cipav": Decimal("0.232")}
    t = taux.get(activite, Decimal("0.224"))
    if acre:
        t = t / 2
    cotisations = round(float(ca * t), 2)
    ir_forfait = {"vente_marchandises": Decimal("0.71"), "prestations_bic": Decimal("0.50"),
                  "prestations_bnc": Decimal("0.34"), "liberal_cipav": Decimal("0.34")}
    abat = ir_forfait.get(activite, Decimal("0.34"))
    revenu_imposable = round(float(ca * (1 - abat)), 2)
    # Calcul IR progressif par tranches (bareme 2026)
    ir_estim = _calculer_ir_simple(revenu_imposable, nb_parts)
    taux_moyen = round(ir_estim / revenu_imposable * 100, 2) if revenu_imposable > 0 else 0
    return {
        "chiffre_affaires": float(ca), "taux_cotisations": float(t),
        "cotisations_sociales": cotisations, "acre_applique": acre,
        "revenu_imposable": revenu_imposable, "impot_estime": ir_estim,
        "nb_parts": nb_parts, "taux_moyen_imposition": taux_moyen,
        "revenu_net": round(float(ca) - cotisations - ir_estim, 2),
    }


@router.get("/api/simulation/tns")
async def sim_tns(
    revenu_net: float = Query(40000),
    type_statut: str = Query("gerant_majoritaire"),
    acre: bool = Query(False),
):
    rev = Decimal(str(revenu_net))
    base = rev
    pass_annuel = Decimal("47100")  # PASS 2025 (confirme)

    # Maladie-maternite : taux progressif selon revenu
    # <= 45% PASS : taux reduit, > 45% PASS : 6.50%
    seuil_maladie_bas = pass_annuel * Decimal("0.45")
    if base <= seuil_maladie_bas:
        taux_maladie = Decimal("0.02")  # Taux reduit (bareme progressif)
    elif base <= pass_annuel:
        taux_maladie = Decimal("0.065")
    else:
        taux_maladie = Decimal("0.065")  # + 0.50% sur la part > 5 PASS (contribution equilibre)
    maladie = round(float(base * taux_maladie), 2)

    # Vieillesse base : 17.75% jusqu'a 1 PASS
    vieillesse_base = round(float(min(base, pass_annuel) * Decimal("0.1775")), 2)
    # Vieillesse complementaire : 7% jusqu'a 4 PASS
    plafond_compl = pass_annuel * 4
    vieillesse_compl = round(float(min(base, plafond_compl) * Decimal("0.07")), 2)
    # Invalidite-deces : 1.30% jusqu'a 1 PASS
    invalidite = round(float(min(base, pass_annuel) * Decimal("0.013")), 2)
    # Allocations familiales : taux progressif
    # <= 110% PASS : 0%, > 110% PASS et <= 140% PASS : progressif, > 140% PASS : 3.10%
    seuil_af_bas = pass_annuel * Decimal("1.10")
    seuil_af_haut = pass_annuel * Decimal("1.40")
    if base <= seuil_af_bas:
        af = 0.0
    elif base <= seuil_af_haut:
        # Taux progressif entre 0% et 3.10%
        ratio = (base - seuil_af_bas) / (seuil_af_haut - seuil_af_bas)
        af = round(float(base * ratio * Decimal("0.0310")), 2)
    else:
        af = round(float(base * Decimal("0.0310")), 2)

    # CSG/CRDS : 9.70% sur revenu + cotisations obligatoires
    csg_crds = round(float(base * Decimal("0.097")), 2)
    # Formation professionnelle : 0.25% du PASS (forfaitaire)
    formation = round(float(pass_annuel * Decimal("0.0025")), 2)

    total = maladie + vieillesse_base + vieillesse_compl + invalidite + af + csg_crds + formation
    if acre:
        total = round(total * 0.5, 2)
    return {
        "revenu_net": float(rev), "type_statut": type_statut,
        "maladie_maternite": maladie, "vieillesse_base": vieillesse_base,
        "vieillesse_complementaire": vieillesse_compl, "invalidite_deces": invalidite,
        "allocations_familiales": af, "csg_crds": csg_crds, "formation": formation,
        "total_cotisations": total, "acre_applique": acre,
        "pass_annuel_2026": float(pass_annuel),
    }


@router.get("/api/simulation/guso")
async def sim_guso(
    salaire_brut: float = Query(500),
    nb_heures: float = Query(8),
    type_contrat: str = Query("cddu"),
    est_artiste: bool = Query(True),
):
    """Simulation GUSO exhaustive: spectacle occasionnel, intermittents, artistes."""
    brut = Decimal(str(salaire_brut))
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    calc = ContributionRules(effectif_entreprise=1)
    res = calc.calculer_bulletin_complet(brut, est_cadre=False)
    # Cotisations specifiques spectacle
    conge_spectacle = round(float(brut * Decimal("0.155")), 2)  # 15.5% patronal
    medecine_travail = round(float(Decimal(str(nb_heures)) * Decimal("0.46")), 2)  # 0.46 EUR/h
    # Audiens prevoyance obligatoire spectacle
    audiens_prevoyance = round(float(brut * Decimal("0.015")), 2)  # 1.5% patronal
    audiens_sante = round(float(brut * Decimal("0.0082")), 2)  # 0.82% patronal complementaire sante
    # FCAP (Fonds commun d aide au placement - Pole emploi spectacle)
    fcap = round(float(brut * Decimal("0.005")), 2)  # 0.5% patronal
    # Chomage spectacle (annexe 8/10)
    taux_chomage_pat = Decimal("0.0405")
    if est_artiste:
        taux_chomage_pat = Decimal("0.0405")  # annexe 10
    chomage_spectacle = round(float(brut * taux_chomage_pat), 2)
    # CSG/CRDS salarie detail
    assiette_csg = float(brut * Decimal("0.9825"))
    csg_deductible = round(assiette_csg * 0.068, 2)
    csg_non_deductible = round(assiette_csg * 0.024, 2)
    crds = round(assiette_csg * 0.005, 2)
    total_csg_crds = round(csg_deductible + csg_non_deductible + crds, 2)
    # Total GUSO (toutes charges patronales + spectacle)
    total_guso = round(float(res["total_patronal"]) + conge_spectacle + medecine_travail + audiens_prevoyance + audiens_sante + fcap, 2)
    net_artiste = round(float(res["net_avant_impot"]) - audiens_prevoyance * 0.5, 2)  # part salariale Audiens
    return {
        "salaire_brut": float(brut), "nb_heures": nb_heures,
        "type_contrat": type_contrat.upper(),
        "est_artiste": est_artiste,
        "cotisations_patronales_urssaf": float(res["total_patronal"]),
        "conge_spectacle_15_5pct": conge_spectacle,
        "medecine_travail": medecine_travail,
        "audiens_prevoyance": audiens_prevoyance,
        "audiens_sante": audiens_sante,
        "fcap": fcap,
        "total_charges_guso": total_guso,
        "detail_csg_crds": {"csg_deductible_6_8": csg_deductible, "csg_non_deductible_2_4": csg_non_deductible, "crds_0_5": crds, "total": total_csg_crds},
        "net_artiste": net_artiste,
        "cout_total_employeur": round(float(brut) + total_guso, 2),
        "rappel": "GUSO: guichet unique spectacle occasionnel. Conge spectacle 15.5%, Audiens obligatoire, FCAP 0.5%. Annexe 8 (techniciens) / Annexe 10 (artistes) pour l assurance chomage.",
    }


@router.get("/api/simulation/impot-independant")
async def sim_ir(
    benefice: float = Query(40000),
    nb_parts: float = Query(1),
    autres_revenus: float = Query(0),
):
    rev = benefice + autres_revenus
    if nb_parts <= 0:
        nb_parts = 1
    qi = rev / nb_parts
    tranches = [(11294, 0), (28797, 0.11), (82341, 0.30), (177106, 0.41), (float("inf"), 0.45)]
    impot_qi = 0
    prev = 0
    for seuil, taux in tranches:
        if qi <= prev:
            break
        tranche = min(qi, seuil) - prev
        impot_qi += tranche * taux
        prev = seuil
    impot_total = round(impot_qi * nb_parts, 2)
    taux_moyen = round(impot_total / rev * 100, 2) if rev > 0 else 0
    return {
        "benefice": benefice, "autres_revenus": autres_revenus,
        "revenu_global": rev, "nb_parts": nb_parts,
        "quotient_familial": round(qi, 2),
        "impot_brut": impot_total,
        "taux_moyen_imposition": taux_moyen,
        "revenu_apres_impot": round(rev - impot_total, 2),
    }


# ======================================================================
# EPARGNE SALARIALE - Simulation & Contrats
# ======================================================================

@router.post("/api/simulation/epargne-salariale")
async def sim_epargne_salariale(
    type_dispositif: str = Form("pee"),
    masse_salariale_brute: str = Form("500000"),
    effectif: str = Form("10"),
    montant_verse: str = Form("10000"),
    abondement_pct: str = Form("100"),
    plafond_abondement: str = Form("0"),
    taux_forfait_social: str = Form("0"),
    benefice_net: str = Form("100000"),
):
    """Simulation epargne salariale : PEE, PERCO/PER, Interessement, Participation."""
    ms = float(masse_salariale_brute)
    eff = int(effectif)
    montant = float(montant_verse)
    abond_pct = float(abondement_pct)
    plaf_abond = float(plafond_abondement)
    tfs_override = float(taux_forfait_social)
    bn = float(benefice_net)
    td = type_dispositif.lower().strip()
    pass_annuel = 47100.0  # PASS 2025 (confirme)

    # Forfait social par defaut selon dispositif
    if tfs_override > 0:
        taux_fs = tfs_override / 100.0
    elif td in ("pee", "perco", "per"):
        taux_fs = 0.20 if eff >= 50 else 0.0
    elif td == "interessement":
        taux_fs = 0.20 if eff >= 250 else 0.0
    elif td == "participation":
        taux_fs = 0.20 if eff >= 50 else 0.0
    else:
        taux_fs = 0.20

    # Plafonds legaux
    plafonds = {
        "pee": {"versement_max_salarie": pass_annuel * 0.25, "abondement_max": pass_annuel * 8 / 100 * 100},
        "perco": {"versement_max_salarie": pass_annuel * 0.25, "abondement_max": pass_annuel * 16 / 100 * 100},
        "per": {"versement_max_salarie": pass_annuel * 0.25, "abondement_max": pass_annuel * 16 / 100 * 100},
        "interessement": {"plafond_global": ms * 0.20, "plafond_individuel": pass_annuel * 0.75},
        "participation": {"plafond_rsp": 0},
    }
    info_plafond = plafonds.get(td, {})

    # Calcul RSP (Reserve Speciale de Participation) si participation
    # Formule legale: RSP = 0.5 * (B - 5%*C) * S/VA (Art. L.3324-1 CT)
    # B=benefice net, C=capitaux propres, S=salaires, VA=valeur ajoutee
    rsp = 0
    if td == "participation" and bn > 0 and ms > 0:
        capitaux_propres = ms * 0.5  # estimation
        valeur_ajoutee = ms * 1.5  # estimation VA = masse salariale * 1.5
        rsp = round(max(0, 0.5 * (bn - 0.05 * capitaux_propres) * (ms / valeur_ajoutee)), 2)
        if montant == 0 or montant > rsp:
            montant = rsp
        info_plafond["plafond_rsp"] = rsp

    # Abondement
    abondement = round(montant * abond_pct / 100, 2)
    if plaf_abond > 0:
        abondement = min(abondement, plaf_abond)
    if td == "pee":
        abondement = min(abondement, pass_annuel * 8 / 100 * 100 / eff) if eff > 0 else abondement
    elif td in ("perco", "per"):
        abondement = min(abondement, pass_annuel * 16 / 100 * 100 / eff) if eff > 0 else abondement
    abondement_total = round(abondement * eff, 2) if td in ("pee", "perco", "per") else 0

    # Cout total pour l'entreprise
    montant_total = montant
    if td in ("interessement", "participation"):
        montant_total = montant  # prime globale
    forfait_social = round((montant_total + abondement_total) * taux_fs, 2)
    csg_crds_taux = 0.097  # 9.7% (CSG 9.2% + CRDS 0.5%)
    csg_crds = round(montant_total * csg_crds_taux, 2)

    cout_brut_entreprise = round(montant_total + abondement_total + forfait_social, 2)

    # Comparaison prime classique equivalente
    taux_charges_patronales = 0.45
    taux_charges_salariales = 0.22
    prime_brute_equiv = montant_total
    charges_patronales_prime = round(prime_brute_equiv * taux_charges_patronales, 2)
    charges_salariales_prime = round(prime_brute_equiv * taux_charges_salariales, 2)
    cout_prime_classique = round(prime_brute_equiv + charges_patronales_prime, 2)
    net_salarie_prime = round(prime_brute_equiv - charges_salariales_prime, 2)

    economie_entreprise = round(cout_prime_classique - cout_brut_entreprise, 2)
    economie_pct = round(economie_entreprise / cout_prime_classique * 100, 2) if cout_prime_classique > 0 else 0

    # Avantage fiscal entreprise (deductible IS)
    taux_is = 0.25
    deduction_is = round(cout_brut_entreprise * taux_is, 2)

    # Gain net salarie (pas de charges sociales hors CSG/CRDS, pas d'IR sur PEE/PERCO 5 ans)
    net_salarie_epargne = round(montant_total - csg_crds, 2)
    gain_salarie = round(net_salarie_epargne - net_salarie_prime, 2)

    return {
        "type_dispositif": td.upper(),
        "montant_verse": montant_total,
        "abondement_employeur": abondement_total,
        "taux_forfait_social": round(taux_fs * 100, 1),
        "forfait_social": forfait_social,
        "csg_crds_salarie": csg_crds,
        "cout_total_entreprise": cout_brut_entreprise,
        "deduction_is": deduction_is,
        "cout_net_apres_is": round(cout_brut_entreprise - deduction_is, 2),
        "comparaison_prime": {
            "prime_brute": prime_brute_equiv,
            "charges_patronales": charges_patronales_prime,
            "cout_total_prime": cout_prime_classique,
            "net_salarie_prime": net_salarie_prime,
        },
        "net_salarie_epargne": net_salarie_epargne,
        "economie_entreprise": economie_entreprise,
        "economie_entreprise_pct": economie_pct,
        "gain_net_salarie": gain_salarie,
        "plafonds_legaux": info_plafond,
        "effectif": eff,
        "masse_salariale": ms,
        "rappel_regles": {
            "pee": "Blocage 5 ans. Abondement max 8% PASS/salarie. Forfait social 20% (>=50 sal.) ou 0%.",
            "perco": "Blocage retraite. Abondement max 16% PASS/salarie. Forfait social 20% (>=50 sal.) ou 0%.",
            "per": "Blocage retraite (sortie capital/rente). Abondement max 16% PASS/salarie.",
            "interessement": "Accord 1-5 ans. Plafond 20% MS, 75% PASS/salarie. Forfait social 20% (>=250 sal.) ou 0%.",
            "participation": "Obligatoire >=50 sal. RSP = formule legale. Forfait social 20% (>=50 sal.) ou 0%.",
        }.get(td, ""),
    }


@router.post("/api/epargne-salariale/contrats")
async def creer_contrat_epargne(
    type_dispositif: str = Form("pee"),
    nom_contrat: str = Form(""),
    organisme: str = Form(""),
    date_mise_en_place: str = Form(""),
    duree_accord: str = Form("3"),
    montant_prevu: str = Form("0"),
    abondement_pct: str = Form("100"),
    plafond_abondement: str = Form("0"),
    beneficiaires: str = Form("tous"),
    observations: str = Form(""),
):
    """Creer un contrat/accord d'epargne salariale."""
    global _epargne_contrats
    import uuid as _uuid_ep
    contrat = {
        "id": str(_uuid_ep.uuid4())[:8],
        "type_dispositif": type_dispositif.upper(),
        "nom_contrat": nom_contrat or f"Accord {type_dispositif.upper()}",
        "organisme": organisme,
        "date_mise_en_place": date_mise_en_place,
        "duree_accord_ans": int(duree_accord),
        "montant_prevu": float(montant_prevu),
        "abondement_pct": float(abondement_pct),
        "plafond_abondement": float(plafond_abondement),
        "beneficiaires": beneficiaires,
        "observations": observations,
        "statut": "actif",
        "date_creation": datetime.now().isoformat(),
    }
    _epargne_contrats.append(contrat)
    return {"ok": True, "contrat": contrat, "total": len(_epargne_contrats)}


@router.get("/api/epargne-salariale/contrats")
async def lister_contrats_epargne():
    """Lister tous les contrats d'epargne salariale."""
    return {"contrats": _epargne_contrats, "total": len(_epargne_contrats)}


@router.delete("/api/epargne-salariale/contrats/{contrat_id}")
async def supprimer_contrat_epargne(contrat_id: str):
    """Supprimer un contrat d'epargne salariale."""
    global _epargne_contrats
    before = len(_epargne_contrats)
    _epargne_contrats = [c for c in _epargne_contrats if c["id"] != contrat_id]
    if len(_epargne_contrats) == before:
        return {"ok": False, "error": "Contrat non trouve"}
    return {"ok": True, "total": len(_epargne_contrats)}


# --- Simulation : Exonerations ---
@router.get("/api/simulation/exonerations")
async def sim_exonerations(
    brut_mensuel: float = Query(2500),
    effectif: int = Query(10),
    zone: str = Query("metropole"),
    statut_salarie: str = Query("standard"),
    age_salarie: int = Query(30),
    ccn: str = Query(""),
    duree_contrat_mois: int = Query(0),
    heures_supplementaires: float = Query(0),
    nb_heures_mensuelles: float = Query(151.67),
    # Nouveaux parametres pour calcul precis
    jours_absence: float = Query(0),
    type_absence: str = Query(""),
    temps_partiel_pct: float = Query(100),
    bareme_lodeom: str = Query("competitivite"),
    est_cadre: bool = Query(False),
    taux_at: float = Query(0),
    nb_salaries_simules: int = Query(1),
    annee: int = Query(2026, description="Annee de reference pour les baremes (2020-2026). Un document 2024 doit utiliser annee=2024."),
):
    """Simulation exhaustive des exonerations avec tous parametres de calcul.

    Le parametre 'annee' permet d'appliquer les baremes de la bonne periode :
    un bulletin 2024 utilise les taux 2024, un bulletin 2026 les taux 2026.
    """
    bar = _get_baremes_pour_annee(annee)
    smic_mensuel_ref = bar["smic_mensuel"]
    smic_horaire = bar["smic_horaire"]

    # Prorata temps partiel
    coeff_tp = max(0.01, min(temps_partiel_pct / 100.0, 1.0))
    heures_contrat = nb_heures_mensuelles * coeff_tp
    smic_mensuel = smic_mensuel_ref * coeff_tp

    # Prorata absences : on deduit les jours d'absence du SMIC reconstitue ET du brut
    jours_ouvres_mois = 21.67
    coeff_presence = max(0, (jours_ouvres_mois - jours_absence) / jours_ouvres_mois)
    smic_retabli = round(smic_mensuel * coeff_presence, 2)

    # Le brut doit aussi etre proratise pour les absences (coherent avec generer_bulletin)
    retenue_absences = round(brut_mensuel / jours_ouvres_mois * jours_absence, 2) if jours_absence > 0 else 0
    brut = round(brut_mensuel - retenue_absences, 2)
    ratio_smic = brut / smic_retabli if smic_retabli > 0 else 999

    exonerations = []
    total_exo = 0.0

    # === Taux patronaux detailles (selon annee selectionnee) ===
    seuil_maladie = bar["seuil_maladie_smic"]  # 2.5 SMIC (CSS art. D241-3-1)
    taux_maladie = bar["taux_maladie_reduit"] if ratio_smic <= seuil_maladie else bar["taux_maladie"]
    taux_vieillesse_plaf = bar["taux_vieillesse_plaf"]
    taux_vieillesse_deplaf = bar["taux_vieillesse_deplaf"]
    seuil_af = bar["seuil_af_smic"]  # 3.5 SMIC (CSS art. D241-3-1)
    taux_af = bar["taux_af_reduit"] if ratio_smic <= seuil_af else bar["taux_af"]
    taux_at_reel = taux_at if taux_at > 0 else bar["taux_at_moyen"]
    taux_fnal = bar["taux_fnal_moins_50"] if effectif < 50 else bar["taux_fnal_50_plus"]
    taux_csa = bar["taux_csa"]
    taux_chom = bar["taux_chomage"]
    taux_ags = bar["taux_ags"]
    taux_agirc = 0.1292 if est_cadre else 0.0786
    taux_pat_total = round(taux_maladie + taux_vieillesse_plaf + taux_vieillesse_deplaf + taux_af + taux_at_reel + taux_fnal + taux_csa + taux_chom + taux_ags + taux_agirc, 4)
    charges_normales = round(brut * taux_pat_total, 2)

    # 1. Reduction generale (Fillon <=2025 / RGDU 2026+) - baremes selon annee
    seuil_rgd = bar["seuil_rgd_smic"]  # 1.6 (<=2025) ou 3.0 (2026+)
    nom_red = bar["nom_reduction"]
    ref_red = bar["ref_reduction"]
    if ratio_smic <= seuil_rgd:
        if annee >= 2026:
            coeff_t = bar["rgdu_taux_max_moins_50"] if effectif < 50 else bar["rgdu_taux_max_50_plus"]
        else:
            # Fillon classique (<=2025) : T varie selon annee
            # 2020-2023: T = 0.3206/<50 ou 0.3246/>=50 (vieillesse deplaf 1.90%)
            # 2024-2025: T = 0.3194/<50 ou 0.3234/>=50 (vieillesse deplaf 2.02%)
            if annee <= 2023:
                coeff_t = 0.3206 if effectif < 50 else 0.3246
            else:
                coeff_t = 0.3194 if effectif < 50 else 0.3234
        # Diviseur = seuil_multiple - 1 : 0.6 pour Fillon (1.6 SMIC), 2.0 pour RGDU (3.0 SMIC)
        diviseur = (seuil_rgd - 1) if seuil_rgd > 0 else 0.6
        coeff = (coeff_t / diviseur) * (seuil_rgd * smic_retabli / brut - 1) if brut > 0 else 0
        coeff = max(0, min(coeff, coeff_t))
        montant_fillon = round(brut * coeff, 2)
        exonerations.append({"nom": nom_red, "reference": ref_red,
            "montant_mensuel": montant_fillon, "montant_annuel": round(montant_fillon * 12, 2),
            "conditions": f"Annee {annee}. Ratio SMIC: {ratio_smic:.3f} (seuil {seuil_rgd}). Coeff T={coeff_t}, coeff calcule={coeff:.5f}. "
                          f"SMIC retabli: {smic_retabli:.2f} EUR (presence {coeff_presence*100:.0f}%, TP {temps_partiel_pct:.0f}%). "
                          f"Heures contrat: {heures_contrat:.2f}h.", "applicable": True})
        total_exo += montant_fillon
    else:
        exonerations.append({"nom": nom_red, "reference": ref_red,
            "montant_mensuel": 0, "montant_annuel": 0,
            "conditions": f"Non applicable: ratio SMIC {ratio_smic:.3f} > {seuil_rgd} (annee {annee})", "applicable": False})

    # 2. Exoneration apprenti
    if statut_salarie == "apprenti":
        from urssaf_analyzer.rules.contribution_rules import ContributionRules as _CR2
        calc_app = _CR2(effectif_entreprise=effectif)
        detail_app = calc_app.calculer_exoneration_apprenti(Decimal(str(brut)))
        exo_app = round(detail_app["exoneration_salariale_mensuelle"] + detail_app["rgdu_patronale_mensuelle"], 2)
        exonerations.append({"nom": "Exoneration apprenti", "reference": "Art. L.6243-2 CT",
            "montant_mensuel": exo_app, "montant_annuel": round(exo_app * 12, 2),
            "conditions": f"Exo salariale <= 79% SMIC ({detail_app['seuil_79_smic']:.0f} EUR) + RGDU patronale. "
                          f"Aide unique: 6 000 EUR/an (diplome <= bac+5).",
            "applicable": True, "detail": detail_app})
        total_exo += exo_app

    # 3. Aide embauche jeune (-26 ans) - EXPIRE 31/05/2021 (Decret 2021-94)
    if age_salarie < 26 and brut <= smic_mensuel_ref * 2 and annee == 2021:
        aide_jeune = 333.33
        exonerations.append({"nom": "Aide embauche jeune (<26 ans)", "reference": "Decret 2021-94 (expire 31/05/2021)",
            "montant_mensuel": aide_jeune, "montant_annuel": round(aide_jeune * 12, 2),
            "conditions": "Salarie < 26 ans, brut <= 2 SMIC. Contrats conclus entre 01/08/2020 et 31/05/2021 uniquement.",
            "applicable": True})
        total_exo += aide_jeune

    # 4. Aide senior (+55 ans)
    if age_salarie >= 55:
        aide_senior = round(brut * 0.08, 2)
        exonerations.append({"nom": "CDD senior / CDI inclusion (+55 ans)", "reference": "Art. L.5134-19-1 CT",
            "montant_mensuel": aide_senior, "montant_annuel": round(aide_senior * 12, 2),
            "conditions": "Salarie >= 55 ans", "applicable": True})
        total_exo += aide_senior

    # 5. AGEFIPH (travailleur handicape)
    if statut_salarie == "handicape":
        aide_th = 250.0
        exonerations.append({"nom": "Aide AGEFIPH embauche TH", "reference": "Art. L.5212-9 CT",
            "montant_mensuel": aide_th, "montant_annuel": round(aide_th * 12, 2),
            "conditions": "Travailleur handicape RQTH", "applicable": True})
        total_exo += aide_th

    # 6. ZRR (Zone de Revitalisation Rurale)
    if zone == "zrr" and effectif < 50:
        exo_zrr = round(brut * 0.28, 2)
        exonerations.append({"nom": "Exoneration ZRR", "reference": "Art. 1465A CGI / Art. L.131-4-2 CSS",
            "montant_mensuel": exo_zrr, "montant_annuel": round(exo_zrr * 12, 2),
            "conditions": "Zone de Revitalisation Rurale, < 50 salaries, 12 mois", "applicable": True})
        total_exo += exo_zrr

    # 7. ZFU (Zone Franche Urbaine)
    if zone == "zfu":
        exo_zfu = round(brut * 0.32, 2)
        exonerations.append({"nom": "Exoneration ZFU-TE", "reference": "Art. 44 octies A CGI",
            "montant_mensuel": exo_zfu, "montant_annuel": round(exo_zfu * 12, 2),
            "conditions": "Zone Franche Urbaine - 5 ans degressif", "applicable": True})
        total_exo += exo_zfu

    # 8. QPV (Quartier Prioritaire Ville)
    if zone == "qpv" and effectif < 50:
        exo_qpv = round(min(brut * 0.28, smic_retabli * 1.4 * 0.28), 2)
        exonerations.append({"nom": "Exoneration QPV", "reference": "Art. L.131-4-3 CSS",
            "montant_mensuel": exo_qpv, "montant_annuel": round(exo_qpv * 12, 2),
            "conditions": f"Quartier prioritaire, < 50 sal, plafond 1.4 SMIC retabli ({smic_retabli*1.4:.2f} EUR)", "applicable": True})
        total_exo += exo_qpv

    # 9. Outre-mer (LODEOM) - 3 baremes distincts (Art. L.752-3-2 CSS)
    if zone == "outremer":
        # Taux total exonerable LODEOM (inclut chomage/AGS, Art. L.752-3-2 CSS)
        taux_lodeom_total = taux_maladie + taux_vieillesse_plaf + taux_vieillesse_deplaf + taux_af + taux_fnal + taux_csa + taux_at_reel + taux_chom + taux_ags
        if bareme_lodeom == "competitivite":
            # Bareme competitivite : exo totale <= 1.3 SMIC, degressive 1.3-2.2 SMIC
            if ratio_smic <= 1.3:
                exo_om = round(brut * taux_lodeom_total, 2)
                desc = "LODEOM competitivite - exoneration totale (<=1.3 SMIC)"
            elif ratio_smic <= 2.2:
                taux_degr = (2.2 - ratio_smic) / (2.2 - 1.3)
                taux_exo = round(0.28 * taux_degr, 4)
                exo_om = round(brut * taux_exo, 2)
                desc = f"LODEOM competitivite - degressif ({taux_degr*100:.0f}% entre 1.3 et 2.2 SMIC)"
            else:
                exo_om = 0
                desc = "LODEOM competitivite - hors plafond (>2.2 SMIC)"
        elif bareme_lodeom == "competitivite_renforcee":
            # Bareme comp. renforcee : exo totale <= 1.7 SMIC, degressive 1.7-2.7 SMIC
            if ratio_smic <= 1.7:
                exo_om = round(brut * taux_lodeom_total, 2)
                desc = "LODEOM comp. renforcee - exoneration totale (<=1.7 SMIC)"
            elif ratio_smic <= 2.7:
                taux_degr = (2.7 - ratio_smic) / (2.7 - 1.7)
                taux_exo = round(0.32 * taux_degr, 4)
                exo_om = round(brut * taux_exo, 2)
                desc = f"LODEOM comp. renforcee - degressif ({taux_degr*100:.0f}% entre 1.7 et 2.7 SMIC)"
            else:
                exo_om = 0
                desc = "LODEOM comp. renforcee - hors plafond (>2.7 SMIC)"
        elif bareme_lodeom == "innovation_croissance":
            # Bareme innovation et croissance : exo totale <= 2.0 SMIC, degressive 2.0-3.0 SMIC
            if ratio_smic <= 2.0:
                exo_om = round(brut * taux_lodeom_total, 2)
                desc = "LODEOM innovation/croissance - exoneration totale (<=2.0 SMIC)"
            elif ratio_smic <= 3.0:
                taux_degr = (3.0 - ratio_smic) / (3.0 - 2.0)
                taux_exo = round(0.32 * taux_degr, 4)
                exo_om = round(brut * taux_exo, 2)
                desc = f"LODEOM innovation/croissance - degressif ({taux_degr*100:.0f}% entre 2.0 et 3.0 SMIC)"
            else:
                exo_om = 0
                desc = "LODEOM innovation/croissance - hors plafond (>3.0 SMIC)"
        else:
            exo_om = round(brut * 0.28, 2)
            desc = "LODEOM bareme par defaut"
        exonerations.append({"nom": f"Exoneration outre-mer ({desc})", "reference": "Art. L.752-3-2 CSS (LODEOM)",
            "montant_mensuel": exo_om, "montant_annuel": round(exo_om * 12, 2),
            "conditions": f"Bareme: {bareme_lodeom}, effectif {effectif}, ratio SMIC {ratio_smic:.3f}. "
                          f"SMIC retabli: {smic_retabli:.2f} EUR.",
            "applicable": exo_om > 0})
        total_exo += exo_om

    # 10. JEI (Jeune Entreprise Innovante)
    if statut_salarie == "jei":
        # Plafond par salarie : 4.5 SMIC mensuel (Art. D.131-6-1 CSS, LFSS 2022)
        # Plafond annuel par etablissement : 5 PASS annuel
        smic_m_ref = bar["smic_mensuel"]
        plafond_jei = smic_m_ref * 4.5
        base_jei = min(brut, plafond_jei)
        taux_jei = taux_maladie + taux_vieillesse_plaf + taux_vieillesse_deplaf + taux_af + taux_fnal + taux_csa
        exo_jei = round(base_jei * taux_jei, 2)
        exonerations.append({"nom": "Exoneration JEI (Jeune Entreprise Innovante)", "reference": "Art. 44 sexies-0 A CGI, Art. D.131-6-1 CSS",
            "montant_mensuel": exo_jei, "montant_annuel": round(exo_jei * 12, 2),
            "conditions": f"Chercheurs, techniciens, mandataires - 8 ans max. Plafond salarie: 4.5 SMIC ({plafond_jei:.0f} EUR). "
                          f"Plafond etablissement: 5 PASS annuel. Hors AT/MP. Base: {base_jei:.2f} EUR, taux: {taux_jei*100:.2f}%.",
            "applicable": True})
        total_exo += exo_jei

    # 11. TEPA - Desocialisation des heures supplementaires
    if heures_supplementaires > 0:
        taux_horaire = round(brut_mensuel / heures_contrat, 2) if heures_contrat > 0 else 0
        # Majoration : 25% (1-8h), 50% (au-dela)
        hs_25 = min(heures_supplementaires, 8) * taux_horaire * 1.25
        hs_50 = max(0, heures_supplementaires - 8) * taux_horaire * 1.50
        montant_hs_total = round(hs_25 + hs_50, 2)
        exo_tepa_sal = round(montant_hs_total * 0.1131, 2)
        # Art. L.241-18 CSS : 1.50 EUR/h si < 20 sal, 0.50 EUR/h si 20-249 sal, 0 si >= 250
        deduc_pat_par_h = 1.50 if effectif < 20 else (0.50 if effectif < 250 else 0.0)
        exo_tepa_pat = round(heures_supplementaires * deduc_pat_par_h, 2)
        exo_ir_hs = round(min(montant_hs_total, 7500 / 12), 2)
        exonerations.append({
            "nom": "TEPA - Heures supplementaires defiscalisees",
            "reference": "Art. 81 quater CGI / Art. L.241-17 CSS",
            "montant_mensuel": round(exo_tepa_sal + exo_tepa_pat, 2),
            "montant_annuel": round((exo_tepa_sal + exo_tepa_pat) * 12, 2),
            "applicable": True,
            "conditions": f"{heures_supplementaires:.1f}h HS/mois, taux horaire {taux_horaire:.2f} EUR. "
                          f"Reduction salariale: {exo_tepa_sal:.2f} EUR, deduction patronale: {exo_tepa_pat:.2f} EUR. "
                          f"Exoneration IR: {exo_ir_hs:.2f} EUR/mois (plafond 7500 EUR/an). "
                          f"Contingent annuel 220h (Art. D.3121-24 CT).",
            "detail": {"heures_sup": heures_supplementaires, "montant_hs_brut": montant_hs_total,
                "reduction_salariale": exo_tepa_sal, "deduction_patronale": exo_tepa_pat, "exoneration_ir": exo_ir_hs},
        })
        total_exo += exo_tepa_sal + exo_tepa_pat
    else:
        exonerations.append({"nom": "TEPA - Heures supplementaires defiscalisees",
            "reference": "Art. 81 quater CGI / Art. L.241-17 CSS",
            "montant_mensuel": 0, "montant_annuel": 0, "applicable": False,
            "conditions": "Pas d heures supplementaires renseignees."})

    # 12. BER (Bassin d'Emploi a Redynamiser)
    if zone == "ber":
        exo_ber = round(brut * 0.32, 2)
        exonerations.append({"nom": "Exoneration BER (Bassin d Emploi a Redynamiser)",
            "reference": "Art. L.131-4-4 CSS / Art. 44 duodecies CGI",
            "montant_mensuel": exo_ber, "montant_annuel": round(exo_ber * 12, 2), "applicable": True,
            "conditions": "Exoneration totale cotisations patronales 5 ans (Ariege, Pyrenees-Orientales)."})
        total_exo += exo_ber

    # 13. Contrat professionnalisation
    if statut_salarie == "contrat_pro" or (age_salarie >= 45 and duree_contrat_mois > 0):
        exo_pro = round(brut * 0.28, 2) if age_salarie >= 45 else round(brut * 0.15, 2)
        exonerations.append({"nom": "Aide contrat de professionnalisation",
            "reference": "Art. L.6325-16 CT / Art. D.6325-21 CT",
            "montant_mensuel": exo_pro, "montant_annuel": round(exo_pro * 12, 2), "applicable": True,
            "conditions": f"Age: {age_salarie} ans. " + ("Aide renforcee (+45 ans)." if age_salarie >= 45 else "Aide standard.")})
        total_exo += exo_pro

    # 14. ACRE (Aide aux Createurs et Repreneurs d Entreprise)
    if statut_salarie == "acre":
        from urssaf_analyzer.rules.contribution_rules import ContributionRules as _CR3
        calc_acre = _CR3(effectif_entreprise=effectif)
        detail_acre = calc_acre.calculer_exoneration_acre(Decimal(str(brut)))
        exo_acre = round(detail_acre["exoneration_mensuelle"], 2)
        exonerations.append({"nom": "ACRE (Aide aux Createurs/Repreneurs)",
            "reference": detail_acre.get("ref", "Art. L.131-6-4 CSS"),
            "montant_mensuel": exo_acre, "montant_annuel": round(exo_acre * 12, 2),
            "applicable": detail_acre["eligible"],
            "conditions": f"Exoneration {detail_acre.get('taux_exoneration', 0)*100:.0f}% cotisations patronales SS. "
                          f"Seuil bas: {detail_acre.get('seuil_bas_1_2_smic', 0):.0f} EUR, haut: {detail_acre.get('seuil_haut_1_6_smic', 0):.0f} EUR.",
            "detail": detail_acre})
        total_exo += exo_acre

    # 15. ZRD (Zone de Restructuration de la Defense)
    if zone == "zrd":
        exo_zrd = round(min(brut * 0.28, smic_retabli * 1.4 * 0.28), 2)
        exonerations.append({"nom": "Exoneration ZRD (Restructuration Defense)",
            "reference": "Art. 44 terdecies CGI / Art. L.131-4-5 CSS",
            "montant_mensuel": exo_zrd, "montant_annuel": round(exo_zrd * 12, 2), "applicable": True,
            "conditions": "Exoneration 5 ans + 3 ans degressif. Plafond 1.4 SMIC."})
        total_exo += exo_zrd

    # 16. AFR (Aide a la Finalite Regionale)
    if zone == "afr":
        exo_afr = round(brut * 0.20, 2)
        exonerations.append({"nom": "Exoneration AFR",
            "reference": "Art. 44 quindecies CGI",
            "montant_mensuel": exo_afr, "montant_annuel": round(exo_afr * 12, 2), "applicable": True,
            "conditions": "Zone a finalite regionale. Exoneration partielle cotisations."})
        total_exo += exo_afr

    # 17. Emplois francs (embauche d'un resident QPV)
    if zone == "qpv" and statut_salarie == "emploi_franc":
        # CDI : 5000 EUR/an pendant 3 ans = 416.67 EUR/mois
        # CDD >= 6 mois : 2500 EUR/an pendant 2 ans = 208.33 EUR/mois
        aide_ef_annuelle = 5000 if duree_contrat_mois == 0 or duree_contrat_mois >= 12 else 2500
        aide_ef_mois = round(aide_ef_annuelle / 12, 2)
        duree_ef = "3 ans (CDI)" if aide_ef_annuelle == 5000 else "2 ans (CDD >= 6 mois)"
        exonerations.append({"nom": "Emploi franc (QPV)",
            "reference": "Decret 2019-1471 / Art. L.5134-66 CT",
            "montant_mensuel": aide_ef_mois, "montant_annuel": aide_ef_annuelle, "applicable": True,
            "conditions": f"Embauche d un resident QPV. Aide {aide_ef_annuelle:.0f} EUR/an pendant {duree_ef}. "
                          f"Cumulable avec la reduction generale et les aides a l insertion."})
        total_exo += aide_ef_mois

    # === REGLES DE NON-CUMUL DES EXONERATIONS ===
    # Certaines exonerations sont mutuellement exclusives (Art. L.131-4-2, L.131-4-3 CSS)
    _NON_CUMUL_GROUPS = {
        "zone": ["Exoneration ZRR", "Exoneration ZFU-TE", "Exoneration QPV",
                 "Exoneration BER", "Exoneration AFR", "Exoneration ZRD"],
        "generale_vs_zone": [nom_red],
    }
    # La reduction generale n'est pas cumulable avec les exo de zone, JEI, LODEOM, ACRE (Art. L.241-13 IX CSS)
    _INCOMPATIBLES_FILLON = [
        "Exoneration ZRR", "Exoneration ZFU-TE", "Exoneration QPV",
        "Exoneration BER", "Exoneration ZRD", "Exoneration AFR",
        "Exoneration JEI (Jeune Entreprise Innovante)",
        "ACRE (Aide aux Createurs/Repreneurs)",
    ]
    # Ajouter les exonerations LODEOM dynamiquement
    for e in exonerations:
        if e["nom"].startswith("Exoneration outre-mer") and e["nom"] not in _INCOMPATIBLES_FILLON:
            _INCOMPATIBLES_FILLON.append(e["nom"])
    # ACRE non cumulable avec JEI
    _INCOMPATIBLES_ACRE = ["Exoneration JEI (Jeune Entreprise Innovante)"]

    # Detecter les exo applicables
    noms_applicables = [e["nom"] for e in exonerations if e.get("applicable") and e.get("montant_mensuel", 0) > 0]

    # Appliquer les regles de non-cumul
    exo_desactivees = set()

    # 1. Exonerations de zone mutuellement exclusives: garder la plus avantageuse
    zone_exos = [e for e in exonerations if e["nom"] in _NON_CUMUL_GROUPS["zone"] and e.get("applicable") and e.get("montant_mensuel", 0) > 0]
    if len(zone_exos) > 1:
        zone_exos.sort(key=lambda e: e.get("montant_mensuel", 0), reverse=True)
        for e in zone_exos[1:]:
            exo_desactivees.add(e["nom"])

    # 2. Reduction generale vs exonerations specifiques
    has_fillon = any(e["nom"] == nom_red and e.get("applicable") and e.get("montant_mensuel", 0) > 0 for e in exonerations)
    exos_specifiques = [e for e in exonerations if e["nom"] in _INCOMPATIBLES_FILLON and e.get("applicable") and e.get("montant_mensuel", 0) > 0]
    if has_fillon and exos_specifiques:
        fillon = next((e for e in exonerations if e["nom"] == nom_red), None)
        best_specific = max(exos_specifiques, key=lambda e: e.get("montant_mensuel", 0))
        if fillon and best_specific["montant_mensuel"] >= fillon["montant_mensuel"]:
            exo_desactivees.add(nom_red)
        else:
            for e in exos_specifiques:
                exo_desactivees.add(e["nom"])

    # 3. ACRE vs JEI
    has_acre = any(e["nom"] == "ACRE (Aide aux Createurs/Repreneurs)" and e.get("applicable") and e.get("montant_mensuel", 0) > 0 for e in exonerations)
    has_jei = any(e["nom"] == "Exoneration JEI (Jeune Entreprise Innovante)" and e.get("applicable") and e.get("montant_mensuel", 0) > 0 for e in exonerations)
    if has_acre and has_jei:
        acre_m = next((e for e in exonerations if "ACRE" in e["nom"]), None)
        jei_m = next((e for e in exonerations if "JEI" in e["nom"]), None)
        if acre_m and jei_m and jei_m.get("montant_mensuel", 0) >= acre_m.get("montant_mensuel", 0):
            exo_desactivees.add("ACRE (Aide aux Createurs/Repreneurs)")
        elif acre_m and jei_m:
            exo_desactivees.add("Exoneration JEI (Jeune Entreprise Innovante)")

    # Recalculer le total en tenant compte des non-cumuls
    total_exo = 0.0
    for e in exonerations:
        if e["nom"] in exo_desactivees:
            e["applicable"] = False
            e["conditions"] = (e.get("conditions", "") or "") + " [NON CUMULABLE - desactivee au profit d'une exoneration plus avantageuse]"
            e["montant_mensuel"] = 0
            e["montant_annuel"] = 0
        if e.get("applicable") and e.get("montant_mensuel", 0) > 0:
            total_exo += e["montant_mensuel"]

    # Impact des absences sur cotisations
    info_absences = {}
    if jours_absence > 0:
        ijss = 0
        complement = 0
        # Les IJSS se calculent sur le salaire de reference (brut_mensuel contractuel)
        if type_absence == "maladie":
            ijss = round(min(brut_mensuel / 30.42, smic_mensuel_ref / 30.42 * 1.8) * 0.5 * jours_absence, 2)
            # Complement employeur apres carence 7j (Art. L.1226-1 CT)
            jours_complement = max(0, jours_absence - 7)
            complement = round((brut_mensuel / 30.42) * 0.9 * min(jours_complement, 30), 2)
        elif type_absence == "maternite":
            ijss = round(min(brut_mensuel / 30.42, smic_mensuel_ref / 30.42 * 1.8) * jours_absence, 2)
        elif type_absence == "at_mp":
            ijss = round((brut_mensuel / 30.42) * 0.6 * min(jours_absence, 28) + (brut_mensuel / 30.42) * 0.8 * max(0, jours_absence - 28), 2)
        elif type_absence == "conge_sans_solde":
            ijss = 0
        info_absences = {
            "type": type_absence if type_absence else "non_precise", "jours": jours_absence,
            "retenue_absences": retenue_absences,
            "brut_contractuel": brut_mensuel, "brut_apres_absences": brut,
            "ijss_estimees": ijss, "complement_employeur": complement,
            "impact_smic_retabli": f"SMIC retabli de {smic_mensuel:.2f} a {smic_retabli:.2f} EUR",
            "impact_ratio": f"Ratio SMIC ajuste: {ratio_smic:.3f}",
        }

    charges_apres_exo = round(max(0, charges_normales - total_exo), 2)

    # Multi-salaries : multiplication
    if nb_salaries_simules > 1:
        total_exo_multi = round(total_exo * nb_salaries_simules, 2)
        charges_normales_multi = round(charges_normales * nb_salaries_simules, 2)
        charges_apres_exo_multi = round(charges_apres_exo * nb_salaries_simules, 2)
    else:
        total_exo_multi = round(total_exo, 2)
        charges_normales_multi = charges_normales
        charges_apres_exo_multi = charges_apres_exo

    return {
        "annee_baremes": annee,
        "baremes_appliques": f"Baremes {annee} (SMIC {smic_mensuel_ref:.2f} EUR, PASS {bar['pass_mensuel']:.2f} EUR)",
        "brut_mensuel": brut, "brut_contractuel": brut_mensuel, "effectif": effectif, "zone": zone, "statut_salarie": statut_salarie,
        "ratio_smic": round(ratio_smic, 3), "smic_retabli": smic_retabli,
        "smic_mensuel_ref": smic_mensuel_ref,
        "heures_contrat": round(heures_contrat, 2),
        "temps_partiel_pct": temps_partiel_pct,
        "jours_absence": jours_absence, "type_absence": type_absence,
        "coeff_presence": round(coeff_presence, 4),
        "bareme_lodeom": bareme_lodeom if zone == "outremer" else None,
        "est_cadre": est_cadre, "taux_at": taux_at_reel,
        "nb_salaries": nb_salaries_simules,
        "taux_patronal_detaille": {
            "maladie": taux_maladie, "vieillesse_plafonnee": taux_vieillesse_plaf,
            "vieillesse_deplafonnee": taux_vieillesse_deplaf, "allocations_familiales": taux_af,
            "at_mp": taux_at_reel, "fnal": taux_fnal, "csa": taux_csa,
            "chomage": taux_chom, "ags": taux_ags,
            "retraite_complementaire": taux_agirc, "total": taux_pat_total,
            "seuil_maladie_reduit": f"{seuil_maladie} SMIC",
            "seuil_af_reduit": f"{seuil_af} SMIC",
        },
        "exonerations": exonerations,
        "total_exonerations_mensuelles": round(total_exo, 2),
        "total_exonerations_annuelles": round(total_exo * 12, 2),
        "charges_patronales_normales": charges_normales,
        "charges_patronales_apres_exo": charges_apres_exo,
        "economie_pct": round(total_exo / charges_normales * 100, 2) if charges_normales > 0 else 0,
        "info_absences": info_absences if info_absences else None,
        "multi_salaries": {
            "nb": nb_salaries_simules,
            "total_exonerations_mensuelles": total_exo_multi,
            "total_exonerations_annuelles": round(total_exo_multi * 12, 2),
            "charges_normales_totales": charges_normales_multi,
            "charges_apres_exo_totales": charges_apres_exo_multi,
        } if nb_salaries_simules > 1 else None,
    }


# --- Simulation : Temps partiel ---
@router.get("/api/simulation/temps-partiel")
async def sim_temps_partiel(
    brut_mensuel: float = Query(1500),
    heures_mensuelles: float = Query(104),
    effectif: int = Query(10),
    est_cadre: bool = Query(False),
):
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    calc = ContributionRules(effectif_entreprise=effectif)
    res = calc.calculer_bulletin_temps_partiel(
        Decimal(str(brut_mensuel)), Decimal(str(heures_mensuelles)), est_cadre=est_cadre,
    )
    return res


# --- Simulation : Convention collective (legal vs conventionnel) ---
@router.get("/api/simulation/ccn")
async def sim_ccn(
    ccn: str = Query("", description="Code CCN (syntec, metallurgie...) ou numero IDCC (1486, 3248...)"),
    brut_mensuel: float = Query(3000, description="Salaire brut mensuel du salarie (EUR)"),
    est_cadre: bool = Query(False, description="Le salarie est-il cadre ?"),
    effectif: int = Query(10, description="Effectif total de l entreprise"),
):
    """Simulation des obligations conventionnelles vs legales.

    Compare les minimums legaux (Code du travail, ANI) avec les obligations
    specifiques de la convention collective applicable. Utilise la base IDCC
    de 60+ conventions couvrant ~90% des salaries.
    """
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    from urssaf_analyzer.config.idcc_database import (
        IDCC_DATABASE, get_ccn_par_idcc, get_prevoyance_par_idcc, rechercher_idcc,
    )

    calc = ContributionRules(effectif_entreprise=effectif)
    bulletin = calc.calculer_bulletin_complet(Decimal(str(brut_mensuel)), est_cadre=est_cadre)

    # Chercher la CCN : par code interne, par IDCC, ou par recherche texte
    ccn_data = None
    idcc = ""
    if ccn:
        # 1. Par IDCC numerique
        ccn_data = get_ccn_par_idcc(ccn)
        if ccn_data:
            idcc = ccn.zfill(4)
        else:
            # 2. Par code interne (syntec, metallurgie...)
            prevoyance = calc.get_prevoyance_ccn(ccn, est_cadre=est_cadre)
            if prevoyance.get("ccn_connue"):
                idcc = prevoyance.get("idcc", "")
                ccn_data = get_ccn_par_idcc(idcc) if idcc else None
            else:
                # 3. Par recherche textuelle
                resultats = rechercher_idcc(ccn)
                if resultats:
                    idcc = resultats[0]["idcc"]
                    ccn_data = get_ccn_par_idcc(idcc)

    # Taux prevoyance
    if ccn_data:
        taux_prev = float(ccn_data["prevoyance_cadre"] if est_cadre else ccn_data["prevoyance_non_cadre"])
        nom_ccn = ccn_data["nom"]
        mut_min = ccn_data.get("mutuelle_employeur_min_pct", 50)
    else:
        taux_prev = 0.015 if est_cadre else 0
        nom_ccn = "Convention non identifiee - minimums legaux appliques"
        mut_min = 50

    cout_prev = round(brut_mensuel * taux_prev, 2)

    # Salaire minimum conventionnel
    smic_mensuel = float(_SMIC_MENSUEL)
    salaire_min_conv = None
    alerte_salaire_minimum = None
    if ccn_data:
        if est_cadre and ccn_data.get("salaire_minimum_cadre"):
            salaire_min_conv = float(ccn_data["salaire_minimum_cadre"])
        elif ccn_data.get("salaire_minimum_conventionnel"):
            salaire_min_conv = float(ccn_data["salaire_minimum_conventionnel"])

    if salaire_min_conv and brut_mensuel < salaire_min_conv:
        alerte_salaire_minimum = {
            "niveau": "haute",
            "message": f"ALERTE MINIMUM CONVENTIONNEL : Le salaire brut ({brut_mensuel:.2f} EUR) est inferieur "
                       f"au minimum conventionnel ({salaire_min_conv:.2f} EUR) pour {'un cadre' if est_cadre else 'un non-cadre'} "
                       f"de la CCN {nom_ccn}. Ref: Art. L.2253-1 CT (principe de faveur).",
        }
    elif brut_mensuel < smic_mensuel:
        alerte_salaire_minimum = {
            "niveau": "haute",
            "message": f"ALERTE SMIC : Le salaire brut ({brut_mensuel:.2f} EUR) est inferieur "
                       f"au SMIC mensuel ({smic_mensuel:.2f} EUR). Ref: Art. L.3231-2 CT.",
        }

    # Obligations conventionnelles specifiques
    obligations_conv = []
    if ccn_data:
        # Salaire minimum conventionnel en premier
        if salaire_min_conv:
            obligations_conv.append({
                "obligation": "Salaire minimum conventionnel",
                "conventionnel": f"{salaire_min_conv:.2f} EUR/mois ({'cadre' if est_cadre else 'non-cadre'})",
                "legal": f"SMIC : {smic_mensuel:.2f} EUR/mois (Art. L.3231-2 CT)",
                "plus_favorable": salaire_min_conv > smic_mensuel,
            })
        if ccn_data.get("maintien_salaire_jours"):
            obligations_conv.append({
                "obligation": "Maintien de salaire maladie",
                "conventionnel": f"{ccn_data['maintien_salaire_jours']} jours",
                "legal": "30 jours apres 1 an anciennete (art. L.1226-1 CT)",
                "plus_favorable": ccn_data["maintien_salaire_jours"] > 30,
            })
        if ccn_data.get("prime_anciennete"):
            obligations_conv.append({
                "obligation": "Prime d anciennete",
                "conventionnel": "Oui (baremes conventionnels)",
                "legal": "Pas d obligation legale",
                "plus_favorable": True,
            })
        if ccn_data.get("conges_anciennete"):
            obligations_conv.append({
                "obligation": "Conges supplementaires anciennete",
                "conventionnel": "Oui (jours sup. selon anciennete)",
                "legal": "2.5 jours/mois uniquement (art. L.3141-3 CT)",
                "plus_favorable": True,
            })
        if ccn_data.get("indemnite_depart_retraite_majoree"):
            obligations_conv.append({
                "obligation": "Indemnite de depart retraite",
                "conventionnel": "Majoree par la CCN",
                "legal": "1/4 mois par annee <= 10 ans, 1/3 au-dela (art. D.1237-1 CT)",
                "plus_favorable": True,
            })
        if ccn_data.get("indemnite_licenciement_majoree") or ccn_data.get("indemnite_licenciement_specifique"):
            obligations_conv.append({
                "obligation": "Indemnite de licenciement",
                "conventionnel": "Majoree/specifique par la CCN",
                "legal": "1/4 mois par annee <= 10 ans, 1/3 au-dela (art. R.1234-2 CT)",
                "plus_favorable": True,
            })
        if ccn_data.get("prime_vacances"):
            obligations_conv.append({
                "obligation": "Prime de vacances",
                "conventionnel": "Oui (obligatoire)",
                "legal": "Pas d obligation legale",
                "plus_favorable": True,
            })
        if ccn_data.get("avantage_nature_repas"):
            obligations_conv.append({
                "obligation": "Avantage en nature repas",
                "conventionnel": "Repas fourni ou indemnite compensatrice",
                "legal": "Evaluation forfaitaire (art. 3 arrete 10/12/2002)",
                "plus_favorable": True,
            })
        if ccn_data.get("jours_feries_garantis"):
            obligations_conv.append({
                "obligation": "Jours feries garantis",
                "conventionnel": f"{ccn_data['jours_feries_garantis']} jours feries payes garantis",
                "legal": "Seul le 1er mai est obligatoirement chome et paye (art. L.3133-6 CT)",
                "plus_favorable": True,
            })
        if ccn_data.get("13eme_mois"):
            obligations_conv.append({
                "obligation": "13eme mois",
                "conventionnel": "Obligatoire",
                "legal": "Pas d obligation legale",
                "plus_favorable": True,
            })
        if ccn_data.get("transfert_personnel_article7"):
            obligations_conv.append({
                "obligation": "Transfert de personnel (art. 7)",
                "conventionnel": "Reprise obligatoire du personnel lors de changement de prestataire",
                "legal": "Pas d obligation legale generale (sauf art. L.1224-1 CT si transfert d entite)",
                "plus_favorable": True,
            })
        if ccn_data.get("duree_travail_specifique"):
            obligations_conv.append({
                "obligation": "Duree du travail specifique",
                "conventionnel": "Regles specifiques (temps de conduite, repos, amplitudes)",
                "legal": "35h/sem. (art. L.3121-27 CT)",
                "plus_favorable": None,
            })
        if ccn_data.get("regime_special"):
            obligations_conv.append({
                "obligation": "Regime special de retraite",
                "conventionnel": f"Regime special: {ccn_data['regime_special'].upper()}",
                "legal": "Regime general CNAV",
                "plus_favorable": None,
            })
        if ccn_data.get("indemnite_fin_mission"):
            obligations_conv.append({
                "obligation": "Indemnite de fin de mission",
                "conventionnel": f"{float(ccn_data['indemnite_fin_mission'])*100:.0f}% du brut",
                "legal": "10% (art. L.1251-32 CT)",
                "plus_favorable": float(ccn_data["indemnite_fin_mission"]) >= 0.10,
            })

    # Obligations legales communes (toujours presentes)
    obligations_leg = [
        {"obligation": "Salaire minimum (SMIC)", "legal": f"{smic_mensuel:.2f} EUR/mois brut (Art. L.3231-2 CT)"},
        {"obligation": "Prevoyance cadres", "legal": "1.50% TA patronal (ANI 2017 / art. 7 CCN 1947)", "conventionnel": f"{taux_prev*100:.2f}%"},
        {"obligation": "Mutuelle obligatoire", "legal": "50% minimum part employeur (ANI 2013 / art. L.911-7 CSS)", "conventionnel": f"{mut_min}%"},
        {"obligation": "Indemnite licenciement", "legal": "1/4 mois/an <= 10 ans, 1/3 au-dela (art. R.1234-2 CT)"},
        {"obligation": "Preavis", "legal": "1 mois (1-2 ans anc.), 2 mois (>2 ans) - art. L.1234-1 CT"},
        {"obligation": "Conges payes", "legal": "2.5 jours ouvrables/mois (art. L.3141-3 CT)"},
    ]

    return {
        "ccn_identifiee": ccn_data is not None,
        "idcc": idcc,
        "nom_ccn": nom_ccn,
        "secteur": ccn_data.get("secteur", "") if ccn_data else "",
        "salaire_minimum_conventionnel": salaire_min_conv,
        "smic_mensuel": smic_mensuel,
        "alerte_salaire_minimum": alerte_salaire_minimum,
        "bulletin": {
            "brut_mensuel": float(bulletin["brut_mensuel"]),
            "total_patronal": float(bulletin["total_patronal"]),
            "total_salarial": float(bulletin["total_salarial"]),
            "net_avant_impot": float(bulletin["net_avant_impot"]),
            "cout_total_employeur": float(bulletin["cout_total_employeur"]),
        },
        "prevoyance_ccn": {
            "taux": taux_prev,
            "montant_mensuel": cout_prev,
            "montant_annuel": round(cout_prev * 12, 2),
        },
        "obligations_conventionnelles": obligations_conv,
        "obligations_legales": obligations_leg,
        "nb_obligations_plus_favorables": sum(1 for o in obligations_conv if o.get("plus_favorable") is True),
        "rappel": "Principe de faveur : la convention collective s applique si plus favorable que la loi (art. L.2251-1 CT). Verifiez toujours la CCN applicable.",
    }


@router.get("/api/simulation/recherche-ccn")
async def recherche_ccn(terme: str = Query("", description="Recherche par IDCC, nom ou secteur")):
    """Recherche dans la base de 60+ conventions collectives nationales.

    Accepte : numero IDCC (ex: 1486), nom (ex: syntec), secteur (ex: batiment).
    """
    from urssaf_analyzer.config.idcc_database import rechercher_idcc, IDCC_DATABASE
    if not terme:
        # Retourner toute la base
        result = []
        for idcc, data in sorted(IDCC_DATABASE.items()):
            result.append({
                "idcc": idcc,
                "nom": data["nom"],
                "secteur": data.get("secteur", ""),
            })
        return {"total": len(result), "resultats": result}
    resultats = rechercher_idcc(terme)
    # Serialiser les Decimal
    for r in resultats:
        for k, v in list(r.items()):
            if isinstance(v, Decimal):
                r[k] = float(v)
    return {"total": len(resultats), "resultats": resultats}


# --- Simulation : Identification CCN ---
@router.get("/api/simulation/identifier-ccn")
async def sim_identifier_ccn(texte: str = Query("")):
    """Identifie une CCN a partir d un texte libre (intitule, IDCC, mots-cles, code NAF)."""
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    from urssaf_analyzer.config.idcc_database import rechercher_idcc, IDCC_DATABASE
    # 1. Chercher dans la base IDCC complete
    resultats = rechercher_idcc(texte)
    if resultats:
        top = resultats[0]
        for k, v in list(top.items()):
            if isinstance(v, Decimal):
                top[k] = float(v)
        return {"identifie": True, "idcc": top["idcc"], "detail": top, "autres_resultats": len(resultats) - 1}
    # 2. Fallback sur le matching par mots-cles
    calc = ContributionRules()
    code = calc.identifier_ccn(texte)
    if code:
        prevoyance = calc.get_prevoyance_ccn(code)
        return {"identifie": True, "code": code, "detail": prevoyance}
    return {
        "identifie": False,
        "code": None,
        "suggestion": f"CCN non reconnue. {len(IDCC_DATABASE)} conventions disponibles. Essayez un numero IDCC ou un mot-cle (batiment, metallurgie, commerce...)",
    }


# --- Simulation : Cout total employeur ---
@router.get("/api/simulation/cout-employeur")
async def sim_cout_employeur(
    brut_mensuel: float = Query(2500, description="Salaire brut mensuel du salarie simule (EUR)"),
    effectif: int = Query(10, description="Effectif total de l entreprise (pour formation, effort construction, participation)"),
    est_cadre: bool = Query(False, description="Le salarie simule est-il cadre ?"),
    avantages_nature: float = Query(0, description="Avantages en nature mensuels (EUR)"),
    frais_km: float = Query(0, description="Frais kilometriques mensuels (EUR)"),
    primes: float = Query(0, description="Primes mensuelles (EUR)"),
    tickets_restaurant: float = Query(0, description="Tickets restaurant mensuels (EUR)"),
    mutuelle_employeur: float = Query(40, description="Part employeur mutuelle mensuelle (EUR)"),
    annee: int = Query(2026, description="Annee de reference pour les baremes (2020-2026)"),
):
    bar = _get_baremes_pour_annee(annee)
    brut = brut_mensuel + primes
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    calc = ContributionRules(effectif_entreprise=effectif)
    res = calc.calculer_bulletin_complet(Decimal(str(brut)), est_cadre=est_cadre)

    # Charges patronales detaillees
    pat = float(res["total_patronal"])
    sal = float(res["total_salarial"])
    net = float(res["net_avant_impot"])

    # Contribution formation (taux selon annee)
    taux_formation = bar["taux_formation_moins_11"] if effectif < 11 else bar["taux_formation_11_plus"]
    formation = round(brut * taux_formation, 2)
    # Taxe apprentissage
    taxe_apprentissage = round(brut * bar["taux_taxe_apprentissage"], 2)
    # Effort construction (PEEC >= 20 salaries, art. L313-1 CCH)
    effort_construction = round(brut * 0.0045, 2) if effectif >= 20 else 0
    # Participation (>= 50)
    participation_oblig = round(brut * 0.005, 2) if effectif >= 50 else 0

    cout_annexes = formation + taxe_apprentissage + effort_construction + participation_oblig
    cout_avantages = avantages_nature + tickets_restaurant + mutuelle_employeur

    cout_total = round(brut + pat + cout_annexes + cout_avantages + frais_km, 2)
    ratio_cout = round(cout_total / net, 2) if net > 0 else 0

    return {
        "annee_baremes": annee,
        "brut_mensuel": brut_mensuel, "primes": primes, "brut_total": brut,
        "charges_patronales_urssaf": pat, "charges_salariales": sal, "net_a_payer": net,
        "formation_professionnelle": formation, "taxe_apprentissage": taxe_apprentissage,
        "effort_construction": effort_construction, "participation_obligatoire": participation_oblig,
        "total_charges_annexes": cout_annexes,
        "avantages_nature": avantages_nature, "frais_km_rembourses": frais_km,
        "tickets_restaurant": tickets_restaurant, "mutuelle_employeur": mutuelle_employeur,
        "total_avantages": cout_avantages,
        "cout_total_mensuel": cout_total, "cout_total_annuel": round(cout_total * 12, 2),
        "ratio_cout_net": ratio_cout,
        "repartition": {"salaire_net": round(net / cout_total * 100, 1) if cout_total else 0,
                        "charges_salariales": round(sal / cout_total * 100, 1) if cout_total else 0,
                        "charges_patronales": round(pat / cout_total * 100, 1) if cout_total else 0,
                        "annexes_avantages": round((cout_annexes + cout_avantages + frais_km) / cout_total * 100, 1) if cout_total else 0},
    }


# --- Simulation : Seuils d'effectif ---
@router.get("/api/simulation/seuils-effectif")
async def sim_seuils(
    effectif_actuel: int = Query(10, description="Effectif total actuel de l entreprise (nb salaries ETP)"),
    masse_salariale_annuelle: float = Query(400000, description="Masse salariale brute annuelle totale de l entreprise (EUR)"),
):
    seuils = [
        {"seuil": 11, "obligations": [
            {"nom": "CSE (elections)", "reference": "Art. L.2311-2 CT", "cout_estime": 3000,
             "detail": "Mise en place du CSE obligatoire"},
            {"nom": "Participation formation", "reference": "Art. L.6331-1 CT", "cout_estime": round(masse_salariale_annuelle * 0.0045, 2),
             "detail": "Taux contribution formation passe de 0.55% a 1%"},
        ]},
        {"seuil": 20, "obligations": [
            {"nom": "FNAL taux plein", "reference": "Art. L.834-1 CSS", "cout_estime": round(masse_salariale_annuelle * 0.0030, 2),
             "detail": "FNAL passe de 0.10% plafonnd a 0.50% totalite"},
            {"nom": "Obligation emploi TH", "reference": "Art. L.5212-2 CT", "cout_estime": round(max(0, 20 - 0) * 600 * 0.04, 2),
             "detail": "6% de l effectif TH ou contribution AGEFIPH"},
        ]},
        {"seuil": 50, "obligations": [
            {"nom": "Participation (benefices)", "reference": "Art. L.3322-2 CT", "cout_estime": round(masse_salariale_annuelle * 0.005, 2),
             "detail": "Accord obligatoire de participation aux resultats"},
            {"nom": "CSE renforce (budgets)", "reference": "Art. L.2315-61 CT", "cout_estime": round(masse_salariale_annuelle * 0.002, 2),
             "detail": "Budget fonctionnement 0.2% + ASC"},
            {"nom": "Plan de sauvegarde emploi", "reference": "Art. L.1233-61 CT", "cout_estime": 0,
             "detail": "PSE obligatoire si licenciement >= 10 salaries"},
            {"nom": "Reglement interieur", "reference": "Art. L.1311-2 CT", "cout_estime": 500,
             "detail": "Redaction et depot obligatoires"},
            {"nom": "Effort construction (1%)", "reference": "Art. L.313-1 CCH", "cout_estime": round(masse_salariale_annuelle * 0.0045, 2),
             "detail": "Participation des employeurs a l effort de construction"},
            {"nom": "Index egalite pro", "reference": "Art. L.1142-8 CT", "cout_estime": 1500,
             "detail": "Calcul et publication obligatoires"},
        ]},
        {"seuil": 250, "obligations": [
            {"nom": "Quota alternants 5%", "reference": "Art. L.6241-1 CT", "cout_estime": round(masse_salariale_annuelle * 0.001, 2),
             "detail": "Contribution supplementaire si < 5% alternants"},
        ]},
        {"seuil": 300, "obligations": [
            {"nom": "Bilan social", "reference": "Art. L.2312-28 CT", "cout_estime": 2000,
             "detail": "Bilan social annuel obligatoire"},
            {"nom": "GPEC (GEPP)", "reference": "Art. L.2242-20 CT", "cout_estime": 5000,
             "detail": "Negociation obligatoire gestion des emplois et parcours professionnels"},
        ]},
    ]

    prochain_seuil = None
    impact_franchissement = []
    total_cout_actuel = 0
    total_cout_prochain = 0

    for s in seuils:
        franchi = effectif_actuel >= s["seuil"]
        for oblig in s["obligations"]:
            oblig["franchi"] = franchi
            if franchi:
                total_cout_actuel += oblig["cout_estime"]
        if not franchi and prochain_seuil is None:
            prochain_seuil = s["seuil"]
            impact_franchissement = s["obligations"]
            total_cout_prochain = sum(o["cout_estime"] for o in s["obligations"])

    return {
        "effectif_actuel": effectif_actuel,
        "masse_salariale_annuelle": masse_salariale_annuelle,
        "seuils": seuils,
        "total_obligations_actuelles": round(total_cout_actuel, 2),
        "prochain_seuil": prochain_seuil,
        "impact_prochain_seuil": impact_franchissement,
        "cout_prochain_seuil": round(total_cout_prochain, 2),
        "marge_avant_seuil": (prochain_seuil - effectif_actuel) if prochain_seuil else None,
    }


# --- Simulation : Masse salariale ---
@router.get("/api/simulation/masse-salariale")
async def sim_masse_salariale(
    brut_moyen: float = Query(2500, description="Salaire brut moyen par salarie (EUR/mois)"),
    effectif: int = Query(10, description="Effectif total de l entreprise (nb salaries) — masse = brut_moyen x effectif x 12"),
    augmentation_pct: float = Query(3.0, description="Augmentation envisagee (%)"),
    inflation_pct: float = Query(2.0, description="Inflation prevue (%)"),
    frais_km_moyen: float = Query(50, description="Frais km moyen par salarie (EUR/mois)"),
    avantages_nature_moyen: float = Query(0, description="Avantages nature moyen par salarie (EUR/mois)"),
    primes_variables_pct: float = Query(5.0, description="Primes variables (% masse salariale)"),
    turnover_pct: float = Query(10.0, description="Turnover annuel previsionnel (%)"),
):
    masse_actuelle = brut_moyen * effectif * 12
    taux_charges = 0.45
    charges_actuelles = masse_actuelle * taux_charges

    # Apres augmentation
    nouveau_brut = brut_moyen * (1 + augmentation_pct / 100)
    masse_apres_aug = nouveau_brut * effectif * 12
    cout_augmentation = masse_apres_aug - masse_actuelle
    charges_suppl_aug = cout_augmentation * taux_charges

    # Impact inflation (perte pouvoir achat si pas d augmentation)
    perte_reel = masse_actuelle * inflation_pct / 100

    # Primes variables
    primes_total = masse_actuelle * primes_variables_pct / 100
    charges_primes = primes_total * taux_charges

    # Frais kilometriques (non soumis)
    frais_km_total = frais_km_moyen * effectif * 12

    # Avantages nature (soumis)
    avantages_total = avantages_nature_moyen * effectif * 12
    charges_avantages = avantages_total * taux_charges

    # Turnover
    cout_recrutement = brut_moyen * 3
    cout_turnover = round(effectif * turnover_pct / 100 * cout_recrutement, 2)

    masse_totale_projetee = masse_apres_aug + primes_total + avantages_total
    charges_totales = masse_totale_projetee * taux_charges
    cout_global = masse_totale_projetee + charges_totales + frais_km_total + cout_turnover

    return {
        "masse_actuelle": round(masse_actuelle, 2),
        "charges_patronales_actuelles": round(charges_actuelles, 2),
        "cout_total_actuel": round(masse_actuelle + charges_actuelles, 2),
        "augmentation_pct": augmentation_pct,
        "nouveau_brut_moyen": round(nouveau_brut, 2),
        "masse_apres_augmentation": round(masse_apres_aug, 2),
        "cout_augmentation_brut": round(cout_augmentation, 2),
        "cout_augmentation_charges": round(charges_suppl_aug, 2),
        "cout_augmentation_total": round(cout_augmentation + charges_suppl_aug, 2),
        "perte_pouvoir_achat_inflation": round(perte_reel, 2),
        "ecart_augmentation_inflation": round(cout_augmentation - perte_reel, 2),
        "primes_variables_total": round(primes_total, 2),
        "charges_primes": round(charges_primes, 2),
        "frais_km_total": round(frais_km_total, 2),
        "avantages_nature_total": round(avantages_total, 2),
        "charges_avantages": round(charges_avantages, 2),
        "cout_turnover_estime": cout_turnover,
        "masse_totale_projetee": round(masse_totale_projetee, 2),
        "charges_totales_projetees": round(charges_totales, 2),
        "cout_global_projete": round(cout_global, 2),
        "evolution_pct": round((cout_global / (masse_actuelle + charges_actuelles) - 1) * 100, 2) if masse_actuelle > 0 else 0,
    }


# --- Simulation : Fin de contrat ---
@router.get("/api/simulation/fin-contrat")
async def sim_fin_contrat(
    type_fin: str = Query("licenciement"),
    salaire_brut: float = Query(2500),
    anciennete_mois: int = Query(36),
    est_cadre: bool = Query(False),
    motif: str = Query("personnel"),
):
    brut = salaire_brut
    anciennete_ans = anciennete_mois / 12
    salaire_ref = brut  # base mensuelle

    result = {"type_fin": type_fin, "salaire_brut": brut, "anciennete_mois": anciennete_mois,
              "anciennete_ans": round(anciennete_ans, 1)}

    if type_fin == "licenciement":
        # Indemnite legale : 1/4 mois par annee (10 premieres) + 1/3 au-dela
        if anciennete_ans <= 10:
            indemnite = salaire_ref * anciennete_ans * 0.25
        else:
            indemnite = salaire_ref * 10 * 0.25 + salaire_ref * (anciennete_ans - 10) / 3
        indemnite = round(indemnite, 2)

        # Preavis
        if anciennete_ans < 0.5:
            preavis_mois = 0
        elif anciennete_ans < 2:
            preavis_mois = 1
        else:
            preavis_mois = 2 if not est_cadre else 3

        indemnite_preavis = round(brut * preavis_mois, 2)
        conges_solde = round(brut * 2.5 / 30 * min(anciennete_mois, 12), 2)

        # Charges patronales sur indemnites
        exo_ss = min(indemnite, 92736)  # 2x PASS 2026
        charges_indemnite = round(max(0, indemnite - exo_ss) * 0.22, 2)

        # Contribution CSP si >= 1 an
        contrib_csp = round(brut * 3, 2) if motif == "economique" and anciennete_ans >= 1 else 0

        result.update({
            "indemnite_licenciement": indemnite,
            "indemnite_preavis": indemnite_preavis,
            "preavis_mois": preavis_mois,
            "conges_solde": conges_solde,
            "exoneration_ss": round(exo_ss, 2),
            "charges_indemnite": charges_indemnite,
            "contribution_csp": contrib_csp,
            "cout_total": round(indemnite + indemnite_preavis + conges_solde + charges_indemnite + contrib_csp, 2),
            "motif": motif,
            "reference": "Art. L.1234-9 CT (indemnite), Art. R.1234-2 CT (calcul)",
        })

    elif type_fin == "rupture_conventionnelle":
        if anciennete_ans <= 10:
            indemnite = salaire_ref * anciennete_ans * 0.25
        else:
            indemnite = salaire_ref * 10 * 0.25 + salaire_ref * (anciennete_ans - 10) / 3
        indemnite = round(max(indemnite, salaire_ref * anciennete_ans * 0.25), 2)

        conges_solde = round(brut * 2.5 / 30 * min(anciennete_mois, 12), 2)
        forfait_social = round(indemnite * 0.20, 2)

        result.update({
            "indemnite_rupture": indemnite,
            "conges_solde": conges_solde,
            "forfait_social_20pct": forfait_social,
            "cout_total": round(indemnite + conges_solde + forfait_social, 2),
            "reference": "Art. L.1237-13 CT - Indemnite >= legale licenciement",
            "note": "Homologation DREETS obligatoire (15 jours ouvrables)",
        })

    elif type_fin == "fin_cdd":
        indemnite_precarite = round(brut * anciennete_mois * 0.10, 2)
        conges_solde = round(brut * anciennete_mois * 0.10, 2)
        charges_precarite = round(indemnite_precarite * 0.22, 2)

        result.update({
            "indemnite_precarite_10pct": indemnite_precarite,
            "conges_payes_10pct": conges_solde,
            "charges_sur_precarite": charges_precarite,
            "cout_total": round(indemnite_precarite + conges_solde + charges_precarite, 2),
            "reference": "Art. L.1243-8 CT - 10% indemnite de precarite",
            "exceptions": "Pas de precarite si: CDI propose, saisonnier, etudiant, usage",
        })

    elif type_fin == "retraite":
        if anciennete_ans >= 30:
            indemnite = brut * 2
        elif anciennete_ans >= 20:
            indemnite = brut * 1.5
        elif anciennete_ans >= 15:
            indemnite = brut * 1
        elif anciennete_ans >= 10:
            indemnite = brut * 0.5
        else:
            indemnite = 0
        indemnite = round(indemnite, 2)
        charges = round(indemnite * 0.097, 2)

        result.update({
            "indemnite_depart_retraite": indemnite,
            "csg_crds_sur_indemnite": charges,
            "cout_total": round(indemnite + charges, 2),
            "reference": "Art. L.1237-9 CT",
        })

    return result


# --- Simulation : Optimisation legale ---
@router.get("/api/simulation/optimisation")
async def sim_optimisation(
    benefice_net: float = Query(80000),
    remuneration_gerant: float = Query(40000),
    dividendes: float = Query(20000),
    interessement: float = Query(0),
    participation: float = Query(0),
    frais_pro: float = Query(0),
    pee_abondement: float = Query(0),
    nb_parts: float = Query(1),
    forme_juridique: str = Query("sas"),
):
    result = {"forme_juridique": forme_juridique, "benefice_net": benefice_net}
    scenarios = []

    def _calcul_is(base_is):
        """IS progressif : 15% jusqu a 42 500 EUR, 25% au-dela."""
        if base_is <= 0:
            return 0.0
        if base_is <= 42500:
            return round(base_is * 0.15, 2)
        return round(42500 * 0.15 + (base_is - 42500) * 0.25, 2)

    # ---------------------------------------------------------------
    # Scenario 1 : 100% Salaire
    # Tout le benefice sert a payer le salaire brut + charges patronales
    # brut + charges_patronales = benefice_net  =>  brut * 1.42 = benefice_net
    # ---------------------------------------------------------------
    brut_1 = round(benefice_net / 1.42, 2)
    charges_pat_1 = round(brut_1 * 0.42, 2)
    charges_sal_1 = round(brut_1 * 0.22, 2)
    net_sal_1 = round(brut_1 - charges_sal_1, 2)
    ir_1 = _calculer_ir_simple(net_sal_1, nb_parts)
    total_net_1 = round(net_sal_1 - ir_1, 2)
    scenarios.append({
        "nom": "100% Salaire",
        "description": "Le benefice est integralement verse en salaire. Pas de dividendes ni d IS.",
        "salaire_brut": brut_1,
        "charges_sociales": charges_pat_1,
        "is_entreprise": 0.0,
        "dividendes": 0.0,
        "pfu_dividendes": 0.0,
        "ir": round(ir_1, 2),
        "net_disponible": total_net_1,
        "cout_entreprise": round(brut_1 + charges_pat_1, 2),
        "protection_sociale": "Maximale (chomage, retraite, prevoyance completes)",
    })

    # ---------------------------------------------------------------
    # Scenario 2 : Mix actuel (salaire + dividendes)
    # L utilisateur choisit la repartition remuneration / dividendes
    # ---------------------------------------------------------------
    charges_pat_2 = round(remuneration_gerant * 0.42, 2)
    charges_sal_2 = round(remuneration_gerant * 0.22, 2)
    net_sal_2 = round(remuneration_gerant - charges_sal_2, 2)
    # Base IS = benefice - (salaire brut + charges patronales) - frais pro
    is_base_2 = max(0, benefice_net - remuneration_gerant - charges_pat_2 - frais_pro)
    is_impot_2 = _calcul_is(is_base_2)
    # Dividendes distribuables = resultat apres IS
    div_distribuables_2 = max(0, is_base_2 - is_impot_2)
    div_reels_2 = min(dividendes, div_distribuables_2)
    pfu_2 = round(div_reels_2 * 0.30, 2)
    ir_2 = _calculer_ir_simple(net_sal_2, nb_parts)
    total_net_2 = round(net_sal_2 - ir_2 + div_reels_2 - pfu_2, 2)
    scenarios.append({
        "nom": "Mix actuel (salaire + dividendes)",
        "description": f"Salaire de {remuneration_gerant:.0f} EUR + dividendes de {div_reels_2:.0f} EUR. Le solde reste en tresorerie.",
        "salaire_brut": round(remuneration_gerant, 2),
        "charges_sociales": charges_pat_2,
        "is_entreprise": is_impot_2,
        "dividendes": round(div_reels_2, 2),
        "pfu_dividendes": pfu_2,
        "ir": round(ir_2, 2),
        "net_disponible": total_net_2,
        "cout_entreprise": round(remuneration_gerant + charges_pat_2 + is_impot_2, 2),
        "protection_sociale": "Moyenne (pas de cotisation retraite/chomage sur dividendes)",
        "tresorerie_residuelle": round(div_distribuables_2 - div_reels_2, 2),
    })

    # ---------------------------------------------------------------
    # Scenario 3 : Maximum dividendes (salaire au SMIC)
    # Le dirigeant se verse le minimum legal, le reste en dividendes
    # ---------------------------------------------------------------
    bar_opt = _get_baremes_pour_annee(2026)
    sal_min = round(bar_opt["smic_mensuel"] * 12, 2)  # SMIC annuel
    charges_pat_3 = round(sal_min * 0.42, 2)
    charges_sal_3 = round(sal_min * 0.22, 2)
    net_sal_3 = round(sal_min - charges_sal_3, 2)
    is_base_3 = max(0, benefice_net - sal_min - charges_pat_3)
    is_impot_3 = _calcul_is(is_base_3)
    div_max = round(max(0, is_base_3 - is_impot_3), 2)
    pfu_3 = round(div_max * 0.30, 2)
    ir_3 = _calculer_ir_simple(net_sal_3, nb_parts)
    total_net_3 = round(net_sal_3 - ir_3 + div_max - pfu_3, 2)
    scenarios.append({
        "nom": "Maximum dividendes (salaire SMIC)",
        "description": f"Salaire au minimum legal ({sal_min:.0f} EUR/an = {bar_opt['smic_mensuel']:.2f} EUR/mois). "
                       f"Le benefice restant ({is_base_3:.0f} EUR) est soumis a l IS puis distribue en dividendes.",
        "salaire_brut": sal_min,
        "charges_sociales": charges_pat_3,
        "is_entreprise": is_impot_3,
        "dividendes": div_max,
        "pfu_dividendes": pfu_3,
        "ir": round(ir_3, 2),
        "net_disponible": total_net_3,
        "cout_entreprise": round(sal_min + charges_pat_3 + is_impot_3, 2),
        "protection_sociale": "Minimale (retraite et chomage au minimum, faible couverture prevoyance)",
    })

    # ---------------------------------------------------------------
    # Scenario 4 : Optimise (interessement + participation + PEE)
    # Le salaire est maintenu, l epargne salariale beneficie d exonerations
    # ---------------------------------------------------------------
    charges_pat_4 = round(remuneration_gerant * 0.42, 2)
    charges_sal_4 = round(remuneration_gerant * 0.22, 2)
    net_sal_4 = round(remuneration_gerant - charges_sal_4, 2)
    is_base_4 = max(0, benefice_net - remuneration_gerant - charges_pat_4 - frais_pro)
    # Interessement : plafond = 3 PASS ou 20% du benefice net (le plus bas)
    int_val = round(min(max(interessement, benefice_net * 0.15), 3 * 47100), 2)
    # Participation : formule legale RSP = 0.5 * (B - 5% CP) * S / VA (simplifie ici)
    part_val = round(max(0, (is_base_4) * 0.5 * 0.5), 2)
    abond_val = round(min(pee_abondement if pee_abondement > 0 else 3709, 3709), 2)
    forfait_social = round((int_val + part_val) * 0.20, 2)
    ir_4 = _calculer_ir_simple(net_sal_4, nb_parts)
    # L epargne salariale est exoneree de charges (hors forfait social 20%) et d IR (si PEE bloque 5 ans)
    # Le salarie percoit : epargne - CSG/CRDS (9.7%)
    epargne_brute = int_val + part_val + abond_val
    epargne_nette = round(epargne_brute * (1 - 0.097), 2)  # apres CSG/CRDS
    total_net_4 = round(net_sal_4 - ir_4 + epargne_nette, 2)
    scenarios.append({
        "nom": "Optimise (salaire + epargne salariale)",
        "description": f"Salaire de {remuneration_gerant:.0f} EUR + interessement ({int_val:.0f} EUR) "
                       f"+ participation ({part_val:.0f} EUR) + abondement PEE ({abond_val:.0f} EUR). "
                       f"Epargne bloquee 5 ans mais exoneree d IR.",
        "salaire_brut": round(remuneration_gerant, 2),
        "charges_sociales": charges_pat_4,
        "is_entreprise": _calcul_is(max(0, is_base_4 - int_val - part_val)),
        "dividendes": 0.0,
        "pfu_dividendes": 0.0,
        "interessement": int_val,
        "participation": part_val,
        "abondement_pee": abond_val,
        "forfait_social": forfait_social,
        "ir": round(ir_4, 2),
        "net_disponible": total_net_4,
        "cout_entreprise": round(remuneration_gerant + charges_pat_4 + forfait_social + int_val + part_val + abond_val, 2),
        "protection_sociale": "Bonne + epargne salariale (bloquee 5 ans, exoneree d IR)",
    })

    # Meilleur scenario
    best = max(scenarios, key=lambda s: s["net_disponible"])
    result["scenarios"] = scenarios
    result["meilleur_scenario"] = best["nom"]
    result["ecart_max"] = round(best["net_disponible"] - min(s["net_disponible"] for s in scenarios), 2)

    # Frais professionnels deductibles
    result["frais_professionnels"] = {
        "frais_declares": frais_pro,
        "economie_is": round(frais_pro * 0.25, 2),
        "types_eligibles": ["Frais de deplacement", "Frais de repas (19.40 EUR/j)",
                            "Materiel professionnel", "Formation", "Abonnements pro",
                            "Cotisations syndicales", "Frais de bureau (domicile)"],
    }

    return result


# --- Simulation : Risques sectoriels ---
@router.get("/api/simulation/risques-sectoriels")
async def sim_risques(
    code_naf: str = Query("6201Z"),
    effectif: int = Query(10),
    masse_salariale: float = Query(400000),
):
    # Base de risques par grand secteur NAF
    secteurs = {
        "A": {"nom": "Agriculture", "taux_at": 3.5, "risques": [
            "Accidents du travail (machines, chutes)", "Exposition produits phytosanitaires",
            "Penibilite C2P (postures, vibrations)", "Saisonniers: DPAE et hebergement",
            "MSA au lieu d URSSAF pour cotisations"]},
        "C": {"nom": "Industrie manufacturiere", "taux_at": 2.8, "risques": [
            "Penibilite (travail de nuit, bruit, temperatures)", "Amiante (suivi post-exposition)",
            "Accidents machines (obligations EPI)", "ICPE et REACH (conformite chimique)",
            "Convention metallurgie: classifications specifiques"]},
        "F": {"nom": "Construction BTP", "taux_at": 5.2, "risques": [
            "Taux AT eleve (chutes de hauteur, engins)", "Carte BTP obligatoire",
            "Conges intemperies (Caisse CIBTP)", "Penibilite C2P: travail de nuit, postures",
            "Sous-traitance: vigilance solidarite financiere",
            "OPPBTP: cotisation obligatoire 0.11%"]},
        "G": {"nom": "Commerce", "taux_at": 1.5, "risques": [
            "Travail du dimanche (majorations)", "Temps partiel (minimum 24h/sem)",
            "Convention collective specifique (commerce detail, gros)",
            "Inventaires: heures supplementaires"]},
        "H": {"nom": "Transport", "taux_at": 3.0, "risques": [
            "Temps de conduite (reglementation EU)", "Versement mobilite (>= 11 sal)",
            "Convention transport routier (frais de route)", "Chronotachygraphe obligatoire",
            "Aptitude medicale renforcee"]},
        "I": {"nom": "Hebergement-restauration", "taux_at": 2.2, "risques": [
            "Avantages en nature repas (evaluation)", "Heures supplementaires (convention HCR)",
            "Saisonniers: DPAE, contrats, DUE", "Pourboires (regime fiscal 2022+)",
            "Hygiene alimentaire (formation HACCP obligatoire)"]},
        "J": {"nom": "Information-communication", "taux_at": 0.8, "risques": [
            "Teletravail (accord, indemnite, assurance)", "Forfait jours (cadres autonomes)",
            "Droit a la deconnexion", "RGPD (DPO si >= 250 salaries)",
            "Propriete intellectuelle des salaries"]},
        "K": {"nom": "Finance-assurance", "taux_at": 0.7, "risques": [
            "Convention collective banque/assurance specifique", "Risques psychosociaux",
            "Conformite reglementaire (AMF, ACPR)", "Lanceurs d alerte",
            "Formation obligatoire continue (DDA, MIF2)"]},
        "M": {"nom": "Activites scientifiques-techniques", "taux_at": 0.9, "risques": [
            "CIR/CII: credit impot recherche/innovation", "JEI: exoneration sociale possible",
            "Propriete intellectuelle (brevets, inventions salaries)",
            "Missions a l etranger (detachement, expatriation)",
            "Convention Syntec: modalites temps travail"]},
        "Q": {"nom": "Sante-action sociale", "taux_at": 2.5, "risques": [
            "Travail de nuit (majorations specifiques)", "Penibilite: manutention patients",
            "Obligation vaccinale (certains postes)", "Convention 66 ou BAD selon structure",
            "Astreintes et gardes (indemnisation specifique)"]},
        "S": {"nom": "Autres services", "taux_at": 1.2, "risques": [
            "Convention collective applicable (verifier IDCC)",
            "Associations: specificites (benevoles vs salaries)",
            "Services a la personne: CESU, mandataire/prestataire"]},
    }

    # Trouver le secteur
    lettre = code_naf[0] if code_naf else "J"
    secteur = secteurs.get(lettre, secteurs["S"])

    # Calcul cout AT
    cout_at = round(masse_salariale * secteur["taux_at"] / 100, 2)

    # Risques financiers
    risques_financiers = []
    if effectif >= 50:
        risques_financiers.append({"risque": "Licenciement collectif (>= 10)", "impact_estime": round(masse_salariale * 0.15, 2),
            "detail": "PSE obligatoire, indemnites supra-legales possibles"})
    risques_financiers.append({"risque": "Controle URSSAF (redressement moyen)", "impact_estime": round(masse_salariale * 0.03, 2),
        "detail": "Redressement moyen PME: 3% de la masse salariale sur 3 ans"})
    risques_financiers.append({"risque": "Prud hommes (moyenne)", "impact_estime": round(3 * (masse_salariale / max(effectif, 1) / 12), 2),
        "detail": "Indemnite moyenne: 3 mois de salaire + frais"})
    risques_financiers.append({"risque": "AT/MP grave", "impact_estime": round(masse_salariale * 0.05, 2),
        "detail": "Surcotisation AT + indemnisation + remplacement"})

    # Subventions possibles
    subventions = []
    if lettre in ("C", "F") and effectif < 50:
        subventions.append({"nom": "Subvention prevention CARSAT", "montant_max": 25000,
            "condition": "TPE 1-49 sal., investissement prevention risques pro"})
    if effectif < 250:
        subventions.append({"nom": "Aide TPE-PME (FACT)", "montant_max": 50000,
            "condition": "Amelioration conditions de travail"})
    subventions.append({"nom": "FNE-Formation", "montant_max": round(effectif * 1500, 2),
        "condition": "Formation salaries en transition ecologique/numerique"})
    if lettre in ("J", "M"):
        subventions.append({"nom": "CIR - Credit Impot Recherche", "montant_max": round(masse_salariale * 0.10 * 0.30, 2),
            "condition": "30% des depenses R&D (estimation ~10% masse salariale en R&D)"})

    return {
        "code_naf": code_naf, "secteur": secteur["nom"], "effectif": effectif,
        "taux_at_moyen": secteur["taux_at"], "cout_at_annuel": cout_at,
        "risques_specifiques": secteur["risques"],
        "risques_financiers": risques_financiers,
        "subventions_eligibles": subventions,
        "recommandations": [
            f"Taux AT {secteur['nom']}: {secteur['taux_at']}% - verifier votre taux reel",
            "Mettre a jour le DUERP avec les risques sectoriels identifies",
            "Souscrire une assurance RC pro adaptee au secteur",
        ],
    }


def _calculer_ir_simple(revenu: float, nb_parts: float) -> float:
    qi = revenu / nb_parts
    tranches = [(11294, 0), (28797, 0.11), (82341, 0.30), (177106, 0.41), (float("inf"), 0.45)]
    impot = 0.0
    prev = 0.0
    for seuil, taux in tranches:
        if qi <= prev:
            break
        tranche = min(qi, seuil) - prev
        impot += tranche * taux
        prev = seuil
    return round(impot * nb_parts, 2)


# ==============================
# DOCUMENTS DEMO / SIMULATION
# ==============================

@router.get("/api/simulation/demo-documents")
async def generer_documents_demo(
    type_demo: str = Query("complet"),
    avec_anomalies: bool = Query(True),
):
    """Genere des documents fictifs pour tester l analyse.

    type_demo: complet, bulletin_seul, dsn_seul, mixte
    avec_anomalies: si True, introduit des erreurs volontaires pour tester la detection
    """
    smic = float(_SMIC_MENSUEL)
    documents = []

    # --- Bulletin de paie fictif (CSV) ---
    if type_demo in ("complet", "bulletin_seul", "mixte"):
        brut_normal = 2850.00
        brut_anomalie = 1650.00 if avec_anomalies else brut_normal  # < SMIC
        pass_m = float(_PASS_MENSUEL)
        # Prevoyance patronale (1.50% cadre obligatoire) pour assiette CSG
        prevoyance_pat = round(brut_normal * 0.015, 2)
        # Assiette CSG = 98.25% brut + prevoyance patronale (sans abattement)
        assiette_csg = round(brut_normal * 0.9825 + prevoyance_pat, 2)
        bull_csv = "Rubrique;Base;Taux salarial;Part salariale;Taux patronal;Part patronal\\n"
        bull_csv += f"Salaire de base;{brut_normal if not avec_anomalies else brut_anomalie};;;;;\\n"
        # Maladie: patronal 13% (ou 7% reduit), salarial 0% depuis 2018
        if avec_anomalies:
            bull_csv += f"Maladie;{brut_normal};0.0850;{round(brut_normal * 0.085, 2)};0.13;{round(brut_normal * 0.13, 2)}\\n"  # salarial faux
        else:
            bull_csv += f"Maladie;{brut_normal};0;0;0.13;{round(brut_normal * 0.13, 2)}\\n"
        # Vieillesse plafonnee: pat 8.55%, sal 6.90%
        bull_csv += f"Vieillesse plafonnee;{min(brut_normal, pass_m)};0.069;{round(min(brut_normal, pass_m) * 0.069, 2)};0.0855;{round(min(brut_normal, pass_m) * 0.0855, 2)}\\n"
        # Vieillesse deplafonnee: pat 2.02%, sal 0.40%
        bull_csv += f"Vieillesse deplafonnee;{brut_normal};0.004;{round(brut_normal * 0.004, 2)};0.0202;{round(brut_normal * 0.0202, 2)}\\n"
        # Prevoyance cadre obligatoire: pat 1.50%
        bull_csv += f"Prevoyance cadre;{brut_normal};;;0.015;{prevoyance_pat}\\n"
        # CSG deductible 6.80%, non deductible 2.40%, CRDS 0.50%
        # Assiette = 98.25% brut + prevoyance patronale (art. L136-1-1 CSS)
        bull_csv += f"CSG deductible;{assiette_csg};0.0680;{round(assiette_csg * 0.068, 2)};;;\\n"
        bull_csv += f"CSG non deductible;{assiette_csg};0.0240;{round(assiette_csg * 0.024, 2)};;;\\n"
        bull_csv += f"CRDS;{assiette_csg};0.005;{round(assiette_csg * 0.005, 2)};;;\\n"
        # Chomage: pat 4.05%, sal 0%
        bull_csv += f"Chomage;{brut_normal};0;0;0.0405;{round(brut_normal * 0.0405, 2)}\\n"
        # AGS: pat 0.15%
        bull_csv += f"AGS;{brut_normal};0;0;0.0015;{round(brut_normal * 0.0015, 2)}\\n"
        if avec_anomalies:
            bull_csv += f"FNAL;{brut_normal};0.0050;0;0.0050;{round(brut_normal * 0.005, 2)}\\n"  # FNAL 0.50% mais effectif < 50
        else:
            bull_csv += f"FNAL;{min(brut_normal, pass_m)};0;0;0.001;{round(min(brut_normal, pass_m) * 0.001, 2)}\\n"
        documents.append({
            "nom": "bulletin_paie_demo_202601.csv",
            "type": "text/csv",
            "contenu": bull_csv,
            "description": "Bulletin de paie janvier 2026" + (" - AVEC anomalies" if avec_anomalies else " - CONFORME"),
            "anomalies_attendues": [
                "Salaire inferieur au SMIC" if avec_anomalies else None,
                "Taux maladie salarial incorrect (8.50% au lieu de 0%)" if avec_anomalies else None,
                "FNAL 0.50% applique alors que effectif < 50" if avec_anomalies else None,
            ] if avec_anomalies else [],
        })

    # --- DSN fictive (format texte structure) ---
    if type_demo in ("complet", "dsn_seul", "mixte"):
        nir_valide = "1850175108888"
        cle_nir = str(97 - (int(nir_valide) % 97)).zfill(2)
        nir_anomalie = "2991375000000" if avec_anomalies else nir_valide  # NIR invalide
        brut_dsn = "2850.00"
        net_dsn = "2223.00"
        if avec_anomalies:
            net_dsn = "3100.00"  # Net > Brut = anomalie

        dsn_txt = "S10.G00.00.001,'00001'\\n"
        dsn_txt += "S10.G00.00.002,'01'\\n"
        dsn_txt += "S10.G00.01.001,'123456789'\\n"
        dsn_txt += "S10.G00.01.002,'DEMO ENTREPRISE SAS'\\n"
        dsn_txt += "S20.G00.05.001,'01'\\n"
        dsn_txt += "S20.G00.05.002,'202601'\\n"
        dsn_txt += "S21.G00.06.001,'12345678900012'\\n"
        dsn_txt += "S21.G00.06.002,'DEMO ENTREPRISE SAS'\\n"
        dsn_txt += f"S21.G00.30.001,'{nir_anomalie if avec_anomalies else nir_valide}{cle_nir}'\\n"
        dsn_txt += "S21.G00.30.002,'DUPONT'\\n"
        dsn_txt += "S21.G00.30.004,'Jean'\\n"
        dsn_txt += "S21.G00.30.006,'01011990'\\n"
        dsn_txt += f"S21.G00.51.001,'{brut_dsn}'\\n"
        dsn_txt += f"S21.G00.51.011,'{net_dsn}'\\n"
        dsn_txt += "S21.G00.51.012,'151.67'\\n"
        dsn_txt += "S21.G00.40.001,'C0001'\\n"
        dsn_txt += "S21.G00.40.002,'01012024'\\n"  # Date embauche
        dsn_txt += "S21.G00.40.007,'02'\\n"  # Non-cadre
        if avec_anomalies:
            dsn_txt += "S21.G00.81.001,''\\n"  # CTP vide = anomalie
        else:
            dsn_txt += "S21.G00.81.001,'100'\\n"
        dsn_txt += f"S21.G00.81.004,'{brut_dsn}'\\n"

        documents.append({
            "nom": "dsn_demo_202601.dsn",
            "type": "text/plain",
            "contenu": dsn_txt,
            "description": "DSN mensuelle janvier 2026" + (" - AVEC anomalies" if avec_anomalies else " - CONFORME"),
            "anomalies_attendues": [
                "NIR invalide (cle de controle incorrecte)" if avec_anomalies else None,
                "Net fiscal > Brut (incoherent)" if avec_anomalies else None,
                "CTP vide (Code Type Personnel obligatoire)" if avec_anomalies else None,
            ] if avec_anomalies else [],
        })

    # --- Recapitulatif salaires format Excel simplifie (CSV) ---
    if type_demo in ("complet", "mixte"):
        recap_csv = "Nom;Salaire brut;Cotisations;Net a payer;Avantage\\n"
        recap_csv += "DUPONT Jean;3000.00;700.00;2300.00;Voiture 500\\n"
        recap_csv += "MARTIN Claire;2200.00;500.00;1700.00;Logement 300\\n"
        if avec_anomalies:
            recap_csv += "PETIT Lucas;1500.00;400.00;1100.00;\\n"  # brut < SMIC
        else:
            recap_csv += "PETIT Lucas;2500.00;580.00;1920.00;\\n"
        documents.append({
            "nom": "recap_salaires_202601.csv",
            "type": "text/csv",
            "contenu": recap_csv,
            "description": "Recapitulatif salaires format simplifie (type Excel)" + (" - salaire sous SMIC" if avec_anomalies else ""),
            "anomalies_attendues": [
                "Salaire inferieur au SMIC pour PETIT Lucas" if avec_anomalies else None,
            ] if avec_anomalies else [],
        })

    # --- Facture fictive (CSV) ---
    if type_demo in ("complet", "mixte"):
        fact_csv = "Type;Date;Numero;Tiers;HT;TVA;TTC\\n"
        fact_csv += "Facture achat;2026-01-15;FA-2026-001;FOURNISSEUR DEMO;1500.00;300.00;1800.00\\n"
        if avec_anomalies:
            fact_csv += "Facture achat;2026-01-20;FA-2026-002;FOURNISSEUR X;2000.00;500.00;2500.00\\n"  # TVA 25% = erreur
        fact_csv += "Facture vente;2026-01-25;FV-2026-001;CLIENT DEMO;3000.00;600.00;3600.00\\n"
        documents.append({
            "nom": "factures_demo_202601.csv",
            "type": "text/csv",
            "contenu": fact_csv,
            "description": "Factures janvier 2026" + (" - TVA incorrecte sur FA-002" if avec_anomalies else ""),
            "anomalies_attendues": [
                "Taux TVA 25% anormal sur FA-2026-002 (taux standards: 5.5%, 10%, 20%)" if avec_anomalies else None,
            ] if avec_anomalies else [],
        })

    # Filtrer les None des anomalies
    for doc in documents:
        doc["anomalies_attendues"] = [a for a in doc.get("anomalies_attendues", []) if a]

    return {
        "type_demo": type_demo,
        "avec_anomalies": avec_anomalies,
        "nb_documents": len(documents),
        "documents": documents,
        "instructions": "Telechargez les fichiers CSV/DSN generes et importez-les via Import/Analyse pour tester la detection d anomalies.",
    }


@router.get("/api/simulation/demo-documents/{index}/telecharger")
async def telecharger_document_demo(
    index: int,
    type_demo: str = Query("complet"),
    avec_anomalies: bool = Query(True),
):
    """Telecharge un document de demo au format fichier."""
    result = await generer_documents_demo(type_demo, avec_anomalies)
    docs = result["documents"]
    if index < 0 or index >= len(docs):
        raise HTTPException(404, "Document non trouve")
    doc = docs[index]
    from fastapi.responses import Response
    content = doc["contenu"].replace("\\n", "\n")
    safe_doc_name = Path(doc["nom"].replace("\\", "/")).name if doc.get("nom") else "document.txt"
    return Response(content=content, media_type="text/plain",
                    headers={"Content-Disposition": f'attachment; filename="{safe_doc_name}"'})


@router.get("/api/simulation/demo-documents/telecharger-tout")
async def telecharger_tous_documents_demo(
    type_demo: str = Query("complet"),
    avec_anomalies: bool = Query(True),
):
    """Telecharge tous les documents demo dans un ZIP."""
    import zipfile
    import io
    result = await generer_documents_demo(type_demo, avec_anomalies)
    docs = result["documents"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        readme = "Documents de test NormaCheck\\n============================\\n\\n"
        for i, doc in enumerate(docs):
            content = doc["contenu"].replace("\\n", "\n")
            zf.writestr(doc["nom"], content)
            readme += f"{i+1}. {doc['nom']} - {doc['description']}\\n"
            anomalies = doc.get("anomalies_attendues", [])
            if anomalies:
                for a in anomalies:
                    readme += f"   -> Anomalie attendue : {a}\\n"
            readme += "\\n"
        readme += "\\nImportez ces fichiers dans NormaCheck via Import > Analyse\\n"
        zf.writestr("LISEZ-MOI.txt", readme.replace("\\n", "\n"))
    buf.seek(0)
    from fastapi.responses import Response
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="normacheck_documents_test.zip"'},
    )