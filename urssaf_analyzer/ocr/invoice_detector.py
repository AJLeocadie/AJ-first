"""Detecteur et analyseur de factures par OCR.

Fonctionnalites :
- Classification automatique : facture d'achat ou de vente
- Extraction des champs cles (emetteur, destinataire, montants, TVA)
- Reconnaissance des ecritures manuscrites
- Detection des clients/fournisseurs
- Association automatique aux comptes comptables

Supporte : PDF (via pdfplumber), images (via base64 + regex OCR-like),
textes bruts, CSV d'exports bancaires.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
from typing import Optional

from urssaf_analyzer.utils.number_utils import parser_montant
from urssaf_analyzer.utils.date_utils import parser_date


class TypeDocument(str, Enum):
    FACTURE_VENTE = "facture_vente"
    FACTURE_ACHAT = "facture_achat"
    AVOIR_VENTE = "avoir_vente"
    AVOIR_ACHAT = "avoir_achat"
    RELEVE_BANCAIRE = "releve_bancaire"
    BULLETIN_PAIE = "bulletin_paie"
    NOTE_FRAIS = "note_frais"
    BORDEREAU_COTISATION = "bordereau_cotisation"
    AVIS_IMPOSITION = "avis_imposition"
    INCONNU = "inconnu"


class TypeTVA(str, Enum):
    TAUX_NORMAL = "20.0"
    TAUX_INTERMEDIAIRE = "10.0"
    TAUX_REDUIT = "5.5"
    TAUX_SUPER_REDUIT = "2.1"
    EXONERE = "0.0"


@dataclass
class LignePiece:
    """Une ligne d'une facture ou piece comptable."""
    description: str = ""
    quantite: Decimal = Decimal("1")
    prix_unitaire_ht: Decimal = Decimal("0")
    montant_ht: Decimal = Decimal("0")
    taux_tva: Decimal = Decimal("20.0")
    montant_tva: Decimal = Decimal("0")
    montant_ttc: Decimal = Decimal("0")
    compte_comptable: str = ""


@dataclass
class TiersDetecte:
    """Client ou fournisseur detecte."""
    nom: str = ""
    siret: str = ""
    siren: str = ""
    numero_tva: str = ""
    adresse: str = ""
    code_postal: str = ""
    ville: str = ""
    est_client: bool = False
    est_fournisseur: bool = False
    compte_tiers: str = ""  # 411xxx ou 401xxx


