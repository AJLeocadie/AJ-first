"""Parseur pour les fichiers PDF (bulletins de paie, factures, contrats, livres de paie, attestations, bordereaux).

Detecte automatiquement le type de document via analyse du contenu
et extrait les donnees structurees (employes, cotisations, montants).
"""

import re
import calendar
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import (
    Document, Declaration, Cotisation, Employe, Employeur, DateRange,
)
from urssaf_analyzer.config.constants import ContributionType
from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.utils.number_utils import parser_montant

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


# ============================================================
# DOCUMENT TYPE CLASSIFICATION KEYWORDS
# ============================================================

_KW_BULLETIN = [
    "bulletin de paie", "bulletin de salaire", "fiche de paie",
    "net a payer", "net à payer", "net imposable",
    "salaire brut", "salaire de base", "brut mensuel",
    "cotisations salariales", "cotisations patronales",
    "retenue salariale", "part salariale", "part patronale",
    "heures travaillees", "heures travaillées",
    "convention collective", "emploi", "classification",
    "conges payes", "congés payés", "cumul brut", "cumul net",
    "prelevement a la source", "prélèvement à la source",
    "indemnite transport", "indemnité transport",
    "titres restaurant", "tickets restaurant",
    "mutuelle", "prevoyance", "prévoyance",
]

_KW_FACTURE = [
    "facture", "invoice", "montant ht", "montant ttc",
    "tva", "t.v.a", "hors taxe", "toutes taxes",
    "conditions de reglement", "conditions de règlement",
    "bon de commande", "numero de facture", "numéro de facture",
    "date de facture", "echeance", "échéance",
    "reglement", "règlement", "rib", "iban",
    "reference client", "référence client",
    "designation", "désignation", "quantite", "quantité",
    "prix unitaire", "remise",
]

_KW_CONTRAT = [
    "contrat de travail", "contrat a duree", "contrat à durée",
    "cdi", "cdd", "contrat d apprentissage", "contrat d'apprentissage",
    "contrat de professionnalisation",
    "article l.", "article r.", "code du travail",
    "periode d essai", "période d'essai",
    "rupture conventionnelle", "licenciement",
    "remuneration mensuelle", "rémunération mensuelle",
    "temps complet", "temps partiel",
    "fait a", "fait à", "en deux exemplaires",
    "l employeur", "l'employeur", "le salarie", "le salarié",
]

_KW_LDP = [
    "livre de paie", "livre de paye",
    "recapitulatif", "récapitulatif",
    "etat recapitulatif", "état récapitulatif",
    "total general", "total général",
    "total etablissement", "total établissement",
    "masse salariale", "effectif total",
    "bordereau recapitulatif", "bordereau récapitulatif",
]

_KW_INTERESSEMENT = [
    "interessement", "intéressement",
    "participation aux resultats", "participation aux résultats",
    "accord d interessement", "accord d'intéressement",
    "accord de participation",
    "supplement d interessement", "supplément d'intéressement",
    "plan d epargne", "plan d'épargne",
    "pee", "perco", "percol",
]

_KW_ATTESTATION = [
    "attestation employeur", "attestation de travail",
    "attestation pole emploi", "attestation pôle emploi",
    "attestation france travail",
    "certificat de travail",
    "solde de tout compte",
    "recu pour solde", "reçu pour solde",
]


# ============================================================
# EXTRACTION REGEX PATTERNS
# ============================================================

# Employee identification
_RE_NOM_PRENOM = re.compile(
    r"(?:nom\s*(?:et\s*)?prenom|nom\s*prenom|salari[eé])\s*[:\s]*"
    r"([A-Z\u00C0-\u00FF][A-Za-z\u00C0-\u00FF\s-]+)",
    re.IGNORECASE,
)
_RE_NOM = re.compile(
    r"(?:nom|NOM)\s*[:\s]+\s*([A-Z\u00C0-\u00FF][A-Z\u00C0-\u00FF\s'-]+)",
    re.IGNORECASE,
)
_RE_PRENOM = re.compile(
    r"(?:pr[eé]nom|PRENOM)\s*[:\s]+\s*([A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF'-]+)",
    re.IGNORECASE,
)
_RE_NIR = re.compile(
    r"\b([12]\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2})\b",
)
_RE_SIRET = re.compile(r"SIRET\s*[:\s]*(\d[\d\s]{12}\d)", re.IGNORECASE)
_RE_SIREN = re.compile(r"SIREN\s*[:\s]*(\d{9})", re.IGNORECASE)
_RE_NAF = re.compile(r"(?:NAF|APE)\s*[:\s]*(\d{4}[A-Z])", re.IGNORECASE)

# Employee status
_RE_CADRE = re.compile(r"\bcadre\b", re.IGNORECASE)
_RE_APPRENTI = re.compile(r"(?:apprenti|apprentissage|alternance|alternant|contrat\s*pro)", re.IGNORECASE)
_RE_EMPLOI = re.compile(r"(?:emploi|poste|fonction|qualification)\s*[:\s]+\s*(.+?)(?:\n|$)", re.IGNORECASE)
_RE_CLASSIFICATION = re.compile(r"(?:classification|coefficient|echelon|niveau)\s*[:\s]+\s*(.+?)(?:\n|$)", re.IGNORECASE)

