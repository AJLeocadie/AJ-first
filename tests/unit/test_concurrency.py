"""Tests de concurrence : thread-safety des modules critiques.

Verifie que les calculs de cotisations et les operations comptables
sont thread-safe pour utilisation en contexte web multi-utilisateur.
"""

import sys
import time
import threading
from pathlib import Path
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.config.constants import (
    ContributionType, PASS_MENSUEL, SMIC_MENSUEL_BRUT,
)
from urssaf_analyzer.rules.contribution_rules import ContributionRules
from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures, Ecriture, LigneEcriture, TypeJournal
from urssaf_analyzer.comptabilite.fec_export import exporter_fec, valider_fec


class TestContributionRulesConcurrent:
    """Thread-safety des calculs de cotisations."""

    def test_bulletins_concurrents_resultats_coherents(self):
        """N bulletins calcules en parallele donnent les memes resultats."""
        brut = Decimal("3500")
        n_threads = 10
        n_calculs = 50
        resultats = []

        def calculer():
            rules = ContributionRules(effectif_entreprise=25)
            for _ in range(n_calculs):
                b = rules.calculer_bulletin_complet(brut, est_cadre=True)
                resultats.append(b["total_patronal"])

        threads = [threading.Thread(target=calculer) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(resultats) == n_threads * n_calculs
        # Tous les resultats doivent etre identiques
        assert len(set(resultats)) == 1, f"Resultats divergents: {set(resultats)}"

    def test_rgdu_concurrent(self):
        """RGDU calcule en parallele avec differents salaires."""
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
        # Tous les resultats doivent etre reproductibles (meme salaire = meme resultat)
        # Recalculer sequentiellement pour verifier
        for sal, rgdu in resultats.items():
            rules_check = ContributionRules(effectif_entreprise=25)
            expected = float(rules_check.calculer_rgdu(Decimal(str(sal))))
            assert abs(rgdu - expected) < 0.01, f"RGDU diverge pour {sal}"

    def test_instances_independantes(self):
        """Chaque instance de ContributionRules est independante."""
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

        # Effectifs differents = charges differentes (a cause FNAL, formation, etc.)
        assert len(results) == len(effectifs)
        # Effectif 49 et 50 doivent differer (FNAL change)
        assert results[49] != results[50]


class TestFECConcurrent:
    """Thread-safety des operations FEC."""

    def _make_moteur_with_ecritures(self, n=10):
        """Cree un moteur avec n ecritures de test."""
        from datetime import date
        moteur = MoteurEcritures()
        for i in range(n):
            moteur.generer_ecriture_facture(
                type_doc="facture_achat",
                date_piece=date(2026, 1, i % 28 + 1),
                numero_piece=f"FA-{i+1:04d}",
                montant_ht=Decimal(str(100 + i * 10)),
                montant_tva=Decimal(str(20 + i * 2)),
                montant_ttc=Decimal(str(120 + i * 12)),
                nom_tiers=f"Fournisseur {i+1}",
            )
        return moteur

    def test_validations_fec_concurrentes(self):
        """Plusieurs validations FEC en parallele."""
        moteur = self._make_moteur_with_ecritures(5)
        moteur.valider_ecritures()
        contenu = exporter_fec(moteur, siren="123456789")

        resultats = []

        def valider():
            r = valider_fec(contenu)
            resultats.append(r["valide"])

        threads = [threading.Thread(target=valider) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(resultats) == 10
        assert all(resultats), "Toutes les validations doivent reussir"

    def test_exports_fec_concurrents(self):
        """Exports FEC concurrents donnent le meme resultat."""
        moteur = self._make_moteur_with_ecritures(5)
        moteur.valider_ecritures()

        contenus = []
        lock = threading.Lock()

        def exporter():
            c = exporter_fec(moteur, siren="123456789")
            with lock:
                contenus.append(c)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(exporter) for _ in range(5)]
            for f in as_completed(futures):
                f.result()

        assert len(contenus) == 5
        # Tous les exports doivent etre identiques
        assert len(set(contenus)) == 1


class TestMoteurEcrituresConcurrent:
    """Thread-safety du moteur d'ecritures (instances separees)."""

    def test_moteurs_independants_concurrents(self):
        """Chaque thread avec son propre moteur produit des ecritures correctes."""
        from datetime import date
        erreurs = []
        lock = threading.Lock()

        def generer_ecritures(thread_id):
            try:
                moteur = MoteurEcritures()
                for i in range(20):
                    moteur.generer_ecriture_facture(
                        type_doc="facture_achat",
                        date_piece=date(2026, 1, 15),
                        numero_piece=f"T{thread_id}-FA-{i+1:04d}",
                        montant_ht=Decimal("1000"),
                        montant_tva=Decimal("200"),
                        montant_ttc=Decimal("1200"),
                    )
                # Verifier equilibre
                for e in moteur.ecritures:
                    if not e.est_equilibree:
                        with lock:
                            erreurs.append(f"Thread {thread_id}: ecriture desequilibree")
            except Exception as ex:
                with lock:
                    erreurs.append(f"Thread {thread_id}: {ex}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(generer_ecritures, i) for i in range(8)]
            for f in as_completed(futures):
                f.result()

        assert not erreurs, f"Erreurs de concurrence: {erreurs}"