@dataclass
class PieceComptable:
    """Piece comptable extraite d'un document."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type_document: TypeDocument = TypeDocument.INCONNU
    numero_piece: str = ""
    date_piece: Optional[date] = None
    date_echeance: Optional[date] = None

    # Tiers
    emetteur: TiersDetecte = field(default_factory=TiersDetecte)
    destinataire: TiersDetecte = field(default_factory=TiersDetecte)

    # Montants
    montant_ht: Decimal = Decimal("0")
    montant_tva: Decimal = Decimal("0")
    montant_ttc: Decimal = Decimal("0")
    lignes: list[LignePiece] = field(default_factory=list)

    # Ventilation TVA
    ventilation_tva: dict[str, Decimal] = field(default_factory=dict)

    # Paiement
    mode_paiement: str = ""
    reference_paiement: str = ""

    # Metadata
    source_fichier: str = ""
    confiance_extraction: float = 0.0  # 0-1
    champs_manuscrits: list[str] = field(default_factory=list)
    texte_brut: str = ""


# --- Patterns regex pour extraction ---

PATTERNS_FACTURE = {
    "numero_facture": re.compile(
        r"(?:facture|invoice|fact\.?)\s*(?:n[°o]?|#|num[ée]ro)?\s*[:\s]*([A-Z0-9][\w\-/]{2,20})",
        re.IGNORECASE,
    ),
    "date_facture": re.compile(
        r"(?:date\s*(?:de\s*)?(?:facture|emission|document)?)\s*[:\s]*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})",
        re.IGNORECASE,
    ),
    "date_echeance": re.compile(
        r"(?:ech[ée]ance|date\s*(?:de\s*)?(?:paiement|reglement|due\s*date))\s*[:\s]*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})",
        re.IGNORECASE,
    ),
    "montant_ht": re.compile(
        r"(?:total\s*)?(?:H\.?T\.?|hors\s*taxe[s]?)\s*[:\s]*([\d\s,.]+)\s*(?:€|EUR)?",
        re.IGNORECASE,
    ),
    "montant_tva": re.compile(
        r"(?:total\s*)?(?:T\.?V\.?A\.?|taxe)\s*[:\s]*([\d\s,.]+)\s*(?:€|EUR)?",
        re.IGNORECASE,
    ),
    "montant_ttc": re.compile(
        r"(?:total\s*)?(?:T\.?T\.?C\.?|toutes\s*taxes|net\s*[àa]\s*payer|amount\s*due)\s*[:\s]*([\d\s,.]+)\s*(?:€|EUR)?",
        re.IGNORECASE,
    ),
    "taux_tva": re.compile(
        r"(?:tva|taxe)\s*(?:[àa])?\s*(20|10|5[.,]5|2[.,]1)\s*%",
        re.IGNORECASE,
    ),
    "siret": re.compile(r"SIRET\s*[:\s]*(\d[\d\s]{12}\d)", re.IGNORECASE),
    "siren": re.compile(r"SIREN\s*[:\s]*(\d{9})", re.IGNORECASE),
    "tva_intra": re.compile(r"(?:TVA\s*intra|N[°o]\s*TVA)\s*[:\s]*(FR\s*\d{2}\s*\d{9})", re.IGNORECASE),
    "iban": re.compile(r"(FR\d{2}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{3})", re.IGNORECASE),
    "mode_paiement": re.compile(
        r"(?:mode\s*(?:de\s*)?(?:paiement|reglement)|payment)\s*[:\s]*(virement|cheque|carte|especes|prelevement|cb|lettre\s*de\s*change)",
        re.IGNORECASE,
    ),
}

# Mots-cles pour classifier le type de document
MOTS_CLES_CLASSIFICATION = {
    TypeDocument.FACTURE_VENTE: [
        "facture", "invoice", "fact.", "facture de vente",
        "doit", "nous vous prions", "veuillez regler",
    ],
    TypeDocument.FACTURE_ACHAT: [
        "facture fournisseur", "bon de commande", "order",
        "purchase", "supplier invoice",
    ],
    TypeDocument.AVOIR_VENTE: [
        "avoir", "credit note", "note de credit", "remboursement",
    ],
    TypeDocument.AVOIR_ACHAT: [
        "avoir fournisseur", "supplier credit",
    ],
    TypeDocument.BULLETIN_PAIE: [
        "bulletin de paie", "bulletin de salaire", "fiche de paie",
        "salaire brut", "net a payer", "conges payes",
    ],
    TypeDocument.NOTE_FRAIS: [
        "note de frais", "frais professionnels", "expense report",
        "remboursement frais",
    ],
    TypeDocument.BORDEREAU_COTISATION: [
        "bordereau de cotisation", "urssaf", "cotisations sociales",
        "dsn", "declaration sociale",
    ],
    TypeDocument.AVIS_IMPOSITION: [
        "avis d'imposition", "impot", "direction generale des finances",
        "dgfip", "taxe", "contribution",
    ],
    TypeDocument.RELEVE_BANCAIRE: [
        "releve de compte", "releve bancaire", "bank statement",
        "solde", "debit", "credit",
    ],
}

# Detection manuscrit : patterns de caracteres irreguliers
PATTERNS_MANUSCRIT = re.compile(
    r"[A-Za-z]{1,3}\d{1,2}[A-Za-z]{0,2}\d{0,3}|"
    r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
)


class InvoiceDetector:
    """Detecte, classe et extrait les donnees des pieces comptables."""

    def __init__(self, entreprise_siret: str = ""):
        self.entreprise_siret = entreprise_siret

    def analyser_document(self, texte: str, nom_fichier: str = "") -> PieceComptable:
        """Analyse un texte extrait d'un document et retourne une piece comptable."""
        piece = PieceComptable(source_fichier=nom_fichier, texte_brut=texte[:5000])

        # 1. Classification du type de document
        piece.type_document = self._classifier_document(texte)

        # 2. Extraction des champs
        piece.numero_piece = self._extraire_champ(texte, "numero_facture")
        piece.date_piece = self._extraire_date(texte, "date_facture")
        piece.date_echeance = self._extraire_date(texte, "date_echeance")

        # 3. Extraction des montants
        piece.montant_ht = self._extraire_montant(texte, "montant_ht")
        piece.montant_tva = self._extraire_montant(texte, "montant_tva")
        piece.montant_ttc = self._extraire_montant(texte, "montant_ttc")

        # Coherence montants
        self._corriger_montants(piece)

        # 4. Ventilation TVA
        taux_match = PATTERNS_FACTURE["taux_tva"].findall(texte)
        for taux_str in taux_match:
            taux = taux_str.replace(",", ".")
            piece.ventilation_tva[taux] = piece.montant_tva  # simplifie

        # 5. Detection emetteur / destinataire (tiers)
        piece.emetteur = self._detecter_tiers(texte, position="haut")
        piece.destinataire = self._detecter_tiers(texte, position="bas")

        # 6. Determiner achat/vente selon le SIRET
        self._classifier_achat_vente(piece)

        # 7. Mode de paiement
        piece.mode_paiement = self._extraire_champ(texte, "mode_paiement")

        # 8. Detection ecritures manuscrites
        piece.champs_manuscrits = self._detecter_manuscrit(texte)

        # 9. Score de confiance
        piece.confiance_extraction = self._calculer_confiance(piece)

        return piece

    def analyser_pdf(self, chemin: Path) -> PieceComptable:
        """Analyse un fichier PDF."""
        try:
            import pdfplumber
            with pdfplumber.open(chemin) as pdf:
                texte = ""
                for page in pdf.pages:
                    texte += (page.extract_text() or "") + "\n"
        except ImportError:
            texte = ""
        except Exception:
            texte = ""

        return self.analyser_document(texte, nom_fichier=chemin.name)

    def analyser_csv_bancaire(self, chemin: Path) -> list[PieceComptable]:
        """Analyse un releve bancaire CSV et genere des pieces."""
        import csv
        pieces = []

        try:
            with open(chemin, "r", encoding="utf-8-sig") as f:
                contenu = f.read()
        except UnicodeDecodeError:
            with open(chemin, "r", encoding="latin-1") as f:
                contenu = f.read()

        import io
        reader = csv.DictReader(io.StringIO(contenu))
        for row in reader:
            piece = PieceComptable(source_fichier=chemin.name)
            piece.type_document = TypeDocument.RELEVE_BANCAIRE

            # Chercher les colonnes date, libelle, montant
            for col, val in row.items():
                if not val:
                    continue
                col_l = col.lower().strip()
                if any(k in col_l for k in ["date", "valeur"]):
                    d = parser_date(val.strip())
                    if d:
                        piece.date_piece = d
                elif any(k in col_l for k in ["libell", "description", "motif", "label"]):
                    piece.numero_piece = val.strip()[:100]
                    piece.texte_brut = val.strip()
                elif any(k in col_l for k in ["debit", "sortie"]):
                    m = parser_montant(val)
                    if m > 0:
                        piece.montant_ttc = m
                        piece.type_document = TypeDocument.FACTURE_ACHAT
                elif any(k in col_l for k in ["credit", "entree", "recette"]):
                    m = parser_montant(val)
                    if m > 0:
                        piece.montant_ttc = m
                        piece.type_document = TypeDocument.FACTURE_VENTE
                elif any(k in col_l for k in ["montant", "amount", "somme"]):
                    m = parser_montant(val)
                    if m != 0:
                        piece.montant_ttc = abs(m)
                        if m < 0:
                            piece.type_document = TypeDocument.FACTURE_ACHAT
                        else:
                            piece.type_document = TypeDocument.FACTURE_VENTE

            if piece.montant_ttc > 0:
                # Estimer HT/TVA
                self._estimer_ht_tva(piece)
                # Detecter le tiers
                if piece.texte_brut:
                    tiers = TiersDetecte(nom=piece.numero_piece)
                    if piece.type_document == TypeDocument.FACTURE_ACHAT:
                        tiers.est_fournisseur = True
                        piece.emetteur = tiers
                    else:
                        tiers.est_client = True
                        piece.destinataire = tiers
                pieces.append(piece)

        return pieces

    # --- Methodes internes ---

    def _classifier_document(self, texte: str) -> TypeDocument:
        """Classifie le type de document selon les mots-cles."""
        texte_lower = texte.lower()
        scores: dict[TypeDocument, int] = {}

        for type_doc, mots_cles in MOTS_CLES_CLASSIFICATION.items():
            score = sum(1 for mc in mots_cles if mc in texte_lower)
            if score > 0:
                scores[type_doc] = score

        if not scores:
            return TypeDocument.INCONNU

        best = max(scores, key=scores.get)

        # Differencier achat/vente si c'est une facture generique
        if best == TypeDocument.FACTURE_VENTE:
            if any(k in texte_lower for k in ["fournisseur", "supplier", "achat"]):
                return TypeDocument.FACTURE_ACHAT

        return best

    def _extraire_champ(self, texte: str, pattern_key: str) -> str:
        pattern = PATTERNS_FACTURE.get(pattern_key)
        if not pattern:
            return ""
        match = pattern.search(texte)
        return match.group(1).strip() if match else ""

    def _extraire_date(self, texte: str, pattern_key: str) -> Optional[date]:
        val = self._extraire_champ(texte, pattern_key)
        return parser_date(val) if val else None

    def _extraire_montant(self, texte: str, pattern_key: str) -> Decimal:
        val = self._extraire_champ(texte, pattern_key)
        return parser_montant(val) if val else Decimal("0")

    def _corriger_montants(self, piece: PieceComptable):
        """Corrige et complete les montants par coherence."""
        if piece.montant_ht > 0 and piece.montant_tva > 0 and piece.montant_ttc == 0:
            piece.montant_ttc = piece.montant_ht + piece.montant_tva
        elif piece.montant_ttc > 0 and piece.montant_ht > 0 and piece.montant_tva == 0:
            piece.montant_tva = piece.montant_ttc - piece.montant_ht
        elif piece.montant_ttc > 0 and piece.montant_ht == 0:
            self._estimer_ht_tva(piece)

    def _estimer_ht_tva(self, piece: PieceComptable, taux: Decimal = Decimal("20")):
        """Estime HT et TVA a partir du TTC."""
        if piece.montant_ttc > 0 and piece.montant_ht == 0:
            coeff = 1 + taux / 100
            piece.montant_ht = (piece.montant_ttc / coeff).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            piece.montant_tva = piece.montant_ttc - piece.montant_ht

    def _detecter_tiers(self, texte: str, position: str = "haut") -> TiersDetecte:
        """Detecte un tiers (client/fournisseur) dans le texte."""
        tiers = TiersDetecte()

        # SIRET
        siret_match = PATTERNS_FACTURE["siret"].search(texte)
        if siret_match:
            tiers.siret = siret_match.group(1).replace(" ", "")
            tiers.siren = tiers.siret[:9]

        # TVA intra
        tva_match = PATTERNS_FACTURE["tva_intra"].search(texte)
        if tva_match:
            tiers.numero_tva = tva_match.group(1).replace(" ", "")

        # Nom : premiere ligne significative du document (heuristique)
        lignes = texte.strip().split("\n")
        for ligne in lignes[:10]:
            ligne = ligne.strip()
            if len(ligne) > 3 and not any(c.isdigit() for c in ligne[:5]):
                if any(kw in ligne.upper() for kw in ["SARL", "SAS", "SA ", "EURL", "SCI", "AUTO"]):
                    tiers.nom = ligne[:100]
                    break
                elif len(ligne) > 5 and ligne[0].isupper():
                    tiers.nom = ligne[:100]
                    break

        return tiers

    def _classifier_achat_vente(self, piece: PieceComptable):
        """Affine la classification achat/vente selon le SIRET de l'entreprise."""
        if not self.entreprise_siret:
            return

        # Si l'emetteur est notre entreprise -> facture de vente
        if piece.emetteur.siret == self.entreprise_siret:
            if piece.type_document in (TypeDocument.FACTURE_VENTE, TypeDocument.FACTURE_ACHAT, TypeDocument.INCONNU):
                piece.type_document = TypeDocument.FACTURE_VENTE
                piece.destinataire.est_client = True
                piece.emetteur.est_fournisseur = False

        # Si le destinataire est notre entreprise -> facture d'achat
        elif piece.destinataire.siret == self.entreprise_siret:
            if piece.type_document in (TypeDocument.FACTURE_VENTE, TypeDocument.FACTURE_ACHAT, TypeDocument.INCONNU):
                piece.type_document = TypeDocument.FACTURE_ACHAT
                piece.emetteur.est_fournisseur = True
                piece.destinataire.est_client = False

    def _detecter_manuscrit(self, texte: str) -> list[str]:
        """Detecte les zones potentiellement manuscrites."""
        manuscrits = []
        # Heuristique : lignes avec melange inhabituel de casse/chiffres
        for ligne in texte.split("\n"):
            ligne = ligne.strip()
            if not ligne:
                continue
            # Ratio majuscules/minuscules irregulier
            upper = sum(1 for c in ligne if c.isupper())
            lower = sum(1 for c in ligne if c.islower())
            total = upper + lower
            if total > 5:
                ratio = upper / total if total > 0 else 0
                if 0.3 < ratio < 0.7:  # Melange inhabituel
                    manuscrits.append(ligne[:100])
            # Annotations courtes (typiquement manuscrites)
            if 2 < len(ligne) < 30 and any(c.isdigit() for c in ligne):
                if not any(kw in ligne.lower() for kw in [
                    "total", "montant", "siret", "date", "tva", "page"
                ]):
                    manuscrits.append(ligne[:100])

        return manuscrits[:10]  # Max 10

    def _calculer_confiance(self, piece: PieceComptable) -> float:
        """Calcule un score de confiance pour l'extraction."""
        score = 0.0
        checks = 0

        # Type document identifie
        checks += 1
        if piece.type_document != TypeDocument.INCONNU:
            score += 1

        # Numero de piece
        checks += 1
        if piece.numero_piece:
            score += 1

        # Date
        checks += 1
        if piece.date_piece:
            score += 1

        # Montant TTC
        checks += 1
        if piece.montant_ttc > 0:
            score += 1

        # Coherence HT + TVA = TTC
        checks += 1
        if piece.montant_ht > 0 and piece.montant_tva >= 0:
            ecart = abs(piece.montant_ht + piece.montant_tva - piece.montant_ttc)
            if ecart < Decimal("0.1"):
                score += 1

        # Tiers detecte
        checks += 1
        if piece.emetteur.nom or piece.emetteur.siret:
            score += 1

        return round(score / checks, 2) if checks > 0 else 0