# Amounts
_RE_BRUT = re.compile(
    r"(?:salaire\s*brut|remuneration\s*brut|brut\s*mensuel|total\s*brut|brut\s*du\s*mois"
    r"|brut\s*soumis|remun[eé]ration\s*brut)"
    r"\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_NET_A_PAYER = re.compile(
    r"(?:net\s*[aà]\s*payer|net\s*pay[eé]|montant\s*net\s*vers[eé])"
    r"\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_NET_IMPOSABLE = re.compile(
    r"(?:net\s*imposable|net\s*fiscal|cumul\s*net\s*imposable)"
    r"\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_NET_AVANT_IMPOT = re.compile(
    r"(?:net\s*avant\s*imp[oô]t|net\s*avant\s*pr[eé]l[eè]vement)"
    r"\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_TOTAL_PATRONAL = re.compile(
    r"total\s+(?:cotisations?\s+)?(?:patronales?|employeur)\s*[:\s]*([\d\s,.]+)",
    re.IGNORECASE,
)
_RE_TOTAL_SALARIAL = re.compile(
    r"total\s+(?:cotisations?\s+)?(?:salariales?|salari[eé])\s*[:\s]*([\d\s,.]+)",
    re.IGNORECASE,
)

# Employer name
_RE_RAISON_SOCIALE = re.compile(
    r"(?:raison\s*sociale|soci[eé]t[eé]|entreprise|employeur)\s*[:\s]+\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)

# Period
_RE_PERIODE_MOIS_ANNEE = re.compile(
    r"(?:p[eé]riode|mois|paie\s*du|bulletin\s*du|mois\s*de)\s*[:\s]*"
    r"(\d{1,2})\s*[/.\-]\s*(\d{4})",
    re.IGNORECASE,
)
_RE_PERIODE_TEXTE = re.compile(
    r"(?:p[eé]riode|mois|paie\s*du|bulletin\s*du|mois\s*de)\s*[:\s]*"
    r"(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre)"
    r"\s*(\d{4})",
    re.IGNORECASE,
)
_MOIS_MAP = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}
_RE_DATE_VIREMENT = re.compile(
    r"(?:date\s*(?:de\s*)?(?:virement|paiement|versement|r[eè]glement))\s*[:\s]*"
    r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})",
    re.IGNORECASE,
)

# Date embauche
_RE_DATE_EMBAUCHE = re.compile(
    r"(?:date\s*(?:d\s*)?(?:entr[eé]e|embauche|d[eé]but))\s*[:\s]*"
    r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})",
    re.IGNORECASE,
)

