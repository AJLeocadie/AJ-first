"""
Test complet simulant l'utilisation par un expert-comptable de 30 dossiers differents.
Couvre: interpretation documents, analyse, report, comptabilite, factures, RH, simulation.
"""
import sys
import json
import time
import os
import traceback
import tempfile
from pathlib import Path
from io import BytesIO

# Setup
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("NORMACHECK_SECRET_KEY", "testsecretkey12345678")

from fastapi.testclient import TestClient
from api.index import app

client = TestClient(app)
results = []
TOTAL = 0
PASSED = 0


def run_test(num, name, fn):
    global TOTAL, PASSED
    TOTAL += 1
    try:
        r = fn()
        ok = r.get("ok", False)
        if ok:
            PASSED += 1
        status = "PASS" if ok else "FAIL"
        detail = r.get("detail", "")
        print(f"  [{status}] #{num}: {name}")
        if not ok and detail:
            print(f"         Detail: {detail}")
        results.append({"num": num, "name": name, "ok": ok, "detail": detail})
    except Exception as e:
        print(f"  [ERROR] #{num}: {name}")
        print(f"         {e}")
        results.append({"num": num, "name": name, "ok": False, "detail": str(e),
                         "error": traceback.format_exc()})


# ============================================================
# SETUP: Creer un compte expert-comptable et se connecter
# ============================================================
def setup():
    r = client.post("/api/auth/register", data={
        "email": "expert@cabinet-test.fr",
        "mot_de_passe": "ExpertPass2026!",
        "nom": "LECOMTE",
        "prenom": "Marie"
    })
    if r.status_code != 200:
        # Essayer login si deja enregistre
        r = client.post("/api/auth/login", data={
            "email": "expert@cabinet-test.fr",
            "mot_de_passe": "ExpertPass2026!"
        })
    assert r.status_code == 200, f"Auth failed: {r.text}"
    print("  [OK] Authentification expert-comptable reussie")
    return True


print("=" * 70)
print("SIMULATION EXPERT-COMPTABLE - 30 DOSSIERS")
print("=" * 70)

setup()

# ============================================================
# DOSSIER 1: PME Commerce - Bulletin standard
# ============================================================
def test_01():
    r = client.get("/api/simulation/bulletin", params={
        "brut_mensuel": 2500, "effectif": 15, "est_cadre": "false"
    })
    d = r.json()
    ok = (r.status_code == 200 and
          d.get("net_a_payer", 0) > 1800 and
          d.get("cout_total_employeur", 0) > 2500 and
          len(d.get("lignes", [])) >= 10)
    return {"ok": ok,
            "detail": f"net={d.get('net_a_payer')}, cout_empl={d.get('cout_total_employeur')}, {len(d.get('lignes',[]))} lignes"}
run_test(1, "PME Commerce - Bulletin non-cadre 2500 EUR", test_01)

# ============================================================
# DOSSIER 2: SAS Tech - Bulletin cadre
# ============================================================
def test_02():
    r = client.get("/api/simulation/bulletin", params={
        "brut_mensuel": 5000, "effectif": 50, "est_cadre": "true"
    })
    d = r.json()
    ok = (r.status_code == 200 and
          d.get("net_a_payer", 0) > 3500 and
          d.get("cout_total_employeur", 0) > 5000)
    return {"ok": ok,
            "detail": f"net={d.get('net_a_payer')}, cout={d.get('cout_total_employeur')}"}
run_test(2, "SAS Tech - Bulletin cadre 5000 EUR", test_02)

# ============================================================
# DOSSIER 3: Micro-entrepreneur prestation BNC
# ============================================================
def test_03():
    r = client.get("/api/simulation/micro-entrepreneur", params={
        "chiffre_affaires": 50000, "activite": "prestations_bnc", "acre": "false"
    })
    d = r.json()
    ok = r.status_code == 200 and any(isinstance(v, (int, float)) for v in d.values())
    return {"ok": ok, "detail": json.dumps({k: round(v, 2) if isinstance(v, float) else v
                                            for k, v in d.items()})[:200]}
run_test(3, "Micro-entrepreneur BNC 50K EUR", test_03)

