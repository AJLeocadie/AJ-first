"""Tests de l'export FEC."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.comptabilite.fec_export import (
    _fmt_date,
    _fmt_montant,
    nom_fichier_fec,
    COLONNES_FEC,
    JOURNAL_LIBELLES,
)


class TestFmtDate:
    """Tests du formatage de date FEC."""

    def test_date_normale(self):
        assert _fmt_date(date(2026, 3, 15)) == "20260315"

    def test_date_none(self):
        assert _fmt_date(None) == ""

    def test_date_premier_janvier(self):
        assert _fmt_date(date(2026, 1, 1)) == "20260101"

    def test_date_fin_annee(self):
        assert _fmt_date(date(2026, 12, 31)) == "20261231"


class TestFmtMontant:
    """Tests du formatage de montant FEC."""

    def test_montant_decimal(self):
        assert _fmt_montant(Decimal("1234.56")) == "1234,56"

    def test_montant_float(self):
        result = _fmt_montant(1234.56)
        assert "1234,56" in result

    def test_montant_int(self):
        assert _fmt_montant(1000) == "1000,00"

    def test_montant_zero(self):
        assert _fmt_montant(Decimal("0")) == "0,00"

    def test_montant_negatif(self):
        result = _fmt_montant(Decimal("-100.50"))
        assert "-100,50" == result


class TestNomFichierFEC:
    """Tests de la generation du nom de fichier FEC."""

    def test_nom_standard(self):
        result = nom_fichier_fec("123456789", date(2026, 12, 31))
        assert result == "123456789FEC20261231.txt"

    def test_siren_vide(self):
        result = nom_fichier_fec("", date(2026, 12, 31))
        assert result == "000000000FEC20261231.txt"

    def test_siren_avec_espaces(self):
        result = nom_fichier_fec("123 456 789", date(2026, 12, 31))
        assert result.startswith("123456789")

    def test_siren_trop_long(self):
        result = nom_fichier_fec("12345678901234", date(2026, 12, 31))
        assert result.startswith("123456789FEC")

    def test_date_par_defaut(self):
        result = nom_fichier_fec("123456789")
        assert "FEC" in result
        assert result.endswith(".txt")


class TestColonnesFEC:
    """Tests des constantes FEC."""

    def test_18_colonnes(self):
        assert len(COLONNES_FEC) == 18

    def test_colonnes_obligatoires(self):
        assert "JournalCode" in COLONNES_FEC
        assert "EcritureDate" in COLONNES_FEC
        assert "CompteNum" in COLONNES_FEC
        assert "Debit" in COLONNES_FEC
        assert "Credit" in COLONNES_FEC

    def test_journal_libelles(self):
        assert len(JOURNAL_LIBELLES) > 0
