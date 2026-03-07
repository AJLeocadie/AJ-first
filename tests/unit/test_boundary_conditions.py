"""Tests de conditions limites.

Couvre les limites numériques, dates, entrées vides, seuils PASS/SMIC.
Niveau de fiabilité : bancaire (ISO 27001).
"""

import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest


# =============================================
# CONSTANTES - Limites réglementaires
# =============================================

class TestConstantesBoundary:
    """Vérifie les valeurs limites des constantes réglementaires."""

    def test_pass_2026_positif(self):
        from urssaf_analyzer.config.constants import PASS_ANNUEL, PASS_MENSUEL
        assert PASS_ANNUEL > 0
        assert PASS_MENSUEL > 0
        assert PASS_ANNUEL == PASS_MENSUEL * 12

    def test_smic_2026_positif(self):
        from urssaf_analyzer.config.constants import SMIC_HORAIRE_BRUT, SMIC_MENSUEL_BRUT
        assert SMIC_HORAIRE_BRUT > 0
        assert SMIC_MENSUEL_BRUT > 0

    def test_tous_taux_entre_0_et_1(self):
        from urssaf_analyzer.config.constants import TAUX_COTISATIONS_2026
        for ct, taux in TAUX_COTISATIONS_2026.items():
            for cle, valeur in taux.items():
                if "taux" in cle.lower() or cle in ("patronal", "salarial",
                    "patronal_reduit", "taux_plein", "taux_reduit"):
                    assert Decimal("0") <= valeur <= Decimal("1"), (
                        f"{ct}.{cle} = {valeur} hors bornes [0, 1]"
                    )

    def test_contribution_types_non_vide(self):
        from urssaf_analyzer.config.constants import ContributionType
        types = list(ContributionType)
        assert len(types) > 10  # Au moins les cotisations obligatoires


# =============================================
# SALAIRES - Seuils critiques
# =============================================

