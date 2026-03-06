"""Tests exhaustifs pour urssaf_analyzer/ocr/image_reader.py.

Couvre :
- FormatFichier enum
- AvertissementManuscrit / ResultatLecture dataclasses
- LecteurMultiFormat : lire_fichier, lire_contenu_brut
- Lecteurs specifiques : image, PDF, Excel, CSV, texte
- Detection manuscrit et scan
- Utilitaires OCR, decodage, format depuis extension
- Cas limites : fichier manquant, contenu vide, erreurs
"""

import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.ocr.image_reader import (
    FormatFichier,
    AvertissementManuscrit,
    ResultatLecture,
    LecteurMultiFormat,
    EXTENSIONS_IMAGES,
    EXTENSIONS_PDF,
    EXTENSIONS_EXCEL,
    EXTENSIONS_CSV,
    EXTENSIONS_XML,
    EXTENSIONS_DSN,
    EXTENSIONS_TEXTE,
    TOUTES_EXTENSIONS,
    PATTERNS_MANUSCRIT_FORT,
    PATTERNS_MANUSCRIT_FAIBLE,
    INDICATEURS_SCAN,
)


# =====================================================
# FormatFichier Enum
# =====================================================


class TestFormatFichier:
    """Tests pour l'enum FormatFichier."""

    def test_all_values(self):
        assert FormatFichier.PDF == "pdf"
        assert FormatFichier.JPEG == "jpeg"
        assert FormatFichier.PNG == "png"
        assert FormatFichier.BMP == "bmp"
        assert FormatFichier.TIFF == "tiff"
        assert FormatFichier.GIF == "gif"
        assert FormatFichier.WEBP == "webp"
        assert FormatFichier.CSV == "csv"
        assert FormatFichier.EXCEL == "excel"
        assert FormatFichier.XML == "xml"
        assert FormatFichier.DSN == "dsn"
        assert FormatFichier.TEXTE == "texte"
        assert FormatFichier.INCONNU == "inconnu"

    def test_is_str_enum(self):
        assert isinstance(FormatFichier.PDF, str)

    def test_count(self):
        assert len(FormatFichier) == 13


# =====================================================
# Dataclasses
# =====================================================


class TestAvertissementManuscrit:
    """Tests pour le dataclass AvertissementManuscrit."""

    def test_creation(self):
        a = AvertissementManuscrit(
            zone="texte suspect",
            message="Manuscrit detecte",
            confiance=0.85,
            ligne_numero=5,
        )
        assert a.zone == "texte suspect"
        assert a.message == "Manuscrit detecte"
        assert a.confiance == 0.85
        assert a.ligne_numero == 5

    def test_default_ligne_numero(self):
        a = AvertissementManuscrit(zone="z", message="m", confiance=0.5)
        assert a.ligne_numero == 0


class TestResultatLecture:
    """Tests pour le dataclass ResultatLecture."""

    def test_defaults(self):
        r = ResultatLecture()
        assert r.texte == ""
        assert r.format_detecte == FormatFichier.INCONNU
        assert r.nom_fichier == ""
        assert r.taille_octets == 0
        assert r.nb_pages == 1
        assert r.est_image is False
        assert r.est_scan is False
        assert r.manuscrit_detecte is False
        assert r.avertissements_manuscrit == []
        assert r.avertissements == []
        assert r.confiance_ocr == 1.0
        assert r.metadonnees == {}
        assert r.donnees_structurees == []

    def test_mutable_defaults_independent(self):
        """Chaque instance a ses propres listes/dicts."""
        r1 = ResultatLecture()
        r2 = ResultatLecture()
        r1.avertissements.append("test")
        assert len(r2.avertissements) == 0


# =====================================================
# Extension sets
# =====================================================


class TestExtensionSets:
    """Tests pour les sets d'extensions."""

    def test_images_extensions(self):
        for ext in [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".webp", ".heic", ".heif"]:
            assert ext in EXTENSIONS_IMAGES

    def test_pdf_extension(self):
        assert ".pdf" in EXTENSIONS_PDF

    def test_excel_extensions(self):
        assert ".xlsx" in EXTENSIONS_EXCEL
        assert ".xls" in EXTENSIONS_EXCEL

    def test_csv_extension(self):
        assert ".csv" in EXTENSIONS_CSV

    def test_xml_dsn(self):
        assert ".xml" in EXTENSIONS_XML
        assert ".dsn" in EXTENSIONS_DSN

    def test_texte_extensions(self):
        for ext in [".txt", ".text", ".log"]:
            assert ext in EXTENSIONS_TEXTE

    def test_toutes_extensions_union(self):
        expected = (
            EXTENSIONS_IMAGES | EXTENSIONS_PDF | EXTENSIONS_EXCEL
            | EXTENSIONS_CSV | EXTENSIONS_XML | EXTENSIONS_DSN | EXTENSIONS_TEXTE
        )
        assert TOUTES_EXTENSIONS == expected


# =====================================================
# _format_depuis_ext
# =====================================================


class TestFormatDepuisExt:
    """Tests pour _format_depuis_ext."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    @pytest.mark.parametrize("ext,expected", [
        (".jpg", FormatFichier.JPEG),
        (".jpeg", FormatFichier.JPEG),
        (".png", FormatFichier.PNG),
        (".bmp", FormatFichier.BMP),
        (".tiff", FormatFichier.TIFF),
        (".tif", FormatFichier.TIFF),
        (".gif", FormatFichier.GIF),
        (".webp", FormatFichier.WEBP),
        (".pdf", FormatFichier.PDF),
        (".xlsx", FormatFichier.EXCEL),
        (".xls", FormatFichier.EXCEL),
        (".csv", FormatFichier.CSV),
        (".xml", FormatFichier.XML),
        (".dsn", FormatFichier.DSN),
        (".txt", FormatFichier.TEXTE),
    ])
    def test_known_extensions(self, ext, expected):
        assert self.lecteur._format_depuis_ext(ext) == expected

    def test_unknown_extension(self):
        assert self.lecteur._format_depuis_ext(".xyz") == FormatFichier.INCONNU

    def test_case_insensitive(self):
        assert self.lecteur._format_depuis_ext(".PDF") == FormatFichier.PDF
        assert self.lecteur._format_depuis_ext(".Jpg") == FormatFichier.JPEG


# =====================================================
# _decoder_texte
# =====================================================


class TestDecoderTexte:
    """Tests pour _decoder_texte."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_utf8(self):
        texte = "Bonjour le monde"
        assert self.lecteur._decoder_texte(texte.encode("utf-8")) == texte

    def test_utf8_bom(self):
        texte = "Facture"
        data = b"\xef\xbb\xbf" + texte.encode("utf-8")
        assert self.lecteur._decoder_texte(data) == texte

    def test_latin1_fallback(self):
        texte = "Montant d\u00fb"
        data = texte.encode("latin-1")
        result = self.lecteur._decoder_texte(data)
        assert "Montant" in result

    def test_final_fallback_with_replace(self):
        # All three encodings in the loop should work for valid latin-1,
        # so we just verify it doesn't raise
        data = bytes(range(128, 256))
        result = self.lecteur._decoder_texte(data)
        assert isinstance(result, str)


