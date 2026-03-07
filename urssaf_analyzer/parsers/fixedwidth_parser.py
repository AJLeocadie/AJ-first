"""Parseur pour les fichiers a largeur fixe (exports comptables).

Formats supportes :
- SAGE PNM (.pnm, .txt) : export comptable a champs fixes
  Structure: journal(3) date(6, JJMMAA) type(2) compte(13) tiers_flag(1)
  tiers(13) piece(13) libelle(25) mode_paiement(1) echeance(6) debit(13.2) credit(13.2)

- CIEL XIMPORT (.txt) : fichier SDF sans delimiteur, max 137 car/ligne
  Structure: n_mouvement(5) journal(2) date(8, AAAAMMJJ) echeance(8) piece(12)
  compte(11) libelle(25) montant(13.2) sens(1, D/C) pointage(12)
  analytique(6) libelle_compte(34) euro(1)
"""

import logging
import re
from decimal import Decimal
from datetime import date
from pathlib import Path
from typing import Any

from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import Document, Declaration, Cotisation
from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.utils.number_utils import parser_montant

logger = logging.getLogger(__name__)


# ============================================================
# SAGE PNM - Champs fixes
# ============================================================

# Positions (0-indexed, debut:fin)
_SAGE_PNM_FIELDS = {
    "journal":        (0, 3),
    "date":           (3, 9),     # JJMMAA
    "type_ligne":     (9, 11),    # OD, AN, etc.
    "compte":         (11, 24),
    "flag_tiers":     (24, 25),   # X si tiers
    "tiers":          (25, 38),
    "piece":          (38, 51),
    "libelle":        (51, 76),
    "mode_paiement":  (76, 77),
    "echeance":       (77, 83),   # JJMMAA
    "debit":          (83, 96),   # 13 car, 2 dec
    "credit":         (96, 109),  # 13 car, 2 dec
}
_SAGE_PNM_LINE_LEN = 109

# ============================================================
# CIEL XIMPORT - Champs fixes
# ============================================================

_CIEL_FIELDS = {
    "n_mouvement":    (0, 5),
    "journal":        (5, 7),
    "date":           (7, 15),    # AAAAMMJJ
    "echeance":       (15, 23),   # AAAAMMJJ
    "piece":          (23, 35),
    "compte":         (35, 46),
    "libelle":        (46, 71),
    "montant":        (71, 84),   # 13 car, 2 dec
    "sens":           (84, 85),   # D ou C
    "pointage":       (85, 97),
    "analytique":     (97, 103),
    "libelle_compte": (103, 137),
}
_CIEL_LINE_LEN_MIN = 85   # Minimum pour lire jusqu'au sens D/C
_CIEL_LINE_LEN_MAX = 141  # Version 2003 avec code euro + version


def _parse_sage_date(s: str) -> date | None:
    """Parse JJMMAA en date."""
    s = s.strip()
    if len(s) != 6 or not s.isdigit():
        return None
    try:
        jj, mm, aa = int(s[:2]), int(s[2:4]), int(s[4:6])
        annee = 2000 + aa if aa < 50 else 1900 + aa
        return date(annee, mm, jj)
    except (ValueError, TypeError):
        return None


def _parse_ciel_date(s: str) -> date | None:
    """Parse AAAAMMJJ en date."""
    s = s.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, TypeError):
        return None


def _parse_fixed_montant(s: str) -> Decimal:
    """Parse un montant en champs fixe (espaces, virgule ou point)."""
    s = s.strip()
    if not s:
        return Decimal("0")
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except Exception as e:
        logger.debug("Echec conversion montant '%s': %s", s, e)
        return Decimal("0")


