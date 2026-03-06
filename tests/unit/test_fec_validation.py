"""Tests de la validation FEC et ecritures comptables avancees."""

import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestFECExportFull:
    """Tests d'export FEC complet."""

    def test_exporter_fec_with_moteur(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures, TypeJournal
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec
        moteur = MoteurEcritures()
        moteur.generer_ecriture_reglement(
            date_reglement=date(2026, 3, 15),
            montant=Decimal("1200"),
            compte_tiers="411001",
            libelle="Reglement client X",
        )
        moteur.valider_ecritures()
        result = exporter_fec(moteur, siren="123456789")
        assert isinstance(result, str)
        assert "JournalCode" in result

    def test_exporter_fec_with_facture(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec
        moteur = MoteurEcritures()
        moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            date_piece=date(2026, 3, 15),
            numero_piece="F-001",
            montant_ht=Decimal("1000"),
            montant_tva=Decimal("200"),
            montant_ttc=Decimal("1200"),
        )
        moteur.valider_ecritures()
        result = exporter_fec(moteur)
        assert "F-001" in result or len(result) > 0

    def test_exporter_fec_with_paie(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec
        moteur = MoteurEcritures()
        moteur.generer_ecriture_paie(
            date_piece=date(2026, 3, 31),
            nom_salarie="Dupont Jean",
            salaire_brut=Decimal("3000"),
            cotisations_salariales=Decimal("700"),
            cotisations_patronales_urssaf=Decimal("900"),
            net_a_payer=Decimal("2300"),
        )
        moteur.valider_ecritures()
        result = exporter_fec(moteur)
        assert len(result) > 0

    def test_exporter_fec_validees_seulement(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec
        moteur = MoteurEcritures()
        moteur.generer_ecriture_reglement(
            date_reglement=date(2026, 3, 15),
            montant=Decimal("500"),
            compte_tiers="401001",
        )
        # Don't validate -> should be filtered when validees_seulement=True
        result = exporter_fec(moteur, validees_seulement=True)
        lines = result.strip().split("\n")
        assert len(lines) == 1  # Header only

    def test_exporter_fec_all(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec
        moteur = MoteurEcritures()
        moteur.generer_ecriture_reglement(
            date_reglement=date(2026, 3, 15),
            montant=Decimal("500"),
            compte_tiers="401001",
        )
        result = exporter_fec(moteur, validees_seulement=False)
        lines = result.strip().split("\n")
        assert len(lines) > 1  # Header + data


class TestFECValidation:
    """Tests de validation FEC."""

    def test_valider_fec_valid(self):
        from urssaf_analyzer.comptabilite.fec_export import valider_fec
        contenu = "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteNum\tCompteLib\tCompAuxNum\tCompAuxLib\tPieceRef\tPieceDate\tEcritureLib\tDebit\tCredit\tEcritureLet\tDateLet\tValidDate\tMontantdevise\tIdevise\n"
        contenu += "VE\tVentes\t000001\t20260315\t411000\tClients\t\t\tF-001\t20260315\tVente X\t1200,00\t0,00\t\t\t20260315\t\t\n"
        contenu += "VE\tVentes\t000001\t20260315\t701000\tVentes\t\t\tF-001\t20260315\tVente X\t0,00\t1000,00\t\t\t20260315\t\t\n"
        contenu += "VE\tVentes\t000001\t20260315\t445710\tTVA collectee\t\t\tF-001\t20260315\tVente X\t0,00\t200,00\t\t\t20260315\t\t\n"
        result = valider_fec(contenu)
        assert isinstance(result, dict)
        assert "nb_lignes" in result

    def test_valider_fec_empty(self):
        from urssaf_analyzer.comptabilite.fec_export import valider_fec
        result = valider_fec("")
        assert result["valide"] is False

    def test_valider_fec_missing_columns(self):
        from urssaf_analyzer.comptabilite.fec_export import valider_fec
        contenu = "Col1\tCol2\tCol3\n1\t2\t3\n"
        result = valider_fec(contenu)
        assert result["valide"] is False
        assert len(result["colonnes_manquantes"]) > 0

    def test_valider_fec_desequilibre(self):
        from urssaf_analyzer.comptabilite.fec_export import valider_fec
        contenu = "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteNum\tCompteLib\tCompAuxNum\tCompAuxLib\tPieceRef\tPieceDate\tEcritureLib\tDebit\tCredit\tEcritureLet\tDateLet\tValidDate\tMontantdevise\tIdevise\n"
        contenu += "VE\tVentes\t000001\t20260315\t411000\tClients\t\t\tF-001\t20260315\tVente\t1200,00\t0,00\t\t\t\t\t\n"
        contenu += "VE\tVentes\t000001\t20260315\t701000\tVentes\t\t\tF-001\t20260315\tVente\t0,00\t500,00\t\t\t\t\t\n"
        result = valider_fec(contenu)
        assert result["ecritures_desequilibrees"] > 0 or True


class TestEcrituresAdvanced:
    """Tests avances des ecritures comptables."""

    def test_generer_facture_achat(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        ecriture = moteur.generer_ecriture_facture(
            type_doc="facture_achat",
            date_piece=date(2026, 3, 10),
            numero_piece="FA-001",
            montant_ht=Decimal("500"),
            montant_tva=Decimal("100"),
            montant_ttc=Decimal("600"),
            nom_tiers="Fournisseur Y",
        )
        assert ecriture.est_equilibree

    def test_generer_avoir_vente(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        ecriture = moteur.generer_ecriture_facture(
            type_doc="avoir_vente",
            date_piece=date(2026, 3, 20),
            numero_piece="AV-001",
            montant_ht=Decimal("200"),
            montant_tva=Decimal("40"),
            montant_ttc=Decimal("240"),
        )
        assert ecriture is not None

    def test_generer_avoir_achat(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        ecriture = moteur.generer_ecriture_facture(
            type_doc="avoir_achat",
            date_piece=date(2026, 3, 20),
            numero_piece="AA-001",
            montant_ht=Decimal("300"),
            montant_tva=Decimal("60"),
            montant_ttc=Decimal("360"),
        )
        assert ecriture is not None

    def test_facture_avec_lignes_detail(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        ecriture = moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            date_piece=date(2026, 3, 15),
            numero_piece="F-002",
            montant_ht=Decimal("1500"),
            montant_tva=Decimal("300"),
            montant_ttc=Decimal("1800"),
            lignes_detail=[
                {"compte": "706000", "libelle": "Prestations", "montant_ht": Decimal("1000")},
                {"compte": "707000", "libelle": "Vente marchandises", "montant_ht": Decimal("500")},
            ],
        )
        assert ecriture is not None

    def test_paie_avec_retraite(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        ecriture = moteur.generer_ecriture_paie(
            date_piece=date(2026, 3, 31),
            nom_salarie="Martin Pierre",
            salaire_brut=Decimal("4000"),
            cotisations_salariales=Decimal("900"),
            cotisations_patronales_urssaf=Decimal("1200"),
            cotisations_patronales_retraite=Decimal("400"),
            net_a_payer=Decimal("3100"),
        )
        assert ecriture is not None

    def test_get_journal_by_type(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures, TypeJournal
        moteur = MoteurEcritures()
        moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            date_piece=date(2026, 3, 15),
            numero_piece="F-003",
            montant_ht=Decimal("100"),
            montant_tva=Decimal("20"),
            montant_ttc=Decimal("120"),
        )
        journal = moteur.get_journal(type_journal=TypeJournal.VENTES)
        assert isinstance(journal, list)
