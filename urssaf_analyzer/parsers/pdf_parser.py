"""Parseur pour les fichiers PDF (bulletins de paie, attestations, bordereaux)."""

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import Document, Declaration, Cotisation, Employe
from urssaf_analyzer.config.constants import ContributionType
from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.utils.number_utils import parser_montant

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


# Patterns regex pour extraire les donnees des PDFs
PATTERNS = {
    "siret": re.compile(r"SIRET\s*[:\s]*(\d{14})", re.IGNORECASE),
    "siren": re.compile(r"SIREN\s*[:\s]*(\d{9})", re.IGNORECASE),
    "nir": re.compile(r"(?:NIR|N[°o]\s*SS)\s*[:\s]*([12]\s*\d{2}\s*\d{2}\s*\d{2}\s*\d{3}\s*\d{3}\s*\d{2})", re.IGNORECASE),
    "salaire_brut": re.compile(r"(?:salaire|remuneration)\s+brut(?:e)?\s*[:\s]*([\d\s,.]+)", re.IGNORECASE),
    "net_imposable": re.compile(r"net\s+imposable\s*[:\s]*([\d\s,.]+)", re.IGNORECASE),
    "periode": re.compile(r"(?:periode|mois)\s*[:\s]*(\w+\s*\d{4})", re.IGNORECASE),
    "montant_cotisation": re.compile(
        r"(maladie|vieillesse|allocations?\s+familiales?|at/?mp|csg|crds|chomage|ags|fnal|formation)"
        r"\s+([\d\s,.]+)\s+([\d,.]+)\s*%?\s+([\d\s,.]+)",
        re.IGNORECASE,
    ),
    "total_cotisations_patronales": re.compile(
        r"total\s+(?:cotisations?\s+)?(?:patronales?|employeur)\s*[:\s]*([\d\s,.]+)",
        re.IGNORECASE,
    ),
    "total_cotisations_salariales": re.compile(
        r"total\s+(?:cotisations?\s+)?(?:salariales?|salarie)\s*[:\s]*([\d\s,.]+)",
        re.IGNORECASE,
    ),
}

TYPE_COTISATION_MAPPING = {
    "maladie": ContributionType.MALADIE,
    "vieillesse": ContributionType.VIEILLESSE_PLAFONNEE,
    "allocations familiales": ContributionType.ALLOCATIONS_FAMILIALES,
    "allocation familiale": ContributionType.ALLOCATIONS_FAMILIALES,
    "at/mp": ContributionType.ACCIDENT_TRAVAIL,
    "atmp": ContributionType.ACCIDENT_TRAVAIL,
    "csg": ContributionType.CSG_DEDUCTIBLE,
    "crds": ContributionType.CRDS,
    "chomage": ContributionType.ASSURANCE_CHOMAGE,
    "ags": ContributionType.AGS,
    "fnal": ContributionType.FNAL,
    "formation": ContributionType.FORMATION_PROFESSIONNELLE,
}


