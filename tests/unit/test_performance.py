"""Tests de performance et de charge NormaCheck.

Verifie que les operations critiques s'executent dans des temps raisonnables :
- Parsing CSV large (10000 lignes) < 5 secondes
- Analyse de 1000 cotisations < 10 secondes
- Generation de 100 bulletins complets < 5 secondes
- RGDU pour 10000 salaires < 2 secondes
- FEC export de 1000 ecritures < 3 secondes
- Memoire sous 500MB pour gros volumes
"""

import sys
import time
import tracemalloc
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.config.constants import (
    ContributionType, PASS_MENSUEL, SMIC_MENSUEL_BRUT, SMIC_ANNUEL_BRUT,
)
from urssaf_analyzer.rules.contribution_rules import ContributionRules


@pytest.fixture
def rules():
    return ContributionRules(
        effectif_entreprise=50,
        taux_at=Decimal("0.0208"),
        taux_versement_mobilite=Decimal("0.025"),
    )


# =============================================
# Performance : Parsing CSV large
# =============================================

class TestParsingPerformance:
    """Tests de performance du parsing."""

    def test_large_csv_generation_and_parsing(self, tmp_path):
        """Generer et parser un CSV de 10000 lignes en moins de 5 secondes."""
        # Generer le fichier CSV
        csv_path = tmp_path / "large_paie.csv"
        header = "nir,nom,prenom,statut,base_brute,type_cotisation,taux_patronal,montant_patronal,taux_salarial,montant_salarial,periode_debut,periode_fin\n"

        lines = [header]
        for i in range(10000):
            nir = f"1{850175123456 + i:012d}"[:13]
            brut = 2000 + (i % 3000)
            lines.append(
                f"{nir},NOM{i},PRENOM{i},non-cadre,{brut:.2f},maladie,7.00,"
                f"{brut * 0.07:.2f},0.00,0.00,01/01/2026,31/01/2026\n"
            )
        csv_path.write_text("".join(lines), encoding="utf-8")

        # Mesurer le temps de lecture et parsing basique
        start = time.time()
        content = csv_path.read_text(encoding="utf-8")
        parsed_lines = content.strip().split("\n")
        # Simuler le parsing des donnees
        for line in parsed_lines[1:]:
            fields = line.split(",")
            _ = float(fields[4])  # base_brute
        elapsed = time.time() - start

        assert elapsed < 5.0, f"Parsing CSV 10000 lignes trop lent : {elapsed:.2f}s"
        assert len(parsed_lines) == 10001  # header + 10000 lignes


# =============================================
# Performance : Analyse de cotisations
# =============================================

class TestAnalysisPerformance:
    """Tests de performance de l'analyse des cotisations."""

    def test_analyze_1000_cotisations(self, rules):
        """Analyser 1000 cotisations (verifier taux + montants) en < 10 secondes."""
        cotisations_types = [
            ContributionType.MALADIE,
            ContributionType.VIEILLESSE_PLAFONNEE,
            ContributionType.VIEILLESSE_DEPLAFONNEE,
            ContributionType.ALLOCATIONS_FAMILIALES,
            ContributionType.ACCIDENT_TRAVAIL,
        ]

        start = time.time()

        for i in range(1000):
            brut = Decimal(str(2000 + (i % 5000)))
            ct = cotisations_types[i % len(cotisations_types)]

            # Verifier le taux
            taux = rules.get_taux_attendu_patronal(ct, brut)
            _ = rules.verifier_taux(ct, taux or Decimal("0"), salaire_brut=brut)

            # Calculer l'assiette
            _ = rules.calculer_assiette(ct, brut)

            # Calculer les montants
            _ = rules.calculer_montant_patronal(ct, brut)
            _ = rules.calculer_montant_salarial(ct, brut)

        elapsed = time.time() - start
        assert elapsed < 10.0, f"Analyse 1000 cotisations trop lente : {elapsed:.2f}s"


# =============================================
# Performance : Generation de bulletins
# =============================================

class TestBulletinPerformance:
    """Tests de performance de la generation de bulletins."""

    def test_generate_100_bulletins(self, rules):
        """Generer 100 bulletins complets en < 5 secondes."""
        start = time.time()

        for i in range(100):
            brut = Decimal(str(2000 + i * 50))
            est_cadre = i % 2 == 0
            bulletin = rules.calculer_bulletin_complet(brut, est_cadre=est_cadre)
            assert isinstance(bulletin, dict)
            assert len(bulletin["lignes"]) > 0

        elapsed = time.time() - start
        assert elapsed < 5.0, f"Generation 100 bulletins trop lente : {elapsed:.2f}s"

    def test_generate_100_bulletins_temps_partiel(self, rules):
        """Generer 100 bulletins temps partiel en < 5 secondes."""
        start = time.time()

        for i in range(100):
            brut = Decimal(str(1500 + i * 20))
            heures = Decimal(str(80 + (i % 72)))  # 80h a 151h
            bulletin = rules.calculer_bulletin_temps_partiel(brut, heures_mensuelles=heures)
            assert isinstance(bulletin, dict)

        elapsed = time.time() - start
        assert elapsed < 5.0, f"Generation 100 bulletins TP trop lente : {elapsed:.2f}s"


