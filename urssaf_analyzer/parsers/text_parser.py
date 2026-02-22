"""Parseur pour les fichiers texte brut (.txt).

Applique les memes regles d'extraction que le PDF parser
(regex pour bulletins, factures, contrats, etc.) sur le contenu texte.
"""

from pathlib import Path
from typing import Any

from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.parsers.pdf_parser import PDFParser
from urssaf_analyzer.models.documents import Document, Declaration


class TextParser(BaseParser):
    """Parse les fichiers .txt en reutilisant la logique du PDF parser."""

    def __init__(self):
        self._pdf_parser = PDFParser()

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() == ".txt"

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        try:
            texte = self._lire_texte(chemin)
            return {
                "format": "texte",
                "nb_caracteres": len(texte),
                "nb_lignes": texte.count("\n") + 1,
            }
        except Exception as e:
            return {"format": "texte", "erreur": str(e)}

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        texte = self._lire_texte(chemin)
        if not texte.strip():
            return []

        # Detect document type using the PDF parser's classification
        doc_type = self._pdf_parser._detecter_type_document(texte, chemin.name)

        if doc_type == "bulletin":
            return self._pdf_parser._parser_bulletin(texte, [], document)
        elif doc_type == "livre_de_paie":
            return self._pdf_parser._parser_livre_de_paie(texte, [], document)
        elif doc_type == "facture":
            return self._pdf_parser._parser_facture(texte, document)
        elif doc_type == "contrat":
            return self._pdf_parser._parser_contrat(texte, document)
        elif doc_type == "interessement":
            return self._pdf_parser._parser_interessement(texte, document)
        elif doc_type == "attestation":
            return self._pdf_parser._parser_attestation(texte, document)
        else:
            return self._pdf_parser._parser_generique(texte, [], document)

    @staticmethod
    def _lire_texte(chemin: Path) -> str:
        """Lit un fichier texte avec detection d'encodage."""
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                return chemin.read_text(encoding=enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return chemin.read_text(encoding="latin-1", errors="replace")