# ============================================================
# DOSSIER 4: Micro-entrepreneur vente avec ACRE
# ============================================================
def test_04():
    r = client.get("/api/simulation/micro-entrepreneur", params={
        "chiffre_affaires": 80000, "activite": "vente_marchandises", "acre": "true"
    })
    d = r.json()
    ok = r.status_code == 200 and any(isinstance(v, (int, float)) for v in d.values())
    return {"ok": ok, "detail": f"ACRE applique, CA=80K"}
run_test(4, "Micro-entrepreneur Vente 80K + ACRE", test_04)

# ============================================================
# DOSSIER 5: TNS Gerant majoritaire
# ============================================================
def test_05():
    r = client.get("/api/simulation/tns", params={
        "revenu_net": 45000, "type_statut": "gerant_majoritaire", "acre": "false"
    })
    d = r.json()
    ok = r.status_code == 200 and any(isinstance(v, (int, float)) for v in d.values())
    return {"ok": ok, "detail": f"TNS gerant maj, revenu=45K"}
run_test(5, "TNS Gerant majoritaire SARL 45K", test_05)

# ============================================================
# DOSSIER 6: Cout employeur detaille
# ============================================================
def test_06():
    r = client.get("/api/simulation/cout-employeur", params={
        "brut_mensuel": 3000, "effectif": 20, "est_cadre": "false",
        "primes": 200, "avantages_nature": 100, "frais_km": 150,
        "tickets_restaurant": 120, "mutuelle_employeur": 50
    })
    d = r.json()
    ok = (r.status_code == 200 and
          d.get("cout_total_mensuel", 0) > 3000 and
          d.get("cout_total_annuel", 0) > 36000 and
          d.get("ratio_cout_net", 0) > 1)
    return {"ok": ok,
            "detail": f"cout_mensuel={d.get('cout_total_mensuel')}, ratio={d.get('ratio_cout_net')}"}
run_test(6, "Cout employeur detaille avec avantages", test_06)

# ============================================================
# DOSSIER 7: Exonerations ZRR
# ============================================================
def test_07():
    r = client.get("/api/simulation/exonerations", params={
        "brut_mensuel": 2000, "effectif": 5, "age_salarie": 25,
        "duree_contrat_mois": 0, "zone": "zrr", "statut_salarie": "standard",
        "heures_supplementaires": 0, "ccn": ""
    })
    d = r.json()
    ok = (r.status_code == 200 and
          d.get("total_exonerations_mensuelles", 0) >= 0 and
          isinstance(d.get("exonerations"), list))
    return {"ok": ok,
            "detail": f"exo_mensuel={d.get('total_exonerations_mensuelles')}, "
                       f"nb_exo={len(d.get('exonerations', []))}"}
run_test(7, "Exonerations ZRR (5 sal, 2000 EUR)", test_07)

# ============================================================
# DOSSIER 8: Exonerations apprenti
# ============================================================
def test_08():
    r = client.get("/api/simulation/exonerations", params={
        "brut_mensuel": 900, "effectif": 10, "age_salarie": 19,
        "duree_contrat_mois": 24, "zone": "metropole",
        "statut_salarie": "apprenti", "heures_supplementaires": 0, "ccn": ""
    })
    d = r.json()
    ok = r.status_code == 200 and d.get("total_exonerations_mensuelles", 0) >= 0
    return {"ok": ok,
            "detail": f"exo={d.get('total_exonerations_mensuelles')}, eco={d.get('economie_pct')}%"}
run_test(8, "Exonerations apprenti 19 ans", test_08)

# ============================================================
# DOSSIER 9: Masse salariale projection
# ============================================================
def test_09():
    r = client.get("/api/simulation/masse-salariale", params={
        "brut_moyen": 2800, "effectif": 25, "augmentation_pct": 3.5,
        "inflation_pct": 2.1, "frais_km_moyen": 80, "avantages_nature_moyen": 0,
        "primes_variables_pct": 8, "turnover_pct": 12
    })
    d = r.json()
    ok = (r.status_code == 200 and
          d.get("masse_actuelle", 0) > 0 and
          d.get("cout_global_projete", 0) > d.get("masse_actuelle", 0))
    return {"ok": ok,
            "detail": f"masse={d.get('masse_actuelle')}, projete={d.get('cout_global_projete')}"}
run_test(9, "Masse salariale 25 sal augmentation 3.5%", test_09)