# Facture amounts
_RE_MONTANT_HT = re.compile(
    r"(?:montant|total)\s*(?:hors\s*taxe|ht|h\.t\.?)\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_MONTANT_TVA = re.compile(
    r"(?:montant|total)\s*(?:tva|t\.v\.a\.?)\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_MONTANT_TTC = re.compile(
    r"(?:montant|total|net\s*[aà]\s*payer)\s*(?:ttc|t\.t\.c\.?|toutes\s*taxes)\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)

# Contrat fields
_RE_TYPE_CONTRAT = re.compile(
    r"contrat\s*(?:[aà]\s*dur[eé]e\s*)?(ind[eé]termin[eé]e|d[eé]termin[eé]e|cdi|cdd)",
    re.IGNORECASE,
)
_RE_REMUNERATION = re.compile(
    r"(?:r[eé]mun[eé]ration|salaire)\s*(?:mensuel(?:le)?|annuel(?:le)?|brut(?:e)?)?\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)

# Cotisation line patterns (for table rows in bulletins)
_COTISATION_PATTERNS = [
    (re.compile(r"maladie", re.I), ContributionType.MALADIE),
    (re.compile(r"vieillesse\s*plaf", re.I), ContributionType.VIEILLESSE_PLAFONNEE),
    (re.compile(r"vieillesse\s*d[eé]plaf", re.I), ContributionType.VIEILLESSE_DEPLAFONNEE),
    (re.compile(r"vieillesse(?!\s*(?:plaf|d[eé]plaf))", re.I), ContributionType.VIEILLESSE_PLAFONNEE),
    (re.compile(r"alloc.*famil", re.I), ContributionType.ALLOCATIONS_FAMILIALES),
    (re.compile(r"accident.*travail|at[/.]?mp", re.I), ContributionType.ACCIDENT_TRAVAIL),
    (re.compile(r"csg\s*d[eé]duct", re.I), ContributionType.CSG_DEDUCTIBLE),
    (re.compile(r"csg\s*(?:non|imp)", re.I), ContributionType.CSG_NON_DEDUCTIBLE),
    (re.compile(r"csg(?!\s*(?:d[eé]duct|non|imp))", re.I), ContributionType.CSG_DEDUCTIBLE),
    (re.compile(r"crds", re.I), ContributionType.CRDS),
    (re.compile(r"ch[oô]mage|assurance\s*ch", re.I), ContributionType.ASSURANCE_CHOMAGE),
    (re.compile(r"\bags\b", re.I), ContributionType.AGS),
    (re.compile(r"retraite\s*compl.*t1|agirc.*t1|arrco.*t1", re.I), ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
    (re.compile(r"retraite\s*compl.*t2|agirc.*t2|arrco.*t2", re.I), ContributionType.RETRAITE_COMPLEMENTAIRE_T2),
    (re.compile(r"retraite\s*compl|agirc|arrco|compl[eé]mentaire", re.I), ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
    (re.compile(r"fnal", re.I), ContributionType.FNAL),
    (re.compile(r"formation\s*pro", re.I), ContributionType.FORMATION_PROFESSIONNELLE),
    (re.compile(r"taxe\s*apprenti", re.I), ContributionType.TAXE_APPRENTISSAGE),
    (re.compile(r"transport|mobilit[eé]", re.I), ContributionType.VERSEMENT_TRANSPORT),
    (re.compile(r"pr[eé]voyance", re.I), ContributionType.PREVOYANCE),
    (re.compile(r"mutuelle|compl[eé]mentaire\s*sant[eé]", re.I), ContributionType.COMPLEMENTAIRE_SANTE),
]

_RE_MONTANT_NUM = re.compile(r"([\d\s]+[.,]\d{2})")


def _parse_montant_local(s: str) -> Decimal:
    """Parse un montant texte en Decimal."""
    s = s.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def _count_keywords(texte_lower: str, keywords: list[str]) -> int:
    """Compte le nombre de mots-cles trouves dans le texte."""
    return sum(1 for kw in keywords if kw in texte_lower)


class PDFParser(BaseParser):
    """Parse les fichiers PDF avec detection automatique du type de document."""

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

        if not texte_complet.strip():
            return []

        # Detect document type from content
        doc_type = self._detecter_type_document(texte_complet, chemin.name)

        if doc_type == "bulletin":
            return self._parser_bulletin(texte_complet, tableaux, document)
        elif doc_type == "livre_de_paie":
            return self._parser_livre_de_paie(texte_complet, tableaux, document)
        elif doc_type == "facture":
            return self._parser_facture(texte_complet, document)
        elif doc_type == "contrat":
            return self._parser_contrat(texte_complet, document)
        elif doc_type == "interessement":
            return self._parser_interessement(texte_complet, document)
        elif doc_type == "attestation":
            return self._parser_attestation(texte_complet, document)
        else:
            # Fallback: try bulletin-style extraction
            return self._parser_generique(texte_complet, tableaux, document)

    def _detecter_type_document(self, texte: str, filename: str = "") -> str:
        """Detecte le type de document via analyse du contenu et du nom de fichier."""
        texte_lower = texte.lower()
        fname_lower = filename.lower()

        scores = {
            "bulletin": 0,
            "facture": 0,
            "contrat": 0,
            "livre_de_paie": 0,
            "interessement": 0,
            "attestation": 0,
        }

        # Content-based scoring
        scores["bulletin"] = _count_keywords(texte_lower, _KW_BULLETIN)
        scores["facture"] = _count_keywords(texte_lower, _KW_FACTURE)
        scores["contrat"] = _count_keywords(texte_lower, _KW_CONTRAT)
        scores["livre_de_paie"] = _count_keywords(texte_lower, _KW_LDP)
        scores["interessement"] = _count_keywords(texte_lower, _KW_INTERESSEMENT)
        scores["attestation"] = _count_keywords(texte_lower, _KW_ATTESTATION)

        # Filename hints (strong boost)
        fname_hints = {
            "bulletin": ["bulletin", "paie", "salaire", "fiche_paie", "bp_", "bul_"],
            "facture": ["facture", "invoice", "fac_", "fact_"],
            "contrat": ["contrat", "cdi", "cdd", "embauche", "avenant"],
            "livre_de_paie": ["livre_de_paie", "ldp", "recapitulatif", "recap"],
            "interessement": ["interessement", "participation", "epargne", "pee"],
            "attestation": ["attestation", "certificat", "solde"],
        }
        for doc_type, hints in fname_hints.items():
            if any(h in fname_lower for h in hints):
                scores[doc_type] += 5

        # Pick highest score (minimum 2 to classify)
        best_type = max(scores, key=scores.get)
        if scores[best_type] >= 2:
            return best_type

        # Fallback heuristics
        if _RE_BRUT.search(texte) and (_RE_NET_A_PAYER.search(texte) or _RE_NET_IMPOSABLE.search(texte)):
            return "bulletin"
        if _RE_MONTANT_HT.search(texte) and _RE_MONTANT_TTC.search(texte):
            return "facture"
        if _RE_TYPE_CONTRAT.search(texte):
            return "contrat"

        return "inconnu"

    # ============================================================
    # BULLETIN DE PAIE
    # ============================================================

    def _parser_bulletin(self, texte: str, tableaux: list, document: Document) -> list[Declaration]:
        """Parse un bulletin de paie avec extraction complete."""
        doc_id = document.id

        # --- Employeur ---
        employeur = self._extraire_employeur(texte, doc_id)

        # --- Employe ---
        emp = self._extraire_employe(texte, doc_id)

        # --- Brut / Net ---
        brut = Decimal("0")
        m = _RE_BRUT.search(texte)
        if m:
            brut = _parse_montant_local(m.group(1))

        net_a_payer = Decimal("0")
        m = _RE_NET_A_PAYER.search(texte)
        if m:
            net_a_payer = _parse_montant_local(m.group(1))

        net_imposable = Decimal("0")
        m = _RE_NET_IMPOSABLE.search(texte)
        if m:
            net_imposable = _parse_montant_local(m.group(1))

        net_avant_impot = Decimal("0")
        m = _RE_NET_AVANT_IMPOT.search(texte)
        if m:
            net_avant_impot = _parse_montant_local(m.group(1))

        total_patronal = Decimal("0")
        m = _RE_TOTAL_PATRONAL.search(texte)
        if m:
            total_patronal = parser_montant(m.group(1))

        total_salarial = Decimal("0")
        m = _RE_TOTAL_SALARIAL.search(texte)
        if m:
            total_salarial = parser_montant(m.group(1))

        # --- Periode ---
        periode = self._extraire_periode(texte)

        # --- Date de virement ---
        date_virement = None
        m = _RE_DATE_VIREMENT.search(texte)
        if m:
            try:
                date_virement = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except (ValueError, TypeError):
                pass

        # --- Date embauche ---
        m = _RE_DATE_EMBAUCHE.search(texte)
        if m:
            try:
                emp.date_embauche = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except (ValueError, TypeError):
                pass

        # --- Cotisations ---
        cotisations = self._extraire_cotisations_bulletin(texte, tableaux, doc_id, emp.id, brut)

        # If no cotisations found from text/tables but we have total amounts, create synthetic ones
        if not cotisations and (total_patronal > 0 or total_salarial > 0 or brut > 0):
            cotisations = self._generer_cotisations_synthetiques(
                brut, total_patronal, total_salarial, doc_id, emp.id, periode,
            )

        # --- Masse salariale ---
        if brut <= 0 and cotisations:
            brut = max(c.base_brute for c in cotisations)

        # If still no brut but net_a_payer is known, estimate brut
        if brut <= 0 and net_a_payer > 0:
            brut = Decimal(str(round(float(net_a_payer) / 0.78, 2)))

        # Store metadata
        metadata = {
            "type_document": "bulletin_de_paie",
            "net_a_payer": float(net_a_payer),
            "net_imposable": float(net_imposable),
            "net_avant_impot": float(net_avant_impot),
            "total_patronal": float(total_patronal),
            "total_salarial": float(total_salarial),
        }
        if date_virement:
            metadata["date_virement"] = date_virement.isoformat()

        decl = Declaration(
            type_declaration="bulletin",
            reference=document.nom_fichier,
            periode=periode,
            employeur=employeur,
            employes=[emp],
            cotisations=cotisations,
            masse_salariale_brute=brut,
            effectif_declare=1,
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    # ============================================================
    # LIVRE DE PAIE / RECAPITULATIF
    # ============================================================

    def _parser_livre_de_paie(self, texte: str, tableaux: list, document: Document) -> list[Declaration]:
        """Parse un livre de paie ou recapitulatif multi-salaries."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)
        periode = self._extraire_periode(texte)

        # Extract multiple employees from tables or text
        employes = []
        cotisations_all = []

        # Try extracting from tables first
        for table in tableaux:
            if len(table) < 2:
                continue
            header = [str(c).lower().strip() if c else "" for c in table[0]]

            # Detect employee name column
            col_nom = col_brut = col_net = col_pat = col_sal = -1
            for i, h in enumerate(header):
                if any(kw in h for kw in ["nom", "salari", "employ"]):
                    col_nom = i
                elif any(kw in h for kw in ["brut"]):
                    col_brut = i
                elif any(kw in h for kw in ["net"]):
                    col_net = i
                elif any(kw in h for kw in ["patronal", "employeur"]):
                    col_pat = i
                elif any(kw in h for kw in ["salarial", "salari"]):
                    col_sal = i

            if col_nom < 0:
                continue

            for row in table[1:]:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue
                if col_nom < len(row) and row[col_nom]:
                    nom_complet = str(row[col_nom]).strip()
                    if not nom_complet or nom_complet.lower() in ("total", "totaux", "sous-total"):
                        continue
                    parts = nom_complet.split(None, 1)
                    emp = Employe(
                        nom=parts[0] if parts else nom_complet,
                        prenom=parts[1] if len(parts) > 1 else "",
                        source_document_id=doc_id,
                    )
                    employes.append(emp)

                    brut_val = Decimal("0")
                    if col_brut >= 0 and col_brut < len(row) and row[col_brut]:
                        brut_val = parser_montant(str(row[col_brut]))

                    if brut_val > 0:
                        cot = Cotisation(
                            type_cotisation=ContributionType.MALADIE,
                            base_brute=brut_val,
                            assiette=brut_val,
                            employe_id=emp.id,
                            source_document_id=doc_id,
                        )
                        if col_pat >= 0 and col_pat < len(row) and row[col_pat]:
                            cot.montant_patronal = parser_montant(str(row[col_pat]))
                        if col_sal >= 0 and col_sal < len(row) and row[col_sal]:
                            cot.montant_salarial = parser_montant(str(row[col_sal]))
                        cotisations_all.append(cot)

        # Fallback: try regex-based multi-employee extraction
        if not employes:
            nirs = list(_RE_NIR.finditer(texte))
            bruts = list(_RE_BRUT.finditer(texte))
            if nirs:
                for m in nirs:
                    emp = Employe(
                        nir=m.group(1).replace(" ", ""),
                        source_document_id=doc_id,
                    )
                    employes.append(emp)
            elif bruts and len(bruts) > 1:
                for i, m in enumerate(bruts):
                    emp = Employe(
                        nom=f"Salarie {i + 1}",
                        source_document_id=doc_id,
                    )
                    brut = _parse_montant_local(m.group(1))
                    cot = Cotisation(
                        type_cotisation=ContributionType.MALADIE,
                        base_brute=brut,
                        assiette=brut,
                        employe_id=emp.id,
                        source_document_id=doc_id,
                    )
                    employes.append(emp)
                    cotisations_all.append(cot)

        # Extract overall cotisations from tables
        cotisations_all.extend(self._extraire_cotisations_tableaux_generiques(tableaux, doc_id))

        # Total masse salariale
        masse = Decimal("0")
        m = re.search(
            r"(?:masse\s*salariale|total\s*(?:g[eé]n[eé]ral|brut))\s*[:\s]*([\d\s]+[.,]\d{2})",
            texte, re.IGNORECASE,
        )
        if m:
            masse = _parse_montant_local(m.group(1))
        elif cotisations_all:
            masse = sum(c.base_brute for c in cotisations_all)

        decl = Declaration(
            type_declaration="livre_de_paie",
            reference=document.nom_fichier,
            periode=periode,
            employeur=employeur,
            employes=employes,
            cotisations=cotisations_all,
            masse_salariale_brute=masse,
            effectif_declare=len(employes),
            source_document_id=doc_id,
            metadata={"type_document": "livre_de_paie"},
        )
        return [decl]

    # ============================================================
    # FACTURE
    # ============================================================

    def _parser_facture(self, texte: str, document: Document) -> list[Declaration]:
        """Parse une facture (achat ou vente)."""
        doc_id = document.id

        montant_ht = Decimal("0")
        m = _RE_MONTANT_HT.search(texte)
        if m:
            montant_ht = _parse_montant_local(m.group(1))

        montant_tva = Decimal("0")
        m = _RE_MONTANT_TVA.search(texte)
        if m:
            montant_tva = _parse_montant_local(m.group(1))

        montant_ttc = Decimal("0")
        m = _RE_MONTANT_TTC.search(texte)
        if m:
            montant_ttc = _parse_montant_local(m.group(1))

        # Try to detect if it's a purchase or sale invoice
        texte_lower = texte.lower()
        is_achat = "facture d'achat" in texte_lower or "fournisseur" in texte_lower
        type_facture = "facture_achat" if is_achat else "facture_vente"

        employeur = self._extraire_employeur(texte, doc_id)

        # Extract the supplier/client name
        m = re.search(
            r"(?:fournisseur|client|destinataire|adresse[eé]\s*[aà])\s*[:\s]+\s*(.+?)(?:\n|$)",
            texte, re.IGNORECASE,
        )
        tiers_nom = m.group(1).strip() if m else ""

        # Extract facture number
        m = re.search(
            r"(?:facture|invoice)\s*(?:n[°o]?|numero|#)\s*[:\s]?\s*([A-Z0-9][\w-]+)",
            texte, re.IGNORECASE,
        )
        num_facture = m.group(1).strip() if m else ""

        decl = Declaration(
            type_declaration="facture",
            reference=num_facture or document.nom_fichier,
            employeur=employeur,
            masse_salariale_brute=Decimal("0"),
            source_document_id=doc_id,
            metadata={
                "type_document": type_facture,
                "montant_ht": float(montant_ht),
                "montant_tva": float(montant_tva),
                "montant_ttc": float(montant_ttc),
                "tiers": tiers_nom,
                "numero_facture": num_facture,
            },
        )
        return [decl]

    # ============================================================
    # CONTRAT DE TRAVAIL
    # ============================================================

    def _parser_contrat(self, texte: str, document: Document) -> list[Declaration]:
        """Parse un contrat de travail."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)
        emp = self._extraire_employe(texte, doc_id)

        # Type de contrat
        type_contrat = "CDI"
        m = _RE_TYPE_CONTRAT.search(texte)
        if m:
            val = m.group(1).lower()
            if "indetermin" in val or "cdi" in val:
                type_contrat = "CDI"
            elif "determin" in val or "cdd" in val:
                type_contrat = "CDD"

        # Remuneration
        brut = Decimal("0")
        m = _RE_REMUNERATION.search(texte)
        if m:
            brut = _parse_montant_local(m.group(1))
        if brut <= 0:
            m = _RE_BRUT.search(texte)
            if m:
                brut = _parse_montant_local(m.group(1))

        # Date embauche
        m = _RE_DATE_EMBAUCHE.search(texte)
        if m:
            try:
                emp.date_embauche = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except (ValueError, TypeError):
                pass

        decl = Declaration(
            type_declaration="contrat",
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[emp],
            masse_salariale_brute=brut,
            effectif_declare=1,
            source_document_id=doc_id,
            metadata={
                "type_document": "contrat_de_travail",
                "type_contrat": type_contrat,
                "remuneration_brute": float(brut),
            },
        )
        return [decl]

    # ============================================================
    # ACCORD D'INTERESSEMENT / PARTICIPATION
    # ============================================================

    def _parser_interessement(self, texte: str, document: Document) -> list[Declaration]:
        """Parse un accord d'interessement ou participation."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)

        texte_lower = texte.lower()
        is_participation = "participation" in texte_lower and "interessement" not in texte_lower
        type_accord = "participation" if is_participation else "interessement"

        decl = Declaration(
            type_declaration=type_accord,
            reference=document.nom_fichier,
            employeur=employeur,
            source_document_id=doc_id,
            metadata={"type_document": f"accord_{type_accord}"},
        )
        return [decl]

    # ============================================================
    # ATTESTATION
    # ============================================================

    def _parser_attestation(self, texte: str, document: Document) -> list[Declaration]:
        """Parse une attestation employeur ou certificat de travail."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)
        emp = self._extraire_employe(texte, doc_id)

        brut = Decimal("0")
        m = _RE_BRUT.search(texte)
        if m:
            brut = _parse_montant_local(m.group(1))

        decl = Declaration(
            type_declaration="attestation",
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[emp] if emp.nom else [],
            masse_salariale_brute=brut,
            source_document_id=doc_id,
            metadata={"type_document": "attestation"},
        )
        return [decl]

    # ============================================================
    # GENERIQUE (FALLBACK)
    # ============================================================

    def _parser_generique(self, texte: str, tableaux: list, document: Document) -> list[Declaration]:
        """Parsing generique quand le type de document n'est pas determine."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)
        emp = self._extraire_employe(texte, doc_id)
        periode = self._extraire_periode(texte)

        cotisations = self._extraire_cotisations_bulletin(texte, tableaux, doc_id, emp.id if emp.nom else "", Decimal("0"))
        cotisations.extend(self._extraire_cotisations_tableaux_generiques(tableaux, doc_id))

        brut = Decimal("0")
        m = _RE_BRUT.search(texte)
        if m:
            brut = _parse_montant_local(m.group(1))
        elif cotisations:
            brut = max(c.base_brute for c in cotisations)

        employes = [emp] if (emp.nom or emp.nir) else []

        decl = Declaration(
            type_declaration="PDF",
            reference=document.nom_fichier,
            periode=periode,
            employeur=employeur,
            employes=employes,
            cotisations=cotisations,
            masse_salariale_brute=brut,
            effectif_declare=len(employes),
            source_document_id=doc_id,
            metadata={"type_document": "inconnu"},
        )
        return [decl]

    # ============================================================
    # SHARED EXTRACTION HELPERS
    # ============================================================

    def _extraire_employeur(self, texte: str, doc_id: str) -> Employeur:
        """Extrait les informations de l'employeur."""
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

        m = _RE_RAISON_SOCIALE.search(texte)
        if m:
            employeur.raison_sociale = m.group(1).strip()[:100]

        m = _RE_NAF.search(texte)
        if m:
            employeur.code_naf = m.group(1)

        return employeur

    def _extraire_employe(self, texte: str, doc_id: str) -> Employe:
        """Extrait les informations du salarie."""
        emp = Employe(source_document_id=doc_id)

        # NIR
        m = _RE_NIR.search(texte)
        if m:
            emp.nir = m.group(1).replace(" ", "")

        # Try combined nom+prenom first
        m = _RE_NOM_PRENOM.search(texte)
        if m:
            full = m.group(1).strip()
            parts = full.split(None, 1)
            if len(parts) >= 2:
                emp.nom = parts[0].strip()
                emp.prenom = parts[1].strip()
            else:
                emp.nom = full
        else:
            # Try separate nom and prenom
            m = _RE_NOM.search(texte)
            if m:
                emp.nom = m.group(1).strip()
            m = _RE_PRENOM.search(texte)
            if m:
                emp.prenom = m.group(1).strip()

        # If no name found, try to infer from text patterns
        if not emp.nom:
            # Pattern: "M./Mme/Mr LASTNAME Firstname"
            m = re.search(
                r"(?:M\.|Mme|Mr|Mlle|Madame|Monsieur)\s+([A-Z\u00C0-\u00FF][A-Z\u00C0-\u00FF'-]+)"
                r"\s+([A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF'-]+)",
                texte,
            )
            if m:
                emp.nom = m.group(1).strip()
                emp.prenom = m.group(2).strip()

        # Statut
        if _RE_APPRENTI.search(texte):
            emp.statut = "apprenti"
        elif _RE_CADRE.search(texte):
            emp.statut = "cadre"
        else:
            emp.statut = "non-cadre"

        # Emploi / poste
        m = _RE_EMPLOI.search(texte)
        if m:
            emp.convention_collective = m.group(1).strip()[:80]

        return emp

    def _extraire_periode(self, texte: str) -> Optional[DateRange]:
        """Extrait la periode du document."""
        # Try MM/YYYY format
        m = _RE_PERIODE_MOIS_ANNEE.search(texte)
        if m:
            try:
                mois = int(m.group(1))
                annee = int(m.group(2))
                if 1 <= mois <= 12 and 2000 <= annee <= 2030:
                    debut = date(annee, mois, 1)
                    fin = date(annee, mois, calendar.monthrange(annee, mois)[1])
                    return DateRange(debut=debut, fin=fin)
            except (ValueError, TypeError):
                pass

        # Try "mois de XXXXX YYYY" format
        m = _RE_PERIODE_TEXTE.search(texte)
        if m:
            mois_str = m.group(1).lower()
            mois = _MOIS_MAP.get(mois_str)
            annee = int(m.group(2))
            if mois and 2000 <= annee <= 2030:
                try:
                    debut = date(annee, mois, 1)
                    fin = date(annee, mois, calendar.monthrange(annee, mois)[1])
                    return DateRange(debut=debut, fin=fin)
                except (ValueError, TypeError):
                    pass

        return None

    def _extraire_cotisations_bulletin(
        self, texte: str, tableaux: list, doc_id: str, emp_id: str, brut: Decimal,
    ) -> list[Cotisation]:
        """Extrait les cotisations d'un bulletin de paie (texte + tableaux)."""
        cotisations = []
        seen_types = set()

        # 1. Try table-based extraction (more reliable)
        for table in tableaux:
            if len(table) < 2:
                continue
            header = [str(c).lower().strip() if c else "" for c in table[0]]

            # Find column indices
            col_type = col_base = col_taux_p = col_taux_s = col_mt_p = col_mt_s = -1
            for i, h in enumerate(header):
                if any(kw in h for kw in ["libell", "type", "cotisation", "designation", "d\xe9signation", "rubrique"]):
                    col_type = i
                elif any(kw in h for kw in ["base", "assiette", "brut"]):
                    col_base = i
                elif "taux" in h and ("patron" in h or "employ" in h or "part p" in h):
                    col_taux_p = i
                elif "taux" in h and ("salari" in h or "part s" in h):
                    col_taux_s = i
                elif "taux" in h and col_taux_p < 0:
                    col_taux_p = i
                elif any(kw in h for kw in ["montant", "part"]) and ("patron" in h or "employ" in h):
                    col_mt_p = i
                elif any(kw in h for kw in ["montant", "part"]) and ("salari" in h):
                    col_mt_s = i
                elif "montant" in h and col_mt_p < 0:
                    col_mt_p = i

            if col_type < 0:
                continue

            for row in table[1:]:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue
                if col_type >= len(row) or not row[col_type]:
                    continue
                label = str(row[col_type]).lower().strip()
                if not label or label in ("total", "totaux", "sous-total"):
                    continue

                ct = None
                for pattern, ctype in _COTISATION_PATTERNS:
                    if pattern.search(label):
                        ct = ctype
                        break
                if ct is None:
                    continue
                if ct.value in seen_types:
                    continue
                seen_types.add(ct.value)

                c = Cotisation(
                    type_cotisation=ct,
                    employe_id=emp_id,
                    source_document_id=doc_id,
                )
                if col_base >= 0 and col_base < len(row) and row[col_base]:
                    c.base_brute = parser_montant(str(row[col_base]))
                    c.assiette = c.base_brute
                elif brut > 0:
                    c.base_brute = brut
                    c.assiette = brut
                if col_taux_p >= 0 and col_taux_p < len(row) and row[col_taux_p]:
                    c.taux_patronal = parser_montant(str(row[col_taux_p]))
                    if c.taux_patronal > 1:
                        c.taux_patronal = c.taux_patronal / 100
                if col_taux_s >= 0 and col_taux_s < len(row) and row[col_taux_s]:
                    c.taux_salarial = parser_montant(str(row[col_taux_s]))
                    if c.taux_salarial > 1:
                        c.taux_salarial = c.taux_salarial / 100
                if col_mt_p >= 0 and col_mt_p < len(row) and row[col_mt_p]:
                    c.montant_patronal = parser_montant(str(row[col_mt_p]))
                if col_mt_s >= 0 and col_mt_s < len(row) and row[col_mt_s]:
                    c.montant_salarial = parser_montant(str(row[col_mt_s]))
                if c.base_brute > 0 or c.montant_patronal > 0 or c.montant_salarial > 0:
                    cotisations.append(c)

        # 2. Text-based extraction (fallback or complement)
        lignes = texte.split("\n")
        for ligne in lignes:
            for pattern, ct in _COTISATION_PATTERNS:
                if ct.value in seen_types:
                    continue
                if pattern.search(ligne):
                    montants = _RE_MONTANT_NUM.findall(ligne)
                    if montants:
                        vals = [_parse_montant_local(m) for m in montants]
                        base = brut if brut > 0 else (vals[0] if vals else Decimal("0"))

                        c = Cotisation(
                            type_cotisation=ct,
                            base_brute=base,
                            assiette=base,
                            employe_id=emp_id,
                            source_document_id=doc_id,
                        )

                        if len(vals) >= 5:
                            # base, taux_p, montant_p, taux_s, montant_s
                            c.base_brute = vals[0]
                            c.assiette = vals[0]
                            c.taux_patronal = vals[1] if vals[1] < 1 else vals[1] / 100
                            c.montant_patronal = vals[2]
                            c.taux_salarial = vals[3] if vals[3] < 1 else vals[3] / 100
                            c.montant_salarial = vals[4]
                        elif len(vals) >= 4:
                            # base, taux, montant_p, montant_s
                            c.base_brute = vals[0]
                            c.assiette = vals[0]
                            c.taux_patronal = vals[1] if vals[1] < 1 else vals[1] / 100
                            c.montant_patronal = vals[2]
                            c.montant_salarial = vals[3]
                        elif len(vals) >= 3:
                            c.base_brute = vals[0]
                            c.assiette = vals[0]
                            c.taux_patronal = vals[1] if vals[1] < 1 else vals[1] / 100
                            c.montant_patronal = vals[2]
                        elif len(vals) >= 2:
                            c.montant_patronal = vals[-1]
                        elif len(vals) == 1:
                            c.montant_patronal = vals[0]

                        seen_types.add(ct.value)
                        cotisations.append(c)
                    break

        return cotisations

    def _extraire_cotisations_tableaux_generiques(self, tableaux: list, doc_id: str) -> list[Cotisation]:
        """Extrait les cotisations depuis les tableaux detectes dans le PDF (methode generique)."""
        cotisations = []
        for table in tableaux:
            if len(table) < 2:
                continue
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
                        for pattern, ct in _COTISATION_PATTERNS:
                            if pattern.search(type_str):
                                c.type_cotisation = ct
                                break
                    if c.base_brute > 0 or c.montant_patronal > 0:
                        cotisations.append(c)
                except Exception:
                    continue
        return cotisations

    def _generer_cotisations_synthetiques(
        self, brut: Decimal, total_pat: Decimal, total_sal: Decimal,
        doc_id: str, emp_id: str, periode: Optional[DateRange],
    ) -> list[Cotisation]:
        """Genere des cotisations synthetiques a partir des totaux connus."""
        if brut <= 0:
            return []

        cotisations = []
        # Repartition standard des cotisations patronales
        repartition_pat = [
            (ContributionType.MALADIE, Decimal("0.070")),
            (ContributionType.VIEILLESSE_PLAFONNEE, Decimal("0.0855")),
            (ContributionType.VIEILLESSE_DEPLAFONNEE, Decimal("0.019")),
            (ContributionType.ALLOCATIONS_FAMILIALES, Decimal("0.0345")),
            (ContributionType.ASSURANCE_CHOMAGE, Decimal("0.0405")),
            (ContributionType.RETRAITE_COMPLEMENTAIRE_T1, Decimal("0.0472")),
        ]
        repartition_sal = [
            (ContributionType.MALADIE, Decimal("0")),
            (ContributionType.VIEILLESSE_PLAFONNEE, Decimal("0.0690")),
            (ContributionType.VIEILLESSE_DEPLAFONNEE, Decimal("0.004")),
            (ContributionType.CSG_DEDUCTIBLE, Decimal("0.0680")),
            (ContributionType.CRDS, Decimal("0.005")),
            (ContributionType.RETRAITE_COMPLEMENTAIRE_T1, Decimal("0.0315")),
        ]

        # Merge repartitions
        types_done = set()
        for ct_pat, taux_p in repartition_pat:
            taux_s = Decimal("0")
            for ct_sal, ts in repartition_sal:
                if ct_sal == ct_pat:
                    taux_s = ts
                    break
            mt_p = round(brut * taux_p, 2) if total_pat > 0 else Decimal("0")
            mt_s = round(brut * taux_s, 2) if total_sal > 0 else Decimal("0")
            cotisations.append(Cotisation(
                type_cotisation=ct_pat,
                base_brute=brut, assiette=brut,
                taux_patronal=taux_p, taux_salarial=taux_s,
                montant_patronal=mt_p, montant_salarial=mt_s,
                employe_id=emp_id, source_document_id=doc_id,
                periode=periode,
            ))
            types_done.add(ct_pat)

        # Add salary-only contributions not in patronal list
        for ct_sal, taux_s in repartition_sal:
            if ct_sal not in types_done:
                mt_s = round(brut * taux_s, 2)
                cotisations.append(Cotisation(
                    type_cotisation=ct_sal,
                    base_brute=brut, assiette=brut,
                    taux_salarial=taux_s,
                    montant_salarial=mt_s,
                    employe_id=emp_id, source_document_id=doc_id,
                    periode=periode,
                ))

        return cotisations
