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
    "nom": "nom", "nom_salarie": "nom", "salarie": "nom", "employe": "nom",
    "prenom": "prenom", "prenom_salarie": "prenom",
    "statut": "statut", "categorie": "statut",
    # Cotisations - base
    "base": "base_brute", "base_brute": "base_brute", "assiette": "assiette",
    "salaire_brut": "base_brute", "brut": "base_brute", "salaire": "base_brute",
    "salaire_de_base": "base_brute", "remuneration": "base_brute",
    "remuneration_brute": "base_brute",
    # Cotisations - taux
    "taux_patronal": "taux_patronal", "taux_employeur": "taux_patronal",
    "taux_pat.": "taux_patronal", "taux_pat": "taux_patronal",
    "taux_salarial": "taux_salarial", "taux_salarie": "taux_salarial",
    "taux_sal.": "taux_salarial", "taux_sal": "taux_salarial",
    # Cotisations - montants patronaux
    "montant_patronal": "montant_patronal", "cotisation_employeur": "montant_patronal",
    "part_patronale": "montant_patronal", "part_patronal": "montant_patronal",
    "part_employeur": "montant_patronal", "charges_patronales": "montant_patronal",
    "cotisations_patronales": "montant_patronal", "patronal": "montant_patronal",
    # Cotisations - montants salariaux
    "montant_salarial": "montant_salarial", "cotisation_salarie": "montant_salarial",
    "part_salariale": "montant_salarial", "part_salarie": "montant_salarial",
    "charges_salariales": "montant_salarial", "cotisations_salariales": "montant_salarial",
    "retenues": "montant_salarial", "salarial": "montant_salarial",
    # Cotisations - total (recapitulatifs)
    "cotisations": "total_cotisations", "charges": "total_cotisations",
    "total_cotisations": "total_cotisations", "total_charges": "total_cotisations",
    "charges_sociales": "total_cotisations",
    # Net a payer
    "net_a_payer": "net_a_payer", "net_à_payer": "net_a_payer",
    "net": "net_a_payer", "net_paye": "net_a_payer", "salaire_net": "net_a_payer",
    # Avantages en nature
    "avantage": "avantage_nature", "avantages": "avantage_nature",
    "avantage_nature": "avantage_nature", "avantages_en_nature": "avantage_nature",
    "avantage_en_nature": "avantage_nature",
    # Type de cotisation / rubrique
    "type_cotisation": "type_cotisation", "code_cotisation": "type_cotisation",
    "rubrique": "type_cotisation", "libelle": "type_cotisation",
    "libelle_cotisation": "type_cotisation", "nature_cotisation": "type_cotisation",
    # Factures / documents comptables
    "type": "type_document_ligne", "numero": "numero_piece",
    "tiers": "tiers", "fournisseur": "tiers", "client": "tiers",
    "ht": "montant_ht", "hors_taxe": "montant_ht", "montant_ht": "montant_ht",
    "tva": "montant_tva", "montant_tva": "montant_tva",
    "ttc": "montant_ttc", "toutes_taxes": "montant_ttc", "montant_ttc": "montant_ttc",
    "date": "date_piece",
    # Periode
    "periode_debut": "periode_debut", "date_debut": "periode_debut",
    "periode_fin": "periode_fin", "date_fin": "periode_fin",
    "mois": "mois", "periode": "mois",
}

# Mots-cles pour detection du type de document CSV
_CSV_TYPE_KEYWORDS = {
    "bulletin_de_paie": ["rubrique", "cotisation", "brut", "salarial", "patronal", "salaire", "net"],
    "recapitulatif_paie": ["nom", "salaire", "cotisations", "net", "avantage"],
    "livre_de_paie": ["nir", "securite_sociale", "nom_salarie"],
    "facture": ["ht", "tva", "ttc", "fournisseur", "client", "facture"],
    "declaration_dsn": ["nir", "ctp", "code_type_personnel"],
    "grand_livre": ["compte", "debit", "credit", "journal"],
}


