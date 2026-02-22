"""Audit complet - 30 scenarios de controle URSSAF, Fiscal et Cour des comptes."""
import sys, json, traceback
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ============================================================
# INFRASTRUCTURE
# ============================================================
results = []
def run_test(num, name, fn):
    try:
        r = fn()
        ok = r.get("ok", False)
        results.append({"num": num, "name": name, "ok": ok, "detail": r.get("detail",""), "error": None})
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] #{num}: {name}")
        if not ok:
            print(f"         Detail: {r.get('detail','')}")
    except Exception as e:
        results.append({"num": num, "name": name, "ok": False, "detail": str(e), "error": traceback.format_exc()})
        print(f"  [ERROR] #{num}: {name}")
        print(f"         {e}")

# ============================================================
# IMPORTS
# ============================================================
from urssaf_analyzer.rules.contribution_rules import ContributionRules
from urssaf_analyzer.config.constants import SMIC_MENSUEL_BRUT, PASS_MENSUEL, PASS_ANNUEL
from urssaf_analyzer.config.idcc_database import rechercher_idcc, get_ccn_par_idcc, get_prevoyance_par_idcc, IDCC_DATABASE
from urssaf_analyzer.config.taux_atmp import get_taux_atmp, TAUX_ATMP_PAR_NAF
from urssaf_analyzer.rules.regimes_speciaux import (
    get_regime, lister_regimes, detecter_regime,
    calculer_supplement_alsace_moselle, calculer_cotisations_msa, REGIMES_SPECIAUX
)
from urssaf_analyzer.rules.travailleurs_detaches import (
    verifier_conformite_detachement, determiner_regime_applicable,
    DETACHEMENT_UE, CONVENTIONS_BILATERALES, TRAVAILLEURS_ETRANGERS
)
from urssaf_analyzer.rules.analyse_multiannuelle import AnalyseMultiAnnuelle

print("=" * 70)
print("AUDIT COMPLET - 30 SCENARIOS DE CONTROLE")
print("=" * 70)

# ============================================================
# 1. BULLETIN CDI cadre PME
# ============================================================
def test_01():
    cr = ContributionRules(effectif_entreprise=45, taux_at=Decimal("0.0150"))
    b = cr.calculer_bulletin_complet(Decimal("4500"), est_cadre=True)
    ok = (
        b["total_patronal"] > 0 and
        b["total_salarial"] > 0 and
        b["net_avant_impot"] > 0 and
        b["net_avant_impot"] < Decimal("4500") and
        b["cout_total_employeur"] > Decimal("4500") and
        len(b["lignes"]) >= 15
    )
    return {"ok": ok, "detail": f"net={b['net_avant_impot']}, patronal={b['total_patronal']}, {len(b['lignes'])} lignes"}
run_test(1, "Bulletin CDI cadre PME (45 sal, 4500 EUR)", test_01)

# ============================================================
# 2. BULLETIN Non cadre micro-entreprise
# ============================================================
def test_02():
    cr = ContributionRules(effectif_entreprise=3, taux_at=Decimal("0.0208"))
    b = cr.calculer_bulletin_complet(Decimal("1900"), est_cadre=False)
    ok = (
        b["net_avant_impot"] > Decimal("1400") and
        b["net_avant_impot"] < Decimal("1900") and
        b["total_patronal"] > 0
    )
    return {"ok": ok, "detail": f"net={b['net_avant_impot']}, patronal={b['total_patronal']}"}
run_test(2, "Bulletin non-cadre micro (3 sal, 1900 EUR)", test_02)

# ============================================================
# 3. BULLETIN AU SMIC
# ============================================================
def test_03():
    cr = ContributionRules(effectif_entreprise=10)
    b = cr.calculer_bulletin_complet(SMIC_MENSUEL_BRUT, est_cadre=False)
    ok = (
        b["net_avant_impot"] > 0 and
        float(b["net_avant_impot"]) < float(SMIC_MENSUEL_BRUT) and
        b["total_patronal"] > 0
    )
    return {"ok": ok, "detail": f"SMIC={SMIC_MENSUEL_BRUT}, net={b['net_avant_impot']}"}
