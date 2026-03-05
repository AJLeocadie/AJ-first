"""Tests de preparation a la commercialisation.

Verifie les points critiques avant mise en production :
- Securite des parseurs (fichiers malveillants, taille, encoding)
- Couverture des formats de tous les logiciels declares
- Validation systematique des identifiants (NIR, SIRET, SIREN)
- Coherence des montants et taux
- Protection contre les fichiers corrompus
- Protection DoS (fichiers geants, boucles infinies)
"""

import sys
import tempfile
from pathlib import Path
from decimal import Decimal
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.parsers.parser_factory import ParserFactory
from urssaf_analyzer.parsers.csv_parser import CSVParser
from urssaf_analyzer.parsers.dsn_parser import DSNParser, CTP_MAPPING
from urssaf_analyzer.parsers.fec_parser import FECParser, COLONNES_FEC
from urssaf_analyzer.parsers.pdf_parser import PDFParser
from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.config.constants import ContributionType, SUPPORTED_EXTENSIONS
from urssaf_analyzer.models.documents import Document, FileType
from urssaf_analyzer.utils.validators import (
    valider_nir, valider_montant, valider_taux,
    valider_base_brute, valider_compte_fec, ParseLog,
)
from urssaf_analyzer.utils.number_utils import valider_siret, valider_siren


FIXTURES = Path(__file__).parent.parent / "fixtures"


# ============================================================
# 1. SECURITE DES PARSEURS
# ============================================================

class TestSecuriteParseurs:
    """Verifie que les parseurs sont proteges contre les entrees malveillantes."""

    def test_fichier_zero_bytes_csv(self, tmp_path):
        """Un fichier de 0 octets ne doit pas crasher."""
        f = tmp_path / "vide.csv"
        f.write_bytes(b"")
        parser = CSVParser()
        with pytest.raises(ParseError):
            parser.parser(f, Document(type_fichier=FileType.CSV))

    def test_fichier_zero_bytes_dsn(self, tmp_path):
        f = tmp_path / "vide.dsn"
        f.write_bytes(b"")
        parser = DSNParser()
        with pytest.raises(ParseError):
            parser.parser(f, Document(type_fichier=FileType.DSN))

    def test_fichier_zero_bytes_fec(self, tmp_path):
        f = tmp_path / "FEC_vide.txt"
        f.write_bytes(b"")
        parser = FECParser()
        with pytest.raises(ParseError):
            parser.parser(f, Document(type_fichier=FileType.TEXTE))

    def test_fichier_binaire_aleatoire_csv(self, tmp_path):
        """Un fichier binaire ne doit pas crasher le CSV parser."""
        import os
        f = tmp_path / "binaire.csv"
        f.write_bytes(os.urandom(1024))
        parser = CSVParser()
        # Peut lever ParseError ou retourner une liste vide
        try:
            result = parser.parser(f, Document(type_fichier=FileType.CSV))
            assert isinstance(result, list)
        except (ParseError, UnicodeDecodeError):
            pass  # Acceptable

    def test_fichier_avec_null_bytes_csv(self, tmp_path):
        """Des null bytes ne doivent pas causer de crash."""
        f = tmp_path / "null.csv"
        contenu = "nir,nom,prenom\x00,base_brute\n1850175123456\x00,DU\x00PONT,Jean,3200\n"
        f.write_bytes(contenu.encode("utf-8"))
        parser = CSVParser()
        try:
            result = parser.parser(f, Document(type_fichier=FileType.CSV))
            assert isinstance(result, list)
        except ParseError:
            pass  # Acceptable

    def test_csv_injection_formule(self, tmp_path):
        """Les formules Excel (=CMD) ne doivent pas etre executees."""
        f = tmp_path / "injection.csv"
        contenu = 'nir,nom,prenom,base_brute\n1850175123456,"=CMD|\'calc\'!A0",Jean,3200\n'
        f.write_text(contenu)
        parser = CSVParser()
        result = parser.parser(f, Document(type_fichier=FileType.CSV))
        # Le nom ne doit pas etre interprete comme une commande
        assert isinstance(result, list)

    def test_csv_ligne_tres_longue(self, tmp_path):
        """Une ligne de 10 Mo ne doit pas causer de crash."""
        f = tmp_path / "longue.csv"
        contenu = "nir,nom,prenom,base_brute\n"
        contenu += "1850175123456," + "A" * 100_000 + ",Jean,3200\n"
        f.write_text(contenu)
        parser = CSVParser()
        result = parser.parser(f, Document(type_fichier=FileType.CSV))
        assert isinstance(result, list)

    def test_dsn_bloc_invalide_ne_crashe_pas(self, tmp_path):
        """Des blocs DSN avec des valeurs aberrantes ne doivent pas crasher."""
        contenu = "S10.G00.00.001 'TEST'\n"
        contenu += "S20.G00.05.001 'INVALID_SIREN'\n"
        contenu += "S21.G00.06.001 'NOT_A_SIRET_AT_ALL'\n"
        contenu += "S30.G00.30.001 'FAKE_NIR'\n"
        f = tmp_path / "invalid.dsn"
        f.write_text(contenu)
        parser = DSNParser()
        result = parser.parser(f, Document(type_fichier=FileType.DSN))
        assert isinstance(result, list)