class CSVParser(BaseParser):
    """Parse les fichiers CSV contenant des donnees de paie ou de cotisations."""

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() == ".csv"

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        metadata = {"format": "csv"}
        try:
            with open(chemin, "r", encoding="utf-8-sig") as f:
                contenu = f.read(8192)
            try:
                dialect = csv.Sniffer().sniff(contenu[:4096])
            except csv.Error:
                first_line = contenu.split("\n", 1)[0]
                dialect = csv.excel
                if ";" in first_line:
                    dialect.delimiter = ";"
                elif "\t" in first_line:
                    dialect = csv.excel_tab
            reader = csv.reader(io.StringIO(contenu), dialect)
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
            # Detecter manuellement le separateur
            first_line = contenu.split("\n", 1)[0]
            if ";" in first_line:
                dialect = csv.excel
                dialect.delimiter = ";"
            elif "\t" in first_line:
                dialect = csv.excel_tab
            else:
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
        employes_sans_nir = []

        # Detecter si format recapitulatif (1 ligne = 1 salarie)
        mapped_fields = set(col_map.values())
        est_recapitulatif = (
            "nom" in mapped_fields
            and "base_brute" in mapped_fields
            and "type_cotisation" not in mapped_fields
        )

        for i, row in enumerate(reader, start=2):
            try:
                # Extraire l'employe si present
                employe = self._extraire_employe(row, col_map, document.id)
                emp_id = None
                if employe:
                    # Cle unique: NIR si disponible, sinon nom
                    cle = employe.nir if employe.nir else f"_{employe.nom}_{employe.prenom}"
                    if cle not in employes_vus:
                        employes_vus[cle] = employe
                    emp_id = employes_vus[cle].id

                if est_recapitulatif:
                    cots = self._parser_ligne_recapitulatif(
                        row, col_map, document.id, i, emp_id
                    )
                    cotisations.extend(cots)
                else:
                    cotisation = self._parser_ligne(row, col_map, document.id, i)
                    if cotisation:
                        if emp_id:
                            cotisation.employe_id = emp_id
                        cotisations.append(cotisation)

            except Exception:
                continue  # Ligne mal formee, on continue

        # Detecter le type de document a partir des colonnes
        type_document = self._detecter_type_document(reader.fieldnames, col_map)
        if est_recapitulatif and type_document in ("inconnu", "document_comptable"):
            type_document = "recapitulatif_paie"

        declaration = Declaration(
            type_declaration="CSV",
            reference=chemin.stem,
            cotisations=cotisations,
            employes=list(employes_vus.values()),
            effectif_declare=len(employes_vus),
            source_document_id=document.id,
        )

        # Ajouter metadata avec type_document
        declaration.metadata = declaration.metadata or {}
        declaration.metadata["type_document"] = type_document
        declaration.metadata["colonnes_detectees"] = list(col_map.values())
        declaration.metadata["nb_lignes_parsees"] = len(cotisations)
        if est_recapitulatif:
            declaration.metadata["format_recapitulatif"] = True

        if cotisations:
            declaration.masse_salariale_brute = sum(
                c.base_brute for c in cotisations
            )

        return [declaration]

    def _detecter_type_document(self, fieldnames: list, col_map: dict) -> str:
        """Detecte le type de document CSV a partir des en-tetes."""
        if not fieldnames:
            return "inconnu"
        headers_lower = {h.strip().lower().replace(" ", "_") for h in fieldnames}
        mapped_fields = set(col_map.values())

        # Score par type
        best_type = "inconnu"
        best_score = 0
        for doc_type, keywords in _CSV_TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if any(kw in h for h in headers_lower))
            if score > best_score:
                best_score = score
                best_type = doc_type

        # Affiner: si plusieurs employes -> livre de paie
        if best_type == "bulletin_de_paie" and "nir" in mapped_fields:
            best_type = "livre_de_paie"

        return best_type if best_score >= 2 else "document_comptable"

    def _parser_ligne(
        self, row: dict, col_map: dict, doc_id: str, ligne: int
    ) -> Cotisation | None:
        """Parse une ligne du CSV en Cotisation."""
        mapped = {}
        for col_csv, champ in col_map.items():
            val = row.get(col_csv, "").strip()
            if val:
                mapped[champ] = val

        # Accepter les lignes avec base_brute, montant_patronal, ou montant_ht (factures)
        has_cotisation = mapped.get("base_brute") or mapped.get("montant_patronal")
        has_facture = mapped.get("montant_ht") or mapped.get("montant_ttc")
        if not has_cotisation and not has_facture:
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

        # Pour les factures: utiliser montant_ht comme base
        if has_facture and not has_cotisation:
            if "montant_ht" in mapped:
                cotisation.base_brute = parser_montant(mapped["montant_ht"])
                cotisation.assiette = cotisation.base_brute
            if "montant_tva" in mapped:
                cotisation.montant_patronal = parser_montant(mapped["montant_tva"])

        if "periode_debut" in mapped and "periode_fin" in mapped:
            debut = parser_date(mapped["periode_debut"])
            fin = parser_date(mapped["periode_fin"])
            if debut and fin:
                cotisation.periode = DateRange(debut=debut, fin=fin)

        return cotisation

    def _parser_ligne_recapitulatif(
        self, row: dict, col_map: dict, doc_id: str, ligne: int,
        employe_id: str | None = None,
    ) -> list[Cotisation]:
        """Parse une ligne recapitulatif (1 ligne = 1 salarie) en cotisations synthetiques.

        Quand le fichier n'a pas de colonne rubrique/type_cotisation,
        on cree une cotisation globale a partir des totaux disponibles.
        """
        mapped = {}
        for col_csv, champ in col_map.items():
            val = row.get(col_csv, "").strip()
            if val:
                mapped[champ] = val

        brut_str = mapped.get("base_brute", "")
        if not brut_str:
            return []

        brut = parser_montant(brut_str)
        if brut <= 0:
            return []

        total_cots = Decimal("0")
        if "total_cotisations" in mapped:
            total_cots = parser_montant(mapped["total_cotisations"])

        net = Decimal("0")
        if "net_a_payer" in mapped:
            net = parser_montant(mapped["net_a_payer"])

        cotisations = []

        # Cotisation synthetique globale avec le brut
        cot = Cotisation(
            source_document_id=doc_id,
            type_cotisation=ContributionType.MALADIE,
            base_brute=brut,
            assiette=brut,
            employe_id=employe_id or "",
        )
        if total_cots > 0:
            cot.montant_salarial = total_cots
        cotisations.append(cot)

        # Extraire avantage en nature comme info supplementaire
        avantage_str = mapped.get("avantage_nature", "")
        if avantage_str:
            # Extraire le montant s'il y en a un
            import re
            montants = re.findall(r'(\d[\d\s]*[.,]?\d*)\s*(?:€|EUR|eur)?', avantage_str)
            if montants:
                montant_avantage = parser_montant(montants[0].strip())
                if montant_avantage > 0:
                    cot_avantage = Cotisation(
                        source_document_id=doc_id,
                        type_cotisation=ContributionType.AVANTAGE_NATURE,
                        base_brute=montant_avantage,
                        assiette=montant_avantage,
                        employe_id=employe_id or "",
                    )
                    cotisations.append(cot_avantage)

        return cotisations

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

        nom = mapped.get("nom", "")
        prenom = mapped.get("prenom", "")

        # Si prenom absent, tenter de separer "NOM Prenom" ou "Prenom NOM"
        if nom and not prenom:
            parts = nom.split()
            if len(parts) >= 2:
                # Chercher un mot tout en majuscules (= nom de famille)
                upper_parts = [p for p in parts if p == p.upper() and len(p) > 1 and not p.isdigit()]
                other_parts = [p for p in parts if p not in upper_parts]
                if upper_parts and other_parts:
                    nom = " ".join(upper_parts)
                    prenom = " ".join(other_parts)
                else:
                    # Convention FR: colonne "Nom" → 1er mot = nom de famille
                    nom = parts[0]
                    prenom = " ".join(parts[1:])

        return Employe(
            nir=mapped.get("nir", ""),
            nom=nom,
            prenom=prenom,
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
            "csg non deductible": ContributionType.CSG_NON_DEDUCTIBLE,
            "csg": ContributionType.CSG_DEDUCTIBLE,
            "crds": ContributionType.CRDS,
            "chomage": ContributionType.ASSURANCE_CHOMAGE,
            "ags": ContributionType.AGS,
            "fnal": ContributionType.FNAL,
            "formation": ContributionType.FORMATION_PROFESSIONNELLE,
            "taxe apprentissage": ContributionType.TAXE_APPRENTISSAGE,
            "prevoyance cadre": ContributionType.PREVOYANCE_CADRE,
            "prevoyance": ContributionType.PREVOYANCE_NON_CADRE,
            "mutuelle": ContributionType.MUTUELLE_OBLIGATOIRE,
            "complementaire sante": ContributionType.MUTUELLE_OBLIGATOIRE,
            "retraite complementaire": ContributionType.RETRAITE_COMPLEMENTAIRE_T1,
            "agirc": ContributionType.RETRAITE_COMPLEMENTAIRE_T2,
            "arrco": ContributionType.RETRAITE_COMPLEMENTAIRE_T1,
            "apec": ContributionType.APEC,
            "ceg": ContributionType.CEG_T1,
            "cet": ContributionType.CET,
        }
        for pattern, ct in mapping.items():
            if pattern in v:
                return ct
        return ContributionType.MALADIE  # fallback
