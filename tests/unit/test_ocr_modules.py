"""Tests des modules OCR (image_reader, image_parser, invoice_detector, legal_document_extractor)."""

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# =====================================================
# IMAGE READER
# =====================================================

class TestImageReader:
    """Tests du lecteur multi-format."""

    def test_format_enums(self):
        from urssaf_analyzer.ocr.image_reader import FormatFichier
        assert FormatFichier.PDF == "pdf"
        assert FormatFichier.JPEG == "jpeg"
        assert FormatFichier.CSV == "csv"
        assert FormatFichier.INCONNU == "inconnu"

    def test_resultat_lecture_defaults(self):
        from urssaf_analyzer.ocr.image_reader import ResultatLecture, FormatFichier
        r = ResultatLecture()
        assert r.texte == ""
        assert r.format_detecte == FormatFichier.INCONNU
        assert r.est_image is False
        assert r.est_scan is False
        assert r.confiance_ocr == 1.0

    def test_avertissement_manuscrit(self):
        from urssaf_analyzer.ocr.image_reader import AvertissementManuscrit
        a = AvertissementManuscrit(zone="header", message="Ecriture manuscrite", confiance=0.8)
        assert a.zone == "header"
        assert a.confiance == 0.8

    def test_lecteur_init(self):
        from urssaf_analyzer.ocr.image_reader import LecteurMultiFormat
        lecteur = LecteurMultiFormat()
        assert lecteur is not None

    def test_format_depuis_ext(self):
        from urssaf_analyzer.ocr.image_reader import LecteurMultiFormat, FormatFichier
        lecteur = LecteurMultiFormat()
        assert lecteur._format_depuis_ext(".pdf") == FormatFichier.PDF
        assert lecteur._format_depuis_ext(".jpg") == FormatFichier.JPEG
        assert lecteur._format_depuis_ext(".csv") == FormatFichier.CSV
        assert lecteur._format_depuis_ext(".xlsx") == FormatFichier.EXCEL

    def test_lire_fichier_txt(self, tmp_path):
        from urssaf_analyzer.ocr.image_reader import LecteurMultiFormat, FormatFichier
        lecteur = LecteurMultiFormat()
        f = tmp_path / "test.txt"
        f.write_text("Contenu texte simple")
        result = lecteur.lire_fichier(f)
        assert result.format_detecte == FormatFichier.TEXTE
        assert "Contenu texte" in result.texte

    def test_lire_fichier_csv(self, tmp_path):
        from urssaf_analyzer.ocr.image_reader import LecteurMultiFormat, FormatFichier
        lecteur = LecteurMultiFormat()
        f = tmp_path / "test.csv"
        f.write_text("col1,col2\nval1,val2")
        result = lecteur.lire_fichier(f)
        assert result.format_detecte == FormatFichier.CSV

    def test_decoder_texte(self):
        from urssaf_analyzer.ocr.image_reader import LecteurMultiFormat
        lecteur = LecteurMultiFormat()
        content = "Hello world".encode("utf-8")
        result = lecteur._decoder_texte(content)
        assert result == "Hello world"

    def test_extensions_constants(self):
        from urssaf_analyzer.ocr.image_reader import (
            EXTENSIONS_IMAGES, EXTENSIONS_PDF, EXTENSIONS_EXCEL,
            EXTENSIONS_CSV, EXTENSIONS_XML, EXTENSIONS_DSN, EXTENSIONS_TEXTE,
        )
        assert ".jpg" in EXTENSIONS_IMAGES or ".jpeg" in EXTENSIONS_IMAGES
        assert ".pdf" in EXTENSIONS_PDF
        assert ".xlsx" in EXTENSIONS_EXCEL
        assert ".csv" in EXTENSIONS_CSV
        assert ".xml" in EXTENSIONS_XML
        assert ".dsn" in EXTENSIONS_DSN
        assert ".txt" in EXTENSIONS_TEXTE


# =====================================================
# IMAGE PARSER
# =====================================================

class TestImageParser:
    """Tests du parseur d'images."""

    def test_peut_traiter_jpg(self):
        from urssaf_analyzer.parsers.image_parser import ImageParser
        parser = ImageParser()
        assert parser.peut_traiter(Path("test.jpg")) is True

    def test_peut_traiter_png(self):
        from urssaf_analyzer.parsers.image_parser import ImageParser
        parser = ImageParser()
        assert parser.peut_traiter(Path("test.png")) is True

    def test_peut_traiter_non_image(self):
        from urssaf_analyzer.parsers.image_parser import ImageParser
        parser = ImageParser()
        assert parser.peut_traiter(Path("test.csv")) is False

    def test_peut_traiter_heic(self):
        from urssaf_analyzer.parsers.image_parser import ImageParser
        parser = ImageParser()
        assert parser.peut_traiter(Path("test.heic")) is True