class PDFParser(BaseParser):
    """Parse les fichiers PDF en extrayant texte et tableaux."""

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() == ".pdf"

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        if not HAS_PDFPLUMBER:
            return {"format": "pdf", "erreur": "pdfplumber non installe"}
        try:
            with pdfplumber.open(chemin) as pdf:
                return {
                    "format": "pdf",
                    "nb_pages": len(pdf.pages),
                    "metadata_pdf": pdf.metadata or {},
                }
        except Exception as e:
            return {"format": "pdf", "erreur": str(e)}

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        if not HAS_PDFPLUMBER:
            raise ParseError("pdfplumber n'est pas installe. Installer avec: pip install pdfplumber")

        try:
            with pdfplumber.open(chemin) as pdf:
                texte_complet = ""
                tableaux = []
                for page in pdf.pages:
                    texte_complet += (page.extract_text() or "") + "\n"
                    tables = page.extract_tables()
                    if tables:
                        tableaux.extend(tables)
        except Exception as e:
            raise ParseError(f"Impossible de lire le PDF {chemin}: {e}") from e

        cotisations = []

        # Extraire les cotisations via regex sur le texte
        cotisations.extend(self._extraire_cotisations_texte(texte_complet, document.id))

        # Extraire les cotisations depuis les tableaux
        cotisations.extend(self._extraire_cotisations_tableaux(tableaux, document.id))

        # Extraire les metadonnees du document
        employes = self._extraire_employes(texte_complet, document.id)
        masse_salariale = self._extraire_masse_salariale(texte_complet)

        declaration = Declaration(
            type_declaration="PDF",
            reference=chemin.stem,
            cotisations=cotisations,
            employes=employes,
            effectif_declare=len(employes),
            masse_salariale_brute=masse_salariale,
            source_document_id=document.id,
        )

        # Extraire SIRET si present
        siret_match = PATTERNS["siret"].search(texte_complet)
        if siret_match:
            from urssaf_analyzer.models.documents import Employeur
            declaration.employeur = Employeur(
                siret=siret_match.group(1),
                source_document_id=document.id,
            )
            siren_match = PATTERNS["siren"].search(texte_complet)
            if siren_match:
                declaration.employeur.siren = siren_match.group(1)

        return [declaration]

    def _extraire_cotisations_texte(self, texte: str, doc_id: str) -> list[Cotisation]:
        """Extrait les cotisations du texte brut du PDF."""
        cotisations = []
        for match in PATTERNS["montant_cotisation"].finditer(texte):
            type_str = match.group(1).lower().strip()
            base = parser_montant(match.group(2))
            taux = parser_montant(match.group(3))
            montant = parser_montant(match.group(4))

            if taux > 1:
                taux = taux / 100

            ct = TYPE_COTISATION_MAPPING.get(type_str, ContributionType.MALADIE)

            cotisations.append(Cotisation(
                type_cotisation=ct,
                base_brute=base,
                assiette=base,
                taux_patronal=taux,
                montant_patronal=montant,
                source_document_id=doc_id,
            ))
        return cotisations

    def _extraire_cotisations_tableaux(self, tableaux: list, doc_id: str) -> list[Cotisation]:
        """Extrait les cotisations depuis les tableaux detectes dans le PDF."""
        cotisations = []
        for table in tableaux:
            if len(table) < 2:
                continue
            # Essayer de detecter les colonnes pertinentes
            header = [str(c).lower().strip() if c else "" for c in table[0]]
            col_type = col_base = col_taux = col_montant = -1

            for i, h in enumerate(header):
                if any(kw in h for kw in ["libell", "type", "cotisation", "designation"]):
                    col_type = i
                elif any(kw in h for kw in ["base", "assiette", "brut"]):
                    col_base = i
                elif any(kw in h for kw in ["taux", "%"]):
                    col_taux = i
                elif any(kw in h for kw in ["montant", "total", "part"]):
                    col_montant = i

            if col_base < 0 and col_montant < 0:
                continue

            for row in table[1:]:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue
                try:
                    c = Cotisation(source_document_id=doc_id)
                    if col_base >= 0 and col_base < len(row) and row[col_base]:
                        c.base_brute = parser_montant(str(row[col_base]))
                        c.assiette = c.base_brute
                    if col_taux >= 0 and col_taux < len(row) and row[col_taux]:
                        c.taux_patronal = parser_montant(str(row[col_taux]))
                        if c.taux_patronal > 1:
                            c.taux_patronal = c.taux_patronal / 100
                    if col_montant >= 0 and col_montant < len(row) and row[col_montant]:
                        c.montant_patronal = parser_montant(str(row[col_montant]))
                    if col_type >= 0 and col_type < len(row) and row[col_type]:
                        type_str = str(row[col_type]).lower()
                        for pattern, ct in TYPE_COTISATION_MAPPING.items():
                            if pattern in type_str:
                                c.type_cotisation = ct
                                break
                    if c.base_brute > 0 or c.montant_patronal > 0:
                        cotisations.append(c)
                except Exception:
                    continue
        return cotisations

    def _extraire_employes(self, texte: str, doc_id: str) -> list[Employe]:
        """Extrait les employes depuis le texte."""
        employes = []
        for match in PATTERNS["nir"].finditer(texte):
            nir = match.group(1).replace(" ", "")
            employes.append(Employe(nir=nir, source_document_id=doc_id))
        return employes

    def _extraire_masse_salariale(self, texte: str) -> Decimal:
        """Extrait la masse salariale brute totale."""
        match = PATTERNS["salaire_brut"].search(texte)
        if match:
            return parser_montant(match.group(1))
        return Decimal("0")