# ============================================================
# DOSSIER 10: Seuils effectif 48 sal -> 50
# ============================================================
def test_10():
    r = client.get("/api/simulation/seuils-effectif", params={
        "effectif_actuel": 48, "masse_salariale_annuelle": 1500000
    })
    d = r.json()
    ok = (r.status_code == 200 and
          d.get("prochain_seuil") == 50 and
          d.get("cout_prochain_seuil", 0) > 0)
    return {"ok": ok,
            "detail": f"prochain={d.get('prochain_seuil')}, cout={d.get('cout_prochain_seuil')}"}
run_test(10, "Seuil effectif 48 -> 50 salaries", test_10)

# ============================================================
# DOSSIER 11: Fin contrat licenciement eco
# ============================================================
def test_11():
    r = client.get("/api/simulation/fin-contrat", params={
        "type_fin": "licenciement", "salaire_brut": 3200,
        "anciennete_mois": 60, "est_cadre": "false", "motif": "economique"
    })
    d = r.json()
    ok = (r.status_code == 200 and
          d.get("cout_total", 0) > 0 and
          d.get("anciennete_ans", 0) == 5)
    return {"ok": ok,
            "detail": f"cout_total={d.get('cout_total')}, type={d.get('type_fin')}"}
run_test(11, "Licenciement economique 5 ans anciennete", test_11)

# ============================================================
# DOSSIER 12: Rupture conventionnelle cadre
# ============================================================
def test_12():
    r = client.get("/api/simulation/fin-contrat", params={
        "type_fin": "rupture_conventionnelle", "salaire_brut": 4500,
        "anciennete_mois": 84, "est_cadre": "true", "motif": "personnel"
    })
    d = r.json()
    ok = (r.status_code == 200 and d.get("cout_total", 0) > 0)
    return {"ok": ok,
            "detail": f"cout_total={d.get('cout_total')}, anciennete={d.get('anciennete_ans')} ans"}
run_test(12, "Rupture conventionnelle cadre 7 ans", test_12)

# ============================================================
# DOSSIER 13: Optimisation remuneration SAS
# ============================================================
def test_13():
    r = client.get("/api/simulation/optimisation", params={
        "benefice_net": 100000, "remuneration_gerant": 48000,
        "dividendes": 30000, "interessement": 5000, "participation": 3000,
        "frais_pro": 8000, "pee_abondement": 2000, "nb_parts": 2,
        "forme_juridique": "sas"
    })
    d = r.json()
    ok = (r.status_code == 200 and
          d.get("meilleur_scenario") and
          isinstance(d.get("scenarios"), list) and
          len(d.get("scenarios", [])) >= 2)
    return {"ok": ok,
            "detail": f"meilleur={d.get('meilleur_scenario')}, {len(d.get('scenarios',[]))} scenarios"}
run_test(13, "Optimisation remuneration SAS 100K benefice", test_13)

# ============================================================
# DOSSIER 14: Risques sectoriels BTP
# ============================================================
def test_14():
    r = client.get("/api/simulation/risques-sectoriels", params={
        "code_naf": "4120A", "effectif": 30, "masse_salariale": 900000
    })
    d = r.json()
    ok = (r.status_code == 200 and
          isinstance(d.get("risques_specifiques"), list) and
          isinstance(d.get("risques_financiers"), list) and
          d.get("taux_at_moyen", 0) > 0)
    return {"ok": ok,
            "detail": f"secteur={d.get('secteur')}, taux_at={d.get('taux_at_moyen')}%"}
run_test(14, "Risques sectoriels BTP (30 sal)", test_14)

# ============================================================
# DOSSIER 15: GUSO spectacle vivant
# ============================================================
def test_15():
    r = client.get("/api/simulation/guso", params={
        "salaire_brut": 500, "nb_heures": 8
    })
    d = r.json()
    ok = r.status_code == 200 and any(isinstance(v, (int, float)) for v in d.values())
    return {"ok": ok, "detail": f"GUSO 500 EUR / 8h"}
run_test(15, "GUSO spectacle vivant 500 EUR / 8h", test_15)

# ============================================================
# DOSSIER 16: IR independant
# ============================================================
def test_16():
    r = client.get("/api/simulation/impot-independant", params={
        "benefice": 55000, "nb_parts": 1.5, "autres_revenus": 5000
    })
    d = r.json()
    ok = r.status_code == 200 and any(isinstance(v, (int, float)) for v in d.values())
    return {"ok": ok, "detail": f"IR benefice=55K, parts=1.5"}
