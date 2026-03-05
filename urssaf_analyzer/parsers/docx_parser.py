"""Parseur pour les fichiers Word (.docx et .doc).

Extrait le texte du document Word puis applique les memes regles
d'extraction que le PDF parser (regex pour bulletins, factures, contrats, etc.).

Strategies d'extraction :
1. .docx : python-docx (natif) ou fallback ZIP/XML
2. .doc (ancien format binaire) : antiword ou LibreOffice en mode headless
   Sur OVH Cloud, installer : apt-get install -y antiword
   Fallback : libreoffice --headless --convert-to docx
"""

import re
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.parsers.pdf_parser import PDFParser
from urssaf_analyzer.models.documents import Document, Declaration

logger = logging.getLogger(__name__)

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

# Detecter les outils disponibles pour le format .doc (ancien Word binaire)
HAS_ANTIWORD = shutil.which("antiword") is not None
HAS_LIBREOFFICE = shutil.which("libreoffice") is not None or shutil.which("soffice") is not None


def _extraire_texte_docx_zip(chemin: Path) -> str:
    """Extraction basique du texte depuis un .docx via ZIP/XML (sans python-docx)."""
    import zipfile
    try:
        with zipfile.ZipFile(chemin, "r") as z:
            if "word/document.xml" not in z.namelist():
                return ""
            xml_content = z.read("word/document.xml").decode("utf-8", errors="replace")
            # Strip XML tags to get plain text
            texte = re.sub(r"<[^>]+>", " ", xml_content)
            texte = re.sub(r"\s+", " ", texte).strip()
            return texte
    except Exception:
        return ""


