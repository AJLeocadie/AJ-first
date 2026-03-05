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
    # Employe - NIR
    "nir": "nir", "numero_ss": "nir", "securite_sociale": "nir",
    "n_ss": "nir", "nss": "nir", "n_secu": "nir", "num_secu": "nir",
    "no_ss": "nir", "no_securite_sociale": "nir",
    "numero_securite_sociale": "nir", "n_securite_sociale": "nir",
    "social_security_number": "nir", "ssn": "nir",
    # Employe - nom/prenom
    "nom": "nom", "nom_salarie": "nom", "salarie": "nom", "employe": "nom",
    "nom_du_salarie": "nom", "nom_employe": "nom", "nom_agent": "nom",
    "nom_de_famille": "nom", "nom_famille": "nom", "patronyme": "nom",
    "nom_usage": "nom", "nom_naissance": "nom",
    "last_name": "nom", "family_name": "nom", "employee_last_name": "nom",
    "collaborateur_nom": "nom",
    "prenom": "prenom", "prenom_salarie": "prenom", "prenom_employe": "prenom",
    "first_name": "prenom", "given_name": "prenom", "employee_first_name": "prenom",
    "collaborateur_prenom": "prenom",
    # Employe - identite combinee
    "nom_prenom": "nom", "nom_et_prenom": "nom", "prenom_nom": "nom",
    "identite": "nom", "nom_complet": "nom", "intitule_salarie": "nom",
    "designation_salarie": "nom", "nom_sal": "nom", "intitule": "nom",
    "nom_collaborateur": "nom", "collaborateur": "nom",
    "identite_salarie": "nom", "libelle_salarie": "nom",
    # Employe - matricule
    "matricule": "matricule", "num_matricule": "matricule",
    "numero_matricule": "matricule", "n_mat": "matricule",
    "code_salarie": "matricule", "ref_salarie": "matricule",
    "no_salarie": "matricule", "code_employe": "matricule",
    "ref_employe": "matricule", "numero_salarie": "matricule",
    "identifiant": "matricule", "employee_id": "matricule",
    "worker_id": "matricule", "file_number": "matricule",
    "statut": "statut", "categorie": "statut",
    "cat_professionnelle": "statut", "classification": "statut",
    "college": "statut", "employee_category": "statut",
    # Cotisations - base
    "base": "base_brute", "base_brute": "base_brute", "assiette": "assiette",
    "salaire_brut": "base_brute", "brut": "base_brute", "salaire": "base_brute",
    "salaire_de_base": "base_brute", "remuneration": "base_brute",
    "remuneration_brute": "base_brute",
    "brut_soumis": "base_brute", "brut_fiscal": "base_brute",
    "base_ss": "base_brute", "base_securite_sociale": "base_brute",
    "assiette_brute": "base_brute", "base_cotisations": "base_brute",
    "montant_brut": "base_brute", "total_brut": "base_brute",
    "brut_mensuel": "base_brute", "brut_total": "base_brute",
    "gross_pay": "base_brute", "gross_salary": "base_brute",
    "total_gross": "base_brute", "salaire_brut_mensuel": "base_brute",
    "brut_contractuel": "base_brute", "remuneration_totale": "base_brute",
    # Cotisations - taux
    "taux_patronal": "taux_patronal", "taux_employeur": "taux_patronal",
    "taux_pat.": "taux_patronal", "taux_pat": "taux_patronal",
    "tx_pat": "taux_patronal", "tx_patronal": "taux_patronal",
    "pct_patronal": "taux_patronal",
    "taux_salarial": "taux_salarial", "taux_salarie": "taux_salarial",
    "taux_sal.": "taux_salarial", "taux_sal": "taux_salarial",
    "tx_sal": "taux_salarial", "tx_salarial": "taux_salarial",
    "pct_salarial": "taux_salarial",
    # Cotisations - montants patronaux
    "montant_patronal": "montant_patronal", "cotisation_employeur": "montant_patronal",
    "part_patronale": "montant_patronal", "part_patronal": "montant_patronal",
    "part_employeur": "montant_patronal", "charges_patronales": "montant_patronal",
    "cotisations_patronales": "montant_patronal", "patronal": "montant_patronal",
    "mt_patronal": "montant_patronal", "montant_part_employeur": "montant_patronal",
    "contribution_employeur": "montant_patronal", "charge_employeur": "montant_patronal",
    "employer_contribution": "montant_patronal", "employer_share": "montant_patronal",
    "total_patronal": "montant_patronal",
    # Cotisations - montants salariaux
    "montant_salarial": "montant_salarial", "cotisation_salarie": "montant_salarial",
    "part_salariale": "montant_salarial", "part_salarie": "montant_salarial",
    "charges_salariales": "montant_salarial", "cotisations_salariales": "montant_salarial",
    "retenues": "montant_salarial", "salarial": "montant_salarial",
    "mt_salarial": "montant_salarial", "montant_part_salarie": "montant_salarial",
    "retenue_salariale": "montant_salarial", "contribution_salarie": "montant_salarial",
    "retenue_salarie": "montant_salarial", "employee_contribution": "montant_salarial",
    "employee_deduction": "montant_salarial", "total_salarial": "montant_salarial",
    # Cotisations - total (recapitulatifs)
    "cotisations": "total_cotisations", "charges": "total_cotisations",
    "total_cotisations": "total_cotisations", "total_charges": "total_cotisations",
    "charges_sociales": "total_cotisations",
    # Net a payer
    "net_a_payer": "net_a_payer", "net_à_payer": "net_a_payer",
    "net": "net_a_payer", "net_paye": "net_a_payer", "salaire_net": "net_a_payer",
    "montant_net": "net_a_payer", "net_verse": "net_a_payer",
    "net_mensuel": "net_a_payer", "net_fiscal": "net_a_payer",
    "net_imposable": "net_a_payer", "net_avant_impot": "net_a_payer",
    "net_pay": "net_a_payer", "take_home_pay": "net_a_payer",
    "net_a_payer_avant_impot": "net_a_payer", "net_apres_retenues": "net_a_payer",
    # Avantages en nature
    "avantage": "avantage_nature", "avantages": "avantage_nature",
    "avantage_nature": "avantage_nature", "avantages_en_nature": "avantage_nature",
    "avantage_en_nature": "avantage_nature",
    # Type de cotisation / rubrique
    "type_cotisation": "type_cotisation", "code_cotisation": "type_cotisation",
    "rubrique": "type_cotisation", "libelle": "type_cotisation",
    "libelle_cotisation": "type_cotisation", "nature_cotisation": "type_cotisation",
    "code_rubrique": "type_cotisation", "libelle_rubrique": "type_cotisation",
    "intitule_rubrique": "type_cotisation", "designation": "type_cotisation",
    "code_caisse": "type_cotisation", "nature": "type_cotisation",
    "libelle_charge": "type_cotisation", "type_charge": "type_cotisation",
    "code_organisme": "type_cotisation", "libelle_organisme": "type_cotisation",
    "deduction_code": "type_cotisation", "deduction_description": "type_cotisation",
    # Heures
    "heures": "heures", "heures_travaillees": "heures", "nb_heures": "heures",
    "h_travaillees": "heures", "horaire": "heures", "heures_mensuelles": "heures",
    "heures_remunerees": "heures", "heures_payees": "heures", "nbre_heures": "heures",
    "hours_worked": "heures", "total_hours": "heures",
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
    # Convention collective / NAF
    "convention_collective": "convention_collective", "ccn": "convention_collective",
    "idcc": "idcc", "code_idcc": "idcc", "numero_idcc": "idcc",
    "code_naf": "code_naf", "naf": "code_naf", "ape": "code_naf",
    "code_ape": "code_naf",
    # Employeur
    "siret": "siret", "siren": "siren", "raison_sociale": "raison_sociale",
    "entreprise": "raison_sociale", "societe": "raison_sociale",
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
                if ";" in first_line:
                    class _SemiDialect(csv.excel):
                        delimiter = ";"
                    dialect = _SemiDialect()
                elif "\t" in first_line:
                    dialect = csv.excel_tab
                else:
                    dialect = csv.excel
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
            # NB: ne PAS muter csv.excel (singleton global), creer un dialect local
            first_line = contenu.split("\n", 1)[0]
            if ";" in first_line:
                class _SemicolonDialect(csv.excel):
                    delimiter = ";"
                dialect = _SemicolonDialect()
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

        # Extraire CCN/IDCC/NAF si present dans les colonnes
        ccn_detectee = ""
        idcc_detecte = ""
        naf_detecte = ""
        for row_data in csv.DictReader(io.StringIO(contenu), dialect=dialect):
            for col_csv, champ in col_map.items():
                val = row_data.get(col_csv, "").strip()
                if not val:
                    continue
                if champ == "convention_collective" and not ccn_detectee:
                    ccn_detectee = val
                elif champ == "idcc" and not idcc_detecte:
                    idcc_detecte = val
                elif champ == "code_naf" and not naf_detecte:
                    naf_detecte = val
            if ccn_detectee or idcc_detecte or naf_detecte:
                break  # Found at least one, no need to scan all rows

        # Ajouter metadata avec type_document
        declaration.metadata = declaration.metadata or {}
        declaration.metadata["type_document"] = type_document
        declaration.metadata["colonnes_detectees"] = list(col_map.values())
        declaration.metadata["nb_lignes_parsees"] = len(cotisations)
        if est_recapitulatif:
            declaration.metadata["format_recapitulatif"] = True
        if ccn_detectee:
            declaration.metadata["convention_collective"] = ccn_detectee
        if idcc_detecte:
            declaration.metadata["idcc"] = idcc_detecte
        if naf_detecte:
            declaration.metadata["code_naf"] = naf_detecte

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
        # Remove accents for matching
        for a, b in [("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"),
                      ("à", "a"), ("â", "a"), ("ô", "o"), ("î", "i"),
                      ("ù", "u"), ("û", "u"), ("ç", "c"), ("ï", "i")]:
            v = v.replace(a, b)
        # Order matters: more specific patterns first
        mapping = [
            # Vieillesse (before maladie to avoid false match)
            ("vieillesse plafonnee", ContributionType.VIEILLESSE_PLAFONNEE),
            ("vieillesse plaf", ContributionType.VIEILLESSE_PLAFONNEE),
            ("vieil. plaf", ContributionType.VIEILLESSE_PLAFONNEE),
            ("vieillesse deplafonnee", ContributionType.VIEILLESSE_DEPLAFONNEE),
            ("vieillesse deplaf", ContributionType.VIEILLESSE_DEPLAFONNEE),
            ("vieil. deplaf", ContributionType.VIEILLESSE_DEPLAFONNEE),
            ("vieillesse tot", ContributionType.VIEILLESSE_DEPLAFONNEE),
            # CSG / CRDS (before generic patterns)
            ("csg non deductible", ContributionType.CSG_NON_DEDUCTIBLE),
            ("csg non ded", ContributionType.CSG_NON_DEDUCTIBLE),
            ("csg imposable", ContributionType.CSG_NON_DEDUCTIBLE),
            ("csg deductible", ContributionType.CSG_DEDUCTIBLE),
            ("csg ded", ContributionType.CSG_DEDUCTIBLE),
            ("csg", ContributionType.CSG_DEDUCTIBLE),
            ("crds", ContributionType.CRDS),
            # Maladie
            ("maladie", ContributionType.MALADIE),
            ("mal.", ContributionType.MALADIE),
            ("mmid", ContributionType.MALADIE),
            ("invalidite deces", ContributionType.MALADIE),
            # Allocations familiales
            ("allocations familiales", ContributionType.ALLOCATIONS_FAMILIALES),
            ("alloc. fam", ContributionType.ALLOCATIONS_FAMILIALES),
            ("alloc fam", ContributionType.ALLOCATIONS_FAMILIALES),
            ("af ", ContributionType.ALLOCATIONS_FAMILIALES),
            # AT/MP
            ("accident travail", ContributionType.ACCIDENT_TRAVAIL),
            ("accident du travail", ContributionType.ACCIDENT_TRAVAIL),
            ("at/mp", ContributionType.ACCIDENT_TRAVAIL),
            ("at mp", ContributionType.ACCIDENT_TRAVAIL),
            ("risque professionnel", ContributionType.ACCIDENT_TRAVAIL),
            # Chomage / AGS
            ("assurance chomage", ContributionType.ASSURANCE_CHOMAGE),
            ("chomage", ContributionType.ASSURANCE_CHOMAGE),
            ("pole emploi", ContributionType.ASSURANCE_CHOMAGE),
            ("france travail", ContributionType.ASSURANCE_CHOMAGE),
            ("ags", ContributionType.AGS),
            ("garantie salaires", ContributionType.AGS),
            # FNAL
            ("fnal", ContributionType.FNAL),
            ("aide au logement", ContributionType.FNAL),
            # Formation / Apprentissage
            ("formation professionnelle", ContributionType.FORMATION_PROFESSIONNELLE),
            ("formation pro", ContributionType.FORMATION_PROFESSIONNELLE),
            ("contribution formation", ContributionType.FORMATION_PROFESSIONNELLE),
            ("taxe apprentissage", ContributionType.TAXE_APPRENTISSAGE),
            ("taxe d'apprentissage", ContributionType.TAXE_APPRENTISSAGE),
            ("contribution suppl", ContributionType.TAXE_APPRENTISSAGE),
            ("csa", ContributionType.TAXE_APPRENTISSAGE),
            # Retraite complementaire
            ("agirc-arrco t2", ContributionType.RETRAITE_COMPLEMENTAIRE_T2),
            ("agirc-arrco tranche 2", ContributionType.RETRAITE_COMPLEMENTAIRE_T2),
            ("agirc arrco t2", ContributionType.RETRAITE_COMPLEMENTAIRE_T2),
            ("retraite compl t2", ContributionType.RETRAITE_COMPLEMENTAIRE_T2),
            ("tranche 2", ContributionType.RETRAITE_COMPLEMENTAIRE_T2),
            ("agirc-arrco t1", ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
            ("agirc-arrco tranche 1", ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
            ("agirc arrco t1", ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
            ("retraite compl t1", ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
            ("tranche 1", ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
            ("retraite complementaire", ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
            ("ret. compl", ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
            ("agirc", ContributionType.RETRAITE_COMPLEMENTAIRE_T2),
            ("arrco", ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
            # CEG / CET
            ("ceg t2", ContributionType.CEG_T2),
            ("ceg t1", ContributionType.CEG_T1),
            ("ceg", ContributionType.CEG_T1),
            ("cet 2", ContributionType.CET),
            ("cet", ContributionType.CET),
            # APEC
            ("apec", ContributionType.APEC),
            # Prevoyance / Mutuelle
            ("prevoyance cadre", ContributionType.PREVOYANCE_CADRE),
            ("prevoyance art 7", ContributionType.PREVOYANCE_CADRE),
            ("deces cadre", ContributionType.PREVOYANCE_CADRE),
            ("prevoyance", ContributionType.PREVOYANCE_NON_CADRE),
            ("incapacite", ContributionType.PREVOYANCE_NON_CADRE),
            ("mutuelle", ContributionType.MUTUELLE_OBLIGATOIRE),
            ("complementaire sante", ContributionType.MUTUELLE_OBLIGATOIRE),
            ("frais de sante", ContributionType.MUTUELLE_OBLIGATOIRE),
            ("sante", ContributionType.MUTUELLE_OBLIGATOIRE),
            # Transport
            ("versement mobilite", ContributionType.VERSEMENT_MOBILITE),
            ("versement transport", ContributionType.VERSEMENT_MOBILITE),
            ("mobilite", ContributionType.VERSEMENT_MOBILITE),
            # Reduction
            ("reduction generale", ContributionType.LOI_FILLON),
            ("reduction fillon", ContributionType.LOI_FILLON),
            ("allègement", ContributionType.LOI_FILLON),
            ("allegement", ContributionType.LOI_FILLON),
        ]
        for pattern, ct in mapping:
            if pattern in v:
                return ct
        return ContributionType.MALADIE  # fallback