run_test(16, "IR independant 55K benefice 1.5 parts", test_16)

# ============================================================
# DOSSIER 17: Ajouter entreprise au portefeuille
# ============================================================
def test_17():
    import random
    siret = f"{random.randint(10000000000000, 99999999999999)}"
    r = client.post("/api/entreprises", data={
        "siret": siret, "raison_sociale": "SARL TestCom",
        "forme_juridique": "SARL", "code_naf": "4711A",
        "effectif": "12", "ville": "Lyon"
    })
    d = r.json()
    ok = r.status_code == 200
    r2 = client.get("/api/entreprises")
    ents = r2.json()
    ok = ok and len(ents) >= 1
    return {"ok": ok, "detail": f"{len(ents)} entreprise(s) en portefeuille"}
run_test(17, "Ajout entreprise portefeuille SARL", test_17)

# ============================================================
# DOSSIER 18: Ajouter 2eme entreprise + recherche
# ============================================================
def test_18():
    import random
    siret = f"{random.randint(10000000000000, 99999999999999)}"
    client.post("/api/entreprises", data={
        "siret": siret, "raison_sociale": "SAS InnoTech",
        "forme_juridique": "SAS", "code_naf": "6201Z",
        "effectif": "45", "ville": "Paris"
    })
    r = client.get("/api/entreprises", params={"q": "Inno"})
    ents = r.json()
    ok = r.status_code == 200 and any("Inno" in e.get("raison_sociale", "") for e in ents)
    return {"ok": ok, "detail": f"Recherche 'Inno': {len(ents)} resultat(s)"}
run_test(18, "Recherche entreprise portefeuille", test_18)

# ============================================================
# DOSSIER 19: Veille juridique 2026
# ============================================================
def test_19():
    r = client.get("/api/veille/baremes/2026")
    d = r.json()
    ok = (r.status_code == 200 and
          "plafond_securite_sociale" in str(d).lower() or "smic" in str(d).lower() or len(d) > 3)
    return {"ok": ok, "detail": f"{len(d)} parametres baremes 2026"}
run_test(19, "Veille juridique baremes 2026", test_19)

# ============================================================
# DOSSIER 20: Veille legislation + comparaison N-1
# ============================================================
def test_20():
    r1 = client.get("/api/veille/legislation/2026")
    r2 = client.get("/api/veille/baremes/comparer/2025/2026")
    d1 = r1.json()
    d2 = r2.json()
    ok = (r1.status_code == 200 and r2.status_code == 200 and
          "textes_cles" in d1 and isinstance(d2, list))
    return {"ok": ok,
            "detail": f"Legislation: {len(d1.get('textes_cles',[]))} textes, "
                       f"Evolutions: {len(d2)} changements"}
run_test(20, "Legislation 2026 + comparaison N-1", test_20)

# ============================================================
# DOSSIER 21: Creer contrat CDI
# ============================================================
def test_21():
    r = client.post("/api/rh/contrats", data={
        "type_contrat": "CDI", "nom_salarie": "MARTIN",
        "prenom_salarie": "Pierre", "poste": "Developpeur",
        "date_debut": "2026-01-15", "date_fin": "",
        "salaire_brut": "3200", "temps_travail": "complet",
        "duree_hebdo": "35", "convention_collective": "SYNTEC",
        "periode_essai_jours": "90", "motif_cdd": ""
    })
    d = r.json()
    ok = (r.status_code == 200 and d.get("type_contrat") == "CDI" and
          "id" in d)
    return {"ok": ok,
            "detail": f"Contrat ID={d.get('id')}, cascading={bool(d.get('cascading_effects'))}"}
run_test(21, "Creation contrat CDI SYNTEC", test_21)

# ============================================================
# DOSSIER 22: Creer contrat CDD avec effets cascade
# ============================================================
def test_22():
    r = client.post("/api/rh/contrats", data={
        "type_contrat": "CDD", "nom_salarie": "DUPONT",
        "prenom_salarie": "Sophie", "poste": "Assistante RH",
        "date_debut": "2026-03-01", "date_fin": "2026-08-31",
        "salaire_brut": "2200", "temps_travail": "complet",
        "duree_hebdo": "35", "convention_collective": "",
        "periode_essai_jours": "30", "motif_cdd": "surcroit"
    })
    d = r.json()
    ok = r.status_code == 200 and d.get("type_contrat") == "CDD"
    cascade = d.get("cascading_effects", {})
    return {"ok": ok,
            "detail": f"CDD cree, dpae={cascade.get('dpae')}, "
                       f"visite={bool(cascade.get('visite_medicale'))}"}
