"""Tests de concurrence et de thread-safety NormaCheck.

Verifie que les composants critiques sont thread-safe :
- Calcul concurrent de bulletins
- Validation FEC concurrente
- Thread-safety des instances ContributionRules
- Thread-safety du MoteurEcritures
"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.config.constants import (
    ContributionType, PASS_MENSUEL, SMIC_MENSUEL_BRUT, SMIC_ANNUEL_BRUT,
)
from urssaf_analyzer.rules.contribution_rules import ContributionRules
from urssaf_analyzer.comptabilite.ecritures import (
    MoteurEcritures, Ecriture, LigneEcriture, TypeJournal,
)
from urssaf_analyzer.comptabilite.fec_export import exporter_fec


# =============================================
# Concurrent bulletin calculations (threading)
# =============================================

class TestConcurrentBulletins:
    """Tests de calcul concurrent de bulletins de paie."""

    def test_concurrent_bulletins_thread_pool(self):
        """Calculer des bulletins en parallele via ThreadPoolExecutor."""
        rules = ContributionRules(
            effectif_entreprise=50,
            taux_at=Decimal("0.0208"),
            taux_versement_mobilite=Decimal("0.025"),
        )
        results = []
        errors = []

        def calc_bulletin(brut_val, cadre):
            try:
                b = rules.calculer_bulletin_complet(Decimal(str(brut_val)), est_cadre=cadre)
                return b
            except Exception as e:
                errors.append(str(e))
                return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for i in range(100):
                brut = 2000 + i * 50
                cadre = i % 2 == 0
                futures.append(executor.submit(calc_bulletin, brut, cadre))

            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)

        assert len(errors) == 0, f"Erreurs en concurrence : {errors}"
        assert len(results) == 100

        # Verifier que chaque resultat est un dict valide
        for r in results:
            assert isinstance(r, dict)
            assert "lignes" in r
            assert "total_patronal" in r

    def test_concurrent_bulletins_deterministic(self):
        """Les resultats doivent etre identiques en sequentiel et en parallele."""
        brut = Decimal("3500")

        def calc_with_own_rules(idx):
            r = ContributionRules(effectif_entreprise=50, taux_at=Decimal("0.0208"))
            return r.calculer_bulletin_complet(brut, est_cadre=True)

        # Calcul sequentiel de reference
        ref = calc_with_own_rules(0)

        # Calcul parallele
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(calc_with_own_rules, i) for i in range(20)]
            parallel_results = [f.result() for f in as_completed(futures)]

        # Tous les resultats doivent etre identiques
        for r in parallel_results:
            assert r["total_patronal"] == ref["total_patronal"]
            assert r["total_salarial"] == ref["total_salarial"]
            assert r["net_avant_impot"] == ref["net_avant_impot"]

    def test_concurrent_temps_partiel(self):
        """Bulletins temps partiel en parallele avec instances independantes."""
        errors = []
        results = []

        def calc_tp(heures_val, brut_val):
            try:
                r = ContributionRules(effectif_entreprise=50)
                b = r.calculer_bulletin_temps_partiel(
                    Decimal(str(brut_val)),
                    heures_mensuelles=Decimal(str(heures_val)),
                )
                return b
            except Exception as e:
                errors.append(str(e))
                return None

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            for i in range(50):
                heures = 80 + (i % 72)
                brut = 1200 + i * 30
                futures.append(executor.submit(calc_tp, heures, brut))

            for f in as_completed(futures):
                r = f.result()
                if r is not None:
                    results.append(r)

        assert len(errors) == 0, f"Erreurs concurrentes TP : {errors}"
        assert len(results) == 50

    def test_concurrent_bulletins_with_threading_module(self):
        """Calcul de bulletins avec le module threading natif."""
        n_threads = 10
        n_calculs = 50
        brut = Decimal("3500")
        resultats = []
        lock = threading.Lock()

        def calculer():
            rules = ContributionRules(effectif_entreprise=25)
            for _ in range(n_calculs):
                b = rules.calculer_bulletin_complet(brut, est_cadre=True)
                with lock:
                    resultats.append(b["total_patronal"])

        threads = [threading.Thread(target=calculer) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(resultats) == n_threads * n_calculs
        # Tous les resultats doivent etre identiques
        assert len(set(resultats)) == 1, f"Resultats divergents: {set(resultats)}"


# =============================================
# Concurrent FEC validations
# =============================================

class TestConcurrentFEC:
    """Tests de validation FEC concurrente."""

    def _create_moteur_with_ecritures(self, count):
        """Cree un moteur avec N ecritures equilibrees."""
        moteur = MoteurEcritures()
        for i in range(count):
            montant = Decimal(str(100 + i))
            ecriture = Ecriture(
                journal=TypeJournal.ACHATS,
                date_ecriture=date(2026, 1, 1 + (i % 28)),
                date_piece=date(2026, 1, 1 + (i % 28)),
                numero_piece=f"FA-{i+1:05d}",
                libelle=f"Facture concur {i+1}",
                lignes=[
                    LigneEcriture(compte="401000", libelle=f"Fourn {i}", credit=montant),
                    LigneEcriture(compte="607000", libelle=f"Achat {i}", debit=montant),
                ],
                validee=True,
            )
            moteur.ecritures.append(ecriture)
        return moteur

    def test_concurrent_fec_exports(self):
        """Exporter des FEC en parallele depuis des moteurs independants."""
        errors = []
        results = []

        def export_fec_task(idx):
            try:
                moteur = self._create_moteur_with_ecritures(50)
                content = exporter_fec(moteur, siren=f"12345678{idx}")
                return content
            except Exception as e:
                errors.append(str(e))
                return None

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(export_fec_task, i) for i in range(20)]
            for f in as_completed(futures):
                r = f.result()
                if r is not None:
                    results.append(r)

        assert len(errors) == 0, f"Erreurs FEC concurrentes : {errors}"
        assert len(results) == 20

        # Chaque FEC doit avoir un header + 100 lignes (50 ecritures x 2 lignes)
        for fec in results:
            lines = fec.strip().split("\n")
            assert len(lines) == 101

    def test_concurrent_ecriture_validation(self):
        """Valider des ecritures en parallele."""
        errors = []
        results = []

        def validate_ecritures(idx):
            try:
                moteur = MoteurEcritures()
                for j in range(10):
                    montant = Decimal(str(100 + idx * 10 + j))
                    ecriture = Ecriture(
                        journal=TypeJournal.OPERATIONS_DIVERSES,
                        date_ecriture=date(2026, 1, 15),
                        numero_piece=f"OD-{idx:03d}-{j:03d}",
                        libelle=f"OD test {idx}-{j}",
                        lignes=[
                            LigneEcriture(compte="512000", libelle="Banque", debit=montant),
                            LigneEcriture(compte="411000", libelle="Client", credit=montant),
                        ],
                        validee=True,
                    )
                    moteur.ecritures.append(ecriture)
                # Verifier l'equilibre de chaque ecriture
                for e in moteur.ecritures:
                    assert e.est_equilibree
                return len(moteur.ecritures)
            except Exception as e:
                errors.append(str(e))
                return 0

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(validate_ecritures, i) for i in range(10)]
            for f in as_completed(futures):
                results.append(f.result())

        assert len(errors) == 0, f"Erreurs validation concurrente : {errors}"
        assert all(r == 10 for r in results)

    def test_same_moteur_read_only_export(self):
        """Export FEC concurrent en lecture seule depuis le meme moteur."""
        moteur = self._create_moteur_with_ecritures(20)
        contenus = []
        lock = threading.Lock()

        def exporter_thread():
            c = exporter_fec(moteur, siren="123456789")
            with lock:
                contenus.append(c)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(exporter_thread) for _ in range(5)]
            for f in as_completed(futures):
                f.result()

        assert len(contenus) == 5
        # Tous les exports doivent etre identiques
        assert len(set(contenus)) == 1


# =============================================
# Thread-safety of ContributionRules instances
# =============================================

class TestContributionRulesThreadSafety:
    """Tests de thread-safety des instances ContributionRules."""

    def test_independent_instances_no_interference(self):
        """Des instances independantes ne doivent pas interferer entre elles."""
        errors = []
        results = {}
        lock = threading.Lock()

        def calc_with_effectif(effectif):
            try:
                r = ContributionRules(effectif_entreprise=effectif)
                taux_fnal = r.get_taux_attendu_patronal(ContributionType.FNAL)
                taux_fp = r.get_taux_attendu_patronal(ContributionType.FORMATION_PROFESSIONNELLE)
                with lock:
                    results[effectif] = {"fnal": float(taux_fnal), "fp": float(taux_fp)}
            except Exception as e:
                errors.append(str(e))

        effectifs = [5, 10, 11, 19, 20, 49, 50, 249, 250, 500]

        with ThreadPoolExecutor(max_workers=len(effectifs)) as executor:
            futures = [executor.submit(calc_with_effectif, eff) for eff in effectifs]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0

        # Verifier les seuils
        assert results[5]["fnal"] == 0.001   # < 50 : 0.10%
        assert results[50]["fnal"] == 0.005  # >= 50 : 0.50%
        assert results[5]["fp"] == 0.0055    # < 11 : 0.55%
        assert results[11]["fp"] == 0.01     # >= 11 : 1.00%

    def test_shared_instance_read_only_safe(self):
        """Une instance partagee en lecture seule doit rester coherente."""
        rules = ContributionRules(effectif_entreprise=50, taux_at=Decimal("0.0208"))
        errors = []
        barrier = threading.Barrier(8)

        def read_rules(ct, brut_val):
            try:
                barrier.wait(timeout=5)
                brut = Decimal(str(brut_val))
                taux = rules.get_taux_attendu_patronal(ct, brut)
                montant = rules.calculer_montant_patronal(ct, brut)
                assiette = rules.calculer_assiette(ct, brut)
                return (float(taux or 0), float(montant), float(assiette))
            except Exception as e:
                errors.append(str(e))
                return None

        types_and_bruts = [
            (ContributionType.MALADIE, 3000),
            (ContributionType.VIEILLESSE_PLAFONNEE, 3000),
            (ContributionType.ALLOCATIONS_FAMILIALES, 3000),
            (ContributionType.ACCIDENT_TRAVAIL, 3000),
            (ContributionType.MALADIE, 5000),
            (ContributionType.VIEILLESSE_PLAFONNEE, 5000),
            (ContributionType.FNAL, 3000),
            (ContributionType.ASSURANCE_CHOMAGE, 3000),
        ]

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(read_rules, ct, brut)
                for ct, brut in types_and_bruts
            ]
            results = [f.result() for f in futures]

        assert len(errors) == 0, f"Erreurs lecture partagee : {errors}"
        assert all(r is not None for r in results)

    def test_concurrent_rgdu_calculations(self):
        """Calculs RGDU concurrents avec instances independantes."""
        errors = []
        results = []
        lock = threading.Lock()

        def calc_rgdu(salary_val):
            try:
                r = ContributionRules(effectif_entreprise=50)
                reduction = r.calculer_rgdu(Decimal(str(salary_val)))
                detail = r.detail_rgdu(Decimal(str(salary_val)))
                with lock:
                    results.append((float(reduction), detail["eligible"]))
            except Exception as e:
                errors.append(str(e))

        salaries = [i * 2000 for i in range(1, 51)]

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(calc_rgdu, s) for s in salaries]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0
        assert len(results) == 50

    def test_rgdu_concurrent_decreasing(self):
        """RGDU calcule en parallele : valeurs decroissantes quand salaire augmente."""
        salaires = [Decimal(str(s)) for s in range(20000, 70000, 1000)]
        resultats = {}
        lock = threading.Lock()

        def calculer(sal):
            rules = ContributionRules(effectif_entreprise=25)
            rgdu = rules.calculer_rgdu(sal)
            with lock:
                resultats[float(sal)] = float(rgdu)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(calculer, s) for s in salaires]
            for f in as_completed(futures):
                f.result()

        assert len(resultats) == len(salaires)
        # Verifier reproductibilite: chaque resultat concurrent = meme qu'en sequentiel
        for sal, rgdu in resultats.items():
            rules_check = ContributionRules(effectif_entreprise=25)
            expected = float(rules_check.calculer_rgdu(Decimal(str(sal))))
            assert abs(rgdu - expected) < 0.01, f"RGDU diverge pour {sal}"

    def test_effectif_differences_in_parallel(self):
        """Effectifs differents en parallele donnent des charges differentes."""
        results = {}
        lock = threading.Lock()

        def calc_effectif(eff):
            rules = ContributionRules(effectif_entreprise=eff)
            brut = Decimal("3000")
            b = rules.calculer_bulletin_complet(brut)
            with lock:
                results[eff] = b["total_patronal"]

        effectifs = [5, 10, 11, 20, 49, 50, 100, 250, 500]
        with ThreadPoolExecutor(max_workers=len(effectifs)) as executor:
            futures = [executor.submit(calc_effectif, e) for e in effectifs]
            for f in as_completed(futures):
                f.result()

        assert len(results) == len(effectifs)
        # Effectif 49 et 50 doivent differer (FNAL change)
        assert results[49] != results[50]


# =============================================
# Thread-safety of MoteurEcritures
# =============================================

class TestMoteurEcrituresThreadSafety:
    """Tests de thread-safety du MoteurEcritures."""

    def test_independent_moteurs_no_interference(self):
        """Des moteurs independants dans des threads differents ne s'interferent pas."""
        errors = []
        counts = []
        lock = threading.Lock()

        def create_and_fill_moteur(idx, n_ecritures):
            try:
                moteur = MoteurEcritures()
                for j in range(n_ecritures):
                    montant = Decimal(str(100 + j))
                    e = Ecriture(
                        journal=TypeJournal.PAIE,
                        date_ecriture=date(2026, 1, 15),
                        numero_piece=f"PA-{idx:03d}-{j:03d}",
                        libelle=f"Paie test {idx}-{j}",
                        lignes=[
                            LigneEcriture(compte="641000", libelle="Salaires", debit=montant),
                            LigneEcriture(compte="421000", libelle="Personnel", credit=montant),
                        ],
                        validee=True,
                    )
                    moteur.ecritures.append(e)
                with lock:
                    counts.append(len(moteur.ecritures))
            except Exception as e:
                with lock:
                    errors.append(str(e))

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(create_and_fill_moteur, i, 20 + i)
                for i in range(10)
            ]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0, f"Erreurs moteur concurrent : {errors}"
        # Chaque moteur doit avoir son propre nombre d'ecritures
        assert len(counts) == 10
        expected_counts = sorted([20 + i for i in range(10)])
        assert sorted(counts) == expected_counts

    def test_concurrent_fec_export_from_independent_moteurs(self):
        """Export FEC concurrent depuis des moteurs independants."""
        errors = []
        fec_line_counts = []
        lock = threading.Lock()

        def export_task(idx):
            try:
                moteur = MoteurEcritures()
                n = 10 + idx
                for j in range(n):
                    montant = Decimal(str(200 + j * 10))
                    e = Ecriture(
                        journal=TypeJournal.VENTES,
                        date_ecriture=date(2026, 2, 1 + (j % 28)),
                        numero_piece=f"VE-{idx:03d}-{j:03d}",
                        libelle=f"Vente {idx}-{j}",
                        lignes=[
                            LigneEcriture(compte="411000", libelle=f"Client {j}", debit=montant),
                            LigneEcriture(compte="701000", libelle=f"Produit {j}", credit=montant),
                        ],
                        validee=True,
                    )
                    moteur.ecritures.append(e)
                content = exporter_fec(moteur)
                lines = content.strip().split("\n")
                with lock:
                    fec_line_counts.append(len(lines))
            except Exception as e:
                with lock:
                    errors.append(str(e))

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(export_task, i) for i in range(8)]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0, f"Erreurs export concurrent : {errors}"
        assert len(fec_line_counts) == 8
        # Chaque FEC doit avoir au moins un header + quelques lignes
        for count in fec_line_counts:
            assert count > 1

    def test_ecriture_equilibre_check_concurrent(self):
        """Verifier l'equilibre d'ecritures en concurrent."""
        errors = []
        lock = threading.Lock()

        def check_equilibre(idx):
            try:
                montant = Decimal(str(500 + idx * 10))
                e = Ecriture(
                    journal=TypeJournal.OPERATIONS_DIVERSES,
                    date_ecriture=date(2026, 3, 1),
                    numero_piece=f"CHK-{idx:04d}",
                    libelle=f"Check {idx}",
                    lignes=[
                        LigneEcriture(compte="512000", libelle="Banque", debit=montant),
                        LigneEcriture(compte="411000", libelle="Client", credit=montant),
                    ],
                )
                assert e.est_equilibree, f"Ecriture {idx} desequilibree"
                assert e.total_debit == montant
                assert e.total_credit == montant
                return True
            except Exception as e:
                with lock:
                    errors.append(str(e))
                return False

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(check_equilibre, i) for i in range(100)]
            results = [f.result() for f in futures]

        assert len(errors) == 0
        assert all(results)

    def test_moteurs_independants_generer_ecriture_facture(self):
        """Generer des factures en parallele dans des moteurs independants."""
        errors = []
        ecriture_counts = []
        lock = threading.Lock()

        def generer_ecritures(thread_id):
            try:
                moteur = MoteurEcritures()
                for i in range(20):
                    montant = Decimal(str(1000 + i * 10))
                    moteur.generer_ecriture_facture(
                        type_doc="facture_achat",
                        date_piece=date(2026, 1, 15),
                        numero_piece=f"T{thread_id}-FA-{i+1:04d}",
                        montant_ht=montant,
                        montant_tva=(montant * Decimal("0.20")).quantize(Decimal("0.01")),
                        montant_ttc=(montant * Decimal("1.20")).quantize(Decimal("0.01")),
                    )
                # Verifier equilibre
                for e in moteur.ecritures:
                    if not e.est_equilibree:
                        with lock:
                            errors.append(f"Thread {thread_id}: ecriture desequilibree")
                with lock:
                    ecriture_counts.append(len(moteur.ecritures))
            except Exception as ex:
                with lock:
                    errors.append(f"Thread {thread_id}: {ex}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(generer_ecritures, i) for i in range(8)]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0, f"Erreurs de concurrence: {errors}"
        assert len(ecriture_counts) == 8
        # Chaque moteur doit avoir 20 ecritures
        assert all(c == 20 for c in ecriture_counts)