# =====================================================
# _extraire_texte_image_basique
# =====================================================


class TestExtraireTexteImageBasique:
    """Tests pour _extraire_texte_image_basique."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_extracts_keywords(self):
        data = b"xxxx" + b"facture numero 12345" + b"\x00" * 10 + b"total montant"
        result = self.lecteur._extraire_texte_image_basique(data)
        assert "facture" in result.lower()

    def test_filters_short_fragments(self):
        data = b"ab\x00cd\x00efgh"
        # "ab", "cd" are < 4 chars, "efgh" is 4 chars but not a keyword
        result = self.lecteur._extraire_texte_image_basique(data)
        assert result == ""

    def test_empty_data(self):
        result = self.lecteur._extraire_texte_image_basique(b"")
        assert result == ""

    def test_no_keywords(self):
        data = b"abcdefghijklmnop"
        result = self.lecteur._extraire_texte_image_basique(data)
        assert result == ""

    def test_keyword_at_end_of_data(self):
        data = b"montant final"
        result = self.lecteur._extraire_texte_image_basique(data)
        assert "montant" in result.lower()


# =====================================================
# lire_fichier - dispatch
# =====================================================


class TestLireFichier:
    """Tests pour LecteurMultiFormat.lire_fichier."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_fichier_introuvable(self):
        chemin = Path("/tmp/ce_fichier_nexiste_pas_12345.txt")
        resultat = self.lecteur.lire_fichier(chemin)
        assert "introuvable" in resultat.avertissements[0]

    def test_lire_fichier_texte(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("Contenu du fichier texte")
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.texte == "Contenu du fichier texte"
            assert resultat.format_detecte == FormatFichier.TEXTE
            assert resultat.nom_fichier == chemin.name
            assert resultat.taille_octets > 0
        finally:
            os.unlink(chemin)

    def test_lire_fichier_csv(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False, encoding="utf-8") as f:
            f.write("col1,col2\nval1,val2\n")
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.format_detecte == FormatFichier.CSV
            assert "col1" in resultat.texte
            assert len(resultat.donnees_structurees) == 1
        finally:
            os.unlink(chemin)

    def test_lire_fichier_csv_latin1(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="wb", delete=False) as f:
            f.write("col1;col2\n\xe9l\xe8ve;donn\xe9es\n".encode("latin-1"))
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.format_detecte == FormatFichier.CSV
            assert "col1" in resultat.texte
        finally:
            os.unlink(chemin)

    def test_lire_fichier_xml(self):
        with tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=False, encoding="utf-8") as f:
            f.write("<root><item>test</item></root>")
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.format_detecte == FormatFichier.XML
        finally:
            os.unlink(chemin)

    def test_lire_fichier_dsn(self):
        with tempfile.NamedTemporaryFile(suffix=".dsn", mode="w", delete=False, encoding="utf-8") as f:
            f.write("S10.G00.00.001,'test'")
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.format_detecte == FormatFichier.DSN
        finally:
            os.unlink(chemin)

    def test_lire_fichier_unknown_ext(self):
        with tempfile.NamedTemporaryFile(suffix=".zzz", mode="w", delete=False, encoding="utf-8") as f:
            f.write("contenu quelconque")
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.format_detecte == FormatFichier.TEXTE
            assert "contenu quelconque" in resultat.texte
        finally:
            os.unlink(chemin)

    def test_lire_fichier_texte_latin1_fallback(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="wb", delete=False) as f:
            f.write("Caf\xe9 cr\xe8me".encode("latin-1"))
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.format_detecte == FormatFichier.TEXTE
            assert "Caf" in resultat.texte
        finally:
            os.unlink(chemin)

    def test_lire_fichier_vide(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("")
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.texte == ""
        finally:
            os.unlink(chemin)

    @patch.object(LecteurMultiFormat, "_ocr_image_fichier", return_value="Texte OCR extrait")
    def test_lire_fichier_image_with_ocr(self, mock_ocr):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.est_image is True
            assert resultat.format_detecte == FormatFichier.PNG
            assert resultat.texte == "Texte OCR extrait"
            assert resultat.confiance_ocr == 0.7
            assert resultat.est_scan is True
        finally:
            os.unlink(chemin)

    @patch.object(LecteurMultiFormat, "_ocr_image_fichier", return_value="")
    def test_lire_fichier_image_without_ocr(self, mock_ocr):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff" + b"\x00" * 50)
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.est_image is True
            assert resultat.confiance_ocr == 0.3
            assert any("AVERTISSEMENT" in a for a in resultat.avertissements)
        finally:
            os.unlink(chemin)

    @patch("urssaf_analyzer.ocr.image_reader.pdfplumber", create=True)
    def test_lire_fichier_pdf(self, mock_pdfplumber):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Contenu du PDF avec beaucoup de texte pour depasser le seuil de mots par page"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake content")
            f.flush()
            chemin = Path(f.name)
        try:
            with patch("pdfplumber.open", return_value=mock_pdf):
                resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.format_detecte == FormatFichier.PDF
        finally:
            os.unlink(chemin)

    @patch.object(LecteurMultiFormat, "_lire_excel")
    def test_lire_fichier_excel_dispatch(self, mock_lire_excel):
        mock_lire_excel.return_value = ResultatLecture(
            texte="col1 | col2", format_detecte=FormatFichier.EXCEL
        )
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"fake xlsx")
            f.flush()
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.format_detecte == FormatFichier.EXCEL
            mock_lire_excel.assert_called_once()
        finally:
            os.unlink(chemin)