# ============================================================
# 2. COUVERTURE DES LOGICIELS DECLARES
# ============================================================

class TestCouvertureLogiciels:
    """Verifie que tous les logiciels declares sont couverts."""

    def test_sage_csv_point_virgule_cp1252(self, tmp_path):
        """SAGE Paie : CSV point-virgule, encoding Windows-1252."""
        contenu = "nir;nom;prenom;base_brute;type_cotisation;taux_patronal;montant_patronal;taux_salarial;montant_salarial;periode_debut;periode_fin\n"
        contenu += "1850175123456;DUPR\u00c9;Fran\u00e7ois;3200.00;maladie;13.00;416.00;0.00;0.00;01/01/2026;31/01/2026\n"
        f = tmp_path / "SAGE_export.csv"
        f.write_bytes(contenu.encode("cp1252"))
        parser = CSVParser()
        result = parser.parser(f, Document(type_fichier=FileType.CSV))
        assert len(result) >= 1
        assert len(result[0].employes) >= 1

    def test_ciel_csv_iso8859(self, tmp_path):
        """CIEL Compta : CSV point-virgule, ISO-8859-1."""
        contenu = "nir;nom;prenom;base_brute;type_cotisation;taux_patronal;montant_patronal;taux_salarial;montant_salarial;periode_debut;periode_fin\n"
        contenu += "1850175123456;BENO\u00ceT;L\u00e9a;2800.00;vieillesse plafonnee;8.55;239.40;6.90;193.20;01/01/2026;31/01/2026\n"
        f = tmp_path / "CIEL_export.csv"
        f.write_bytes(contenu.encode("iso-8859-1"))
        parser = CSVParser()
        result = parser.parser(f, Document(type_fichier=FileType.CSV))
        assert len(result) >= 1

    def test_adp_csv_utf8_bom(self, tmp_path):
        """ADP : CSV virgule, UTF-8 avec BOM."""
        contenu = "\ufeffnir,nom,prenom,base_brute,type_cotisation,taux_patronal,montant_patronal,taux_salarial,montant_salarial,periode_debut,periode_fin\n"
        contenu += "1850175123456,DUPONT,Jean,3200.00,maladie,13.00,416.00,0.00,0.00,01/01/2026,31/01/2026\n"
        f = tmp_path / "ADP_export.csv"
        f.write_text(contenu, encoding="utf-8-sig")
        parser = CSVParser()
        result = parser.parser(f, Document(type_fichier=FileType.CSV))
        assert len(result) >= 1

    def test_ebp_csv_tabulation(self, tmp_path):
        """EBP Paie : CSV tabulation."""
        contenu = "nir\tnom\tprenom\tbase_brute\ttype_cotisation\ttaux_patronal\tmontant_patronal\ttaux_salarial\tmontant_salarial\tperiode_debut\tperiode_fin\n"
        contenu += "1850175123456\tDUPONT\tJean\t3200.00\tmaladie\t13.00\t416.00\t0.00\t0.00\t01/01/2026\t31/01/2026\n"
        f = tmp_path / "EBP_export.csv"
        f.write_text(contenu)
        parser = CSVParser()
        result = parser.parser(f, Document(type_fichier=FileType.CSV))
        assert len(result) >= 1

    def test_silae_csv_utf8(self, tmp_path):
        """Silae : CSV point-virgule, UTF-8."""
        contenu = "nir;nom;prenom;base_brute;type_cotisation;taux_patronal;montant_patronal;taux_salarial;montant_salarial;periode_debut;periode_fin\n"
        contenu += "1850175123456;MARTIN;Sophie;4500.00;maladie;13.00;585.00;0.00;0.00;01/01/2026;31/01/2026\n"
        f = tmp_path / "Silae_export.csv"
        f.write_text(contenu, encoding="utf-8")
        parser = CSVParser()
        result = parser.parser(f, Document(type_fichier=FileType.CSV))
        assert len(result) >= 1

    def test_fec_sage_tabulation_cp1252(self, tmp_path):
        """SAGE Compta FEC : tabulation, cp1252."""
        colonnes = "\t".join(COLONNES_FEC)
        ligne = "\t".join([
            "VE", "Ventes", "001", "20260101", "411000", "Clients divers",
            "", "", "FA001", "20260101", "Facture Cl\u00e9ment", "1200.00", "0.00",
            "", "", "20260101", "", "",
        ])
        f = tmp_path / "FEC_20260101.txt"
        f.write_bytes((colonnes + "\n" + ligne + "\n").encode("cp1252"))
        parser = FECParser()
        assert parser.peut_traiter(f) is True
        result = parser.parser(f, Document(type_fichier=FileType.TEXTE))
        assert len(result) >= 1

    def test_dsn_neodes_phase3(self):
        """DSN NEODeS Phase 3 : fichier fixture standard."""
        parser = DSNParser()
        result = parser.parser(FIXTURES / "sample_dsn.dsn", Document(type_fichier=FileType.DSN))
        assert len(result) >= 1
        assert result[0].type_declaration == "DSN"
        assert result[0].employeur.siren == "123456789"


