"""Parseur pour les fichiers CSV (exports comptables, listes de salaries, etc.)."""

import csv
import io
from decimal import Decimal, InvalidOperation
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


# Mapping flexible des noms de colonnes vers les champs internes
COLONNES_MAPPING = {
    # Employe
    "nir": "nir", "numero_ss": "nir", "securite_sociale": "nir",
    "nom": "nom", "nom_salarie": "nom",
    "prenom": "prenom", "prenom_salarie": "prenom",
    "statut": "statut", "categorie": "statut",
    # Cotisations
    "base": "base_brute", "base_brute": "base_brute", "assiette": "assiette",
    "salaire_brut": "base_brute", "brut": "base_brute",
    "taux_patronal": "taux_patronal", "taux_employeur": "taux_patronal",
    "taux_salarial": "taux_salarial", "taux_salarie": "taux_salarial",
    "montant_patronal": "montant_patronal", "cotisation_employeur": "montant_patronal",
    "montant_salarial": "montant_salarial", "cotisation_salarie": "montant_salarial",
    "type_cotisation": "type_cotisation", "code_cotisation": "type_cotisation",
    # Periode
    "periode_debut": "periode_debut", "date_debut": "periode_debut",
    "periode_fin": "periode_fin", "date_fin": "periode_fin",
    "mois": "mois", "periode": "mois",
}


class CSVParser(BaseParser):
    """Parse les fichiers CSV contenant des donnees de paie ou de cotisations."""

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() == ".csv"

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        metadata = {"format": "csv"}
        try:
            with open(chemin, "r", encoding="utf-8-sig") as f:
                dialect = csv.Sniffer().sniff(f.read(4096))
                f.seek(0)
                reader = csv.reader(f, dialect)
                header = next(reader, [])
                nb_lignes = sum(1 for _ in reader)
                metadata["separateur"] = dialect.delimiter
                metadata["colonnes"] = header
                metadata["nb_lignes"] = nb_lignes
        except Exception as e:
            metadata["erreur_lecture"] = str(e)
        return metadata

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        try:
            with open(chemin, "r", encoding="utf-8-sig") as f:
                contenu = f.read()
        except UnicodeDecodeError:
            with open(chemin, "r", encoding="latin-1") as f:
                contenu = f.read()

        try:
            dialect = csv.Sniffer().sniff(contenu[:4096])
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(io.StringIO(contenu), dialect=dialect)

        if not reader.fieldnames:
            raise ParseError(f"Impossible de detecter les colonnes du CSV: {chemin}")

        # Normaliser les noms de colonnes
        col_map = {}
        for col in reader.fieldnames:
            col_lower = col.strip().lower().replace(" ", "_")
            if col_lower in COLONNES_MAPPING:
                col_map[col] = COLONNES_MAPPING[col_lower]

        cotisations = []
        employes_vus = {}

        for i, row in enumerate(reader, start=2):
            try:
                cotisation = self._parser_ligne(row, col_map, document.id, i)
                if cotisation:
                    cotisations.append(cotisation)

                # Extraire l'employe si present
                employe = self._extraire_employe(row, col_map, document.id)
                if employe and employe.nir and employe.nir not in employes_vus:
                    employes_vus[employe.nir] = employe

            except Exception:
                continue  # Ligne mal formee, on continue

        declaration = Declaration(
            type_declaration="CSV",
            reference=chemin.stem,
            cotisations=cotisations,
            employes=list(employes_vus.values()),
            effectif_declare=len(employes_vus),
            source_document_id=document.id,
        )

        if cotisations:
            declaration.masse_salariale_brute = sum(
                c.base_brute for c in cotisations
            )

        return [declaration]

    def _parser_ligne(
        self, row: dict, col_map: dict, doc_id: str, ligne: int
    ) -> Cotisation | None:
        """Parse une ligne du CSV en Cotisation."""
        mapped = {}
        for col_csv, champ in col_map.items():
            val = row.get(col_csv, "").strip()
            if val:
                mapped[champ] = val

        if not mapped.get("base_brute") and not mapped.get("montant_patronal"):
            return None

        cotisation = Cotisation(source_document_id=doc_id)

        if "base_brute" in mapped:
            cotisation.base_brute = parser_montant(mapped["base_brute"])
            cotisation.assiette = cotisation.base_brute

        if "assiette" in mapped:
            cotisation.assiette = parser_montant(mapped["assiette"])

        if "taux_patronal" in mapped:
            cotisation.taux_patronal = parser_montant(mapped["taux_patronal"])
            # Convertir en pourcentage si > 1
            if cotisation.taux_patronal > 1:
                cotisation.taux_patronal = cotisation.taux_patronal / 100

        if "taux_salarial" in mapped:
            cotisation.taux_salarial = parser_montant(mapped["taux_salarial"])
            if cotisation.taux_salarial > 1:
                cotisation.taux_salarial = cotisation.taux_salarial / 100

        if "montant_patronal" in mapped:
            cotisation.montant_patronal = parser_montant(mapped["montant_patronal"])

        if "montant_salarial" in mapped:
            cotisation.montant_salarial = parser_montant(mapped["montant_salarial"])

        if "type_cotisation" in mapped:
            cotisation.type_cotisation = self._mapper_type_cotisation(
                mapped["type_cotisation"]
            )

        if "periode_debut" in mapped and "periode_fin" in mapped:
            debut = parser_date(mapped["periode_debut"])
            fin = parser_date(mapped["periode_fin"])
            if debut and fin:
                cotisation.periode = DateRange(debut=debut, fin=fin)

        return cotisation

    def _extraire_employe(
        self, row: dict, col_map: dict, doc_id: str
    ) -> Employe | None:
        mapped = {}
        for col_csv, champ in col_map.items():
            val = row.get(col_csv, "").strip()
            if val:
                mapped[champ] = val

        if not mapped.get("nir") and not mapped.get("nom"):
            return None

        return Employe(
            nir=mapped.get("nir", ""),
            nom=mapped.get("nom", ""),
            prenom=mapped.get("prenom", ""),
            statut=mapped.get("statut", ""),
            source_document_id=doc_id,
        )

    @staticmethod
    def _mapper_type_cotisation(valeur: str) -> ContributionType:
        """Mappe une valeur textuelle vers un ContributionType."""
        v = valeur.lower().strip()
        mapping = {
            "maladie": ContributionType.MALADIE,
            "vieillesse plafonnee": ContributionType.VIEILLESSE_PLAFONNEE,
            "vieillesse deplafonnee": ContributionType.VIEILLESSE_DEPLAFONNEE,
            "allocations familiales": ContributionType.ALLOCATIONS_FAMILIALES,
            "af": ContributionType.ALLOCATIONS_FAMILIALES,
            "at": ContributionType.ACCIDENT_TRAVAIL,
            "accident travail": ContributionType.ACCIDENT_TRAVAIL,
            "at/mp": ContributionType.ACCIDENT_TRAVAIL,
            "csg": ContributionType.CSG_DEDUCTIBLE,
            "crds": ContributionType.CRDS,
            "chomage": ContributionType.ASSURANCE_CHOMAGE,
            "ags": ContributionType.AGS,
            "fnal": ContributionType.FNAL,
            "formation": ContributionType.FORMATION_PROFESSIONNELLE,
        }
        for pattern, ct in mapping.items():
            if pattern in v:
                return ct
        return ContributionType.MALADIE  # fallback