run_test(3, "Bulletin au SMIC (verification seuils)", test_03)

# ============================================================
# 4. BULLETIN CADRE > PASS
# ============================================================
def test_04():
    cr = ContributionRules(effectif_entreprise=200, taux_at=Decimal("0.0120"))
    b = cr.calculer_bulletin_complet(Decimal("8000"), est_cadre=True)
    ok = (
        b["net_avant_impot"] > 0 and
        b["cout_total_employeur"] > Decimal("8000") and
        any("T2" in l.get("libelle", "") or "tranche 2" in l.get("libelle", "").lower() for l in b["lignes"])
    )
    return {"ok": ok, "detail": f"net={b['net_avant_impot']}, cout_emp={b['cout_total_employeur']}"}
run_test(4, "Bulletin cadre sup > PASS (8000 EUR, 200 sal)", test_04)

# ============================================================
# 5. TEMPS PARTIEL 24h/semaine
# ============================================================
def test_05():
    cr = ContributionRules(effectif_entreprise=15)
    b = cr.calculer_bulletin_temps_partiel(Decimal("1200"), Decimal("104"), est_cadre=False)
    ok = "temps_partiel" in b and b["net_avant_impot"] > 0
    return {"ok": ok, "detail": f"net={b['net_avant_impot']}, ratio={b['temps_partiel'].get('ratio','')}"}
run_test(5, "Bulletin temps partiel 24h/sem (1200 EUR)", test_05)

# ============================================================
# 6. EXONERATION ACRE - Eligible
# ============================================================
def test_06():
    cr = ContributionRules(effectif_entreprise=1)
    exo = cr.calculer_exoneration_acre(SMIC_MENSUEL_BRUT * Decimal("1.1"))
    ok = exo["eligible"] and exo["exoneration_mensuelle"] > 0
    return {"ok": ok, "detail": f"exo={exo['exoneration_mensuelle']}, taux={exo.get('taux_exoneration','')}"}
run_test(6, "Exoneration ACRE eligible (1.1 SMIC)", test_06)

# ============================================================
# 7. ACRE Non eligible (> 1.6 SMIC)
# ============================================================
def test_07():
    cr = ContributionRules(effectif_entreprise=1)
    exo = cr.calculer_exoneration_acre(SMIC_MENSUEL_BRUT * Decimal("1.7"))
    ok = not exo["eligible"] or exo["exoneration_mensuelle"] == 0
    return {"ok": ok, "detail": f"eligible={exo['eligible']}, exo={exo['exoneration_mensuelle']}"}
run_test(7, "ACRE non eligible (1.7 SMIC)", test_07)

# ============================================================
# 8. EXONERATION APPRENTI
# ============================================================
def test_08():
    cr = ContributionRules(effectif_entreprise=20)
    exo = cr.calculer_exoneration_apprenti(SMIC_MENSUEL_BRUT * Decimal("0.5"), annee_apprentissage=1)
    ok = exo["eligible"] and exo["exoneration_salariale_mensuelle"] >= 0
    return {"ok": ok, "detail": f"exo_sal={exo['exoneration_salariale_mensuelle']}"}
run_test(8, "Exoneration apprenti 1ere annee (50% SMIC)", test_08)

# ============================================================
# 9. CCN SYNTEC cadre
# ============================================================
def test_09():
    cr = ContributionRules(effectif_entreprise=30)
    prev = cr.get_prevoyance_ccn("syntec", est_cadre=True)
    ok = prev["ccn_connue"] and prev["taux_prevoyance_patronal"] > 0
    return {"ok": ok, "detail": f"prev={prev['taux_prevoyance_patronal']}"}
run_test(9, "CCN SYNTEC prevoyance cadre", test_09)

# ============================================================
# 10. CCN BATIMENT non-cadre
# ============================================================
def test_10():
    cr = ContributionRules(effectif_entreprise=8)
    prev = cr.get_prevoyance_ccn("batiment", est_cadre=False)
    ok = prev["ccn_connue"] and prev["taux_prevoyance_patronal"] > 0
    return {"ok": ok, "detail": f"prev={prev['taux_prevoyance_patronal']}"}