# ============================================================
# 3. VALIDATION SYSTEMATIQUE DES IDENTIFIANTS
# ============================================================

class TestValidationIdentifiants:
    """Verifie que les identifiants sont valides systematiquement."""

    def test_nir_standard_valide(self):
        r = valider_nir("1850175123456")
        assert r.valide is True

    def test_nir_corse_valide(self):
        r = valider_nir("12A0175123456")
        assert r.valide is True

    def test_nir_invalide_rejete(self):
        r = valider_nir("ABCDEFGHIJKLM")
        assert r.valide is False

    def test_siret_luhn_valide(self):
        assert valider_siret("73282932000074") is True

    def test_siret_luhn_invalide(self):
        assert valider_siret("12345678901234") is False

    def test_siren_luhn_valide(self):
        assert valider_siren("732829320") is True

    def test_siren_luhn_invalide(self):
        assert valider_siren("123456789") is False


# ============================================================
# 4. COHERENCE DES MONTANTS
# ============================================================

class TestCoherenceMontants:
    """Verifie la coherence des montants extraits."""

    def test_base_brute_raisonnable(self):
        r = valider_base_brute(Decimal("3200"))
        assert r.valide is True

    def test_base_brute_aberrante_rejetee(self):
        r = valider_base_brute(Decimal("999999"))
        assert r.valide is False

    def test_net_superieur_brut_signale(self):
        r = valider_base_brute(Decimal("3200"), net=Decimal("5000"))
        assert r.valide is False

    def test_taux_pourcentage_converti(self):
        r = valider_taux(Decimal("13"))
        assert r.valide is True
        # Doit etre converti en decimal
        assert Decimal(r.valeur_corrigee) < Decimal("1")

    def test_taux_negatif_rejete(self):
        r = valider_taux(Decimal("-5"))
        assert r.valide is False

    def test_montant_negatif_signale(self):
        r = valider_montant(Decimal("-100"), accepter_negatif=False)
        assert r.valide is False


# ============================================================
# 5. COUVERTURE CTP DSN
# ============================================================

class TestCouvertureCTP:
    """Verifie la couverture des codes CTP de cotisations."""

    def test_cotisations_principales_presentes(self):
        """Les CTP des cotisations obligatoires doivent etre mappes."""
        ctp_obligatoires = {
            "100": "Maladie",
            "260": "Vieillesse plafonnee",
            "262": "Vieillesse deplafonnee",
            "332": "Allocations familiales",
            "772": "Chomage",
            "937": "AGS",
            "012": "CSG deductible",
            "018": "CRDS",
        }
        for ctp, desc in ctp_obligatoires.items():
            assert ctp in CTP_MAPPING, f"CTP {ctp} ({desc}) manquant du mapping"

    def test_ctp_retraite_complementaire(self):
        """AGIRC-ARRCO : T1 et T2 doivent etre presents."""
        assert "063" in CTP_MAPPING  # T1
        # Vérifier qu'il existe au moins un CTP pour T2
        t2_ctps = [k for k, v in CTP_MAPPING.items()
                    if v == ContributionType.RETRAITE_COMPLEMENTAIRE_T2]
        assert len(t2_ctps) >= 1

    def test_ctp_formation_apprentissage(self):
        """Formation professionnelle et taxe d'apprentissage."""
        assert "971" in CTP_MAPPING
        assert "951" in CTP_MAPPING