run_test(22, "Creation contrat CDD + effets cascade", test_22)

# ============================================================
# DOSSIER 23: Generer bulletin de paie
# ============================================================
def test_23():
    r = client.post("/api/rh/bulletins/generer", data={
        "nom_salarie": "MARTIN", "prenom_salarie": "Pierre",
        "mois": "2026-01", "salaire_brut": "3200",
        "est_cadre": "true", "heures_travaillees": "151.67",
        "heures_supplementaires": "5", "primes": "200",
        "avantages_nature": "0", "jours_absence": "0"
    })
    d = r.json()
    ok = (r.status_code == 200 and
          d.get("net_a_payer", 0) > 0 and
          d.get("total_patronal", 0) > 0)
    return {"ok": ok,
            "detail": f"net={d.get('net_a_payer')}, patronal={d.get('total_patronal')}"}
run_test(23, "Bulletin de paie MARTIN janv 2026", test_23)

# ============================================================
# DOSSIER 24: Enregistrer conge
# ============================================================
def test_24():
    r = client.post("/api/rh/conges", data={
        "nom_salarie": "MARTIN Pierre", "type_conge": "cp",
        "date_debut": "2026-04-01", "date_fin": "2026-04-10",
        "nb_jours": "7", "statut": "valide"
    })
    d = r.json()
    ok = (r.status_code == 200 and
          (d.get("type") == "cp" or d.get("type_conge") == "cp"))
    return {"ok": ok,
            "detail": f"Conge enregistre: type={d.get('type') or d.get('type_conge')}, "
                       f"{d.get('nb_jours')} jours, status={r.status_code}"}
run_test(24, "Enregistrement conge paye MARTIN", test_24)

# ============================================================
# DOSSIER 25: Ecriture comptable manuelle
# ============================================================
def test_25():
    r = client.post("/api/comptabilite/ecriture/manuelle", data={
        "date_piece": "2026-01-15", "libelle": "Achat fournitures bureau",
        "compte_debit": "606100", "compte_credit": "401000",
        "montant": "350.50", "has_justificatif": "true"
    })
    d = r.json()
    ok = r.status_code == 200 and "ecriture_id" in d and d.get("sans_justificatif") == False
    return {"ok": ok,
            "detail": f"Ecriture ID={d.get('ecriture_id')}, sans_justif={d.get('sans_justificatif')}"}
run_test(25, "Ecriture comptable achat fournitures", test_25)

# ============================================================
# DOSSIER 26: Ecriture sans justificatif (anomalie)
# ============================================================
def test_26():
    r = client.post("/api/comptabilite/ecriture/manuelle", data={
        "date_piece": "2026-02-10", "libelle": "Frais divers",
        "compte_debit": "625000", "compte_credit": "512000",
        "montant": "1200", "has_justificatif": "false"
    })
    d = r.json()
    ok = (r.status_code == 200 and
          d.get("sans_justificatif") == True and
          d.get("alerte"))
    return {"ok": ok,
            "detail": f"Sans justif={d.get('sans_justificatif')}, alerte={d.get('alerte','')[:80]}"}
run_test(26, "Ecriture SANS justificatif (anomalie)", test_26)

# ============================================================
# DOSSIER 27: Journal comptable + balance
# ============================================================
def test_27():
    r1 = client.get("/api/comptabilite/journal")
    r2 = client.get("/api/comptabilite/balance")
    j = r1.json()
    b = r2.json()
    ok = (r1.status_code == 200 and r2.status_code == 200 and
          isinstance(j, list) and len(j) >= 2 and
          isinstance(b, list) and len(b) >= 2)
    return {"ok": ok,
            "detail": f"Journal: {len(j)} ecritures, Balance: {len(b)} comptes"}
run_test(27, "Consultation journal + balance", test_27)

# ============================================================
# DOSSIER 28: Compte de resultat + bilan
# ============================================================
def test_28():
    r1 = client.get("/api/comptabilite/compte-resultat")
    r2 = client.get("/api/comptabilite/bilan")
    cr = r1.json()
    bi = r2.json()
    ok = (r1.status_code == 200 and r2.status_code == 200 and
          "charges" in cr and "produits" in cr and "resultat_net" in cr and
          "actif" in bi and "passif" in bi)
    return {"ok": ok,
            "detail": f"Resultat net={cr.get('resultat_net')}, "
                       f"Actif={bi.get('actif',{}).get('total')}, "
                       f"Passif={bi.get('passif',{}).get('total')}"}
