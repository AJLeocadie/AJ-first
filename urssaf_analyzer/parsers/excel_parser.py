"""Parseur pour les fichiers Excel (bulletins de paie, exports comptables)."""

from decimal import Decimal
from pathlib import Path
from typing import Any

from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import (
    Document, Declaration, Cotisation, Employe, DateRange,
)
from urssaf_analyzer.config.constants import ContributionType
from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.utils.date_utils import parser_date
from urssaf_analyzer.utils.number_utils import parser_montant

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


class ExcelParser(BaseParser):
    """Parse les fichiers Excel (.xlsx)."""

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() in (".xlsx", ".xls")

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        if not HAS_OPENPYXL:
            return {"erreur": "openpyxl non installe"}
        try:
            wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
            metadata = {
                "format": "excel",
                "feuilles": wb.sheetnames,
                "nb_feuilles": len(wb.sheetnames),
            }
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                metadata[f"feuille_{sheet_name}_dims"] = ws.dimensions
            wb.close()
            return metadata
        except Exception as e:
            return {"format": "excel", "erreur": str(e)}

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        if not HAS_OPENPYXL:
            raise ParseError("openpyxl n'est pas installe. Installer avec: pip install openpyxl")

        try:
            wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
        except Exception as e:
            raise ParseError(f"Impossible de lire le fichier Excel {chemin}: {e}") from e

        declarations = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            decl = self._parser_feuille(ws, sheet_name, document.id)
            if decl and (decl.cotisations or decl.employes):
                declarations.append(decl)

        wb.close()
        return declarations

    def _parser_feuille(
        self, ws: Any, nom_feuille: str, doc_id: str
    ) -> Declaration | None:
        """Parse une feuille Excel."""
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            return None

        # Premiere ligne = en-tetes
        header = [str(c).strip().lower().replace(" ", "_") if c else "" for c in rows[0]]
        col_indices = self._mapper_colonnes(header)

        if not col_indices:
            return None

        cotisations = []
        employes_vus = {}

        for row_data in rows[1:]:
            if not row_data or all(c is None for c in row_data):
                continue

            row_dict = {}
            for i, val in enumerate(row_data):
                if i < len(header) and header[i]:
                    row_dict[header[i]] = val

            cotisation = self._extraire_cotisation(row_dict, col_indices, doc_id)
            if cotisation:
                cotisations.append(cotisation)

            employe = self._extraire_employe(row_dict, col_indices, doc_id)
            if employe and employe.nir and employe.nir not in employes_vus:
                employes_vus[employe.nir] = employe

        declaration = Declaration(
            type_declaration="EXCEL",
            reference=nom_feuille,
            cotisations=cotisations,
            employes=list(employes_vus.values()),
            effectif_declare=len(employes_vus),
            source_document_id=doc_id,
        )
        if cotisations:
            declaration.masse_salariale_brute = sum(c.base_brute for c in cotisations)

        return declaration

    def _mapper_colonnes(self, header: list[str]) -> dict[str, int]:
        """Identifie les colonnes utiles a partir des en-tetes."""
        mapping = {}
        keywords = {
            "nir": ["nir", "numero_ss", "securite_sociale"],
            "nom": ["nom", "nom_salarie"],
            "prenom": ["prenom"],
            "base_brute": ["base", "base_brute", "salaire_brut", "brut"],
            "taux_patronal": ["taux_patronal", "taux_employeur"],
            "taux_salarial": ["taux_salarial", "taux_salarie"],
            "montant_patronal": ["montant_patronal", "cotisation_employeur"],
            "montant_salarial": ["montant_salarial", "cotisation_salarie"],
            "type_cotisation": ["type_cotisation", "code_cotisation", "libelle"],
        }
        for i, col in enumerate(header):
            for field_name, kws in keywords.items():
                if col in kws and field_name not in mapping:
                    mapping[field_name] = i
        return mapping

    def _extraire_cotisation(
        self, row: dict, col_indices: dict, doc_id: str
    ) -> Cotisation | None:
        base = row.get("base_brute") or row.get("base") or row.get("salaire_brut") or row.get("brut")
        montant_p = row.get("montant_patronal") or row.get("cotisation_employeur")

        if base is None and montant_p is None:
            return None

        c = Cotisation(source_document_id=doc_id)
        if base is not None:
            c.base_brute = Decimal(str(base)) if not isinstance(base, str) else parser_montant(base)
            c.assiette = c.base_brute
        if montant_p is not None:
            c.montant_patronal = Decimal(str(montant_p)) if not isinstance(montant_p, str) else parser_montant(montant_p)

        montant_s = row.get("montant_salarial") or row.get("cotisation_salarie")
        if montant_s is not None:
            c.montant_salarial = Decimal(str(montant_s)) if not isinstance(montant_s, str) else parser_montant(montant_s)

        tp = row.get("taux_patronal") or row.get("taux_employeur")
        if tp is not None:
            c.taux_patronal = Decimal(str(tp)) if not isinstance(tp, str) else parser_montant(tp)
            if c.taux_patronal > 1:
                c.taux_patronal = c.taux_patronal / 100

        ts = row.get("taux_salarial") or row.get("taux_salarie")
        if ts is not None:
            c.taux_salarial = Decimal(str(ts)) if not isinstance(ts, str) else parser_montant(ts)
            if c.taux_salarial > 1:
                c.taux_salarial = c.taux_salarial / 100

        return c

    def _extraire_employe(self, row: dict, col_indices: dict, doc_id: str) -> Employe | None:
        nir = row.get("nir") or row.get("numero_ss") or row.get("securite_sociale")
        nom = row.get("nom") or row.get("nom_salarie")
        if not nir and not nom:
            return None
        return Employe(
            nir=str(nir) if nir else "",
            nom=str(nom) if nom else "",
            prenom=str(row.get("prenom", "")),
            source_document_id=doc_id,
        )