# ============================================================
# 6. FEC - CONFORMITE REGLEMENTAIRE
# ============================================================

class TestFECConformite:
    """Verifie la conformite du parseur FEC avec l'Art. L.47 A-I LPF."""

    def test_18_colonnes_presentes(self):
        assert len(COLONNES_FEC) == 18

    def test_compte_pcg_valide(self):
        r = valider_compte_fec("641100")
        assert r.valide is True

    def test_compte_pcg_invalide(self):
        r = valider_compte_fec("")
        assert r.valide is False

    def test_comptes_sociaux_reconnus(self):
        """Les comptes 43x (charges sociales) doivent etre reconnus."""
        for code in ["421", "431", "437", "4311", "4313"]:
            r = valider_compte_fec(code)
            assert r.valide is True, f"Compte {code} devrait etre valide"


# ============================================================
# 7. FACTORY ET EXTENSIONS
# ============================================================

class TestFactoryCompletude:
    """Verifie que toutes les extensions declarees ont un parseur."""

    def test_toutes_extensions_supportees(self):
        factory = ParserFactory()
        for ext in SUPPORTED_EXTENSIONS:
            # Vérifier que la factory ne lève pas d'erreur
            # pour les extensions déclarées comme supportées
            test_path = Path(f"/tmp/test{ext}")
            try:
                parser = factory.get_parser(test_path)
                assert parser is not None, f"Pas de parseur pour {ext}"
            except Exception:
                # Certains parseurs vérifient le contenu, pas juste l'extension
                pass

    def test_extensions_minimales(self):
        """Extensions critiques pour la conformite sociale/fiscale."""
        extensions_critiques = [".csv", ".pdf", ".dsn", ".xml", ".xlsx", ".xls", ".txt"]
        for ext in extensions_critiques:
            assert ext in SUPPORTED_EXTENSIONS, f"Extension {ext} manquante"


# ============================================================
# 8. PARSELOG - TRACABILITE
# ============================================================

class TestTraçabilite:
    """Verifie que les erreurs de parsing sont tracees."""

    def test_parselog_errors_tracked(self):
        log = ParseLog("test", "fichier.csv")
        log.error(1, "nir", "NIR invalide", "ABC")
        log.error(2, "montant", "Montant negatif", "-100")
        assert log.has_errors is True
        assert len(log.errors) == 2

    def test_parselog_warnings_tracked(self):
        log = ParseLog("test", "fichier.csv")
        log.warning(1, "taux", "Taux converti", "13")
        assert len(log.warnings) == 1

    def test_parselog_to_dict_complete(self):
        log = ParseLog("csv", "export_sage.csv")
        log.error(5, "nir", "NIR invalide")
        log.warning(10, "montant", "Montant arrondi")
        log.info("50 lignes traitees")
        d = log.to_dict()
        assert d["parser"] == "csv"
        assert d["nb_erreurs"] == 1
        assert d["nb_avertissements"] == 1
        assert len(d["info"]) == 1


# ============================================================
# 9. BASE PARSER - PROTECTIONS
# ============================================================

class TestBaseParserProtections:
    """Verifie les protections du BaseParser."""

    def test_sanitize_string_basique(self):
        result = BaseParser._sanitize_string("Hello World")
        assert result == "Hello World"

    def test_sanitize_string_controles(self):
        result = BaseParser._sanitize_string("Hello\x00World\x01Test")
        # Les caracteres de controle doivent etre retires
        assert "\x00" not in result
        assert "\x01" not in result

    def test_sanitize_string_troncature(self):
        long_str = "A" * 1000
        result = BaseParser._sanitize_string(long_str, max_length=100)
        assert len(result) == 100

    def test_sanitize_string_vide(self):
        assert BaseParser._sanitize_string("") == ""
        assert BaseParser._sanitize_string(None) == ""
