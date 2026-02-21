"""Parseur d'images de bulletins de paie et documents sociaux.

Utilise le LecteurMultiFormat (OCR pytesseract si disponible,
extraction basique sinon) pour extraire le texte des images,
puis applique les memes regex que le PDF parser pour detecter
les donnees sociales.

Sur Vercel serverless (pas de Tesseract), effectue une classification
par nom de fichier et tente une extraction basique des metadonnees.
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

# Classification par nom de fichier
_FNAME_TYPE_MAP = {
    "bulletin": ["bulletin", "paie", "salaire", "fiche_paie", "bp_", "bul_"],
    "facture": ["facture", "invoice", "fac_", "fact_"],
    "contrat": ["contrat", "cdi", "cdd", "embauche"],
    "livre_de_paie": ["livre_de_paie", "ldp", "recap"],
    "attestation": ["attestation", "certificat", "solde"],
    "accord": ["accord", "nao", "gpec", "qvt"],
    "pv_ag": ["pv_ag", "proces_verbal", "assemblee", "ag_"],
    "contrat_service": ["prestation", "sous_traitance"],
    "liasse_fiscale": ["liasse", "2050", "2051", "2065"],
    "declaration_tva": ["tva", "ca3", "ca12"],
    "das2": ["das2", "honoraires"],
    "bilan": ["bilan", "comptes_annuels"],
    "compte_resultat": ["compte_resultat"],
    "dpae": ["dpae", "due_"],
    "registre_personnel": ["registre", "effectif"],
    "duerp": ["duerp", "document_unique"],
    "reglement_interieur": ["reglement_interieur"],
    "avenant": ["avenant"],
    "statuts": ["statuts"],
    "kbis": ["kbis", "k_bis"],
    "bail": ["bail"],
    "assurance": ["assurance", "police_"],
    "releve_bancaire": ["releve_bancaire", "releve_compte"],
    "devis": ["devis"],
    "avoir": ["avoir"],
    "note_frais": ["note_frais", "ndf"],
    "bon_commande": ["bon_commande", "commande"],
    "budget": ["budget", "previsionnel"],
}

# Labels for document types
_TYPE_LABELS = {
    "bulletin": "Bulletin de paie (image)",
    "facture": "Facture (image)",
    "contrat": "Contrat de travail (image)",
    "livre_de_paie": "Livre de paie (image)",
    "attestation": "Attestation (image)",
    "accord": "Accord d entreprise (image)",
    "pv_ag": "PV d assemblee generale (image)",
    "contrat_service": "Contrat de prestation (image)",
    "liasse_fiscale": "Liasse fiscale (image)",
    "declaration_tva": "Declaration TVA (image)",
    "das2": "DAS2 (image)",
    "bilan": "Bilan (image)",
    "compte_resultat": "Compte de resultat (image)",
    "dpae": "DPAE (image)",
    "registre_personnel": "Registre du personnel (image)",
    "duerp": "DUERP (image)",
    "reglement_interieur": "Reglement interieur (image)",
    "avenant": "Avenant (image)",
    "statuts": "Statuts (image)",
    "kbis": "Extrait Kbis (image)",
    "bail": "Bail (image)",
    "assurance": "Assurance (image)",
    "releve_bancaire": "Releve bancaire (image)",
    "devis": "Devis (image)",
    "avoir": "Avoir (image)",
    "note_frais": "Note de frais (image)",
    "bon_commande": "Bon de commande (image)",
    "budget": "Budget (image)",
}


def _parse_montant(s: str) -> Decimal:
    """Parse un montant texte en Decimal."""
    s = s.replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def _classify_by_filename(filename: str) -> str:
    """Classify document type from filename."""
    fname_lower = filename.lower()
    for doc_type, hints in _FNAME_TYPE_MAP.items():
        if any(h in fname_lower for h in hints):
            return doc_type
    return ""


class ImageParser(BaseParser):
    """Parse les images de documents sociaux (bulletins, etc.)."""

    def __init__(self):
        self.lecteur = LecteurMultiFormat()

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() in EXTENSIONS_IMAGES

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        resultat = self.lecteur.lire_fichier(chemin)
        texte = resultat.texte
        ocr_available = resultat.confiance_ocr >= 0.5

        # Classify document by filename first
        fname_type = _classify_by_filename(chemin.name)

        if texte and len(texte.strip()) >= 10 and ocr_available:
            # OCR available and produced text - full extraction
            return self._extraire_declarations(texte, document, fname_type)

        # OCR NOT available (Vercel) or poor text - filename-based classification
        return self._parser_sans_ocr(document, chemin, fname_type, resultat.avertissements)

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

    def _parser_sans_ocr(self, document: Document, chemin: Path, fname_type: str, avertissements: list) -> list[Declaration]:
        """Parse when OCR is not available - uses filename classification."""
        doc_id = document.id
        employeur = Employeur(source_document_id=doc_id)
        metadata = {
            "type_document": fname_type or "image_non_ocr",
            "ocr_disponible": False,
            "avertissements": avertissements + [
                "L extraction automatique du contenu de cette image n est pas disponible "
                "sur cette plateforme (moteur OCR Tesseract non installe). "
                "Le type de document a ete identifie a partir du nom de fichier. "
                "Pour une extraction complete, renommez vos fichiers de maniere descriptive "
                "(ex: bulletin_paie_dupont_01_2025.jpg, facture_fournisseur_123.png)."
            ],
        }

        # Try to extract info from filename
        fname = chemin.stem.lower()
        # Look for SIRET in filename
        m = re.search(r"(\d{14})", fname)
        if m:
            employeur.siret = m.group(1)
            employeur.siren = m.group(1)[:9]

        # Look for period in filename
        periode = None
        m = re.search(r"(\d{2})[_\-]?(\d{4})", fname)
        if m:
            try:
                from datetime import date as date_cls
                import calendar
                mois = int(m.group(1))
                annee = int(m.group(2))
                if 1 <= mois <= 12 and 2000 <= annee <= 2030:
                    debut = date_cls(annee, mois, 1)
                    fin = date_cls(annee, mois, calendar.monthrange(annee, mois)[1])
                    periode = DateRange(debut=debut, fin=fin)
            except (ValueError, TypeError):
                pass

        # Look for name in filename
        emp = Employe(source_document_id=doc_id)
        parts = re.split(r'[_\-\s]+', chemin.stem)
        excluded = {"bulletin", "paie", "salaire", "fiche", "bp", "bul", "pdf", "jpg",
                     "png", "scan", "img", "photo", "document", "doc", "facture",
                     "contrat", "attestation", "accord", "devis", "avoir", "bilan"}
        for p in parts:
            if len(p) >= 3 and p.isalpha() and p.lower() not in excluded:
                emp.nom = p.upper()
                break

        employes = [emp] if emp.nom else []

        decl = Declaration(
            type_declaration=fname_type or "image",
            reference=document.nom_fichier,
            periode=periode,
            employeur=employeur,
            employes=employes,
            masse_salariale_brute=Decimal("0"),
            effectif_declare=len(employes),
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    def _extraire_declarations(self, texte: str, document: Document, fname_type: str) -> list[Declaration]:
        """Extrait les declarations depuis le texte OCR."""
        doc_id = document.id

        # Employeur
        employeur = Employeur(source_document_id=doc_id)
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
        emp = Employe(source_document_id=doc_id)
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

        # Detect type from content
        doc_type = self._detect_type_from_text(texte) or fname_type or "bulletin_de_paie"

        # Cotisations (only for paie-related documents)
        cotisations = []
        if doc_type in ("bulletin", "bulletin_de_paie", "livre_de_paie", ""):
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
                                source_document_id=doc_id,
                            ))
                        break

        metadata = {
            "type_document": doc_type,
            "ocr_disponible": True,
        }

        decl = Declaration(
            type_declaration=doc_type.split("_")[0] if "_" in doc_type else doc_type,
            reference=document.nom_fichier,
            periode=periode,
            employeur=employeur,
            employes=[emp] if (emp.nom or emp.nir) else [],
            cotisations=cotisations,
            masse_salariale_brute=brut,
            effectif_declare=1 if (emp.nom or emp.nir) else 0,
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    def _detect_type_from_text(self, texte: str) -> str:
        """Simple content-based type detection for OCR text."""
        texte_lower = texte.lower()
        checks = [
            ("bulletin", ["bulletin de paie", "net a payer", "cotisations salariales", "salaire brut"]),
            ("facture", ["facture", "montant ht", "montant ttc", "tva"]),
            ("contrat", ["contrat de travail", "periode d essai", "cdi", "cdd"]),
            ("attestation", ["attestation employeur", "certificat de travail", "solde de tout compte"]),
            ("accord", ["accord d entreprise", "accord collectif", "negociation annuelle"]),
            ("pv_ag", ["assemblee generale", "proces verbal", "resolution"]),
            ("bilan", ["bilan", "total actif", "total passif", "capitaux propres"]),
            ("declaration_tva", ["declaration de tva", "tva collectee", "tva deductible"]),
            ("liasse_fiscale", ["liasse fiscale", "cerfa 2050", "declaration de resultats"]),
        ]
        best = ""
        best_score = 0
        for doc_type, keywords in checks:
            score = sum(1 for kw in keywords if kw in texte_lower)
            if score > best_score:
                best_score = score
                best = doc_type
        return best if best_score >= 2 else ""