def _convertir_doc_vers_texte(chemin: Path) -> str:
    """Convertit un fichier .doc (ancien format binaire) en texte.

    Essaie dans l'ordre :
    1. antiword (rapide, leger)
    2. LibreOffice headless (conversion vers .docx puis extraction)
    """
    # Methode 1: antiword
    if HAS_ANTIWORD:
        try:
            result = subprocess.run(
                ["antiword", "-w", "0", str(chemin)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.info("Extraction .doc via antiword reussie: %s", chemin.name)
                return result.stdout
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("antiword a echoue pour %s: %s", chemin.name, e)

    # Methode 2: LibreOffice headless -> convertir en .docx
    if HAS_LIBREOFFICE:
        try:
            with tempfile.TemporaryDirectory() as td:
                lo_cmd = "libreoffice" if shutil.which("libreoffice") else "soffice"
                result = subprocess.run(
                    [lo_cmd, "--headless", "--convert-to", "docx",
                     "--outdir", td, str(chemin)],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    converted = Path(td) / (chemin.stem + ".docx")
                    if converted.exists():
                        if HAS_DOCX:
                            doc = docx.Document(str(converted))
                            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                            texte = "\n".join(paragraphs)
                        else:
                            texte = _extraire_texte_docx_zip(converted)
                        if texte.strip():
                            logger.info("Extraction .doc via LibreOffice reussie: %s", chemin.name)
                            return texte
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("LibreOffice a echoue pour %s: %s", chemin.name, e)

    return ""


def _extraire_tableaux_doc(chemin: Path) -> list:
    """Tente d'extraire les tableaux d'un .doc en convertissant d'abord en .docx."""
    if not HAS_LIBREOFFICE or not HAS_DOCX:
        return []
    try:
        with tempfile.TemporaryDirectory() as td:
            lo_cmd = "libreoffice" if shutil.which("libreoffice") else "soffice"
            result = subprocess.run(
                [lo_cmd, "--headless", "--convert-to", "docx",
                 "--outdir", td, str(chemin)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                converted = Path(td) / (chemin.stem + ".docx")
                if converted.exists():
                    doc = docx.Document(str(converted))
                    tableaux = []
                    for table in doc.tables:
                        rows = []
                        for row in table.rows:
                            cells = [cell.text.strip() for cell in row.cells]
                            rows.append(cells)
                        if rows:
                            tableaux.append(rows)
                    return tableaux
    except Exception:
        pass
    return []


class DocxParser(BaseParser):
    """Parse les fichiers .docx et .doc en extrayant le texte puis en reutilisant le PDF parser."""

    def __init__(self):
        self._pdf_parser = PDFParser()

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() in (".docx", ".doc")

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        ext = chemin.suffix.lower()
        try:
            texte = self._extraire_texte(chemin)
            meta = {
                "format": "doc" if ext == ".doc" else "docx",
                "nb_caracteres": len(texte),
                "python_docx_disponible": HAS_DOCX,
            }
            if ext == ".doc":
                meta["antiword_disponible"] = HAS_ANTIWORD
                meta["libreoffice_disponible"] = HAS_LIBREOFFICE
                if not HAS_ANTIWORD and not HAS_LIBREOFFICE:
                    meta["avertissement"] = (
                        "Aucun outil d'extraction .doc disponible. "
                        "Installer antiword (apt-get install antiword) ou LibreOffice."
                    )
            if HAS_DOCX and ext == ".docx":
                try:
                    doc = docx.Document(str(chemin))
                    meta["nb_paragraphes"] = len(doc.paragraphs)
                    meta["nb_tableaux"] = len(doc.tables)
                except Exception:
                    pass
            return meta
        except Exception as e:
            return {"format": ext.lstrip("."), "erreur": str(e)}

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        texte = self._extraire_texte(chemin)
        tableaux = self._extraire_tableaux(chemin)
        if not texte.strip():
            # Return empty declaration with warning for .doc without extraction tools
            if chemin.suffix.lower() == ".doc" and not HAS_ANTIWORD and not HAS_LIBREOFFICE:
                from urssaf_analyzer.models.documents import Employeur
                decl = Declaration(
                    type_declaration="document_non_extractible",
                    reference=document.nom_fichier,
                    employeur=Employeur(source_document_id=document.id),
                    source_document_id=document.id,
                    metadata={
                        "type_document": "doc_ancien_format",
                        "avertissement": (
                            "Le format .doc (ancien Word binaire) necessite antiword ou LibreOffice "
                            "pour l'extraction de texte. Veuillez convertir le fichier en .docx ou "
                            "installer antiword sur le serveur (apt-get install antiword)."
                        ),
                    },
                )
                return [decl]
            return []

        doc_type = self._pdf_parser._detecter_type_document(texte, chemin.name)

        if doc_type == "bulletin":
            return self._pdf_parser._parser_bulletin(texte, tableaux, document)
        elif doc_type == "livre_de_paie":
            return self._pdf_parser._parser_livre_de_paie(texte, tableaux, document)
        elif doc_type == "facture":
            return self._pdf_parser._parser_facture(texte, document)
        elif doc_type == "contrat":
            return self._pdf_parser._parser_contrat(texte, document)
        elif doc_type == "interessement":
            return self._pdf_parser._parser_interessement(texte, document)
        elif doc_type == "attestation":
            return self._pdf_parser._parser_attestation(texte, document)
        else:
            return self._pdf_parser._parser_generique(texte, tableaux, document)

    def _extraire_texte(self, chemin: Path) -> str:
        """Extrait le texte du document Word (.docx ou .doc)."""
        ext = chemin.suffix.lower()

        # Format .doc (ancien binaire) : utiliser antiword ou LibreOffice
        if ext == ".doc":
            return _convertir_doc_vers_texte(chemin)

        # Format .docx
        if HAS_DOCX:
            try:
                doc = docx.Document(str(chemin))
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                return "\n".join(paragraphs)
            except Exception:
                pass
        # Fallback: extraction basique via ZIP
        return _extraire_texte_docx_zip(chemin)

    def _extraire_tableaux(self, chemin: Path) -> list:
        """Extrait les tableaux du document Word au format compatible PDF parser."""
        ext = chemin.suffix.lower()

        # Format .doc : conversion necessaire
        if ext == ".doc":
            return _extraire_tableaux_doc(chemin)

        if not HAS_DOCX:
            return []
        try:
            doc = docx.Document(str(chemin))
            tableaux = []
            for table in doc.tables:
                rows = []
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    rows.append(cells)
                if rows:
                    tableaux.append(rows)
            return tableaux
        except Exception:
            return []