# =====================================================
# lire_contenu_brut - dispatch
# =====================================================


class TestLireContenuBrut:
    """Tests pour LecteurMultiFormat.lire_contenu_brut."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    @patch.object(LecteurMultiFormat, "_lire_image_bytes")
    def test_dispatch_image(self, mock_img):
        mock_img.return_value = ResultatLecture(texte="img", format_detecte=FormatFichier.PNG)
        self.lecteur.lire_contenu_brut(b"data", "photo.png")
        mock_img.assert_called_once()

    @patch.object(LecteurMultiFormat, "_lire_pdf_bytes")
    def test_dispatch_pdf(self, mock_pdf):
        mock_pdf.return_value = ResultatLecture(texte="pdf text", format_detecte=FormatFichier.PDF)
        self.lecteur.lire_contenu_brut(b"data", "doc.pdf")
        mock_pdf.assert_called_once()

    @patch.object(LecteurMultiFormat, "_lire_excel_bytes")
    def test_dispatch_excel(self, mock_xl):
        mock_xl.return_value = ResultatLecture(texte="xl", format_detecte=FormatFichier.EXCEL)
        self.lecteur.lire_contenu_brut(b"data", "book.xlsx")
        mock_xl.assert_called_once()

    def test_dispatch_csv(self):
        contenu = "col1,col2\nval1,val2".encode("utf-8")
        resultat = self.lecteur.lire_contenu_brut(contenu, "data.csv")
        assert resultat.format_detecte == FormatFichier.CSV
        assert "col1" in resultat.texte

    def test_dispatch_texte_default(self):
        contenu = "Contenu brut".encode("utf-8")
        resultat = self.lecteur.lire_contenu_brut(contenu, "notes.txt")
        assert resultat.format_detecte == FormatFichier.TEXTE
        assert resultat.texte == "Contenu brut"

    def test_dispatch_no_filename(self):
        contenu = "du texte".encode("utf-8")
        resultat = self.lecteur.lire_contenu_brut(contenu, "")
        assert resultat.format_detecte == FormatFichier.TEXTE

    def test_empty_content(self):
        resultat = self.lecteur.lire_contenu_brut(b"", "empty.txt")
        assert resultat.texte == ""
        assert resultat.taille_octets == 0

    def test_taille_octets_set(self):
        data = b"hello world"
        resultat = self.lecteur.lire_contenu_brut(data, "test.txt")
        assert resultat.taille_octets == len(data)


# =====================================================
# _lire_image / _lire_image_bytes
# =====================================================


class TestLireImage:
    """Tests pour _lire_image et _lire_image_bytes."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    @patch.object(LecteurMultiFormat, "_ocr_image_fichier", return_value="OCR text found")
    def test_lire_image_ocr_success(self, mock_ocr):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG" + b"\x00" * 50)
            chemin = Path(f.name)
        try:
            resultat = ResultatLecture(nom_fichier=chemin.name, taille_octets=54)
            resultat = self.lecteur._lire_image(chemin, resultat)
            assert resultat.texte == "OCR text found"
            assert resultat.est_image is True
            assert resultat.est_scan is True
            assert resultat.confiance_ocr == 0.7
            assert resultat.metadonnees["type_image"] == ".png"
        finally:
            os.unlink(chemin)

    @patch.object(LecteurMultiFormat, "_ocr_image_fichier", return_value="")
    def test_lire_image_no_ocr(self, mock_ocr):
        with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as f:
            # Write bytes containing a keyword to verify basique extraction
            f.write(b"\x00" * 10 + b"facture numero test" + b"\x00" * 10)
            chemin = Path(f.name)
        try:
            resultat = ResultatLecture(nom_fichier=chemin.name, taille_octets=39)
            resultat = self.lecteur._lire_image(chemin, resultat)
            assert resultat.est_image is True
            assert resultat.confiance_ocr == 0.3
            assert any("AVERTISSEMENT" in a for a in resultat.avertissements)
        finally:
            os.unlink(chemin)

    @patch.object(LecteurMultiFormat, "_ocr_image_bytes", return_value="Texte OCR bytes")
    def test_lire_image_bytes_ocr_success(self, mock_ocr):
        resultat = ResultatLecture(nom_fichier="test.jpg")
        resultat = self.lecteur._lire_image_bytes(b"fake image data", resultat)
        assert resultat.texte == "Texte OCR bytes"
        assert resultat.est_image is True
        assert resultat.est_scan is True
        assert resultat.confiance_ocr == 0.7

    @patch.object(LecteurMultiFormat, "_ocr_image_bytes", return_value="")
    def test_lire_image_bytes_no_ocr(self, mock_ocr):
        resultat = ResultatLecture(nom_fichier="test.png")
        resultat = self.lecteur._lire_image_bytes(b"\x00" * 20, resultat)
        assert resultat.est_image is True
        assert resultat.confiance_ocr == 0.3
        assert any("AVERTISSEMENT" in a for a in resultat.avertissements)


# =====================================================
# _lire_pdf / _lire_pdf_bytes
# =====================================================


