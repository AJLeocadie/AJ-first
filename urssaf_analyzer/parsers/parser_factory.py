"""Factory pour selectionner automatiquement le bon parseur."""

from pathlib import Path

from urssaf_analyzer.core.exceptions import UnsupportedFormatError
from urssaf_analyzer.config.constants import SUPPORTED_EXTENSIONS
from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.parsers.csv_parser import CSVParser
from urssaf_analyzer.parsers.excel_parser import ExcelParser
from urssaf_analyzer.parsers.pdf_parser import PDFParser
from urssaf_analyzer.parsers.xml_parser import XMLParser
from urssaf_analyzer.parsers.dsn_parser import DSNParser


class ParserFactory:
    """Selectionne et instancie le parseur adapte au type de fichier."""

    def __init__(self):
        self._parsers: list[BaseParser] = [
            DSNParser(),    # DSN en priorite (peut traiter certains XML)
            CSVParser(),
            ExcelParser(),
            PDFParser(),
            XMLParser(),    # XML en dernier (generique)
        ]

    def get_parser(self, chemin: Path) -> BaseParser:
        """Retourne le parseur adapte au fichier donne."""
        ext = chemin.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise UnsupportedFormatError(
                f"Format '{ext}' non supporte. "
                f"Formats acceptes : {', '.join(SUPPORTED_EXTENSIONS.keys())}"
            )

        for parser in self._parsers:
            if parser.peut_traiter(chemin):
                return parser

        raise UnsupportedFormatError(
            f"Aucun parseur disponible pour le fichier {chemin.name}"
        )

    def formats_supportes(self) -> list[str]:
        """Liste les extensions de fichiers supportees."""
        return list(SUPPORTED_EXTENSIONS.keys())
