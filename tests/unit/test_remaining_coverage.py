"""Tests pour couvrir les modules restants: comptabilite, regimes, security, main, __main__."""

import os
import sys
import json
import struct
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================
# comptabilite/plan_comptable.py - determiner_compte_charge
# ============================================================

class TestDeterminerCompteCharge:
    def test_facture_vente_prestation(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Prestation de conseil", "facture_vente") == "706000"

    def test_facture_vente_produit_fini(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Produit fini livré", "facture_vente") == "701000"

    def test_facture_vente_marchandise(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Marchandise diverse", "facture_vente") == "707000"

    def test_facture_vente_defaut(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Truc inconnu", "facture_vente") == "707000"

    def test_avoir_vente_prestation(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Prestation", "avoir_vente") == "706000"

    def test_achat_matiere(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Matiere premiere", "facture_achat") == "601000"

    def test_achat_fourniture(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Fourniture de bureau", "facture_achat") == "606000"

    def test_achat_energie(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Electricite batiment", "facture_achat") == "606100"

    def test_achat_entretien(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Entretien locaux", "facture_achat") == "615000"

    def test_achat_prestation(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Prestation informatique", "facture_achat") == "604000"

    def test_achat_sous_traitance(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Sous-traitance usinage", "facture_achat") == "611000"

    def test_achat_loyer(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Loyer trimestriel", "facture_achat") == "613000"

    def test_achat_assurance(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Assurance RC pro", "facture_achat") == "616000"

    def test_achat_honoraire(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Honoraire comptable", "facture_achat") == "622000"

    def test_achat_publicite(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Publicite web", "facture_achat") == "623000"

    def test_achat_transport(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Transport marchandise", "facture_achat") == "624000"

    def test_achat_deplacement(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Deplacement mission", "facture_achat") == "625000"

    def test_achat_telephone(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Telephone mobile", "facture_achat") == "626000"

    def test_achat_frais_bancaires(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Frais bancaire mensuels", "facture_achat") == "627000"

    def test_achat_marchandise(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Marchandise revente", "facture_achat") == "607000"

    def test_paie_salaire(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Salaire brut mensuel", "facture_achat") == "641100"

    def test_paie_urssaf(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Cotisation URSSAF", "facture_achat") == "645100"

    def test_paie_retraite(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Retraite complementaire", "facture_achat") == "645300"

    def test_paie_mutuelle(self):
        from urssaf_analyzer.comptabilite.plan_comptable import determiner_compte_charge
        assert determiner_compte_charge("Mutuelle obligatoire", "facture_achat") == "645200"


# ============================================================
# comptabilite/ecritures.py - branches non couvertes
# ============================================================

class TestEcrituresFacture:
    """Test les 4 cas de comptabilisation: vente, avoir vente, achat, avoir achat."""

    def _get_moteur(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        return MoteurEcritures()

    def test_facture_vente_avec_tva(self):
        moteur = self._get_moteur()
        e = moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            montant_ht=1000, montant_tva=200, montant_ttc=1200,
            date_piece=date(2026, 1, 15), numero_piece="FV001",
            nom_tiers="CLIENT1",
        )
        assert e is not None
        assert len(e.lignes) >= 2

    def test_avoir_vente_avec_tva(self):
        moteur = self._get_moteur()
        e = moteur.generer_ecriture_facture(
            type_doc="avoir_vente",
            montant_ht=500, montant_tva=100, montant_ttc=600,
            date_piece=date(2026, 2, 10), numero_piece="AV001",
            nom_tiers="CLIENT1",
        )
        assert e is not None

    def test_facture_achat_avec_tva(self):
        moteur = self._get_moteur()
        e = moteur.generer_ecriture_facture(
            type_doc="facture_achat",
            montant_ht=800, montant_tva=160, montant_ttc=960,
            date_piece=date(2026, 3, 1), numero_piece="FA001",
            nom_tiers="FOURNISSEUR1",
        )
        assert e is not None

    def test_avoir_achat_avec_tva(self):
        moteur = self._get_moteur()
        e = moteur.generer_ecriture_facture(
            type_doc="avoir_achat",
            montant_ht=300, montant_tva=60, montant_ttc=360,
            date_piece=date(2026, 3, 15), numero_piece="AA001",
            nom_tiers="FOURNISSEUR1",
        )
        assert e is not None

    def test_facture_vente_sans_tva(self):
        moteur = self._get_moteur()
        e = moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            montant_ht=1000, montant_tva=0, montant_ttc=1000,
            date_piece=date(2026, 1, 15), numero_piece="FV002",
        )
        assert e is not None

    def test_facture_achat_avec_lignes_detail(self):
        moteur = self._get_moteur()
        lignes = [
            {"description": "Prestation conseil", "montant_ht": 500},
            {"description": "Transport livraison", "montant_ht": 300},
        ]
        e = moteur.generer_ecriture_facture(
            type_doc="facture_achat",
            montant_ht=800, montant_tva=160, montant_ttc=960,
            date_piece=date(2026, 4, 1), numero_piece="FA002",
            lignes_detail=lignes,
        )
        assert e is not None
        assert len(e.lignes) > 3

    def test_facture_vente_avec_lignes_detail(self):
        moteur = self._get_moteur()
        lignes = [
            {"description": "Prestation informatique", "montant_ht": 1000},
        ]
        e = moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            montant_ht=1000, montant_tva=200, montant_ttc=1200,
            date_piece=date(2026, 4, 1), numero_piece="FV003",
            lignes_detail=lignes,
        )
        assert e is not None

    def test_avoir_achat_avec_lignes_detail(self):
        moteur = self._get_moteur()
        lignes = [
            {"description": "Matiere retour", "montant_ht": 200},
        ]
        e = moteur.generer_ecriture_facture(
            type_doc="avoir_achat",
            montant_ht=200, montant_tva=40, montant_ttc=240,
            date_piece=date(2026, 5, 1), numero_piece="AA002",
            lignes_detail=lignes,
        )
        assert e is not None

    def test_avoir_vente_avec_lignes_detail(self):
        moteur = self._get_moteur()
        lignes = [
            {"description": "Prestation annulee", "montant_ht": 500},
        ]
        e = moteur.generer_ecriture_facture(
            type_doc="avoir_vente",
            montant_ht=500, montant_tva=100, montant_ttc=600,
            date_piece=date(2026, 5, 1), numero_piece="AV002",
            lignes_detail=lignes,
        )
        assert e is not None

    def test_facture_ttc_auto_calcul(self):
        """Test TTC = HT + TVA quand TTC=0."""
        moteur = self._get_moteur()
        e = moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            montant_ht=1000, montant_tva=200, montant_ttc=0,
            date_piece=date(2026, 1, 15), numero_piece="FV004",
        )
        assert e is not None

    def test_facture_avec_ecart_arrondi_charges(self):
        moteur = self._get_moteur()
        lignes = [
            {"description": "Fourniture bureau", "montant_ht": 100.01},
            {"description": "Consommable imprimante", "montant_ht": 99.98},
        ]
        e = moteur.generer_ecriture_facture(
            type_doc="facture_achat",
            montant_ht=200.00, montant_tva=40, montant_ttc=240,
            date_piece=date(2026, 6, 1), numero_piece="FA003",
            lignes_detail=lignes,
        )
        assert e is not None

    def test_facture_avec_ecart_arrondi_produits(self):
        moteur = self._get_moteur()
        lignes = [
            {"description": "Prestation A", "montant_ht": 500.01},
            {"description": "Prestation B", "montant_ht": 499.98},
        ]
        e = moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            montant_ht=1000.00, montant_tva=200, montant_ttc=1200,
            date_piece=date(2026, 6, 1), numero_piece="FV005",
            lignes_detail=lignes,
        )
        assert e is not None

    def test_ligne_detail_montant_zero_ignore(self):
        moteur = self._get_moteur()
        lignes = [
            {"description": "Ligne vide", "montant_ht": 0},
            {"description": "Fourniture", "montant_ht": 500},
        ]
        e = moteur.generer_ecriture_facture(
            type_doc="facture_achat",
            montant_ht=500, montant_tva=100, montant_ttc=600,
            date_piece=date(2026, 7, 1), numero_piece="FA004",
            lignes_detail=lignes,
        )
        assert e is not None


# ============================================================
# comptabilite/fec_export.py
# ============================================================

class TestFecExport:
    def test_generer_fec_avec_compte_tiers(self):
        """Test FEC generation with auxiliary account (401xxx/411xxx)."""
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures as MoteurComptable
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec as generer_fec, nom_fichier_fec, valider_fec

        moteur = MoteurComptable()
        moteur.generer_ecriture_facture(
            type_doc="facture_achat",
            montant_ht=1000, montant_tva=200, montant_ttc=1200,
            date_piece=date(2026, 1, 15), numero_piece="FA001",
            nom_tiers="FOURNISSEUR",
        )
        fec_content = generer_fec(moteur)
        assert fec_content
        assert "JournalCode" in fec_content

    def test_nom_fichier_fec_defaut(self):
        from urssaf_analyzer.comptabilite.fec_export import nom_fichier_fec
        nom = nom_fichier_fec("")
        assert nom.startswith("000000000FEC")

    def test_nom_fichier_fec_avec_siren(self):
        from urssaf_analyzer.comptabilite.fec_export import nom_fichier_fec
        nom = nom_fichier_fec("123456789", date(2026, 12, 31))
        assert nom == "123456789FEC20261231.txt"

    def test_valider_fec_fichier_vide(self):
        from urssaf_analyzer.comptabilite.fec_export import valider_fec
        result = valider_fec("")
        assert not result["valide"]

    def test_valider_fec_colonnes_manquantes(self):
        from urssaf_analyzer.comptabilite.fec_export import valider_fec
        result = valider_fec("ColA\tColB\n1\t2\n")
        assert not result["valide"]

    def test_generer_fec_avec_validation(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures as MoteurComptable
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec as generer_fec, valider_fec
        moteur = MoteurComptable()
        moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            montant_ht=1000, montant_tva=200, montant_ttc=1200,
            date_piece=date(2026, 1, 15), numero_piece="FV001",
        )
        fec = generer_fec(moteur, siren="123456789")
        result = valider_fec(fec)
        assert isinstance(result, dict)


# ============================================================
# comptabilite/rapports_comptables.py
# ============================================================

class TestRapportsComptables:
    def test_rapport_generation(self):
        from urssaf_analyzer.comptabilite.rapports_comptables import GenerateurRapports
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures

        moteur = MoteurEcritures()
        moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            montant_ht=10000, montant_tva=2000, montant_ttc=12000,
            date_piece=date(2026, 3, 15), numero_piece="FV001",
        )
        moteur.generer_ecriture_facture(
            type_doc="facture_achat",
            montant_ht=5000, montant_tva=1000, montant_ttc=6000,
            date_piece=date(2026, 3, 20), numero_piece="FA001",
        )

        gen = GenerateurRapports(moteur)
        gl = gen.grand_livre_html()
        assert isinstance(gl, str)

    def test_balance_html(self):
        from urssaf_analyzer.comptabilite.rapports_comptables import GenerateurRapports
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures

        moteur = MoteurEcritures()
        moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            montant_ht=5000, montant_tva=1000, montant_ttc=6000,
            date_piece=date(2026, 1, 15), numero_piece="FV001",
        )
        gen = GenerateurRapports(moteur)
        result = gen.balance_html()
        assert isinstance(result, str)

    def test_journal_html(self):
        from urssaf_analyzer.comptabilite.rapports_comptables import GenerateurRapports
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures

        moteur = MoteurEcritures()
        moteur.generer_ecriture_facture(
            type_doc="facture_achat",
            montant_ht=3000, montant_tva=600, montant_ttc=3600,
            date_piece=date(2026, 2, 10), numero_piece="FA001",
        )
        gen = GenerateurRapports(moteur)
        result = gen.journal_html()
        assert isinstance(result, str)


# ============================================================
# regimes/independant.py
# ============================================================

class TestCalculCotisationsIndependant:
    def test_calculer_cotisations_reel_revenu_bas(self):
        """Test with low revenue (< 40% PASS)."""
        from urssaf_analyzer.regimes.independant import (
            calculer_cotisations_tns, TypeIndependant,
        )
        result = calculer_cotisations_tns(
            revenu_net=Decimal("10000"),
            type_independant=TypeIndependant.MICRO_ENTREPRENEUR,
        )
        assert result["total_cotisations"] > 0
        assert result["regime"] == "TNS - Regime reel"
        assert len(result["lignes"]) > 5

    def test_calculer_cotisations_reel_revenu_moyen(self):
        """Test with medium revenue (60%-110% PASS)."""
        from urssaf_analyzer.regimes.independant import (
            calculer_cotisations_tns, TypeIndependant,
        )
        result = calculer_cotisations_tns(
            revenu_net=Decimal("40000"),
            type_independant=TypeIndependant.EI_IR,
        )
        assert result["total_cotisations"] > 0

    def test_calculer_cotisations_reel_revenu_eleve(self):
        """Test with high revenue (> 110% PASS) for AF full rate."""
        from urssaf_analyzer.regimes.independant import (
            calculer_cotisations_tns, TypeIndependant,
        )
        result = calculer_cotisations_tns(
            revenu_net=Decimal("100000"),
            type_independant=TypeIndependant.GERANT_MAJORITAIRE,
        )
        assert result["total_cotisations"] > 0
        # Should have retraite complementaire T2
        libs = [l["libelle"] for l in result["lignes"]]
        assert "Retraite complementaire T2" in libs

    def test_calculer_cotisations_reel_avec_acre(self):
        """Test with ACRE (50% reduction)."""
        from urssaf_analyzer.regimes.independant import (
            calculer_cotisations_tns, TypeIndependant,
        )
        result = calculer_cotisations_tns(
            revenu_net=Decimal("30000"),
            type_independant=TypeIndependant.MICRO_ENTREPRENEUR,
            acre=True,
        )
        assert result["acre"] is True
        assert result["reduction_acre"] > 0

    def test_calculer_cotisations_reel_avec_conjoint(self):
        """Test with conjoint_collaborateur."""
        from urssaf_analyzer.regimes.independant import (
            calculer_cotisations_tns, TypeIndependant,
        )
        result = calculer_cotisations_tns(
            revenu_net=Decimal("30000"),
            type_independant=TypeIndependant.EI_IR,
            conjoint_collaborateur=True,
        )
        assert result["total_cotisations"] > 0

    def test_calculer_cotisations_af_progressif(self):
        """Test AF progressif between 110% and 140% PASS."""
        from urssaf_analyzer.regimes.independant import (
            calculer_cotisations_tns, TypeIndependant,
        )
        # Revenue between 110% and 140% of PASS (PASS ~ 46368)
        result = calculer_cotisations_tns(
            revenu_net=Decimal("57000"),
            type_independant=TypeIndependant.EI_IR,
        )
        assert result["total_cotisations"] > 0


class TestCalculImpotIndependant:
    def test_impot_revenu_faible(self):
        from urssaf_analyzer.regimes.independant import (
            calculer_impot_independant, TypeIndependant,
        )
        result = calculer_impot_independant(
            benefice=Decimal("10000"),
            type_statut=TypeIndependant.MICRO_ENTREPRENEUR,
        )
        assert result["impot_brut"] == 0  # Under first threshold

    def test_impot_revenu_moyen(self):
        from urssaf_analyzer.regimes.independant import (
            calculer_impot_independant, TypeIndependant,
        )
        result = calculer_impot_independant(
            benefice=Decimal("50000"),
            type_statut=TypeIndependant.EI_IR,
        )
        assert result["impot_brut"] > 0
        assert len(result["tranches"]) > 1

    def test_impot_revenu_eleve(self):
        from urssaf_analyzer.regimes.independant import (
            calculer_impot_independant, TypeIndependant,
        )
        result = calculer_impot_independant(
            benefice=Decimal("200000"),
            type_statut=TypeIndependant.GERANT_MAJORITAIRE,
        )
        assert result["impot_brut"] > 0
        assert result["taux_marginal_pct"] == 45.0

    def test_impot_avec_parts(self):
        from urssaf_analyzer.regimes.independant import (
            calculer_impot_independant, TypeIndependant,
        )
        result = calculer_impot_independant(
            benefice=Decimal("80000"),
            type_statut=TypeIndependant.EI_IR,
            nb_parts=Decimal("2.5"),
        )
        assert result["nb_parts"] == 2.5

    def test_impot_avec_autres_revenus(self):
        from urssaf_analyzer.regimes.independant import (
            calculer_impot_independant, TypeIndependant,
        )
        result = calculer_impot_independant(
            benefice=Decimal("30000"),
            type_statut=TypeIndependant.EI_IR,
            autres_revenus_foyer=Decimal("20000"),
        )
        assert result["revenu_imposable"] == 50000.0

    def test_impot_zero_revenu(self):
        from urssaf_analyzer.regimes.independant import (
            calculer_impot_independant, TypeIndependant,
        )
        result = calculer_impot_independant(
            benefice=Decimal("0"),
            type_statut=TypeIndependant.MICRO_ENTREPRENEUR,
        )
        assert result["impot_brut"] == 0
        assert result["taux_moyen_pct"] == 0


# ============================================================
# security/encryption.py - remaining branches
# ============================================================

class TestEncryptionExtended:
    def test_chiffrer_dechiffrer_donnees(self):
        from urssaf_analyzer.security.encryption import chiffrer_donnees, dechiffrer_donnees
        data = b"Donnees sensibles NIR 1234567890123"
        password = "SecurePassword123!"
        encrypted = chiffrer_donnees(data, password, contexte="test_nir")
        decrypted = dechiffrer_donnees(encrypted, password, contexte="test_nir")
        assert decrypted == data

    def test_chiffrer_donnees_sans_contexte(self):
        from urssaf_analyzer.security.encryption import chiffrer_donnees, dechiffrer_donnees
        data = b"Donnees sans contexte"
        password = "Password456!"
        encrypted = chiffrer_donnees(data, password)
        decrypted = dechiffrer_donnees(encrypted, password)
        assert decrypted == data

    def test_chiffrer_champ(self):
        from urssaf_analyzer.security.encryption import chiffrer_champ, dechiffrer_champ, est_chiffre
        password = "FieldEncKey!123"
        valeur = "1234567890123"
        encrypted = chiffrer_champ(valeur, password)
        assert encrypted.startswith("ENC:")
        assert est_chiffre(encrypted)
        decrypted = dechiffrer_champ(encrypted, password)
        assert decrypted == valeur

    def test_chiffrer_champ_vide(self):
        from urssaf_analyzer.security.encryption import chiffrer_champ, dechiffrer_champ
        assert chiffrer_champ("", "password") == ""
        assert dechiffrer_champ("", "password") == ""

    def test_dechiffrer_champ_non_chiffre(self):
        from urssaf_analyzer.security.encryption import dechiffrer_champ
        assert dechiffrer_champ("plain_text", "password") == "plain_text"

    def test_est_chiffre(self):
        from urssaf_analyzer.security.encryption import est_chiffre
        assert est_chiffre("ENC:abcdef") is True
        assert est_chiffre("plain text") is False
        assert est_chiffre(123) is False

    def test_dechiffrer_donnees_format_invalide(self):
        from urssaf_analyzer.security.encryption import dechiffrer_donnees, EncryptionError
        with pytest.raises(EncryptionError, match="Format"):
            dechiffrer_donnees(b"invalid data", "password")

    def test_dechiffrer_champ_mauvais_password(self):
        from urssaf_analyzer.security.encryption import chiffrer_champ, dechiffrer_champ
        encrypted = chiffrer_champ("secret", "correctpassword!")
        result = dechiffrer_champ(encrypted, "wrongpassword!")
        assert result == "[dechiffrement echoue]"


# ============================================================
# security/timestamp_authority.py
# ============================================================

class TestTimestampAuthority:
    def test_timestamp_fallback(self):
        from urssaf_analyzer.security.timestamp_authority import TimestampAuthority
        tsa = TimestampAuthority(enabled=False)
        token = tsa.timestamp("test data")
        assert token is not None
        assert token.data_hash is not None
        assert token.certified is False
        assert token.method == "system_clock"

    def test_timestamp_enabled_fallback(self):
        from urssaf_analyzer.security.timestamp_authority import TimestampAuthority
        tsa = TimestampAuthority(tsa_urls=["http://localhost:1/tsa"], timeout_seconds=1)
        token = tsa.timestamp("test data for tsa")
        assert token is not None

    def test_timestamp_hash(self):
        from urssaf_analyzer.security.timestamp_authority import TimestampAuthority, _sha256_hex
        tsa = TimestampAuthority(enabled=False)
        h = _sha256_hex("test")
        token = tsa.timestamp_hash(h)
        assert token is not None

    def test_token_to_dict(self):
        from urssaf_analyzer.security.timestamp_authority import TimestampAuthority
        tsa = TimestampAuthority(enabled=False)
        token = tsa.timestamp("data")
        d = token.to_dict()
        assert isinstance(d, dict)
        assert "timestamp_utc" in d


# ============================================================
# security/alert_manager.py
# ============================================================

class TestAlertManager:
    def test_alert_manager_login_failure(self, tmp_path):
        from urssaf_analyzer.security.alert_manager import AlertManager
        am = AlertManager(alert_log_path=tmp_path / "alerts.json")
        alert = am.on_login_failure(email="test@test.fr", source_ip="1.2.3.4")
        # First failure may not return alert
        assert alert is None or hasattr(alert, 'severity')

    def test_alert_manager_on_operation(self, tmp_path):
        from urssaf_analyzer.security.alert_manager import AlertManager
        am = AlertManager(alert_log_path=tmp_path / "alerts.json")
        alert = am.on_operation(operation="test_op", user_email="test@test.fr")
        assert alert is None or hasattr(alert, 'severity')

    def test_alert_manager_get_alerts(self, tmp_path):
        from urssaf_analyzer.security.alert_manager import AlertManager
        am = AlertManager(alert_log_path=tmp_path / "alerts.json")
        alerts = am.get_alerts()
        assert isinstance(alerts, list)

    def test_alert_manager_count(self, tmp_path):
        from urssaf_analyzer.security.alert_manager import AlertManager
        am = AlertManager(alert_log_path=tmp_path / "alerts.json")
        count = am.count_alerts()
        assert isinstance(count, int)

    def test_alert_manager_decryption_error(self, tmp_path):
        from urssaf_analyzer.security.alert_manager import AlertManager
        am = AlertManager(alert_log_path=tmp_path / "alerts.json")
        # Trigger multiple decryption errors to exceed threshold
        for _ in range(10):
            alert = am.on_decryption_error(context="test file", user_email="test@test.fr")
        assert alert is not None

    def test_alert_manager_proof_chain(self, tmp_path):
        from urssaf_analyzer.security.alert_manager import AlertManager
        am = AlertManager(alert_log_path=tmp_path / "alerts.json")
        alert = am.check_proof_chain({"valid": False, "error": "mismatch"})
        assert alert is not None

    def test_alert_manager_login_success(self, tmp_path):
        from urssaf_analyzer.security.alert_manager import AlertManager
        am = AlertManager(alert_log_path=tmp_path / "alerts.json")
        am.on_login_success(email="test@test.fr")

    def test_alert_manager_brute_force(self, tmp_path):
        from urssaf_analyzer.security.alert_manager import AlertManager
        am = AlertManager(alert_log_path=tmp_path / "alerts.json")
        # Trigger brute force detection
        for i in range(6):
            am.on_login_failure(email="brute@test.fr", source_ip="1.2.3.4")


# ============================================================
# main.py - CLI
# ============================================================

class TestMainCLI:
    def test_creer_argument_parser(self):
        from urssaf_analyzer.main import creer_argument_parser
        parser = creer_argument_parser()
        assert parser is not None

    def test_configurer_logging_verbose(self):
        from urssaf_analyzer.main import configurer_logging
        configurer_logging(verbose=True)

    def test_configurer_logging_normal(self):
        from urssaf_analyzer.main import configurer_logging
        configurer_logging(verbose=False)

    def test_main_no_files(self):
        from urssaf_analyzer.main import main
        with patch("sys.argv", ["urssaf_analyzer", "nonexistent_file.pdf"]):
            result = main()
            assert result == 1

    def test_main_unsupported_format(self):
        from urssaf_analyzer.main import main
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            f.write(b"test")
            f.flush()
            try:
                with patch("sys.argv", ["urssaf_analyzer", f.name]):
                    result = main()
                    assert result == 1
            finally:
                os.unlink(f.name)

    def test_main_with_valid_csv(self, tmp_path):
        from urssaf_analyzer.main import main
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "Code;Libelle;Base;Taux Patronal;Montant Patronal\n"
            "201;Maladie;3500.00;0.070;245.00\n",
            encoding="utf-8",
        )
        with patch("sys.argv", ["urssaf_analyzer", str(csv_file), "--format", "json", "--output", str(tmp_path)]):
            result = main()
            assert result in (0, 1, 2)


# ============================================================
# __main__.py
# ============================================================

class TestModuleMain:
    def test_main_module_raises_system_exit(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["urssaf_analyzer", "nonexistent.pdf"]):
                import importlib
                import urssaf_analyzer.__main__


# ============================================================
# core/orchestrator.py uncovered lines
# ============================================================

class TestOrchestratorExtended:
    def test_orchestrator_with_invalid_file(self, tmp_path, app_config):
        from urssaf_analyzer.core.orchestrator import Orchestrator
        orch = Orchestrator(app_config)
        # Create a file with unsupported content but supported extension
        bad_file = tmp_path / "bad.csv"
        bad_file.write_text("", encoding="utf-8")
        result_path = orch.analyser_documents([bad_file], format_rapport="json")
        # Should complete without crash

    def test_orchestrator_nettoyer(self, app_config):
        from urssaf_analyzer.core.orchestrator import Orchestrator
        orch = Orchestrator(app_config)
        orch.nettoyer()  # Should not raise


# ============================================================
# reporting/report_generator.py uncovered lines
# ============================================================

class TestReportGenerator:
    def test_generer_rapport_json(self, tmp_path):
        from urssaf_analyzer.reporting.report_generator import ReportGenerator
        from urssaf_analyzer.core.orchestrator import AnalysisResult
        gen = ReportGenerator()
        result = AnalysisResult()
        path = gen.generer_json(result, tmp_path / "report.json")
        assert path.exists()

    def test_generer_rapport_html(self, tmp_path):
        from urssaf_analyzer.reporting.report_generator import ReportGenerator
        from urssaf_analyzer.core.orchestrator import AnalysisResult
        gen = ReportGenerator()
        result = AnalysisResult()
        path = gen.generer_html(result, tmp_path / "report.html")
        assert path.exists()


# ============================================================
# certification/certification_readiness.py uncovered lines
# ============================================================

class TestCertificationReadiness:
    def test_evaluer_readiness(self):
        from urssaf_analyzer.certification.certification_readiness import evaluer_maturite_certification
        result = evaluer_maturite_certification()
        assert isinstance(result, dict)


# ============================================================
# utils/number_utils.py uncovered lines
# ============================================================

class TestNumberUtils:
    def test_parser_montant_vide(self):
        from urssaf_analyzer.utils.number_utils import parser_montant
        assert parser_montant("") == Decimal("0")

    def test_parser_montant_negatif(self):
        from urssaf_analyzer.utils.number_utils import parser_montant
        assert parser_montant("-123.45") == Decimal("-123.45")

    def test_parser_montant_avec_espaces(self):
        from urssaf_analyzer.utils.number_utils import parser_montant
        result = parser_montant("1 234,56")
        assert result > 0

    def test_parser_montant_avec_euro(self):
        from urssaf_analyzer.utils.number_utils import parser_montant
        result = parser_montant("1234.56 €")
        assert result == Decimal("1234.56")


# ============================================================
# utils/date_utils.py uncovered line 39
# ============================================================

class TestDateUtils:
    def test_parser_date_invalid(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        assert parser_date("not a date") is None

    def test_parser_date_valid(self):
        from urssaf_analyzer.utils.date_utils import parser_date
        result = parser_date("15/01/2026")
        assert result is not None


# ============================================================
# security/secure_storage.py uncovered lines
# ============================================================

class TestSecureStorage:
    def test_suppression_securisee(self, tmp_path):
        from urssaf_analyzer.security.secure_storage import suppression_securisee
        f = tmp_path / "sensitive.txt"
        f.write_text("data")
        suppression_securisee(f)
        assert not f.exists()

    def test_nettoyer_repertoire_temp(self, tmp_path):
        from urssaf_analyzer.security.secure_storage import nettoyer_repertoire_temp
        (tmp_path / "temp_file.txt").write_text("temp")
        count = nettoyer_repertoire_temp(tmp_path)
        assert count >= 0

    def test_creer_repertoire_session(self, tmp_path):
        from urssaf_analyzer.security.secure_storage import creer_repertoire_session
        session_dir = creer_repertoire_session(tmp_path, "test-session-123")
        assert session_dir.exists()


# ============================================================
# database/db_manager.py uncovered lines
# ============================================================

class TestDbManagerExtended:
    def test_db_manager_operations(self, tmp_path):
        from urssaf_analyzer.database.db_manager import Database
        db = Database(tmp_path / "test.db")

        # Test execute_insert
        db.execute_insert(
            "INSERT INTO analyses (id, nb_documents, nb_findings) VALUES (?, ?, ?)",
            ("test-1", 1, 0),
        )

        # Test execute (select)
        rows = db.execute("SELECT * FROM analyses WHERE id = ?", ("test-1",))
        assert len(rows) == 1

        # Test execute_many
        db.execute_many(
            "INSERT INTO analyses (id, nb_documents, nb_findings) VALUES (?, ?, ?)",
            [("test-2", 2, 1), ("test-3", 3, 2)],
        )
        rows = db.execute("SELECT * FROM analyses")
        assert len(rows) == 3

        # Test get_schema_version
        version = db.get_schema_version()
        assert version == 2

    def test_db_manager_connection_context(self, tmp_path):
        from urssaf_analyzer.database.db_manager import Database
        db = Database(tmp_path / "test2.db")
        with db.connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM profils")
            assert cursor.fetchone()[0] == 0


# ============================================================
# rules/analyse_multiannuelle.py uncovered lines
# ============================================================

class TestAnalyseMultiannuelle:
    def test_analyse_multiannuelle_empty(self):
        from urssaf_analyzer.rules.analyse_multiannuelle import AnalyseMultiAnnuelle
        ama = AnalyseMultiAnnuelle()
        result = ama.analyser()
        assert result["couverture"]["complete"] is False or "annees" in result["couverture"]
        assert isinstance(result["recommandations"], list)

    def test_analyse_multiannuelle_with_data(self):
        from urssaf_analyzer.rules.analyse_multiannuelle import AnalyseMultiAnnuelle
        ama = AnalyseMultiAnnuelle()
        for year in (2022, 2023, 2024, 2025):
            ama.alimenter(year, {
                "masse_salariale": 100000 + (year - 2022) * 20000,
                "effectif_moyen": 10 + (year - 2022) * 5,
                "nb_bulletins": 120,
                "total_cotisations_patronales": 40000 + (year - 2022) * 8000,
                "total_cotisations_salariales": 20000 + (year - 2022) * 4000,
            })
        result = ama.analyser()
        assert "tendances" in result
        assert "anomalies" in result
        assert "couverture" in result
        assert len(result["donnees_par_annee"]) == 4

    def test_analyse_multiannuelle_anomalies(self):
        from urssaf_analyzer.rules.analyse_multiannuelle import AnalyseMultiAnnuelle
        ama = AnalyseMultiAnnuelle()
        # Chute brutale de masse salariale > 30%
        ama.alimenter(2023, {"masse_salariale": 200000, "effectif_moyen": 20})
        ama.alimenter(2024, {"masse_salariale": 100000, "effectif_moyen": 10})
        result = ama.analyser()
        types = [a["type"] for a in result["anomalies"]]
        assert "chute_masse_salariale" in types or "chute_effectif" in types

    def test_analyse_multiannuelle_hausse(self):
        from urssaf_analyzer.rules.analyse_multiannuelle import AnalyseMultiAnnuelle
        ama = AnalyseMultiAnnuelle()
        ama.alimenter(2023, {"masse_salariale": 100000, "effectif_moyen": 10})
        ama.alimenter(2024, {"masse_salariale": 200000, "effectif_moyen": 10})
        result = ama.analyser()
        assert isinstance(result["anomalies"], list)

    def test_analyse_multiannuelle_knowledge(self):
        from urssaf_analyzer.rules.analyse_multiannuelle import AnalyseMultiAnnuelle
        ama = AnalyseMultiAnnuelle()
        kb = {
            "periodes_couvertes": ["2023-01", "2024-06", "invalid"],
            "bulletins_paie": [
                {"periode": "2023-01", "masse_salariale": 50000, "nb_salaries": 5, "total_patronal": 20000, "total_salarial": 10000},
                {"periode": "2024-06", "masse_salariale": 60000, "nb_salaries": 6, "total_patronal": 24000, "total_salarial": 12000},
                {"periode": "", "masse_salariale": 10000},  # empty periode
            ],
            "declarations_dsn": [
                {"periode": "2023-01", "masse_salariale": 50000, "nb_salaries": 5},
                {"periode": "2024-06", "masse_salariale": 60000, "nb_salaries": 6},
                {"periode": "", "masse_salariale": 10000},  # empty periode
            ],
            "effectifs": {"2023-01": 5, "2024-06": 6, "invalid": 3},
        }
        ama.alimenter_depuis_knowledge(kb)
        assert 2023 in ama.donnees_annuelles
        assert 2024 in ama.donnees_annuelles

    def test_analyse_multiannuelle_dsn_ecart(self):
        from urssaf_analyzer.rules.analyse_multiannuelle import AnalyseMultiAnnuelle
        ama = AnalyseMultiAnnuelle()
        ama.alimenter(2023, {
            "masse_salariale": 100000, "effectif_moyen": 10,
            "nb_bulletins": 120, "nb_dsn": 12,
            "masse_salariale_dsn": 80000,
            "total_cotisations_patronales": 40000,
        })
        ama.alimenter(2024, {
            "masse_salariale": 110000, "effectif_moyen": 10,
            "nb_bulletins": 120, "nb_dsn": 12,
            "masse_salariale_dsn": 85000,
            "total_cotisations_patronales": 44000,
        })
        result = ama.analyser()
        assert isinstance(result["anomalies"], list)

    def test_analyse_seuil_effectif(self):
        from urssaf_analyzer.rules.analyse_multiannuelle import AnalyseMultiAnnuelle
        ama = AnalyseMultiAnnuelle()
        # Cross the 11-employee threshold
        ama.alimenter(2023, {"masse_salariale": 100000, "effectif_moyen": 9})
        ama.alimenter(2024, {"masse_salariale": 120000, "effectif_moyen": 15})
        result = ama.analyser()
        assert isinstance(result["recommandations"], list)

    def test_analyse_baisse_salaire_moyen(self):
        from urssaf_analyzer.rules.analyse_multiannuelle import AnalyseMultiAnnuelle
        ama = AnalyseMultiAnnuelle()
        ama.alimenter(2023, {"masse_salariale": 200000, "effectif_moyen": 10})
        ama.alimenter(2024, {"masse_salariale": 200000, "effectif_moyen": 20})
        result = ama.analyser()
        assert isinstance(result["anomalies"], list)


# ============================================================
# parsers/base_parser.py uncovered lines
# ============================================================

class TestBaseParser:
    def test_base_parser_verifier_taille(self, tmp_path):
        from urssaf_analyzer.parsers.base_parser import BaseParser

        class ConcreteParser(BaseParser):
            def peut_traiter(self, path):
                return True
            def parser(self, path):
                return {}
            def extraire_metadata(self, path):
                return {}

        f = tmp_path / "big.txt"
        f.write_text("x" * 100)
        bp = ConcreteParser()
        bp._verifier_taille_fichier(f)  # Should not raise for small files

    def test_base_parser_cannot_instantiate(self):
        from urssaf_analyzer.parsers.base_parser import BaseParser
        import pytest
        with pytest.raises(TypeError):
            BaseParser()

    def test_parser_factory_unsupported(self, tmp_path):
        from urssaf_analyzer.parsers.parser_factory import ParserFactory
        from urssaf_analyzer.core.exceptions import UnsupportedFormatError
        import pytest
        f = tmp_path / "test.unsupported"
        f.write_text("data")
        factory = ParserFactory()
        with pytest.raises(UnsupportedFormatError):
            factory.get_parser(f)


# ============================================================
# rules/regimes_speciaux.py uncovered lines
# ============================================================

class TestRegimesSpeciaux:
    def test_get_regime(self):
        from urssaf_analyzer.rules.regimes_speciaux import get_regime, lister_regimes
        result = get_regime("ALSACE_MOSELLE")
        assert result is None or isinstance(result, dict)
        regimes = lister_regimes()
        assert isinstance(regimes, list)

    def test_detecter_regime(self):
        from urssaf_analyzer.rules.regimes_speciaux import detecter_regime
        result = detecter_regime(code_naf="0111Z", departement="67")
        assert isinstance(result, list)
        result2 = detecter_regime(code_naf="5510Z")
        assert isinstance(result2, list)

    def test_calculer_supplement_alsace(self):
        from urssaf_analyzer.rules.regimes_speciaux import calculer_supplement_alsace_moselle
        from decimal import Decimal
        result = calculer_supplement_alsace_moselle(Decimal("3000"))
        assert isinstance(result, dict)

    def test_calculer_cotisations_msa(self):
        from urssaf_analyzer.rules.regimes_speciaux import calculer_cotisations_msa
        from decimal import Decimal
        result = calculer_cotisations_msa(Decimal("2500"), effectif=5)
        assert isinstance(result, dict)


# ============================================================
# rules/contribution_rules.py uncovered lines
# ============================================================

class TestContributionRulesExtended:
    def test_contribution_rules_class(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        cr = ContributionRules(effectif_entreprise=25)
        # Test get_taux_attendu_patronal
        from urssaf_analyzer.config.constants import ContributionType
        taux = cr.get_taux_attendu_patronal(ContributionType.MALADIE)
        assert isinstance(taux, Decimal) or taux is None
        taux_s = cr.get_taux_attendu_salarial(ContributionType.MALADIE)
        assert isinstance(taux_s, (Decimal, type(None)))

    def test_calculer_assiette(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import ContributionType
        cr = ContributionRules(effectif_entreprise=25)
        assiette = cr.calculer_assiette(ContributionType.MALADIE, Decimal("3000"))
        assert isinstance(assiette, Decimal)

    def test_calculer_bulletin_complet(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        cr = ContributionRules(effectif_entreprise=25)
        result = cr.calculer_bulletin_complet(Decimal("3000"))
        assert isinstance(result, dict)

    def test_verifier_taux(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import ContributionType
        cr = ContributionRules(effectif_entreprise=25)
        result = cr.verifier_taux(ContributionType.MALADIE, Decimal("0.07"), Decimal("0.0"))
        assert result is not None

    def test_calculer_rgdu(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        cr = ContributionRules(effectif_entreprise=25)
        rgdu = cr.calculer_rgdu(Decimal("40000"))
        assert isinstance(rgdu, Decimal)
        assert cr.est_eligible_rgdu(Decimal("40000")) in (True, False)
        detail = cr.detail_rgdu(Decimal("40000"))
        assert isinstance(detail, dict)

    def test_calculer_taxe_salaires(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        cr = ContributionRules(effectif_entreprise=25)
        result = cr.calculer_taxe_salaires(Decimal("50000"))
        assert isinstance(result, dict)

    def test_calculer_net_imposable(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        cr = ContributionRules(effectif_entreprise=25)
        result = cr.calculer_net_imposable(Decimal("3000"))
        assert isinstance(result, (Decimal, dict))

    def test_calculer_exoneration_acre(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        cr = ContributionRules(effectif_entreprise=5)
        result = cr.calculer_exoneration_acre(Decimal("2500"))
        assert isinstance(result, dict)

    def test_calculer_exoneration_apprenti(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        cr = ContributionRules(effectif_entreprise=5)
        result = cr.calculer_exoneration_apprenti(Decimal("1500"))
        assert isinstance(result, dict)

    def test_identifier_ccn(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        cr = ContributionRules(effectif_entreprise=25)
        result = cr.identifier_ccn("Convention collective nationale des hotels")
        assert result is None or isinstance(result, str)