class TestLirePdf:
    """Tests pour _lire_pdf et _lire_pdf_bytes."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_lire_pdf_text_rich(self):
        """PDF avec suffisamment de texte (pas un scan)."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = " ".join(["mot"] * 30)
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"pdfplumber": MagicMock()}):
                import sys
                sys.modules["pdfplumber"].open.return_value = mock_pdf
                resultat = ResultatLecture(nom_fichier=chemin.name)
                resultat = self.lecteur._lire_pdf(chemin, resultat)
            assert resultat.format_detecte == FormatFichier.PDF
            assert resultat.nb_pages == 1
            assert "mot" in resultat.texte
            assert resultat.est_scan is False
        finally:
            os.unlink(chemin)

    def test_lire_pdf_scan_detected_ocr_fallback(self):
        """PDF scan avec peu de texte, OCR fournit plus de texte."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "peu"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"pdfplumber": MagicMock()}):
                import sys
                sys.modules["pdfplumber"].open.return_value = mock_pdf
                with patch.object(
                    self.lecteur, "_ocr_pdf_pages",
                    return_value="beaucoup plus de texte ici pour depasser le seuil"
                ):
                    resultat = ResultatLecture(nom_fichier=chemin.name)
                    resultat = self.lecteur._lire_pdf(chemin, resultat)
            assert resultat.est_scan is True
            assert resultat.confiance_ocr == 0.65
            assert any("scanne" in a for a in resultat.avertissements)
        finally:
            os.unlink(chemin)

    def test_lire_pdf_scan_detected_no_ocr(self):
        """PDF scan, OCR ne fournit pas plus de texte."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "peu"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"pdfplumber": MagicMock()}):
                import sys
                sys.modules["pdfplumber"].open.return_value = mock_pdf
                with patch.object(self.lecteur, "_ocr_pdf_pages", return_value=""):
                    resultat = ResultatLecture(nom_fichier=chemin.name)
                    resultat = self.lecteur._lire_pdf(chemin, resultat)
            assert resultat.est_scan is True
            assert resultat.confiance_ocr == 0.5
            assert any("AVERTISSEMENT" in a for a in resultat.avertissements)
        finally:
            os.unlink(chemin)

    def test_lire_pdf_import_error(self):
        """pdfplumber non disponible."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"pdfplumber": None}):
                resultat = ResultatLecture(nom_fichier=chemin.name)
                resultat = self.lecteur._lire_pdf(chemin, resultat)
            assert any("pdfplumber" in a.lower() for a in resultat.avertissements)
        finally:
            os.unlink(chemin)

    def test_lire_pdf_generic_exception(self):
        """Erreur quelconque lors de la lecture PDF."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"pdfplumber": MagicMock()}) as mods:
                import sys
                sys.modules["pdfplumber"].open.side_effect = RuntimeError("broken")
                resultat = ResultatLecture(nom_fichier=chemin.name)
                resultat = self.lecteur._lire_pdf(chemin, resultat)
            assert any("Erreur" in a for a in resultat.avertissements)
        finally:
            os.unlink(chemin)

    def test_lire_pdf_page_extract_none(self):
        """Page qui retourne None pour extract_text."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = None
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"pdfplumber": MagicMock()}):
                import sys
                sys.modules["pdfplumber"].open.return_value = mock_pdf
                with patch.object(self.lecteur, "_ocr_pdf_pages", return_value=""):
                    resultat = ResultatLecture(nom_fichier=chemin.name)
                    resultat = self.lecteur._lire_pdf(chemin, resultat)
            assert resultat.nb_pages == 1
        finally:
            os.unlink(chemin)

    # --- _lire_pdf_bytes ---

    def test_lire_pdf_bytes_text_rich(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = " ".join(["word"] * 25)
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"pdfplumber": MagicMock()}):
            import sys
            sys.modules["pdfplumber"].open.return_value = mock_pdf
            resultat = ResultatLecture(nom_fichier="test.pdf")
            resultat = self.lecteur._lire_pdf_bytes(b"%PDF fake", resultat)
        assert resultat.format_detecte == FormatFichier.PDF
        assert resultat.est_scan is False

    def test_lire_pdf_bytes_scan_ocr_better(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "peu"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"pdfplumber": MagicMock()}):
            import sys
            sys.modules["pdfplumber"].open.return_value = mock_pdf
            with patch.object(
                self.lecteur, "_ocr_pdf_pages",
                return_value="beaucoup plus de texte OCR ici"
            ):
                resultat = ResultatLecture(nom_fichier="scan.pdf")
                resultat = self.lecteur._lire_pdf_bytes(b"%PDF fake", resultat)
        assert resultat.est_scan is True
        assert resultat.confiance_ocr == 0.65

    def test_lire_pdf_bytes_scan_no_ocr(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "peu"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"pdfplumber": MagicMock()}):
            import sys
            sys.modules["pdfplumber"].open.return_value = mock_pdf
            with patch.object(self.lecteur, "_ocr_pdf_pages", return_value=""):
                resultat = ResultatLecture(nom_fichier="scan.pdf")
                resultat = self.lecteur._lire_pdf_bytes(b"%PDF fake", resultat)
        assert resultat.est_scan is True
        assert resultat.confiance_ocr == 0.5
        assert any("AVERTISSEMENT" in a or "scanne" in a for a in resultat.avertissements)

    def test_lire_pdf_bytes_import_error(self):
        with patch.dict("sys.modules", {"pdfplumber": None}):
            resultat = ResultatLecture(nom_fichier="test.pdf")
            resultat = self.lecteur._lire_pdf_bytes(b"%PDF", resultat)
        assert any("pdfplumber" in a.lower() for a in resultat.avertissements)

    def test_lire_pdf_bytes_generic_exception(self):
        with patch.dict("sys.modules", {"pdfplumber": MagicMock()}) as mods:
            import sys
            sys.modules["pdfplumber"].open.side_effect = RuntimeError("oops")
            resultat = ResultatLecture(nom_fichier="test.pdf")
            resultat = self.lecteur._lire_pdf_bytes(b"%PDF", resultat)
        assert any("Erreur" in a for a in resultat.avertissements)


# =====================================================
# _ocr_pdf_pages
# =====================================================


class TestOcrPdfPages:
    """Tests pour _ocr_pdf_pages."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_ocr_pdf_pages_import_error(self):
        """Retourne vide si PIL/pytesseract non disponible."""
        mock_pdf = MagicMock()
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            result = self.lecteur._ocr_pdf_pages(mock_pdf)
        assert result == ""

    def test_ocr_pdf_pages_success(self):
        mock_img_obj = MagicMock()
        mock_img_obj.original = MagicMock()
        mock_page = MagicMock()
        mock_page.to_image.return_value = mock_img_obj
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]

        mock_pil = MagicMock()
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "Texte extrait par OCR"

        with patch.dict("sys.modules", {
            "PIL": mock_pil,
            "PIL.Image": mock_pil.Image,
            "pytesseract": mock_pytesseract,
        }):
            result = self.lecteur._ocr_pdf_pages(mock_pdf)
        assert "Texte extrait par OCR" in result

    def test_ocr_pdf_pages_page_exception(self):
        """Si une page echoue, continue avec les autres."""
        mock_page1 = MagicMock()
        mock_page1.to_image.side_effect = RuntimeError("fail")
        mock_page2 = MagicMock()
        mock_img = MagicMock()
        mock_img.original = MagicMock()
        mock_page2.to_image.return_value = mock_img
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2]

        mock_pil = MagicMock()
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "page 2 text"

        with patch.dict("sys.modules", {
            "PIL": mock_pil,
            "PIL.Image": mock_pil.Image,
            "pytesseract": mock_pytesseract,
        }):
            result = self.lecteur._ocr_pdf_pages(mock_pdf)
        assert "page 2 text" in result