run_test(28, "Compte de resultat + bilan", test_28)

# ============================================================
# DOSSIER 29: Plan comptable + recherche
# ============================================================
def test_29():
    r1 = client.get("/api/comptabilite/plan-comptable")
    r2 = client.get("/api/comptabilite/plan-comptable", params={"terme": "fournisseur"})
    pc = r1.json()
    pcs = r2.json()
    ok = (r1.status_code == 200 and r2.status_code == 200 and
          len(pc) >= 50 and
          all("numero" in c and "libelle" in c for c in pc[:5]))
    return {"ok": ok,
            "detail": f"Plan: {len(pc)} comptes, recherche 'fournisseur': {len(pcs)} resultats"}
run_test(29, "Plan comptable + recherche", test_29)

# ============================================================
# DOSSIER 30: Comptabiliser facture manuelle
# ============================================================
def test_30():
    r = client.post("/api/factures/comptabiliser", data={
        "type": "facture_achat", "date": "2026-01-20",
        "numero_piece": "FA-2026-001", "tiers": "Fournisseur X",
        "montant_ht": "800", "montant_tva": "160", "montant_ttc": "960"
    })
    d = r.json()
    ok = r.status_code == 200
    return {"ok": ok,
            "detail": f"Facture comptabilisee, ecriture={d.get('ecriture_id','?')}"}
run_test(30, "Comptabiliser facture achat FA-2026-001", test_30)


# ============================================================
# TESTS SUPPLEMENTAIRES: Verification integration
# ============================================================
print()
print("-" * 70)
print("TESTS SUPPLEMENTAIRES - COHERENCE ET REPORTING")
print("-" * 70)

# TVA
def test_s1():
    r = client.get("/api/comptabilite/declaration-tva", params={"mois": 1, "annee": 2026})
    d = r.json()
    ok = (r.status_code == 200 and
          "chiffre_affaires_ht" in d and "tva_collectee" in d and
          "tva_deductible_totale" in d)
    return {"ok": ok, "detail": f"CA_HT={d.get('chiffre_affaires_ht')}, TVA coll={d.get('tva_collectee')}"}
run_test("S1", "Declaration TVA janvier 2026", test_s1)

# Charges sociales detail
def test_s2():
    r = client.get("/api/comptabilite/charges-sociales-detail")
    d = r.json()
    ok = (r.status_code == 200 and
          "destinataires" in d and isinstance(d.get("destinataires"), list))
    return {"ok": ok,
            "detail": f"{len(d.get('destinataires',[]))} destinataires, total={d.get('total')}"}
run_test("S2", "Charges sociales detail", test_s2)

# Grand livre
def test_s3():
    r = client.get("/api/comptabilite/grand-livre-detail")
    d = r.json()
    ok = r.status_code == 200 and isinstance(d, list)
    return {"ok": ok, "detail": f"{len(d)} comptes dans le grand livre"}
run_test("S3", "Grand livre detail", test_s3)

# Alertes RH
def test_s4():
    r = client.get("/api/rh/alertes")
    d = r.json()
    ok = r.status_code == 200 and "alertes" in d
    return {"ok": ok, "detail": f"{d.get('nb_alertes', 0)} alerte(s) RH"}
run_test("S4", "Alertes RH automatiques", test_s4)

# Equipe + audit log
def test_s5():
    r = client.get("/api/collaboration/equipe")
    d = r.json()
    ok = (r.status_code == 200 and
          "audit_log" in d and isinstance(d.get("audit_log"), list) and
          len(d.get("audit_log", [])) >= 1)
    return {"ok": ok, "detail": f"{len(d.get('audit_log',[]))} entrees journal d'audit"}
run_test("S5", "Journal audit + equipe", test_s5)

# Knowledge base
def test_s6():
    r = client.get("/api/bibliotheque/knowledge")
    d = r.json()
    ok = r.status_code == 200 and "summary" in d
    return {"ok": ok, "detail": f"Base de connaissances accessible"}
run_test("S6", "Bibliotheque - base de connaissances", test_s6)