# =============================================
# Performance : RGDU
# =============================================

class TestRGDUPerformance:
    """Tests de performance du calcul RGDU."""

    def test_rgdu_10000_salaries(self, rules):
        """Calculer la RGDU pour 10000 salaires en < 2 secondes."""
        start = time.time()

        for i in range(10000):
            salaire_annuel = Decimal(str(18000 + i * 5))
            _ = rules.calculer_rgdu(salaire_annuel)

        elapsed = time.time() - start
        assert elapsed < 2.0, f"RGDU 10000 salaires trop lent : {elapsed:.2f}s"

    def test_rgdu_detail_1000(self, rules):
        """Calculer le detail RGDU pour 1000 salaires en < 5 secondes."""
        start = time.time()

        for i in range(1000):
            salaire = Decimal(str(20000 + i * 30))
            detail = rules.detail_rgdu(salaire)
            assert isinstance(detail, dict)

        elapsed = time.time() - start
        assert elapsed < 5.0, f"Detail RGDU 1000 trop lent : {elapsed:.2f}s"


# =============================================
# Performance : FEC Export
# =============================================

class TestFECExportPerformance:
    """Tests de performance de l'export FEC."""

    def test_fec_export_1000_ecritures(self):
        """Exporter 1000 ecritures FEC en < 3 secondes."""
        from urssaf_analyzer.comptabilite.ecritures import (
            MoteurEcritures, Ecriture, LigneEcriture, TypeJournal,
        )
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec

        moteur = MoteurEcritures()

        # Generer 1000 ecritures equilibrees
        for i in range(1000):
            montant = Decimal(str(100 + i))
            ecriture = Ecriture(
                journal=TypeJournal.ACHATS,
                date_ecriture=date(2026, 1, 1 + (i % 28)),
                date_piece=date(2026, 1, 1 + (i % 28)),
                numero_piece=f"FA-{i+1:05d}",
                libelle=f"Facture test perf {i+1}",
                lignes=[
                    LigneEcriture(
                        compte="401000",
                        libelle=f"Fournisseur {i}",
                        credit=montant,
                    ),
                    LigneEcriture(
                        compte="607000",
                        libelle=f"Achat {i}",
                        debit=montant,
                    ),
                ],
                validee=True,
            )
            moteur.ecritures.append(ecriture)

        start = time.time()
        fec_content = exporter_fec(moteur, siren="123456789")
        elapsed = time.time() - start

        assert elapsed < 3.0, f"Export FEC 1000 ecritures trop lent : {elapsed:.2f}s"

        # Verifier le contenu genere
        lines = fec_content.strip().split("\n")
        # Header + 1000 ecritures x 2 lignes = 2001
        assert len(lines) == 2001


# =============================================
# Performance : Memoire
# =============================================

class TestMemoryUsage:
    """Tests d'utilisation memoire."""

    def test_memory_large_bulletin_batch(self, rules):
        """La memoire doit rester sous 500MB pour un batch de bulletins."""
        tracemalloc.start()

        bulletins = []
        for i in range(500):
            brut = Decimal(str(2000 + i * 10))
            bulletin = rules.calculer_bulletin_complet(brut, est_cadre=(i % 2 == 0))
            bulletins.append(bulletin)

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # peak en octets, convertir en MB
        peak_mb = peak / (1024 * 1024)
        assert peak_mb < 500, f"Pic memoire trop eleve : {peak_mb:.1f} MB"

    def test_memory_large_rgdu_batch(self, rules):
        """La memoire doit rester sous 500MB pour 10000 calculs RGDU."""
        tracemalloc.start()

        results = []
        for i in range(10000):
            salaire = Decimal(str(18000 + i * 5))
            results.append(rules.calculer_rgdu(salaire))

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / (1024 * 1024)
        assert peak_mb < 500, f"Pic memoire RGDU trop eleve : {peak_mb:.1f} MB"

    def test_memory_fec_generation(self):
        """La memoire doit rester sous 500MB pour generer un gros FEC."""
        from urssaf_analyzer.comptabilite.ecritures import (
            MoteurEcritures, Ecriture, LigneEcriture, TypeJournal,
        )
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec

        tracemalloc.start()

        moteur = MoteurEcritures()
        for i in range(1000):
            montant = Decimal(str(100 + i))
            ecriture = Ecriture(
                journal=TypeJournal.ACHATS,
                date_ecriture=date(2026, 1, 1 + (i % 28)),
                date_piece=date(2026, 1, 1 + (i % 28)),
                numero_piece=f"FA-{i+1:05d}",
                libelle=f"Facture memoire {i+1}",
                lignes=[
                    LigneEcriture(compte="401000", libelle=f"Fourn {i}", credit=montant),
                    LigneEcriture(compte="607000", libelle=f"Achat {i}", debit=montant),
                ],
                validee=True,
            )
            moteur.ecritures.append(ecriture)

        _ = exporter_fec(moteur)

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / (1024 * 1024)
        assert peak_mb < 500, f"Pic memoire FEC trop eleve : {peak_mb:.1f} MB"