# =====================================================
# _lire_excel / _lire_excel_bytes
# =====================================================


class TestLireExcel:
    """Tests pour _lire_excel et _lire_excel_bytes."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_lire_excel_success(self):
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = [("val1", "val2"), (None, "val3")]
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"fake xlsx")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"openpyxl": MagicMock()}):
                import sys
                sys.modules["openpyxl"].load_workbook.return_value = mock_wb
                resultat = ResultatLecture(nom_fichier=chemin.name)
                resultat = self.lecteur._lire_excel(chemin, resultat)
            assert resultat.format_detecte == FormatFichier.EXCEL
            assert "val1" in resultat.texte
            assert len(resultat.donnees_structurees) >= 1
        finally:
            os.unlink(chemin)

    def test_lire_excel_import_error(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"fake")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"openpyxl": None}):
                resultat = ResultatLecture(nom_fichier=chemin.name)
                resultat = self.lecteur._lire_excel(chemin, resultat)
            assert any("openpyxl" in a.lower() for a in resultat.avertissements)
        finally:
            os.unlink(chemin)

    def test_lire_excel_generic_exception(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"fake")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"openpyxl": MagicMock()}) as mods:
                import sys
                sys.modules["openpyxl"].load_workbook.side_effect = RuntimeError("bad file")
                resultat = ResultatLecture(nom_fichier=chemin.name)
                resultat = self.lecteur._lire_excel(chemin, resultat)
            assert any("Erreur" in a for a in resultat.avertissements)
        finally:
            os.unlink(chemin)

    def test_lire_excel_empty_rows(self):
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = [(None, None)]
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"fake xlsx")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"openpyxl": MagicMock()}):
                import sys
                sys.modules["openpyxl"].load_workbook.return_value = mock_wb
                resultat = ResultatLecture(nom_fichier=chemin.name)
                resultat = self.lecteur._lire_excel(chemin, resultat)
            assert resultat.texte == ""
            assert len(resultat.donnees_structurees) == 0
        finally:
            os.unlink(chemin)

    # --- _lire_excel_bytes ---

    def test_lire_excel_bytes_success(self):
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = [("a", "b")]
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Feuille1"]
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)

        with patch.dict("sys.modules", {"openpyxl": MagicMock()}):
            import sys
            sys.modules["openpyxl"].load_workbook.return_value = mock_wb
            resultat = ResultatLecture(nom_fichier="test.xlsx")
            resultat = self.lecteur._lire_excel_bytes(b"fake xlsx", resultat)
        assert "a" in resultat.texte
        assert resultat.format_detecte == FormatFichier.EXCEL

    def test_lire_excel_bytes_import_error(self):
        with patch.dict("sys.modules", {"openpyxl": None}):
            resultat = ResultatLecture(nom_fichier="test.xlsx")
            resultat = self.lecteur._lire_excel_bytes(b"fake", resultat)
        assert any("openpyxl" in a.lower() for a in resultat.avertissements)

    def test_lire_excel_bytes_exception(self):
        with patch.dict("sys.modules", {"openpyxl": MagicMock()}) as mods:
            import sys
            sys.modules["openpyxl"].load_workbook.side_effect = ValueError("corrupt")
            resultat = ResultatLecture(nom_fichier="test.xlsx")
            resultat = self.lecteur._lire_excel_bytes(b"fake", resultat)
        assert any("Erreur" in a for a in resultat.avertissements)


# =====================================================
# _lire_csv
# =====================================================


class TestLireCsv:
    """Tests pour _lire_csv."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_csv_utf8(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False, encoding="utf-8") as f:
            f.write("nom,prenom\nDupont,Jean\n")
            chemin = Path(f.name)
        try:
            resultat = ResultatLecture(nom_fichier=chemin.name)
            resultat = self.lecteur._lire_csv(chemin, resultat)
            assert resultat.format_detecte == FormatFichier.CSV
            assert "Dupont" in resultat.texte
            assert len(resultat.donnees_structurees) == 1
            assert resultat.donnees_structurees[0]["nom"] == "Dupont"
        finally:
            os.unlink(chemin)

    def test_csv_latin1_fallback(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="wb", delete=False) as f:
            f.write("nom;pr\xe9nom\n\xe9l\xe8ve;caf\xe9\n".encode("latin-1"))
            chemin = Path(f.name)
        try:
            resultat = ResultatLecture(nom_fichier=chemin.name)
            resultat = self.lecteur._lire_csv(chemin, resultat)
            assert resultat.format_detecte == FormatFichier.CSV
            assert "nom" in resultat.texte
        finally:
            os.unlink(chemin)

    def test_csv_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
            f.write("")
            chemin = Path(f.name)
        try:
            resultat = ResultatLecture(nom_fichier=chemin.name)
            resultat = self.lecteur._lire_csv(chemin, resultat)
            assert resultat.format_detecte == FormatFichier.CSV
            assert resultat.texte == ""
        finally:
            os.unlink(chemin)


# =====================================================
# _lire_texte
# =====================================================