run_test(10, "CCN Batiment prevoyance non-cadre", test_10)

# ============================================================
# 11. BASE IDCC - Recherche
# ============================================================
def test_11():
    res = rechercher_idcc("metallurgie")
    ok = len(res) > 0 and any(r["idcc"] == "3248" for r in res)
    return {"ok": ok, "detail": f"{len(res)} resultats"}
run_test(11, "Base IDCC recherche metallurgie", test_11)

# ============================================================
# 12. IDCC 1486 prevoyance
# ============================================================
def test_12():
    prev = get_prevoyance_par_idcc("1486", est_cadre=True)
    ok = prev is not None and prev.get("taux_prevoyance", 0) > 0
    return {"ok": ok, "detail": f"prev={prev}"}
run_test(12, "IDCC 1486 (SYNTEC) prevoyance cadre", test_12)

# ============================================================
# 13. TAUX AT/MP - BTP
# ============================================================
def test_13():
    r = get_taux_atmp("43.21A", 15)
    ok = r.get("taux_collectif", 0) > 0
    return {"ok": ok, "detail": f"taux={r.get('taux_collectif')}, mode={r.get('mode_tarification','')}"}
run_test(13, "Taux AT/MP BTP (43.21A, 15 sal)", test_13)

# ============================================================
# 14. TAUX AT/MP - Informatique
# ============================================================
def test_14():
    r = get_taux_atmp("62.02A", 50)
    ok = r.get("taux_collectif", 0) > 0
    return {"ok": ok, "detail": f"taux={r.get('taux_collectif')}, mode={r.get('mode_tarification','')}"}
run_test(14, "Taux AT/MP Informatique (62.02A, 50 sal)", test_14)

# ============================================================
# 15. REGIME MSA - Cotisations
# ============================================================
def test_15():
    cot = calculer_cotisations_msa(Decimal("2000"), 5)
    ok = (
        isinstance(cot, dict) and
        "lignes" in cot and
        len(cot["lignes"]) > 0 and
        cot.get("total_patronal", 0) > 0
    )
    return {"ok": ok, "detail": f"{len(cot.get('lignes',[]))} lignes, patronal={cot.get('total_patronal','')}"}
run_test(15, "Regime MSA cotisations (2000 EUR, 5 sal)", test_15)

# ============================================================
# 16. ALSACE-MOSELLE supplement
# ============================================================
def test_16():
    sup = calculer_supplement_alsace_moselle(Decimal("3000"))
    ok = (
        sup.get("montant_salarial_mensuel", 0) > 0 and
        sup.get("taux_salarial") == Decimal("0.013")
    )
    return {"ok": ok, "detail": f"montant={sup.get('montant_salarial_mensuel')}, taux={sup.get('taux_salarial')}"}
run_test(16, "Alsace-Moselle supplement (3000 EUR)", test_16)

# ============================================================
# 17. DETECTION REGIME - Agriculture
# ============================================================
def test_17():
    reg = detecter_regime(code_naf="01.11Z", departement="33")
    ok = isinstance(reg, list) and "msa" in [r.lower() if isinstance(r, str) else r.get("code","").lower() for r in reg]
    return {"ok": ok, "detail": f"regimes={reg}"}
run_test(17, "Detection regime agricole (NAF 01.11Z)", test_17)

# ============================================================
# 18. DETECTION REGIME - Alsace-Moselle
# ============================================================
def test_18():
    reg = detecter_regime(departement="67")
    ok = isinstance(reg, list) and any("alsace" in str(r).lower() for r in reg)
    return {"ok": ok, "detail": f"regimes={reg}"}
run_test(18, "Detection regime Alsace dept 67", test_18)

# ============================================================
# 19. DETACHE UE - Conforme
# ============================================================
def test_19():
    r = verifier_conformite_detachement(
        nationalite="polonaise", pays_employeur="Pologne",
        a1_present=True, sipsi_declare=True,
        duree_mois=6, remuneration_brute=Decimal("2500"),
        secteur_btp=False, carte_btp=False
    )
    ok = len(r.get("anomalies", [])) == 0
    return {"ok": ok, "detail": f"anomalies={len(r.get('anomalies',[]))}, alertes={len(r.get('alertes',[]))}"}
