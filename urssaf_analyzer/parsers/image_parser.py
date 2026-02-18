"""Parseur d'images de bulletins de paie et documents sociaux.

Utilise le LecteurMultiFormat (OCR pytesseract si disponible,
extraction basique sinon) pour extraire le texte des images,
puis applique les memes regex que le PDF parser pour detecter
les donnees sociales.
"""

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.models.documents import (
    Document, Declaration, Employeur, Employe, Cotisation, DateRange,
)
from urssaf_analyzer.config.constants import ContributionType
from urssaf_analyzer.ocr.image_reader import LecteurMultiFormat, EXTENSIONS_IMAGES


# Regex d'extraction de donnees sociales depuis du texte OCR
_RE_SIRET = re.compile(r"(?:SIRET|siret)\s*[:\s]?\s*(\d[\d\s]{12}\d)", re.IGNORECASE)
_RE_SIREN = re.compile(r"(?:SIREN|siren)\s*[:\s]?\s*(\d{9})", re.IGNORECASE)
_RE_NIR = re.compile(r"\b([12]\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2})\b")
_RE_NOM = re.compile(r"(?:Nom|NOM)\s*[:\s]?\s*([A-Z\u00C0-\u00FF][A-Z\u00C0-\u00FF\s-]+)", re.IGNORECASE)
_RE_PRENOM = re.compile(r"(?:Prenom|PRENOM|Pr.nom)\s*[:\s]?\s*([A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF]+)", re.IGNORECASE)
_RE_BRUT = re.compile(r"(?:brut|salaire\s*brut|total\s*brut)\s*[:\s]?\s*([\d\s]+[.,]\d{2})", re.IGNORECASE)
_RE_NET = re.compile(r"(?:net\s*(?:a\s*payer|fiscal|imposable))\s*[:\s]?\s*([\d\s]+[.,]\d{2})", re.IGNORECASE)
_RE_APPRENTI = re.compile(r"(?:apprenti|apprentissage|alternance|alternant|contrat\s*pro)", re.IGNORECASE)
_RE_CADRE = re.compile(r"\b(?:cadre)\b", re.IGNORECASE)
_RE_PERIODE = re.compile(r"(?:periode|mois|paie\s*du)\s*[:\s]?\s*(\d{2})[/.-](\d{4})", re.IGNORECASE)