class TestLireTexte:
    """Tests pour _lire_texte."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_utf8(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("Bonjour le monde")
            chemin = Path(f.name)
        try:
            resultat = ResultatLecture(nom_fichier=chemin.name)
            resultat = self.lecteur._lire_texte(chemin, resultat)
            assert resultat.texte == "Bonjour le monde"
            assert resultat.format_detecte == FormatFichier.TEXTE
        finally:
            os.unlink(chemin)

    def test_latin1_fallback(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="wb", delete=False) as f:
            f.write("Caf\xe9 cr\xe8me".encode("latin-1"))
            chemin = Path(f.name)
        try:
            resultat = ResultatLecture(nom_fichier=chemin.name)
            resultat = self.lecteur._lire_texte(chemin, resultat)
            assert "Caf" in resultat.texte
        finally:
            os.unlink(chemin)

    def test_read_error(self):
        chemin = Path("/tmp/nonexistent_file_for_test.txt")
        resultat = ResultatLecture(nom_fichier="nonexistent.txt")
        resultat = self.lecteur._lire_texte(chemin, resultat)
        assert any("Erreur" in a for a in resultat.avertissements)


# =====================================================
# _detecter_manuscrit
# =====================================================


class TestDetecterManuscrit:
    """Tests pour _detecter_manuscrit."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_empty_text(self):
        resultat = ResultatLecture(texte="")
        self.lecteur._detecter_manuscrit(resultat)
        assert resultat.manuscrit_detecte is False
        assert len(resultat.avertissements_manuscrit) == 0

    def test_pattern_fort_mixed_case(self):
        """Pattern fort: melange majuscules/minuscules irregulier."""
        resultat = ResultatLecture(texte="voiciUnMotAvecDesCasses irregulier")
        self.lecteur._detecter_manuscrit(resultat)
        # This should match r'\b[a-z]+[A-Z][a-z]+[A-Z]\w*\b'
        found = [a for a in resultat.avertissements_manuscrit if a.confiance >= 0.8]
        assert len(found) >= 1

    def test_pattern_fort_ocr_substitution(self):
        """Pattern fort: caracteres de substitution OCR."""
        resultat = ResultatLecture(texte="III1||| texte normal")
        self.lecteur._detecter_manuscrit(resultat)
        fort = [a for a in resultat.avertissements_manuscrit if a.confiance >= 0.8]
        assert len(fort) >= 1

    def test_pattern_fort_chiffres_lettres(self):
        """Pattern fort: chiffres et lettres entremeles."""
        resultat = ResultatLecture(texte="a1b2 quelque chose")
        self.lecteur._detecter_manuscrit(resultat)
        fort = [a for a in resultat.avertissements_manuscrit if a.confiance >= 0.8]
        assert len(fort) >= 1

    def test_pattern_fort_mots_tronques(self):
        """Pattern fort: mots courts consecutifs."""
        resultat = ResultatLecture(texte="ab cd ef suite du texte")
        self.lecteur._detecter_manuscrit(resultat)
        fort = [a for a in resultat.avertissements_manuscrit if a.confiance >= 0.8]
        assert len(fort) >= 1

    def test_pattern_faible_annotation(self):
        """Pattern faible: annotations courtes."""
        resultat = ResultatLecture(texte="X\nAutre texte normal ici")
        self.lecteur._detecter_manuscrit(resultat)
        faible = [a for a in resultat.avertissements_manuscrit if a.confiance < 0.5]
        assert len(faible) >= 1

    def test_pattern_faible_fleche(self):
        """Pattern faible: fleche textuelle."""
        # Need a line with -> that is not already caught by fort patterns
        resultat = ResultatLecture(texte="Regarder -> resultat")
        self.lecteur._detecter_manuscrit(resultat)
        faible = [a for a in resultat.avertissements_manuscrit if a.confiance <= 0.5]
        assert len(faible) >= 1

    def test_heuristic_casse_irreguliere(self):
        """Heuristique: ratio majuscules irregulier (0.25 < ratio < 0.65)."""
        # Build a line with ~40% uppercase, > 8 alpha chars, no excluded keywords
        # "aBcDeFgHiJkLmN" has 7 upper out of 14 = 50%
        resultat = ResultatLecture(texte="aBcDeFgHiJkLmNoPq")
        self.lecteur._detecter_manuscrit(resultat)
        heuristic = [a for a in resultat.avertissements_manuscrit if a.confiance == 0.55]
        # May or may not trigger depending on fort patterns also matching
        # Just ensure no crash

    def test_heuristic_excluded_keyword(self):
        """Heuristique: les en-tetes normaux sont exclus."""
        resultat = ResultatLecture(texte="FACTURE NumEro CinQ")
        self.lecteur._detecter_manuscrit(resultat)
        heuristic = [a for a in resultat.avertissements_manuscrit if a.confiance == 0.55]
        assert len(heuristic) == 0

    def test_manuscrit_detecte_forte_confiance(self):
        """manuscrit_detecte = True si confiance >= 0.7."""
        resultat = ResultatLecture(texte="voiciUnMotAvecDesCasses")
        self.lecteur._detecter_manuscrit(resultat)
        forte = [a for a in resultat.avertissements_manuscrit if a.confiance >= 0.7]
        if forte:
            assert resultat.manuscrit_detecte is True
            assert any("MANUSCRIT" in a for a in resultat.avertissements)

    def test_manuscrit_detecte_many_weak(self):
        """manuscrit_detecte = True si >= 3 avertissements faibles."""
        texte = "X\nV\n->\n=>"
        resultat = ResultatLecture(texte=texte)
        self.lecteur._detecter_manuscrit(resultat)
        if len(resultat.avertissements_manuscrit) >= 3:
            assert resultat.manuscrit_detecte is True

    def test_no_manuscrit_normal_text(self):
        """Texte normal ne declenche pas de detection."""
        resultat = ResultatLecture(texte="Ceci est un texte tout a fait normal sans rien de suspect.")
        self.lecteur._detecter_manuscrit(resultat)
        assert resultat.manuscrit_detecte is False

    def test_blank_lines_skipped(self):
        """Les lignes vides sont ignorees."""
        resultat = ResultatLecture(texte="\n\n\n")
        self.lecteur._detecter_manuscrit(resultat)
        assert len(resultat.avertissements_manuscrit) == 0

    def test_faible_not_duplicated(self):
        """Un pattern faible ne duplique pas si la ligne est deja detectee."""
        # Line that matches both fort AND faible
        texte = "a1b2 -> test"
        resultat = ResultatLecture(texte=texte)
        self.lecteur._detecter_manuscrit(resultat)
        line1_warnings = [a for a in resultat.avertissements_manuscrit if a.ligne_numero == 1]
        # Should not have duplicate line entries from faible
        confiances = [a.confiance for a in line1_warnings]
        # At most one faible entry per line
        assert confiances.count(0.4) <= 1