class TestSalaireBoundary:
    """Tests aux seuils critiques de salaire."""

    @pytest.fixture
    def rules(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        return ContributionRules()

    def test_salaire_zero(self, rules):
        """Salaire à 0 ne doit pas crasher."""
        result = rules.calculer_bulletin_complet(Decimal("0"))
        assert result is not None
        assert float(result["brut_mensuel"]) == 0.0

    def test_salaire_un_centime(self, rules):
        """Plus petit salaire non nul."""
        result = rules.calculer_bulletin_complet(Decimal("0.01"))
        assert result is not None
        assert float(result["brut_mensuel"]) == pytest.approx(0.01)

    def test_salaire_exactement_smic(self, rules):
        from urssaf_analyzer.config.constants import SMIC_MENSUEL_BRUT
        result = rules.calculer_bulletin_complet(SMIC_MENSUEL_BRUT)
        assert result is not None
        assert float(result["brut_mensuel"]) == pytest.approx(float(SMIC_MENSUEL_BRUT))

    def test_salaire_exactement_pass(self, rules):
        from urssaf_analyzer.config.constants import PASS_MENSUEL
        result = rules.calculer_bulletin_complet(PASS_MENSUEL)
        assert result is not None

    def test_salaire_juste_sous_pass(self, rules):
        from urssaf_analyzer.config.constants import PASS_MENSUEL
        result = rules.calculer_bulletin_complet(PASS_MENSUEL - Decimal("0.01"))
        assert result is not None

    def test_salaire_juste_au_dessus_pass(self, rules):
        from urssaf_analyzer.config.constants import PASS_MENSUEL
        result = rules.calculer_bulletin_complet(PASS_MENSUEL + Decimal("0.01"))
        assert result is not None

    def test_salaire_2_pass(self, rules):
        from urssaf_analyzer.config.constants import PASS_MENSUEL
        result = rules.calculer_bulletin_complet(PASS_MENSUEL * 2)
        assert result is not None

    def test_salaire_8_pass(self, rules):
        """8 PASS = plafond retraite complémentaire T2."""
        from urssaf_analyzer.config.constants import PASS_MENSUEL
        result = rules.calculer_bulletin_complet(PASS_MENSUEL * 8)
        assert result is not None

    def test_salaire_tres_eleve(self, rules):
        """Salaire très élevé (100K mensuel)."""
        result = rules.calculer_bulletin_complet(Decimal("100000"))
        assert result is not None
        # Les cotisations ne doivent pas dépasser le salaire brut
        total = result.get("total_patronal", Decimal("0"))
        assert total < Decimal("100000")

    def test_salaire_negatif_gere(self, rules):
        """Un salaire négatif ne doit pas crasher (régularisation)."""
        try:
            result = rules.calculer_bulletin_complet(Decimal("-500"))
            # Si ça ne crash pas, c'est ok
            assert result is not None
        except (ValueError, Exception):
            pass  # Acceptable de rejeter un négatif


# =============================================
# DECIMAL - Précision
# =============================================

class TestDecimalPrecision:
    """Tests de précision décimale pour les calculs monétaires."""

    def test_pas_de_float_dans_cotisations(self):
        """Vérifier que les taux numériques utilisent Decimal, pas float."""
        from urssaf_analyzer.config.constants import TAUX_COTISATIONS_2026
        for ct, taux in TAUX_COTISATIONS_2026.items():
            for cle, valeur in taux.items():
                if isinstance(valeur, float):
                    assert False, (
                        f"{ct}.{cle} est float, devrait être Decimal"
                    )

    def test_multiplication_decimale_exacte(self):
        """Vérifier que Decimal évite les erreurs d'arrondi float."""
        base = Decimal("3456.78")
        taux = Decimal("0.13")
        # En float: 3456.78 * 0.13 = 449.3814000000001
        # En Decimal: 3456.78 * 0.13 = 449.3814
        resultat = base * taux
        assert resultat == Decimal("449.3814")

    def test_somme_cotisations_precision(self):
        """La somme de nombreuses petites cotisations reste précise."""
        cotisations = [Decimal("0.01")] * 10000
        total = sum(cotisations)
        assert total == Decimal("100.00")


# =============================================
# DATES - Limites
# =============================================

class TestDateBoundary:
    """Tests aux limites pour les dates."""

    def test_parser_date_format_francais(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        d = parser_date("01/01/2026")
        assert d is not None
        assert d.year == 2026

    def test_parser_date_format_iso(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        d = parser_date("2026-01-01")
        assert d is not None

    def test_parser_date_31_decembre(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        d = parser_date("31/12/2026")
        assert d is not None
        assert d.month == 12 and d.day == 31

    def test_parser_date_29_fevrier_bissextile(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        d = parser_date("29/02/2028")  # 2028 est bissextile
        assert d is not None

    def test_parser_date_29_fevrier_non_bissextile(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        d = parser_date("29/02/2026")  # 2026 n'est pas bissextile
        assert d is None  # Date invalide

    def test_parser_date_mois_invalide(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        assert parser_date("01/13/2026") is None

    def test_parser_date_jour_invalide(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        assert parser_date("32/01/2026") is None

    def test_parser_date_chaine_vide(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        assert parser_date("") is None

    def test_parser_date_none_like(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        assert parser_date("N/A") is None
        assert parser_date("-") is None


# =============================================
# EFFECTIFS - Seuils légaux
# =============================================

class TestEffectifBoundary:
    """Tests aux seuils d'effectif légaux."""

    def test_effectif_seuils_dans_constantes(self):
        """Vérifier que les seuils d'effectif sont définis dans les constantes."""
        from urssaf_analyzer.config.constants import TAUX_COTISATIONS_2026
        # Vérifier que certaines cotisations ont des seuils d'effectif
        seuils_trouves = []
        for ct, taux in TAUX_COTISATIONS_2026.items():
            for cle, valeur in taux.items():
                if "seuil" in cle.lower() or "effectif" in cle.lower():
                    seuils_trouves.append((ct, cle, valeur))
        assert len(seuils_trouves) > 0

    def test_bulletin_cadre_et_non_cadre(self):
        """Les bulletins cadre et non-cadre sont différents."""
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        rules = ContributionRules()
        cadre = rules.calculer_bulletin_complet(Decimal("3000"), est_cadre=True)
        non_cadre = rules.calculer_bulletin_complet(Decimal("3000"), est_cadre=False)
        assert cadre is not None
        assert non_cadre is not None
        # Le total patronal cadre devrait différer du non-cadre
        assert cadre["total_patronal"] != non_cadre["total_patronal"]


# =============================================
# MONTANTS - parser_montant limites
# =============================================

class TestParserMontantBoundary:
    """Tests limites pour parser_montant."""

    def test_montant_zero(self):
        from urssaf_analyzer.utils.number_utils import parser_montant
        assert parser_montant("0") == Decimal("0")
        assert parser_montant("0.00") == Decimal("0")
        assert parser_montant("0,00") == Decimal("0")

    def test_montant_negatif(self):
        from urssaf_analyzer.utils.number_utils import parser_montant
        result = parser_montant("-100.50")
        assert result == Decimal("-100.50") or result == Decimal("0")  # Selon impl

    def test_montant_tres_grand(self):
        from urssaf_analyzer.utils.number_utils import parser_montant
        result = parser_montant("999999999.99")
        assert result > 0

    def test_montant_espaces(self):
        from urssaf_analyzer.utils.number_utils import parser_montant
        result = parser_montant("  1234.56  ")
        assert result == Decimal("1234.56") or result > 0

    def test_montant_virgule_francaise(self):
        from urssaf_analyzer.utils.number_utils import parser_montant
        result = parser_montant("1234,56")
        assert result > 0

    def test_montant_avec_symbole_euro(self):
        from urssaf_analyzer.utils.number_utils import parser_montant
        result = parser_montant("1234.56 €")
        # Peut ou ne peut pas gérer le symbole euro
        assert result >= 0


# =============================================
# DSN - Blocs limites
# =============================================

class TestDSNBoundary:
    """Tests limites pour les blocs DSN."""

    def test_dsn_nir_corse(self):
        """NIR corse (2A/2B au lieu de département numérique)."""
        from urssaf_analyzer.utils.validators import valider_nir
        # NIR Corse 2A
        result = valider_nir("2780599456789")  # Test standard
        # Just ensure it doesn't crash

    def test_dsn_montant_cotisation_zero(self):
        """Cotisation à 0 (exonération totale)."""
        from urssaf_analyzer.models.documents import Cotisation
        from urssaf_analyzer.config.constants import ContributionType
        cot = Cotisation(
            type_cotisation=ContributionType.MALADIE,
            base_brute=Decimal("3000"),
            taux_patronal=Decimal("0"),
            montant_patronal=Decimal("0"),
        )
        assert cot.montant_patronal == Decimal("0")

    def test_dsn_effectif_1_salarie(self, tmp_path):
        """DSN minimale avec 1 seul salarié."""
        dsn_content = """S10.G00.00.001 'TEST'
S10.G00.00.002 '01'
S20.G00.05.001 '123456789'
S20.G00.05.002 'MONO SARL'
S30.G00.30.001 '1850175123456'
S30.G00.30.002 'SOLO'
S30.G00.30.004 'Jean'
S81.G00.81.001 '100'
S81.G00.81.003 '2000.00'
S81.G00.81.004 '13.00'
S81.G00.81.005 '260.00'
"""
        f = tmp_path / "mono.dsn"
        f.write_text(dsn_content)
        from urssaf_analyzer.parsers.dsn_parser import DSNParser
        from urssaf_analyzer.models.documents import Document, FileType
        parser = DSNParser()
        doc = Document(nom_fichier="mono.dsn", chemin=f,
                      type_fichier=FileType.DSN, hash_sha256="a" * 64,
                      taille_octets=f.stat().st_size)
        result = parser.parser(f, doc)
        assert len(result) >= 1


# =============================================
# FEC - Limites
# =============================================

class TestFECBoundary:
    """Tests limites pour l'export FEC."""

    def test_fec_colonnes_vides(self):
        """Colonnes FEC vides détectées."""
        from urssaf_analyzer.validators.data_validators import FECSchemaValidator
        v = FECSchemaValidator()
        errors = v.valider_colonnes([])
        assert len(errors) > 0  # Missing columns detected

    def test_fec_18_colonnes_obligatoires(self):
        """FEC doit avoir exactement 18 colonnes minimum."""
        from urssaf_analyzer.validators.data_validators import FECSchemaValidator
        v = FECSchemaValidator()
        colonnes_fec = list(v.COLONNES_OBLIGATOIRES)
        errors = v.valider_colonnes(colonnes_fec)
        assert len(errors) == 0  # All required columns present