# Cotisations detectables par mots-cles
_COTISATION_PATTERNS = [
    (re.compile(r"maladie", re.I), ContributionType.MALADIE),
    (re.compile(r"vieillesse\s*plaf", re.I), ContributionType.VIEILLESSE_PLAFONNEE),
    (re.compile(r"vieillesse\s*d.plaf", re.I), ContributionType.VIEILLESSE_DEPLAFONNEE),
    (re.compile(r"alloc.*famil", re.I), ContributionType.ALLOCATIONS_FAMILIALES),
    (re.compile(r"accident.*travail|at.?mp", re.I), ContributionType.ACCIDENT_TRAVAIL),
    (re.compile(r"csg\s*d.duct", re.I), ContributionType.CSG_DEDUCTIBLE),
    (re.compile(r"csg\s*non", re.I), ContributionType.CSG_NON_DEDUCTIBLE),
    (re.compile(r"crds", re.I), ContributionType.CRDS),
    (re.compile(r"ch.mage|chomage", re.I), ContributionType.ASSURANCE_CHOMAGE),
    (re.compile(r"ags", re.I), ContributionType.AGS),
    (re.compile(r"retraite\s*compl.*t1|agirc.*t1|arrco.*t1", re.I), ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
    (re.compile(r"fnal", re.I), ContributionType.FNAL),
    (re.compile(r"formation\s*pro", re.I), ContributionType.FORMATION_PROFESSIONNELLE),
    (re.compile(r"taxe\s*apprenti", re.I), ContributionType.TAXE_APPRENTISSAGE),
]

_RE_MONTANT = re.compile(r"([\d\s]+[.,]\d{2})")


def _parse_montant(s: str) -> Decimal:
    """Parse un montant texte en Decimal."""
    s = s.replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


class ImageParser(BaseParser):
    """Parse les images de documents sociaux (bulletins, etc.)."""

    def __init__(self):
        self.lecteur = LecteurMultiFormat()

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() in EXTENSIONS_IMAGES

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        resultat = self.lecteur.lire_fichier(chemin)
        texte = resultat.texte
        if not texte or len(texte.strip()) < 10:
            return []

        return self._extraire_declarations(texte, document)

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        resultat = self.lecteur.lire_fichier(chemin)
        return {
            "format": resultat.format_detecte.value,
            "est_image": resultat.est_image,
            "est_scan": resultat.est_scan,
            "confiance_ocr": resultat.confiance_ocr,
            "manuscrit_detecte": resultat.manuscrit_detecte,
            "avertissements": resultat.avertissements,
        }

    def _extraire_declarations(self, texte: str, document: Document) -> list[Declaration]:
        """Extrait les declarations depuis le texte OCR."""
        # Employeur
        employeur = Employeur(source_document_id=document.id)
        m = _RE_SIRET.search(texte)
        if m:
            siret = m.group(1).replace(" ", "")
            employeur.siret = siret
            employeur.siren = siret[:9]
        else:
            m = _RE_SIREN.search(texte)
            if m:
                employeur.siren = m.group(1)

        # Employe
        emp = Employe(source_document_id=document.id)
        m = _RE_NIR.search(texte)
        if m:
            emp.nir = m.group(1).replace(" ", "")
        m = _RE_NOM.search(texte)
        if m:
            emp.nom = m.group(1).strip()
        m = _RE_PRENOM.search(texte)
        if m:
            emp.prenom = m.group(1).strip()

        # Statut
        if _RE_APPRENTI.search(texte):
            emp.statut = "apprenti"
        elif _RE_CADRE.search(texte):
            emp.statut = "cadre"
        else:
            emp.statut = "non-cadre"

        # Brut / Net
        brut = Decimal("0")
        m = _RE_BRUT.search(texte)
        if m:
            brut = _parse_montant(m.group(1))

        # Periode
        periode = None
        m = _RE_PERIODE.search(texte)
        if m:
            from datetime import date
            try:
                mois = int(m.group(1))
                annee = int(m.group(2))
                debut = date(annee, mois, 1)
                import calendar
                dernier_jour = calendar.monthrange(annee, mois)[1]
                fin = date(annee, mois, dernier_jour)
                periode = DateRange(debut=debut, fin=fin)
            except (ValueError, TypeError):
                pass

        # Cotisations
        cotisations = []
        lignes = texte.split("\n")
        for ligne in lignes:
            for pattern, ct in _COTISATION_PATTERNS:
                if pattern.search(ligne):
                    montants = _RE_MONTANT.findall(ligne)
                    if montants:
                        vals = [_parse_montant(m) for m in montants]
                        base = brut if brut > 0 else (vals[0] if len(vals) >= 1 else Decimal("0"))
                        taux_p = vals[1] if len(vals) >= 4 else Decimal("0")
                        montant_p = vals[2] if len(vals) >= 4 else (vals[-1] if vals else Decimal("0"))
                        cotisations.append(Cotisation(
                            type_cotisation=ct,
                            base_brute=base,
                            assiette=base,
                            taux_patronal=taux_p,
                            montant_patronal=montant_p,
                            employe_id=emp.id,
                            employeur_id=employeur.id,
                            periode=periode,
                            source_document_id=document.id,
                        ))
                    break

        decl = Declaration(
            type_declaration="bulletin",
            reference=document.nom_fichier,
            periode=periode,
            employeur=employeur,
            employes=[emp],
            cotisations=cotisations,
            masse_salariale_brute=brut,
            effectif_declare=1,
            source_document_id=document.id,
        )
        return [decl]