run_test(19, "Detache UE conforme (Pologne, A1, SIPSI)", test_19)

# ============================================================
# 20. DETACHE - Non conforme
# ============================================================
def test_20():
    r = verifier_conformite_detachement(
        nationalite="roumaine", pays_employeur="Roumanie",
        a1_present=False, sipsi_declare=False,
        duree_mois=12, remuneration_brute=Decimal("1500"),
        secteur_btp=True, carte_btp=False
    )
    ok = len(r.get("anomalies", [])) >= 2
    return {"ok": ok, "detail": f"{len(r.get('anomalies',[]))} anomalies detectees"}
run_test(20, "Detache non conforme (pas A1, pas SIPSI, BTP)", test_20)

# ============================================================
# 21. REGIME APPLICABLE - Convention Maroc
# ============================================================
def test_21():
    r = determiner_regime_applicable(
        nationalite="marocaine", pays_residence="Maroc",
        pays_employeur="Maroc", certificat_a1=False, convention_bilaterale=True
    )
    ok = "regime" in r and len(r["regime"]) > 0
    return {"ok": ok, "detail": f"regime={r.get('regime','')}"}
run_test(21, "Regime applicable - Convention Maroc", test_21)

# ============================================================
# 22. CONVENTIONS BILATERALES - Couverture
# ============================================================
def test_22():
    pays = CONVENTIONS_BILATERALES.get("pays_couverts", {})
    ok = len(pays) >= 10
    return {"ok": ok, "detail": f"{len(pays)} pays couverts: {list(pays.keys())[:8]}..."}
run_test(22, "Conventions bilaterales (10+ pays)", test_22)

# ============================================================
# 23. ANALYSE MULTI-ANNUELLE - Tendances
# ============================================================
def test_23():
    am = AnalyseMultiAnnuelle()
    am.alimenter(2021, {"masse_salariale": 500000, "effectif": 12, "taux_charges_patronales": 0.42})
    am.alimenter(2022, {"masse_salariale": 520000, "effectif": 13, "taux_charges_patronales": 0.43})
    am.alimenter(2023, {"masse_salariale": 550000, "effectif": 14, "taux_charges_patronales": 0.42})
    am.alimenter(2024, {"masse_salariale": 580000, "effectif": 15, "taux_charges_patronales": 0.44})
    am.alimenter(2025, {"masse_salariale": 600000, "effectif": 15, "taux_charges_patronales": 0.43})
    rapport = am.analyser()
    ok = (
        "couverture" in rapport and
        "tendances" in rapport and
        rapport["couverture"].get("annees_importees") is not None and
        len(rapport["couverture"]["annees_importees"]) == 5
    )
    return {"ok": ok, "detail": f"annees={rapport['couverture'].get('annees_importees',[])}, tendances={len(rapport.get('tendances',{}))}"}
run_test(23, "Analyse multi-annuelle 5 ans (croissance)", test_23)

# ============================================================
# 24. MULTI-ANNUEL - Detection anomalie chute
# ============================================================
def test_24():
    am = AnalyseMultiAnnuelle()
    am.alimenter(2022, {"masse_salariale": 800000, "effectif": 20})
    am.alimenter(2023, {"masse_salariale": 500000, "effectif": 12})
    am.alimenter(2024, {"masse_salariale": 480000, "effectif": 11})
    rapport = am.analyser()
    ok = len(rapport.get("anomalies", [])) > 0
    return {"ok": ok, "detail": f"{len(rapport.get('anomalies',[]))} anomalies"}
run_test(24, "Multi-annuel - detection chute masse salariale", test_24)

# ============================================================
# 25. REGIMES SPECIAUX - Completude
# ============================================================
def test_25():
    regimes = lister_regimes()
    codes_attendus = ["msa", "alsace_moselle", "mines", "sncf", "ratp", "ieg", "crpcen", "enim", "bdf"]
    codes_trouves = [r["code"] for r in regimes] if isinstance(regimes[0], dict) else regimes
    manquants = [c for c in codes_attendus if c not in codes_trouves]
    ok = len(regimes) >= 9 and len(manquants) == 0
    return {"ok": ok, "detail": f"{len(regimes)} regimes, manquants={manquants}"}