class FixedWidthParser(BaseParser):
    """Parse les fichiers comptables a largeur fixe (SAGE PNM, CIEL XIMPORT)."""

    def peut_traiter(self, chemin: Path) -> bool:
        ext = chemin.suffix.lower()
        if ext == ".pnm":
            return True
        if ext != ".txt":
            return False
        # Pour les .txt, verifier si c'est un format a largeur fixe
        try:
            with open(chemin, "r", encoding="cp1252", errors="replace") as f:
                lignes = [f.readline() for _ in range(5)]
            return self._detecter_format(lignes) is not None
        except Exception as e:
            logger.debug("Echec detection format fixedwidth pour %s: %s", chemin.name, e)
            return False

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        try:
            contenu = self._lire(chemin)
            lignes = contenu.split("\n")
            fmt = self._detecter_format(lignes[:10])
            return {
                "format": f"fixedwidth_{fmt or 'inconnu'}",
                "nb_lignes": len(lignes),
                "logiciel": fmt or "inconnu",
            }
        except Exception as e:
            return {"format": "fixedwidth", "erreur": str(e)}

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        self._verifier_taille_fichier(chemin)
        contenu = self._lire(chemin)
        lignes = contenu.split("\n")

        if not lignes:
            raise ParseError(f"Fichier vide: {chemin}")

        fmt = self._detecter_format(lignes[:10])

        if fmt == "sage_pnm":
            return self._parser_sage_pnm(lignes, document)
        elif fmt == "ciel_ximport":
            return self._parser_ciel_ximport(lignes, document)
        else:
            raise ParseError(f"Format a largeur fixe non reconnu: {chemin}")

    # ============================================================

    def _detecter_format(self, lignes: list[str]) -> str | None:
        """Detecte le format a partir des premieres lignes."""
        if not lignes:
            return None

        # Ignorer les lignes vides
        non_vides = [l for l in lignes if l.strip()]
        if not non_vides:
            return None

        # SAGE PNM: lignes de ~109 caracteres, commence par 3 car journal + 6 chiffres date
        sage_count = 0
        for l in non_vides[:5]:
            if len(l.rstrip()) >= 80:
                # Verifier si positions 3-9 sont des chiffres (date JJMMAA)
                if len(l) >= 9 and l[3:9].strip().isdigit():
                    sage_count += 1
        if sage_count >= 2:
            return "sage_pnm"

        # CIEL XIMPORT: lignes de 85-141 car, positions 0-5 numeriques,
        # positions 7-15 date AAAAMMJJ, position 84 = D ou C
        ciel_count = 0
        for l in non_vides[:5]:
            if _CIEL_LINE_LEN_MIN <= len(l.rstrip()) <= _CIEL_LINE_LEN_MAX:
                if (len(l) >= 85
                        and l[:5].strip().isdigit()
                        and l[7:15].strip().isdigit()
                        and l[84:85] in ("D", "C")):
                    ciel_count += 1
        if ciel_count >= 2:
            return "ciel_ximport"

        return None

    def _parser_sage_pnm(self, lignes: list[str], document: Document) -> list[Declaration]:
        """Parse un export SAGE PNM."""
        doc_id = document.id
        cotisations = []
        raison_sociale = ""
        journaux = set()

        # Premiere ligne = nom de la societe (max 30 car, pas de structure fixe)
        if lignes and not lignes[0][3:9].strip().isdigit():
            raison_sociale = lignes[0].strip()[:100]
            lignes = lignes[1:]

        for i, ligne in enumerate(lignes, start=2):
            if not ligne.strip() or len(ligne.rstrip()) < 80:
                continue

            try:
                fields = {}
                for name, (start, end) in _SAGE_PNM_FIELDS.items():
                    if end <= len(ligne):
                        fields[name] = ligne[start:end].strip()

                journal = fields.get("journal", "")
                compte = fields.get("compte", "")
                libelle = fields.get("libelle", "")
                debit = _parse_fixed_montant(fields.get("debit", ""))
                credit = _parse_fixed_montant(fields.get("credit", ""))
                dt = _parse_sage_date(fields.get("date", ""))

                if journal:
                    journaux.add(journal)

                if debit > 0 or credit > 0:
                    cot = Cotisation(
                        source_document_id=doc_id,
                        base_brute=debit if debit > 0 else credit,
                        montant_patronal=debit,
                        montant_salarial=credit,
                    )
                    cotisations.append(cot)

            except Exception as e:
                logger.debug("Echec parsing ligne PNM: %s", e)
                continue

        total_debit = sum(c.montant_patronal for c in cotisations)
        total_credit = sum(c.montant_salarial for c in cotisations)

        decl = Declaration(
            type_declaration="export_comptable",
            reference=document.nom_fichier,
            masse_salariale_brute=total_debit,
            cotisations=cotisations,
            source_document_id=doc_id,
            metadata={
                "type_document": "export_comptable_sage_pnm",
                "logiciel": "sage",
                "raison_sociale": raison_sociale,
                "nb_ecritures": len(cotisations),
                "journaux": sorted(journaux),
                "total_debit": float(total_debit),
                "total_credit": float(total_credit),
                "ecart": float(total_debit - total_credit),
            },
        )
        return [decl]

    def _parser_ciel_ximport(self, lignes: list[str], document: Document) -> list[Declaration]:
        """Parse un fichier CIEL XIMPORT."""
        doc_id = document.id
        cotisations = []
        journaux = set()

        for i, ligne in enumerate(lignes, start=1):
            if not ligne.strip() or len(ligne.rstrip()) < _CIEL_LINE_LEN_MIN:
                continue

            try:
                fields = {}
                for name, (start, end) in _CIEL_FIELDS.items():
                    if end <= len(ligne):
                        fields[name] = ligne[start:end].strip()
                    elif start < len(ligne):
                        fields[name] = ligne[start:].strip()

                journal = fields.get("journal", "")
                compte = fields.get("compte", "")
                libelle = fields.get("libelle", "")
                montant = _parse_fixed_montant(fields.get("montant", ""))
                sens = fields.get("sens", "")

                if journal:
                    journaux.add(journal)

                if montant > 0:
                    debit = montant if sens == "D" else Decimal("0")
                    credit = montant if sens == "C" else Decimal("0")
                    cot = Cotisation(
                        source_document_id=doc_id,
                        base_brute=montant,
                        montant_patronal=debit,
                        montant_salarial=credit,
                    )
                    cotisations.append(cot)

            except Exception as e:
                logger.debug("Echec parsing ligne XIMPORT: %s", e)
                continue

        total_debit = sum(c.montant_patronal for c in cotisations)
        total_credit = sum(c.montant_salarial for c in cotisations)

        decl = Declaration(
            type_declaration="export_comptable",
            reference=document.nom_fichier,
            masse_salariale_brute=total_debit,
            cotisations=cotisations,
            source_document_id=doc_id,
            metadata={
                "type_document": "export_comptable_ciel_ximport",
                "logiciel": "ciel",
                "nb_ecritures": len(cotisations),
                "journaux": sorted(journaux),
                "total_debit": float(total_debit),
                "total_credit": float(total_credit),
                "ecart": float(total_debit - total_credit),
            },
        )
        return [decl]

    @staticmethod
    def _lire(chemin: Path) -> str:
        """Lit le fichier avec detection d'encodage (SAGE=cp1252, CIEL=iso-8859-1)."""
        for enc in ("cp1252", "iso-8859-1", "utf-8-sig", "utf-8", "latin-1"):
            try:
                return chemin.read_text(encoding=enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return chemin.read_text(encoding="latin-1", errors="replace")