# IDCC
def test_s7():
    r = client.get("/api/idcc/recherche", params={"terme": "informatique"})
    d = r.json()
    resultats = d.get("resultats", d) if isinstance(d, dict) else d
    ok = r.status_code == 200 and len(resultats) > 0
    return {"ok": ok, "detail": f"Recherche IDCC 'informatique': {len(resultats)} resultat(s)"}
run_test("S7", "Recherche IDCC informatique", test_s7)

# ATMP
def test_s8():
    r = client.get("/api/atmp/taux", params={"code_naf": "6201Z", "effectif": 20})
    d = r.json()
    ok = r.status_code == 200 and d.get("taux") is not None
    return {"ok": ok, "detail": f"Taux AT/MP 6201Z: {d.get('taux', d.get('taux_collectif'))}%"}
run_test("S8", "Taux AT/MP informatique", test_s8)

# Config entete
def test_s9():
    r = client.post("/api/config/entete", data={
        "nom_entreprise": "Cabinet Expert Test",
        "adresse": "10 rue de la Paix, 75002 Paris",
        "telephone": "01 23 45 67 89",
        "email": "contact@cabinet-test.fr",
        "siret": "12345678901234",
        "code_ape": "6920Z"
    })
    ok = r.status_code == 200
    return {"ok": ok, "detail": "Configuration entete sauvegardee"}
run_test("S9", "Configuration en-tete documents", test_s9)

# Validation ecritures
def test_s10():
    r = client.post("/api/comptabilite/valider")
    d = r.json()
    ok = r.status_code == 200 and "nb_validees" in d
    return {"ok": ok, "detail": f"Validees: {d.get('nb_validees')}, erreurs: {d.get('erreurs',[])}"}
run_test("S10", "Validation ecritures comptables", test_s10)

# Health
def test_s11():
    r = client.get("/api/health")
    d = r.json()
    ok = r.status_code == 200 and d.get("status") == "ok"
    return {"ok": ok, "detail": f"v{d.get('version')} - {d.get('env')}"}
run_test("S11", "Health check serveur", test_s11)

# Version
def test_s12():
    r = client.get("/api/version")
    d = r.json()
    ok = r.status_code == 200 and d.get("version", "").startswith("3.")
    return {"ok": ok, "detail": f"v{d.get('version')}, checks={d.get('audit_checks')}"}
run_test("S12", "Version et capacites", test_s12)


# ============================================================
# RAPPORT FINAL
# ============================================================
print()
print("=" * 70)
print(f"RESULTATS: {PASSED}/{TOTAL} PASSES, {TOTAL-PASSED} ECHEC(S)")
print("=" * 70)

failures = [r for r in results if not r["ok"]]
if failures:
    print()
    print("DETAIL DES ECHECS:")
    for f in failures:
        print(f"\n  #{f['num']}: {f['name']}")
        print(f"  Detail: {f['detail']}")
        if f.get("error"):
            print(f"  Traceback: {f['error'][:200]}")
else:
    print()
    print("TOUS LES TESTS SONT PASSES !")

print()
print("RESUME FONCTIONNALITES TESTEES:")
print("  - Simulation bulletins de paie (cadre/non-cadre)")
print("  - Micro-entrepreneur (BNC, vente, ACRE)")
print("  - TNS gerant majoritaire")
print("  - Cout employeur detaille avec avantages")
print("  - Exonerations (ZRR, apprenti)")
print("  - Masse salariale projection")
print("  - Seuils effectif")
print("  - Fins de contrats (licenciement, rupture conventionnelle)")
print("  - Optimisation remuneration")
print("  - Risques sectoriels")
print("  - GUSO spectacle vivant")
print("  - IR independant")
print("  - Portefeuille multi-entreprises")
print("  - Veille juridique + comparaison N-1")
print("  - Contrats de travail CDI/CDD + effets cascade")
print("  - Bulletins de paie")
print("  - Conges")
print("  - Ecritures comptables (avec/sans justificatif)")
print("  - Journal + balance + compte de resultat + bilan")
print("  - Plan comptable")
print("  - Facturation")
print("  - TVA + charges sociales")
print("  - Grand livre")
print("  - Alertes RH")
print("  - Journal d'audit + equipe")
print("  - IDCC + AT/MP")
print("  - Configuration")

sys.exit(0 if not failures else 1)