run_test(25, "9 regimes speciaux presents", test_25)

# ============================================================
# 26. RGDU (reduction generale) - Eligible a 1.4 SMIC
# ============================================================
def test_26():
    cr = ContributionRules(effectif_entreprise=50)
    brut_annuel = SMIC_MENSUEL_BRUT * 12 * Decimal("1.4")
    eligible = cr.est_eligible_rgdu(brut_annuel)
    detail = cr.detail_rgdu(brut_annuel)
    ok = eligible and detail.get("reduction_annuelle", 0) > 0
    return {"ok": ok, "detail": f"eligible={eligible}, reduction={detail.get('reduction_annuelle',0)}"}
run_test(26, "RGDU eligible (1.4 SMIC annuel)", test_26)

# ============================================================
# 27. RGDU - Non eligible (> 3 SMIC = seuil 2026)
# ============================================================
def test_27():
    cr = ContributionRules(effectif_entreprise=50)
    brut_annuel = SMIC_MENSUEL_BRUT * 12 * Decimal("3.1")  # Au-dela du seuil 3 SMIC
    eligible = cr.est_eligible_rgdu(brut_annuel)
    ok = not eligible
    return {"ok": ok, "detail": f"eligible={eligible} (attendu False pour >3 SMIC)"}
run_test(27, "RGDU non eligible (3.1 SMIC = > seuil 3 SMIC)", test_27)

# ============================================================
# 28. TAXE SUR SALAIRES - 3 tranches
# ============================================================
def test_28():
    cr = ContributionRules(effectif_entreprise=20)
    ts = cr.calculer_taxe_salaires(Decimal("100000"))
    ok = (
        "total" in ts and
        ts["total"] > 0 and
        ("tranche_1" in ts or "tranches" in ts)
    )
    return {"ok": ok, "detail": f"total={ts.get('total',0)}, cles={list(ts.keys())}"}
run_test(28, "Taxe sur salaires (100K brut annuel)", test_28)

# ============================================================
# 29. NET IMPOSABLE cadre
# ============================================================
def test_29():
    cr = ContributionRules(effectif_entreprise=30)
    ni = cr.calculer_net_imposable(Decimal("3500"), est_cadre=True)
    ok = "net_imposable" in ni and ni["net_imposable"] > 0
    return {"ok": ok, "detail": f"net_imposable={ni.get('net_imposable','')}"}
run_test(29, "Net imposable cadre (3500 EUR)", test_29)

# ============================================================
# 30. IDCC DATABASE - Completude
# ============================================================
def test_30():
    nb_ccn = len(IDCC_DATABASE)
    secteurs = set(v.get("secteur", "") for v in IDCC_DATABASE.values())
    secteurs_attendus = {"batiment", "metallurgie", "commerce", "informatique", "sante"}
    manquants = secteurs_attendus - secteurs
    ok = nb_ccn >= 50 and len(manquants) == 0
    return {"ok": ok, "detail": f"{nb_ccn} CCN, {len(secteurs)} secteurs, manquants={manquants}"}
run_test(30, "Base IDCC completude (50+ CCN)", test_30)

# ============================================================
# RESUME
# ============================================================
print("\n" + "=" * 70)
passed = sum(1 for r in results if r["ok"])
failed = sum(1 for r in results if not r["ok"])
print(f"RESULTATS: {passed}/{len(results)} PASSES, {failed} ECHECS")
print("=" * 70)

if failed > 0:
    print("\nDETAIL DES ECHECS:")
    for r in results:
        if not r["ok"]:
            print(f"\n  #{r['num']}: {r['name']}")
            print(f"  Detail: {r['detail']}")
            if r.get("error"):
                lines = r['error'].strip().split('\n')
                print(f"  Error: {lines[-1]}")

with open("/tmp/audit_30cases_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
