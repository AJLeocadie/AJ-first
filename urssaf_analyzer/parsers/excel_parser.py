"""Parseur pour les fichiers Excel (bulletins de paie, exports comptables)."""

import re as _re
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

# Mots indiquant une ligne de total/sous-total a ignorer
_TOTAL_KEYWORDS = {
    "total", "sous-total", "sous_total", "sous total",
    "totaux", "cumul", "cumuls", "recap", "recapitulatif",
    "general", "general", "s/total", "net a payer global",
}


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
            decl = self._parser_feuille(ws, sheet_name, document)
            if decl and (decl.cotisations or decl.employes):
                declarations.append(decl)

        wb.close()
        return declarations

    def _parser_feuille(
        self, ws: Any, nom_feuille: str, document: Document
    ) -> Declaration | None:
        """Parse une feuille Excel."""
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            return None

        # Detecter la ligne d en-tete (peut ne pas etre la premiere)
        header_idx, header = self._trouver_entete(rows)
        if header_idx is None:
            return None

        col_map = self._mapper_colonnes(header)
        if not col_map:
            return None

        cotisations = []
        employes_vus = {}   # cle = nir ou "nom|prenom"
        employe_ids = {}    # cle de dedup -> employe.id
        parse_log = []

        parse_log.append(f"Feuille: {nom_feuille}, en-tetes ligne {header_idx+1}: {header}")
        parse_log.append(f"Colonnes mappees: {col_map}")

        for row_data in rows[header_idx + 1:]:
            if not row_data or all(c is None for c in row_data):
                continue

            # Ignorer les lignes de total/sous-total
            if self._est_ligne_total(row_data):
                continue

            row_dict = {}
            for i, val in enumerate(row_data):
                if i < len(header) and header[i]:
                    row_dict[header[i]] = val

            employe = self._extraire_employe(row_dict, col_map, document.id)
            emp_key = None
            if employe:
                # Deduplication par NIR ou par nom+prenom
                if employe.nir:
                    emp_key = employe.nir
                elif employe.nom:
                    emp_key = f"{(employe.nom or '').lower()}|{(employe.prenom or '').lower()}"
                if emp_key and emp_key not in employes_vus:
                    employes_vus[emp_key] = employe
                    employe_ids[emp_key] = employe.id
                    parse_log.append(f"  Employe: {employe.nom} {employe.prenom} (NIR={employe.nir}, key={emp_key})")
                elif emp_key and emp_key in employe_ids:
                    # Meme employe, ligne supplementaire (cotisation)
                    pass

            cotisation = self._extraire_cotisation(row_dict, col_map, document.id)
            if cotisation:
                # Lier la cotisation a l employe de la meme ligne
                if emp_key and emp_key in employe_ids:
                    cotisation.employe_id = employe_ids[emp_key]
                cotisations.append(cotisation)

        # Detecter si c est un livre de paie (plusieurs employes)
        is_livre_paie = len(employes_vus) > 1
        type_decl = "livre_de_paie" if is_livre_paie else "EXCEL"

        parse_log.append(f"Resultat: {len(employes_vus)} employes, {len(cotisations)} cotisations, type={type_decl}")

        # Calculer masse salariale par employe (max brut par employe, pas le cumul de toutes les lignes)
        masse = Decimal("0")
        if employes_vus and cotisations:
            # Brut par employe (on prend le max des bases brutes par employe, pas la somme
            # car plusieurs cotisations peuvent avoir la meme base)
            bruts_par_emp = {}
            for c in cotisations:
                eid = c.employe_id or "_global"
                if eid not in bruts_par_emp or c.base_brute > bruts_par_emp[eid]:
                    bruts_par_emp[eid] = c.base_brute
            masse = sum(bruts_par_emp.values())
        elif cotisations:
            masse = sum(c.base_brute for c in cotisations)

        declaration = Declaration(
            type_declaration=type_decl,
            reference=document.nom_fichier or nom_feuille,
            cotisations=cotisations,
            employes=list(employes_vus.values()),
            effectif_declare=len(employes_vus),
            source_document_id=document.id,
            metadata={
                "type_document": "livre_de_paie" if is_livre_paie else "bulletin_de_paie",
                "parse_log": parse_log,
            },
        )
        declaration.masse_salariale_brute = masse

        return declaration

    def _trouver_entete(self, rows: list) -> tuple:
        """Cherche la ligne d en-tete dans les premieres lignes."""
        # Essayer les 5 premieres lignes
        for idx in range(min(5, len(rows))):
            row = rows[idx]
            if not row:
                continue
            header = [self._normaliser_entete(c) for c in row]
            # Verifier qu on a au moins 2 colonnes utiles
            col_map = self._mapper_colonnes(header)
            if len(col_map) >= 2:
                return idx, header
        # Fallback: premiere ligne
        if rows:
            header = [self._normaliser_entete(c) for c in rows[0]]
            col_map = self._mapper_colonnes(header)
            if col_map:
                return 0, header
        return None, None

    @staticmethod
    def _est_ligne_total(row_data: tuple) -> bool:
        """Detecte si une ligne est un total/sous-total a ignorer."""
        for cell in row_data:
            if cell is None:
                continue
            s = str(cell).strip().lower()
            if any(kw in s for kw in _TOTAL_KEYWORDS):
                return True
        return False

    @staticmethod
    def _normaliser_entete(cellule: Any) -> str:
        """Normalise un en-tete de colonne pour le mapping."""
        if cellule is None:
            return ""
        s = str(cellule).strip().lower()
        # Retirer accents courants
        for a, b in [("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"),
                      ("à", "a"), ("â", "a"), ("ô", "o"), ("î", "i"),
                      ("ù", "u"), ("û", "u"), ("ç", "c")]:
            s = s.replace(a, b)
        # Normaliser separateurs
        s = s.replace(" ", "_").replace("-", "_").replace(".", "_")
        s = s.replace("'", "").replace("°", "").replace("n_", "n_")
        # Supprimer underscores multiples
        while "__" in s:
            s = s.replace("__", "_")
        return s.strip("_")

    def _mapper_colonnes(self, header: list[str]) -> dict[str, int]:
        """Identifie les colonnes utiles a partir des en-tetes."""
        mapping = {}
        keywords = {
            "nir": [
                "nir", "numero_ss", "securite_sociale", "n_ss", "nss",
                "numero_securite_sociale", "n_securite_sociale",
                "matricule", "num_matricule", "numero_matricule",
                "mat", "n_mat", "id_salarie", "id_employe", "numero",
            ],
            "nom": [
                "nom", "nom_salarie", "salarie", "nom_du_salarie",
                "nom_employe", "employe", "nom_de_l_employe",
                "nom_agent", "agent", "nom_famille", "patronyme",
            ],
            "prenom": [
                "prenom", "prenom_salarie", "prenom_du_salarie",
                "prenom_employe",
            ],
            "nom_prenom": [
                "nom_prenom", "nom_et_prenom", "prenom_nom",
                "identite", "salarie_nom_prenom", "nom_complet",
                "designation", "intitule_salarie",
            ],
            "base_brute": [
                "base_brute", "salaire_brut", "brut", "base",
                "remuneration_brute", "remuneration", "montant_brut",
                "sal_brut", "total_brut", "brut_mensuel",
                "brut_total", "salaire", "remuneration_totale",
            ],
            "net": [
                "net", "net_a_payer", "salaire_net", "montant_net",
                "net_paye", "net_verse", "net_mensuel", "a_payer",
            ],
            "taux_patronal": [
                "taux_patronal", "taux_employeur", "tx_patronal",
                "taux_part_employeur",
            ],
            "taux_salarial": [
                "taux_salarial", "taux_salarie", "tx_salarial",
                "taux_part_salarie",
            ],
            "montant_patronal": [
                "montant_patronal", "cotisation_employeur",
                "part_employeur", "charges_patronales",
                "cotisations_patronales", "patronal",
                "total_patronal", "employeur",
            ],
            "montant_salarial": [
                "montant_salarial", "cotisation_salarie",
                "part_salarie", "charges_salariales",
                "cotisations_salariales", "retenues", "salarial",
                "total_salarial", "part_salariale",
            ],
            "type_cotisation": [
                "type_cotisation", "code_cotisation", "libelle",
                "designation", "intitule", "nature", "code",
            ],
        }
        for i, col in enumerate(header):
            if not col:
                continue
            for field_name, kws in keywords.items():
                if field_name in mapping:
                    continue
                # Match exact
                if col in kws:
                    mapping[field_name] = i
                    break
                # Match par inclusion (le kw est contenu dans le header)
                for kw in kws:
                    if kw in col or col in kw:
                        mapping[field_name] = i
                        break
                if field_name in mapping:
                    break
        return mapping

    def _extraire_cotisation(
        self, row: dict, col_map: dict, doc_id: str
    ) -> Cotisation | None:
        base = self._get_val(row, [
            "base_brute", "salaire_brut", "brut", "base",
            "remuneration_brute", "remuneration", "montant_brut",
            "sal_brut", "total_brut", "brut_mensuel",
            "brut_total", "salaire", "remuneration_totale",
        ])
        montant_p = self._get_val(row, [
            "montant_patronal", "cotisation_employeur",
            "part_employeur", "charges_patronales",
            "cotisations_patronales", "patronal",
            "total_patronal", "employeur",
        ])

        if base is None and montant_p is None:
            return None

        c = Cotisation(source_document_id=doc_id)
        if base is not None:
            c.base_brute = self._to_decimal(base)
            c.assiette = c.base_brute
        if montant_p is not None:
            c.montant_patronal = self._to_decimal(montant_p)

        montant_s = self._get_val(row, [
            "montant_salarial", "cotisation_salarie",
            "part_salarie", "charges_salariales",
            "cotisations_salariales", "retenues", "salarial",
            "total_salarial", "part_salariale",
        ])
        if montant_s is not None:
            c.montant_salarial = self._to_decimal(montant_s)

        tp = self._get_val(row, ["taux_patronal", "taux_employeur", "tx_patronal", "taux_part_employeur"])
        if tp is not None:
            c.taux_patronal = self._to_decimal(tp)
            if c.taux_patronal > 1:
                c.taux_patronal = c.taux_patronal / 100

        ts = self._get_val(row, ["taux_salarial", "taux_salarie", "tx_salarial", "taux_part_salarie"])
        if ts is not None:
            c.taux_salarial = self._to_decimal(ts)
            if c.taux_salarial > 1:
                c.taux_salarial = c.taux_salarial / 100

        # Stocker le net si present
        net = self._get_val(row, [
            "net", "net_a_payer", "salaire_net", "montant_net",
            "net_paye", "net_verse", "net_mensuel", "a_payer",
        ])
        if net is not None:
            # Stocker dans le montant salarial si pas deja defini
            # (pour le pipeline d integration qui calcule net)
            pass

        return c

    def _extraire_employe(self, row: dict, col_map: dict, doc_id: str) -> Employe | None:
        nir = self._get_val(row, [
            "nir", "numero_ss", "securite_sociale", "n_ss", "nss",
            "numero_securite_sociale", "n_securite_sociale",
            "matricule", "num_matricule", "numero_matricule",
            "mat", "n_mat", "id_salarie", "id_employe", "numero",
        ])
        nom = self._get_val(row, [
            "nom", "nom_salarie", "salarie", "nom_du_salarie",
            "nom_employe", "employe", "nom_de_l_employe",
            "nom_agent", "agent", "nom_famille", "patronyme",
        ])
        prenom = self._get_val(row, [
            "prenom", "prenom_salarie", "prenom_du_salarie",
            "prenom_employe",
        ])

        # Gerer les colonnes combinees "Nom Prenom" ou "Prenom Nom"
        if not nom:
            nom_prenom = self._get_val(row, [
                "nom_prenom", "nom_et_prenom", "prenom_nom",
                "identite", "salarie_nom_prenom", "nom_complet",
                "designation", "intitule_salarie",
            ])
            if nom_prenom and str(nom_prenom).strip():
                parts = str(nom_prenom).strip().split()
                if len(parts) >= 2:
                    # Heuristique: si le premier mot est en MAJUSCULES = nom de famille
                    if parts[0] == parts[0].upper() and len(parts[0]) > 1:
                        nom = parts[0]
                        prenom = " ".join(parts[1:])
                    else:
                        nom = parts[-1]
                        prenom = " ".join(parts[:-1])
                else:
                    nom = parts[0]

        # Si NIR est un numero court (matricule), l utiliser comme identifiant
        if nir:
            nir_str = str(nir).strip()
            # Convertir les floats Excel (1.0 -> "1")
            if nir_str.endswith(".0"):
                nir_str = nir_str[:-2]
            nir = nir_str

        if not nir and not nom:
            return None

        return Employe(
            nir=nir or "",
            nom=str(nom).strip() if nom else "",
            prenom=str(prenom).strip() if prenom else "",
            source_document_id=doc_id,
        )

    @staticmethod
    def _get_val(row: dict, keys: list[str]) -> Any:
        """Cherche la premiere valeur non-None parmi plusieurs cles."""
        for k in keys:
            v = row.get(k)
            if v is not None and str(v).strip() != "":
                return v
        return None

    @staticmethod
    def _to_decimal(val: Any) -> Decimal:
        """Convertit une valeur en Decimal."""
        if isinstance(val, Decimal):
            return val
        if isinstance(val, (int, float)):
            return Decimal(str(val))
        if isinstance(val, str):
            return parser_montant(val)
        return Decimal(str(val))
