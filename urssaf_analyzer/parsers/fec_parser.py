"""Parseur pour les fichiers FEC (Fichier des Ecritures Comptables).

Format reglementaire defini par l'Art. L.47 A-I du Livre des Procedures Fiscales.
Non-presentation = amende 5 000 EUR (art. 1729 D CGI).

Le FEC est un fichier texte a champs separes (tabulation ou pipe) avec 18 colonnes
obligatoires dans un ordre precis.
"""

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import Document, Declaration, Cotisation
from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.utils.date_utils import parser_date
from urssaf_analyzer.utils.number_utils import parser_montant

# Les 18 colonnes obligatoires du FEC (art. A.47 A-1 LPF)
COLONNES_FEC = [
    "JournalCode",
    "JournalLib",
    "EcritureNum",
    "EcritureDate",
    "CompteNum",
    "CompteLib",
    "CompAuxNum",
    "CompAuxLib",
    "PieceRef",
    "PieceDate",
    "EcritureLib",
    "Debit",
    "Credit",
    "EcrtureLet",
    "DateLet",
    "ValidDate",
    "Montantdevise",
    "Idevise",
]

# Noms alternatifs acceptes (tolerant aux variantes mineures)
COLONNES_FEC_ALT = {
    "journalcode": "JournalCode",
    "journal_code": "JournalCode",
    "journallib": "JournalLib",
    "journal_lib": "JournalLib",
    "ecriturenum": "EcritureNum",
    "ecriture_num": "EcritureNum",
    "ecrituredate": "EcritureDate",
    "ecriture_date": "EcritureDate",
    "comptenum": "CompteNum",
    "compte_num": "CompteNum",
    "comptelib": "CompteLib",
    "compte_lib": "CompteLib",
    "compauxnum": "CompAuxNum",
    "comp_aux_num": "CompAuxNum",
    "compauxlib": "CompAuxLib",
    "comp_aux_lib": "CompAuxLib",
    "pieceref": "PieceRef",
    "piece_ref": "PieceRef",
    "piecedate": "PieceDate",
    "piece_date": "PieceDate",
    "ecriturelib": "EcritureLib",
    "ecriture_lib": "EcritureLib",
    "debit": "Debit",
    "credit": "Credit",
    "ecrturelet": "EcrtureLet",
    "ecriture_let": "EcrtureLet",
    "ecriturelet": "EcrtureLet",
    "datelet": "DateLet",
    "date_let": "DateLet",
    "validdate": "ValidDate",
    "valid_date": "ValidDate",
    "montantdevise": "Montantdevise",
    "montant_devise": "Montantdevise",
    "idevise": "Idevise",
}


def _parser_date_fec(val: str) -> date | None:
    """Parse une date au format FEC (YYYYMMDD ou YYYY-MM-DD ou DD/MM/YYYY)."""
    if not val or not val.strip():
        return None
    val = val.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    # Fallback vers le parser generique
    return parser_date(val)


def _parser_montant_fec(val: str) -> Decimal:
    """Parse un montant FEC (accepte virgule ou point comme separateur decimal)."""
    if not val or not val.strip():
        return Decimal("0.00")
    val = val.strip().replace(" ", "")
    # Format francais : virgule decimale
    if "," in val and "." in val:
        # ex: 1.234,56 -> 1234.56
        val = val.replace(".", "").replace(",", ".")
    elif "," in val:
        val = val.replace(",", ".")
    try:
        return Decimal(val)
    except InvalidOperation:
        return Decimal("0.00")


def detecter_fec(chemin: Path) -> bool:
    """Detecte si un fichier est un FEC en analysant ses en-tetes."""
    try:
        with open(chemin, "r", encoding="utf-8-sig") as f:
            premiere_ligne = f.readline()
    except (UnicodeDecodeError, OSError):
        try:
            with open(chemin, "r", encoding="latin-1") as f:
                premiere_ligne = f.readline()
        except OSError:
            return False

    if not premiere_ligne:
        return False

    # Detecter le separateur
    for sep in ("\t", "|", ";"):
        colonnes = [c.strip().lower() for c in premiere_ligne.split(sep)]
        if len(colonnes) >= 15:
            # Verifier que les colonnes FEC essentielles sont presentes
            colonnes_norm = set()
            for c in colonnes:
                if c in COLONNES_FEC_ALT:
                    colonnes_norm.add(COLONNES_FEC_ALT[c])
                elif c in {x.lower() for x in COLONNES_FEC}:
                    colonnes_norm.add(c.title() if c[0].islower() else c)
            essentielles = {"JournalCode", "EcritureNum", "CompteNum", "Debit", "Credit"}
            if essentielles.issubset(colonnes_norm) or len(colonnes_norm) >= 10:
                return True
    return False