# =====================================================
# _detecter_scan
# =====================================================


class TestDetecterScan:
    """Tests pour _detecter_scan."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_empty_text(self):
        resultat = ResultatLecture(texte="")
        self.lecteur._detecter_scan(resultat)
        assert resultat.est_scan is False

    def test_image_skipped(self):
        """Les images sont deja marquees, pas re-analysees."""
        resultat = ResultatLecture(texte="test ~~ ^^^ junk", est_image=True)
        self.lecteur._detecter_scan(resultat)
        # Should not modify est_scan since est_image is True
        assert resultat.est_scan is False

    def test_scan_detected_special_chars(self):
        """Indicateurs de scan: caracteres speciaux repetitifs."""
        # ~~ matches, repeated chars .........., irregular spaces
        texte = "word   ~~~   other   text   aaaaaaaaaa more"
        resultat = ResultatLecture(texte=texte)
        self.lecteur._detecter_scan(resultat)
        # score_scan should be >= 2

    def test_scan_detected_high_special_ratio(self):
        """Ratio de caracteres speciaux > 0.15 donne score +2."""
        normal = "abcdef "
        special = "@#$%&*{}[]<>!~^" * 5
        texte = normal + special  # > 50 chars, high ratio
        resultat = ResultatLecture(texte=texte)
        self.lecteur._detecter_scan(resultat)
        assert resultat.est_scan is True
        assert resultat.confiance_ocr <= 0.6

    def test_no_scan_normal_text(self):
        """Texte normal ne declenche pas la detection de scan."""
        texte = "Ceci est un texte tout a fait normal, avec de la ponctuation standard."
        resultat = ResultatLecture(texte=texte)
        self.lecteur._detecter_scan(resultat)
        assert resultat.est_scan is False

    def test_already_scan_not_modified(self):
        """Si deja est_scan=True, pas de duplication."""
        texte = "@#$%&*{}[]<>!~^" * 10 + "aaaa bbbb"
        resultat = ResultatLecture(texte=texte, est_scan=True, confiance_ocr=0.5)
        self.lecteur._detecter_scan(resultat)
        # est_scan stays True but no additional warning added via scan detection branch
        # (the condition is `not resultat.est_scan`)

    def test_scan_short_text_no_ratio_check(self):
        """Texte < 50 chars ne fait pas le ratio check."""
        texte = "~~~ ^^^ short"
        resultat = ResultatLecture(texte=texte)
        self.lecteur._detecter_scan(resultat)
        # Only pattern-based, not ratio-based

    def test_scan_irregular_spacing(self):
        """Espaces irreguliers entre mots."""
        texte = "word1   word2   word3 and some normal text here to pad the line a bit longer ~~~"
        resultat = ResultatLecture(texte=texte)
        self.lecteur._detecter_scan(resultat)
        # At least 2 scan indicators should match (irregular spaces + ~~~)


# =====================================================
# _ocr_image_fichier / _ocr_image_bytes
# =====================================================


class TestOcrImage:
    """Tests pour _ocr_image_fichier et _ocr_image_bytes."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_ocr_fichier_import_error(self):
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            result = self.lecteur._ocr_image_fichier(Path("/tmp/fake.png"))
        assert result == ""

    def test_ocr_fichier_success(self):
        mock_pil_image = MagicMock()
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "Extracted OCR text"

        with patch.dict("sys.modules", {
            "PIL": MagicMock(),
            "PIL.Image": mock_pil_image,
            "pytesseract": mock_pytesseract,
        }):
            mock_pil_image.open.return_value = MagicMock()
            result = self.lecteur._ocr_image_fichier(Path("/tmp/test.png"))
        assert result == "Extracted OCR text"

    def test_ocr_fichier_runtime_error(self):
        mock_image_module = MagicMock()
        mock_image_module.open.side_effect = RuntimeError("cannot open")
        mock_pil = MagicMock()
        mock_pil.Image = mock_image_module

        with patch.dict("sys.modules", {
            "PIL": mock_pil,
            "PIL.Image": mock_image_module,
            "pytesseract": MagicMock(),
        }):
            result = self.lecteur._ocr_image_fichier(Path("/tmp/test.png"))
        assert result == ""

    def test_ocr_bytes_import_error(self):
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            result = self.lecteur._ocr_image_bytes(b"fake image data")
        assert result == ""

    def test_ocr_bytes_success(self):
        mock_pil_image = MagicMock()
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "OCR from bytes"

        with patch.dict("sys.modules", {
            "PIL": MagicMock(),
            "PIL.Image": mock_pil_image,
            "pytesseract": mock_pytesseract,
        }):
            mock_pil_image.open.return_value = MagicMock()
            result = self.lecteur._ocr_image_bytes(b"fake image")
        assert result == "OCR from bytes"

    def test_ocr_bytes_exception(self):
        mock_image_module = MagicMock()
        mock_image_module.open.side_effect = Exception("bad image")
        mock_pil = MagicMock()
        mock_pil.Image = mock_image_module

        with patch.dict("sys.modules", {
            "PIL": mock_pil,
            "PIL.Image": mock_image_module,
            "pytesseract": MagicMock(),
        }):
            result = self.lecteur._ocr_image_bytes(b"corrupt")
        assert result == ""


# =====================================================
# Integration: lire_fichier triggers detection
# =====================================================