# =====================================================
# INVOICE DETECTOR
# =====================================================

class TestInvoiceDetector:
    """Tests du detecteur de factures."""

    def test_type_document_enum(self):
        from urssaf_analyzer.ocr.invoice_detector import TypeDocument
        assert TypeDocument.FACTURE_VENTE == "facture_vente"
        assert TypeDocument.FACTURE_ACHAT == "facture_achat"
        assert TypeDocument.INCONNU == "inconnu"

    def test_type_tva_enum(self):
        from urssaf_analyzer.ocr.invoice_detector import TypeTVA
        assert TypeTVA.TAUX_NORMAL == "20.0"
        assert TypeTVA.TAUX_REDUIT == "5.5"
        assert TypeTVA.EXONERE == "0.0"

    def test_ligne_piece_defaults(self):
        from urssaf_analyzer.ocr.invoice_detector import LignePiece
        lp = LignePiece()
        assert lp.quantite == Decimal("1")
        assert lp.taux_tva == Decimal("20.0")
        assert lp.montant_ht == Decimal("0")

    def test_tiers_detecte_defaults(self):
        from urssaf_analyzer.ocr.invoice_detector import TiersDetecte
        t = TiersDetecte()
        assert t.nom == ""
        assert t.est_client is False
        assert t.est_fournisseur is False

    def test_piece_comptable_defaults(self):
        from urssaf_analyzer.ocr.invoice_detector import PieceComptable, TypeDocument
        pc = PieceComptable()
        assert pc.type_document == TypeDocument.INCONNU
        assert pc.montant_ht == Decimal("0")
        assert pc.montant_ttc == Decimal("0")
        assert pc.id is not None and len(pc.id) > 0

    def test_piece_comptable_with_values(self):
        from urssaf_analyzer.ocr.invoice_detector import PieceComptable, TypeDocument
        pc = PieceComptable(
            type_document=TypeDocument.FACTURE_VENTE,
            numero_piece="F-001",
            montant_ht=Decimal("1000"),
            montant_tva=Decimal("200"),
            montant_ttc=Decimal("1200"),
        )
        assert pc.montant_ht == Decimal("1000")


# =====================================================
# LEGAL DOCUMENT EXTRACTOR
# =====================================================

class TestLegalDocumentExtractor:
    """Tests de l'extracteur de documents juridiques."""

    def test_dirigeant_defaults(self):
        from urssaf_analyzer.ocr.legal_document_extractor import Dirigeant
        d = Dirigeant()
        assert d.nom == ""
        assert d.fonction == ""
        assert d.date_naissance is None

    def test_info_entreprise_defaults(self):
        from urssaf_analyzer.ocr.legal_document_extractor import InfoEntreprise
        ie = InfoEntreprise()
        assert ie.siren == ""
        assert ie.siret == ""
        assert ie.capital_social == Decimal("0")
        assert ie.pays == "France"
        assert ie.duree_societe == 99
        assert ie.effectif == 0

    def test_info_entreprise_with_values(self):
        from urssaf_analyzer.ocr.legal_document_extractor import InfoEntreprise
        ie = InfoEntreprise(
            siren="123456789",
            raison_sociale="Test Corp",
            forme_juridique="SAS",
            capital_social=Decimal("10000"),
        )
        assert ie.siren == "123456789"
        assert ie.capital_social == Decimal("10000")

    def test_dirigeant_with_values(self):
        from urssaf_analyzer.ocr.legal_document_extractor import Dirigeant
        d = Dirigeant(nom="Dupont", prenom="Jean", fonction="President")
        assert d.nom == "Dupont"
        assert d.fonction == "President"

    def test_info_entreprise_dirigeants_list(self):
        from urssaf_analyzer.ocr.legal_document_extractor import InfoEntreprise, Dirigeant
        ie = InfoEntreprise(
            dirigeants=[
                Dirigeant(nom="A", fonction="President"),
                Dirigeant(nom="B", fonction="DG"),
            ]
        )
        assert len(ie.dirigeants) == 2
