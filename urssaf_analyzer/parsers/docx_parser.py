"""Parseur pour les fichiers Word (.docx).

Extrait le texte du document Word puis applique les memes regles
d'extraction que le PDF parser (regex pour bulletins, factures, contrats, etc.).
Fonctionne aussi si python-docx n'est pas installe (extraction basique ZIP/XML).
"""

import re
from pathlib import Path
from typing import Any

from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.parsers.pdf_parser import PDFParser
from urssaf_analyzer.models.documents import Document, Declaration

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


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


class DocxParser(BaseParser):
    """Parse les fichiers .docx en extrayant le texte puis en reutilisant le PDF parser."""

    def __init__(self):
        self._pdf_parser = PDFParser()

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() in (".docx", ".doc")

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        try:
            texte = self._extraire_texte(chemin)
            meta = {
                "format": "docx",
                "nb_caracteres": len(texte),
                "python_docx_disponible": HAS_DOCX,
            }
            if HAS_DOCX:
                try:
                    doc = docx.Document(str(chemin))
                    meta["nb_paragraphes"] = len(doc.paragraphs)
                    meta["nb_tableaux"] = len(doc.tables)
                except Exception:
                    pass
            return meta
        except Exception as e:
            return {"format": "docx", "erreur": str(e)}

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        texte = self._extraire_texte(chemin)
        tableaux = self._extraire_tableaux(chemin)
        if not texte.strip():
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
        """Extrait le texte du document Word."""
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