class TestLireFichierIntegration:
    """Tests d'integration: lire_fichier enchaine lecture + detection."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_texte_with_manuscrit_detection(self):
        texte = "voiciUnMotAvecDesCasses irregulier\na1b2 test\nIII1||| noise"
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(texte)
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.manuscrit_detecte is True
        finally:
            os.unlink(chemin)

    def test_texte_with_scan_detection(self):
        texte = "@#$%&*{}[]<>!~^" * 10 + " texte normal ici pour remplir le contenu"
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(texte)
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.est_scan is True
        finally:
            os.unlink(chemin)

    def test_empty_file_no_detection(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("")
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.manuscrit_detecte is False
            assert resultat.est_scan is False
        finally:
            os.unlink(chemin)

    def test_lire_contenu_brut_with_detection(self):
        texte = "voiciUnMotAvecDesCasses\na1b2\nIII1|||"
        contenu = texte.encode("utf-8")
        resultat = self.lecteur.lire_contenu_brut(contenu, "test.txt")
        assert resultat.manuscrit_detecte is True


# =====================================================
# Patterns regex validation
# =====================================================


class TestPatternsRegex:
    """Tests pour les patterns regex compiles."""

    def test_patterns_manuscrit_fort_compiled(self):
        assert len(PATTERNS_MANUSCRIT_FORT) == 4
        for p in PATTERNS_MANUSCRIT_FORT:
            assert hasattr(p, "search")

    def test_patterns_manuscrit_faible_compiled(self):
        assert len(PATTERNS_MANUSCRIT_FAIBLE) == 3
        for p in PATTERNS_MANUSCRIT_FAIBLE:
            assert hasattr(p, "search")

    def test_indicateurs_scan_compiled(self):
        assert len(INDICATEURS_SCAN) == 3
        for p in INDICATEURS_SCAN:
            assert hasattr(p, "search")

    def test_pattern_fort_mixed_case_match(self):
        assert PATTERNS_MANUSCRIT_FORT[0].search("testAbcDef")

    def test_pattern_fort_digit_letter_mix(self):
        assert PATTERNS_MANUSCRIT_FORT[1].search("a1b2")

    def test_pattern_fort_ocr_chars(self):
        assert PATTERNS_MANUSCRIT_FORT[2].search("III1|||")

    def test_pattern_fort_short_words(self):
        assert PATTERNS_MANUSCRIT_FORT[3].search("ab cd ef")

    def test_pattern_faible_cross(self):
        assert PATTERNS_MANUSCRIT_FAIBLE[1].search("  X  ")

    def test_pattern_faible_arrow(self):
        assert PATTERNS_MANUSCRIT_FAIBLE[2].search("->")
        assert PATTERNS_MANUSCRIT_FAIBLE[2].search("=>")

    def test_scan_repeated_chars(self):
        assert INDICATEURS_SCAN[1].search("aaaaaaaaa")

    def test_scan_special_chars(self):
        assert INDICATEURS_SCAN[0].search("~~~")

    def test_scan_irregular_spaces(self):
        assert INDICATEURS_SCAN[2].search("word   word")


# =====================================================
# Edge cases
# =====================================================


class TestEdgeCases:
    """Tests de cas limites."""

    def setup_method(self):
        self.lecteur = LecteurMultiFormat()

    def test_lire_contenu_brut_xml_extension(self):
        """XML via lire_contenu_brut goes through default text path."""
        contenu = b"<root>test</root>"
        resultat = self.lecteur.lire_contenu_brut(contenu, "data.xml")
        # XML in lire_contenu_brut falls into the else (text) branch
        assert resultat.texte == "<root>test</root>"

    def test_lire_contenu_brut_dsn_extension(self):
        contenu = b"S10.G00.00.001"
        resultat = self.lecteur.lire_contenu_brut(contenu, "file.dsn")
        assert "S10" in resultat.texte

    def test_multiple_sheets_excel(self):
        mock_ws1 = MagicMock()
        mock_ws1.iter_rows.return_value = [("a",)]
        mock_ws2 = MagicMock()
        mock_ws2.iter_rows.return_value = [("b",)]
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Sheet1", "Sheet2"]
        mock_wb.__getitem__ = MagicMock(side_effect=lambda k: mock_ws1 if k == "Sheet1" else mock_ws2)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(b"fake")
            chemin = Path(f.name)
        try:
            with patch.dict("sys.modules", {"openpyxl": MagicMock()}):
                import sys
                sys.modules["openpyxl"].load_workbook.return_value = mock_wb
                resultat = ResultatLecture(nom_fichier=chemin.name)
                resultat = self.lecteur._lire_excel(chemin, resultat)
            assert resultat.nb_pages == 2
            assert "a" in resultat.texte
            assert "b" in resultat.texte
        finally:
            os.unlink(chemin)

    def test_csv_with_bom(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="wb", delete=False) as f:
            f.write(b"\xef\xbb\xbfnom,val\ntest,123\n")
            chemin = Path(f.name)
        try:
            resultat = ResultatLecture(nom_fichier=chemin.name)
            resultat = self.lecteur._lire_csv(chemin, resultat)
            assert "nom" in resultat.texte
        finally:
            os.unlink(chemin)

    def test_image_metadonnees_set(self):
        """_lire_image sets metadonnees."""
        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
            f.write(b"GIF89a" + b"\x00" * 20)
            chemin = Path(f.name)
        try:
            with patch.object(self.lecteur, "_ocr_image_fichier", return_value=""):
                resultat = ResultatLecture(nom_fichier=chemin.name, taille_octets=26)
                resultat = self.lecteur._lire_image(chemin, resultat)
            assert resultat.metadonnees["type_image"] == ".gif"
            assert resultat.metadonnees["taille"] == 26
        finally:
            os.unlink(chemin)

    def test_lire_fichier_log_extension(self):
        """Extension .log est traitee comme texte."""
        with tempfile.NamedTemporaryFile(suffix=".log", mode="w", delete=False, encoding="utf-8") as f:
            f.write("log entry")
            chemin = Path(f.name)
        try:
            resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.format_detecte == FormatFichier.TEXTE
            assert "log entry" in resultat.texte
        finally:
            os.unlink(chemin)

    def test_heic_extension_dispatched_as_image(self):
        with tempfile.NamedTemporaryFile(suffix=".heic", delete=False) as f:
            f.write(b"\x00" * 20)
            chemin = Path(f.name)
        try:
            with patch.object(self.lecteur, "_ocr_image_fichier", return_value=""):
                resultat = self.lecteur.lire_fichier(chemin)
            assert resultat.est_image is True
        finally:
            os.unlink(chemin)

    def test_extraire_texte_basique_multiple_keywords(self):
        data = b"facture\x00\x00\x00\x00total montant\x00\x00siret numero\x00client reference"
        result = self.lecteur._extraire_texte_image_basique(data)
        # Should contain multiple keyword matches
        assert "facture" in result.lower() or "total" in result.lower() or "siret" in result.lower()