class FECParser(BaseParser):
    """Parse les fichiers FEC conformes a l'art. L.47 A-I LPF."""

    def peut_traiter(self, chemin: Path) -> bool:
        ext = chemin.suffix.lower()
        if ext == ".fec":
            return True
        # Un fichier .txt ou .csv peut etre un FEC
        if ext in (".txt", ".csv"):
            return detecter_fec(chemin)
        return False

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        metadata = {"format": "fec"}
        try:
            contenu = self._lire_fichier(chemin)
            lignes = contenu.split("\n")
            metadata["nb_lignes"] = len(lignes) - 1  # -1 pour en-tete
            sep = self._detecter_separateur(lignes[0] if lignes else "")
            metadata["separateur"] = repr(sep)
            if lignes:
                colonnes = [c.strip() for c in lignes[0].split(sep)]
                metadata["colonnes"] = colonnes
                metadata["nb_colonnes"] = len(colonnes)
                conformite = self._verifier_conformite_colonnes(colonnes)
                metadata["colonnes_conformes"] = conformite["conformes"]
                metadata["colonnes_manquantes"] = conformite["manquantes"]
        except Exception as e:
            metadata["erreur_lecture"] = str(e)
        return metadata

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        contenu = self._lire_fichier(chemin)
        lignes = contenu.split("\n")
        if not lignes:
            raise ParseError(f"Fichier FEC vide: {chemin}")

        sep = self._detecter_separateur(lignes[0])
        header = [c.strip() for c in lignes[0].split(sep)]
        col_map = self._mapper_colonnes(header)

        # Verifier les colonnes obligatoires minimales
        obligatoires = {"JournalCode", "EcritureNum", "CompteNum", "Debit", "Credit"}
        presentes = set(col_map.values())
        manquantes = obligatoires - presentes
        if manquantes:
            raise ParseError(
                f"Colonnes FEC obligatoires manquantes: {', '.join(manquantes)}. "
                f"Fichier: {chemin}"
            )

        # Parser les ecritures
        ecritures_fec = []
        erreurs = []
        for i, ligne in enumerate(lignes[1:], start=2):
            ligne = ligne.strip()
            if not ligne:
                continue
            champs = ligne.split(sep)
            if len(champs) < len(obligatoires):
                erreurs.append(f"Ligne {i}: nombre de champs insuffisant ({len(champs)})")
                continue
            try:
                ecriture = self._parser_ligne_fec(champs, header, col_map, i)
                if ecriture:
                    ecritures_fec.append(ecriture)
            except Exception as e:
                erreurs.append(f"Ligne {i}: {e}")

        # Convertir en Declaration(s) — regrouper par journal
        cotisations = []
        journaux_vus = set()
        comptes_vus = set()
        total_debit = Decimal("0")
        total_credit = Decimal("0")

        for ec in ecritures_fec:
            journaux_vus.add(ec.get("journal_code", ""))
            comptes_vus.add(ec.get("compte_num", ""))
            debit = ec.get("debit", Decimal("0"))
            credit = ec.get("credit", Decimal("0"))
            total_debit += debit
            total_credit += credit

            # Creer une Cotisation synthétique pour chaque ligne FEC
            cot = Cotisation(source_document_id=document.id)
            cot.base_brute = debit if debit > 0 else credit
            cot.assiette = cot.base_brute
            cot.montant_patronal = debit
            cot.montant_salarial = credit
            cotisations.append(cot)

        declaration = Declaration(
            type_declaration="FEC",
            reference=chemin.stem,
            cotisations=cotisations,
            employes=[],
            effectif_declare=0,
            source_document_id=document.id,
        )

        conformite = self._verifier_conformite_colonnes(header)

        declaration.metadata = declaration.metadata or {}
        declaration.metadata.update({
            "type_document": "fec",
            "format_fec": True,
            "nb_ecritures": len(ecritures_fec),
            "nb_journaux": len(journaux_vus),
            "journaux": sorted(journaux_vus),
            "nb_comptes": len(comptes_vus),
            "total_debit": float(total_debit),
            "total_credit": float(total_credit),
            "equilibre": abs(total_debit - total_credit) < Decimal("0.01"),
            "colonnes_conformes": conformite["conformes"],
            "colonnes_manquantes": conformite["manquantes"],
            "erreurs_parsing": erreurs[:20],  # limiter
            "ecritures_fec": ecritures_fec,
        })

        return [declaration]

    def _lire_fichier(self, chemin: Path) -> str:
        try:
            with open(chemin, "r", encoding="utf-8-sig") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(chemin, "r", encoding="latin-1") as f:
                return f.read()

    @staticmethod
    def _detecter_separateur(premiere_ligne: str) -> str:
        """Detecte le separateur du FEC (tab, pipe, ou point-virgule)."""
        for sep in ("\t", "|", ";"):
            if sep in premiere_ligne:
                return sep
        return "\t"  # defaut FEC = tabulation

    @staticmethod
    def _mapper_colonnes(header: list[str]) -> dict[int, str]:
        """Mappe les indices de colonnes vers les noms FEC standard."""
        col_map = {}
        for i, col in enumerate(header):
            col_lower = col.strip().lower()
            if col_lower in COLONNES_FEC_ALT:
                col_map[i] = COLONNES_FEC_ALT[col_lower]
            elif col.strip() in COLONNES_FEC:
                col_map[i] = col.strip()
            else:
                # Tentative de matching partiel
                for fec_col in COLONNES_FEC:
                    if fec_col.lower() == col_lower:
                        col_map[i] = fec_col
                        break
        return col_map

    def _parser_ligne_fec(
        self, champs: list[str], header: list[str], col_map: dict[int, str], num_ligne: int
    ) -> dict | None:
        """Parse une ligne FEC en dictionnaire structure."""
        ecriture = {}
        for i, val in enumerate(champs):
            if i not in col_map:
                continue
            nom = col_map[i]
            val = val.strip()
            ecriture[nom] = val

        # Convertir les types
        result = {
            "journal_code": ecriture.get("JournalCode", ""),
            "journal_lib": ecriture.get("JournalLib", ""),
            "ecriture_num": ecriture.get("EcritureNum", ""),
            "ecriture_date": None,
            "compte_num": ecriture.get("CompteNum", ""),
            "compte_lib": ecriture.get("CompteLib", ""),
            "comp_aux_num": ecriture.get("CompAuxNum", ""),
            "comp_aux_lib": ecriture.get("CompAuxLib", ""),
            "piece_ref": ecriture.get("PieceRef", ""),
            "piece_date": None,
            "ecriture_lib": ecriture.get("EcritureLib", ""),
            "debit": Decimal("0"),
            "credit": Decimal("0"),
            "ecrture_let": ecriture.get("EcrtureLet", ""),
            "date_let": None,
            "valid_date": None,
            "montant_devise": Decimal("0"),
            "idevise": ecriture.get("Idevise", ""),
            "ligne": num_ligne,
        }

        # Dates
        result["ecriture_date"] = _parser_date_fec(ecriture.get("EcritureDate", ""))
        result["piece_date"] = _parser_date_fec(ecriture.get("PieceDate", ""))
        result["date_let"] = _parser_date_fec(ecriture.get("DateLet", ""))
        result["valid_date"] = _parser_date_fec(ecriture.get("ValidDate", ""))

        # Montants
        result["debit"] = _parser_montant_fec(ecriture.get("Debit", ""))
        result["credit"] = _parser_montant_fec(ecriture.get("Credit", ""))
        result["montant_devise"] = _parser_montant_fec(ecriture.get("Montantdevise", ""))

        # Serialiser les dates pour JSON
        for key in ("ecriture_date", "piece_date", "date_let", "valid_date"):
            if result[key]:
                result[key] = result[key].isoformat()

        # Serialiser les Decimal pour JSON
        for key in ("debit", "credit", "montant_devise"):
            result[key] = float(result[key]) if isinstance(result[key], Decimal) else result[key]

        return result

    @staticmethod
    def _verifier_conformite_colonnes(header: list[str]) -> dict:
        """Verifie si les colonnes du fichier sont conformes au FEC."""
        header_lower = [c.strip().lower() for c in header]
        trouvees = set()
        for c in header_lower:
            if c in COLONNES_FEC_ALT:
                trouvees.add(COLONNES_FEC_ALT[c])
            else:
                for fec_col in COLONNES_FEC:
                    if fec_col.lower() == c:
                        trouvees.add(fec_col)
                        break

        manquantes = [c for c in COLONNES_FEC if c not in trouvees]
        return {
            "conformes": len(manquantes) == 0,
            "trouvees": sorted(trouvees),
            "manquantes": manquantes,
            "taux_conformite": round((len(trouvees) / len(COLONNES_FEC)) * 100, 1),
        }
