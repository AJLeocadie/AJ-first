"""Extracteur d'informations depuis documents juridiques.

Extrait automatiquement les informations cles depuis :
- KBIS / Extrait K (immatriculation RCS)
- Statuts constitutifs de societe
- Actes modificatifs
- Avis de situation SIRENE / INSEE
- Certificats d'inscription (URSSAF, CMA, etc.)

Informations extraites :
- SIREN, SIRET, RCS
- Raison sociale, nom commercial
- Forme juridique (SAS, SARL, EURL, SA, SCI, etc.)
- Capital social
- Adresse du siege social
- Objet social
- Dirigeants (gerant, president, DG)
- Date de creation / immatriculation
- Code NAF / APE
- Convention collective
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass
class Dirigeant:
    """Dirigeant ou mandataire social."""
    nom: str = ""
    prenom: str = ""
    fonction: str = ""  # Gerant, President, DG, etc.
    date_naissance: Optional[date] = None
    nationalite: str = ""


@dataclass
class InfoEntreprise:
    """Informations extraites d'un document juridique."""
    # Identifiants
    siren: str = ""
    siret: str = ""
    rcs: str = ""  # ex: RCS Paris B 123 456 789
    numero_tva: str = ""

    # Denomination
    raison_sociale: str = ""
    nom_commercial: str = ""
    enseigne: str = ""
    sigle: str = ""

    # Forme juridique
    forme_juridique: str = ""
    forme_juridique_code: str = ""  # Code INSEE

    # Capital
    capital_social: Decimal = Decimal("0")
    capital_devise: str = "EUR"
    capital_variable: bool = False

    # Siege
    adresse: str = ""
    code_postal: str = ""
    ville: str = ""
    pays: str = "France"

    # Activite
    objet_social: str = ""
    code_naf: str = ""
    activite_principale: str = ""

    # Dates
    date_immatriculation: Optional[date] = None
    date_creation: Optional[date] = None
    date_cloture_exercice: str = ""  # ex: "31 decembre"
    duree_societe: int = 99  # en annees

    # Dirigeants
    dirigeants: list[Dirigeant] = field(default_factory=list)

    # Convention collective
    convention_collective_idcc: str = ""
    convention_collective_titre: str = ""

    # Effectif
    effectif: int = 0
    tranche_effectif: str = ""  # Code INSEE

    # Metadata
    type_document_source: str = ""
    confiance_extraction: float = 0.0
    champs_extraits: list[str] = field(default_factory=list)
    champs_manquants: list[str] = field(default_factory=list)


# ===================================================================
# PATTERNS REGEX POUR EXTRACTION
# ===================================================================

PATTERNS_JURIDIQUES = {
    # Identifiants
    "siren": re.compile(
        r"(?:SIREN|N[°o]?\s*SIREN)\s*[:\s]*(\d{3}\s*\d{3}\s*\d{3})",
        re.IGNORECASE,
    ),
    "siret": re.compile(
        r"(?:SIRET|N[°o]?\s*SIRET)\s*[:\s]*(\d{3}\s*\d{3}\s*\d{3}\s*\d{5})",
        re.IGNORECASE,
    ),
    "rcs": re.compile(
        r"(?:RCS|R\.C\.S\.?|Registre\s+du\s+Commerce)\s*[:\s]*([\w\s]+?[A-Z]\s*\d{3}\s*\d{3}\s*\d{3})",
        re.IGNORECASE,
    ),
    "tva_intra": re.compile(
        r"(?:TVA\s*intra|N[°o]\s*TVA|Identifiant\s*TVA)\s*[:\s]*(FR\s*\d{2}\s*\d{9})",
        re.IGNORECASE,
    ),

    # Capital
    "capital": re.compile(
        r"[Cc]apital\s*(?:social)?\s*(?:de)?\s*[:\s]*([\d\s,.]+)\s*(?:€|EUR|euros?)",
        re.IGNORECASE,
    ),
    "capital_variable": re.compile(
        r"capital\s*variable",
        re.IGNORECASE,
    ),

    # Forme juridique
    "forme_juridique": re.compile(
        r"(?:Forme\s*(?:juridique)?\s*[:\s]*|societe\s+)"
        r"((?:SAS|SARL|EURL|SA|SCI|SNC|SASU|SELARL|SELURL|SELAFA|"
        r"Societe\s+(?:par\s+actions\s+simplifiee|a\s+responsabilite\s+limitee|"
        r"civile\s+immobiliere|anonyme|en\s+nom\s+collectif))"
        r"(?:\s+a\s+(?:capital\s+variable|associe\s+unique))?)",
        re.IGNORECASE,
    ),

    # Dates
    "date_immatriculation": re.compile(
        r"(?:immatricul[ée]e?\s*(?:le|du|en)|date\s*(?:d[e']?)?\s*immatriculation)\s*[:\s]*"
        r"(\d{1,2}[/.\-\s]+\w+[/.\-\s]+\d{4}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})",
        re.IGNORECASE,
    ),
    "date_creation": re.compile(
        r"(?:cr[ée][ée]e?\s*(?:le|du|en)|date\s*(?:de\s*)?cr[ée]ation|constitu[ée]e?\s*(?:le|en))\s*[:\s]*"
        r"(\d{1,2}[/.\-\s]+\w+[/.\-\s]+\d{4}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})",
        re.IGNORECASE,
    ),
    "duree": re.compile(
        r"dur[ée]e\s*(?:de\s*la\s*soci[ée]t[ée])?\s*[:\s]*(\d+)\s*(?:ans?|ann[ée]es?)",
        re.IGNORECASE,
    ),
    "cloture_exercice": re.compile(
        r"cl[oô]ture\s*(?:de\s*l['']\s*exercice|exercice\s*social)?\s*[:\s]*"
        r"(\d{1,2}\s*(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre))",
        re.IGNORECASE,
    ),

    # Code NAF
    "code_naf": re.compile(
        r"(?:Code\s*(?:NAF|APE)|NAF|APE)\s*[:\s]*(\d{4}[A-Z])",
        re.IGNORECASE,
    ),

    # Activite
    "activite": re.compile(
        r"(?:Activit[ée]\s*(?:principale)?|Objet\s*(?:social)?)\s*[:\s]*(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),

    # Effectif
    "effectif": re.compile(
        r"(?:Effectif|Nombre\s*(?:de\s*)?salari[ée]s?)\s*[:\s]*(\d+)",
        re.IGNORECASE,
    ),

    # Convention collective
    "convention_collective": re.compile(
        r"(?:Convention\s*collective|CCN|IDCC)\s*[:\s]*(?:n[°o]?\s*)?(\d{4})\s*[-:]\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),

    # Adresse
    "adresse_siege": re.compile(
        r"(?:Si[èe]ge\s*(?:social)?|Adresse)\s*[:\s]*(.*?)(?:\n|$)",
        re.IGNORECASE,
    ),
    "code_postal_ville": re.compile(
        r"(\d{5})\s+([\w\s-]+?)(?:\s*(?:Cedex|cedex)\s*\d*)?(?:\n|$)",
    ),

    # Dirigeants
    "gerant": re.compile(
        r"(?:G[ée]rant|Dirigeant|Repr[ée]sentant\s*l[ée]gal)\s*[:\s]*((?:M(?:me|r|lle)?\.?\s*)?[\w\s-]+)",
        re.IGNORECASE,
    ),
    "president": re.compile(
        r"(?:Pr[ée]sident(?:e)?)\s*[:\s]*((?:M(?:me|r|lle)?\.?\s*)?[\w\s-]+)",
        re.IGNORECASE,
    ),
    "directeur_general": re.compile(
        r"(?:Directeur\s*[Gg][ée]n[ée]ral|DG)\s*[:\s]*((?:M(?:me|r|lle)?\.?\s*)?[\w\s-]+)",
        re.IGNORECASE,
    ),
}

# Mapping formes juridiques -> codes INSEE
FORMES_JURIDIQUES = {
    "SAS": ("5710", "Societe par actions simplifiee"),
    "SASU": ("5710", "Societe par actions simplifiee a associe unique"),
    "SARL": ("5499", "Societe a responsabilite limitee"),
    "EURL": ("5498", "SARL unipersonnelle"),
    "SA": ("5599", "Societe anonyme"),
    "SCI": ("6540", "Societe civile immobiliere"),
    "SNC": ("5202", "Societe en nom collectif"),
    "SELARL": ("5485", "Societe d'exercice liberal a responsabilite limitee"),
    "SELURL": ("5485", "SELARL unipersonnelle"),
    "EI": ("1000", "Entrepreneur individuel"),
    "EIRL": ("1000", "Entrepreneur individuel a responsabilite limitee"),
    "MICRO": ("1000", "Micro-entrepreneur"),
}


class LegalDocumentExtractor:
    """Extracteur d'informations depuis documents juridiques."""

    def extraire(self, texte: str, type_document: str = "") -> InfoEntreprise:
        """Extrait les informations d'un document juridique.

        Args:
            texte: Texte brut du document
            type_document: Type identifie (kbis, statuts, avis_sirene, etc.)
        """
        info = InfoEntreprise(type_document_source=type_document)

        # Identifier le type de document si non fourni
        if not type_document:
            type_document = self._identifier_type_document(texte)
            info.type_document_source = type_document

        # Extraction des champs
        self._extraire_identifiants(texte, info)
        self._extraire_denomination(texte, info)
        self._extraire_forme_juridique(texte, info)
        self._extraire_capital(texte, info)
        self._extraire_adresse(texte, info)
        self._extraire_activite(texte, info)
        self._extraire_dates(texte, info)
        self._extraire_dirigeants(texte, info)
        self._extraire_effectif_convention(texte, info)

        # Score de confiance et champs manquants
        self._evaluer_extraction(info)

        return info

    def _identifier_type_document(self, texte: str) -> str:
        """Identifie le type de document juridique."""
        texte_lower = texte.lower()

        if any(k in texte_lower for k in ["extrait kbis", "k bis", "extrait k", "greffe du tribunal"]):
            return "kbis"
        elif any(k in texte_lower for k in ["statuts", "statut constitutif", "il est forme"]):
            return "statuts"
        elif any(k in texte_lower for k in ["avis de situation", "sirene", "repertoire des entreprises"]):
            return "avis_sirene"
        elif any(k in texte_lower for k in ["certificat d'inscription", "urssaf"]):
            return "certificat_urssaf"
        elif any(k in texte_lower for k in ["chambre des metiers", "repertoire des metiers"]):
            return "inscription_cma"
        elif any(k in texte_lower for k in ["acte modificatif", "assemblee generale"]):
            return "acte_modificatif"
        return "inconnu"

    def _extraire_identifiants(self, texte: str, info: InfoEntreprise):
        """Extrait SIREN, SIRET, RCS, TVA."""
        # SIRET (prioritaire car contient SIREN)
        m = PATTERNS_JURIDIQUES["siret"].search(texte)
        if m:
            info.siret = m.group(1).replace(" ", "")
            info.siren = info.siret[:9]
            info.champs_extraits.append("siret")

        # SIREN (si SIRET non trouve)
        if not info.siren:
            m = PATTERNS_JURIDIQUES["siren"].search(texte)
            if m:
                info.siren = m.group(1).replace(" ", "")
                info.champs_extraits.append("siren")

        # RCS
        m = PATTERNS_JURIDIQUES["rcs"].search(texte)
        if m:
            info.rcs = m.group(1).strip()
            info.champs_extraits.append("rcs")
            # Extraire SIREN du RCS si pas encore trouve
            if not info.siren:
                digits = re.findall(r"\d+", info.rcs)
                siren_candidate = "".join(digits)
                if len(siren_candidate) >= 9:
                    info.siren = siren_candidate[:9]

        # TVA intra
        m = PATTERNS_JURIDIQUES["tva_intra"].search(texte)
        if m:
            info.numero_tva = m.group(1).replace(" ", "")
            info.champs_extraits.append("tva_intra")

    def _extraire_denomination(self, texte: str, info: InfoEntreprise):
        """Extrait la raison sociale et le nom commercial."""
        # Patterns specifiques pour la denomination
        patterns_denomination = [
            re.compile(r"(?:D[ée]nomination|Raison\s*sociale)\s*[:\s]*(.+?)(?:\n|$)", re.IGNORECASE),
            re.compile(r"(?:Nom\s*commercial|Enseigne)\s*[:\s]*(.+?)(?:\n|$)", re.IGNORECASE),
        ]

        m = patterns_denomination[0].search(texte)
        if m:
            info.raison_sociale = m.group(1).strip()[:200]
            info.champs_extraits.append("raison_sociale")

        m = patterns_denomination[1].search(texte)
        if m:
            info.nom_commercial = m.group(1).strip()[:200]

        # Fallback: chercher dans les premieres lignes
        if not info.raison_sociale:
            for ligne in texte.strip().split("\n")[:15]:
                ligne = ligne.strip()
                if any(kw in ligne.upper() for kw in ["SAS", "SARL", "EURL", "SA ", "SCI", "SNC"]):
                    info.raison_sociale = ligne[:200]
                    info.champs_extraits.append("raison_sociale")
                    break

    def _extraire_forme_juridique(self, texte: str, info: InfoEntreprise):
        """Extrait la forme juridique."""
        m = PATTERNS_JURIDIQUES["forme_juridique"].search(texte)
        if m:
            forme_brute = m.group(1).strip().upper()
            info.forme_juridique = forme_brute

            # Normaliser
            for code, (code_insee, libelle) in FORMES_JURIDIQUES.items():
                if code in forme_brute:
                    info.forme_juridique = code
                    info.forme_juridique_code = code_insee
                    break

            info.champs_extraits.append("forme_juridique")
        else:
            # Chercher dans le texte brut
            texte_upper = texte.upper()
            for code in ["SASU", "SAS", "EURL", "SARL", "SA", "SCI", "SNC", "SELARL"]:
                if f" {code} " in texte_upper or f" {code}," in texte_upper:
                    info.forme_juridique = code
                    fg = FORMES_JURIDIQUES.get(code)
                    if fg:
                        info.forme_juridique_code = fg[0]
                    info.champs_extraits.append("forme_juridique")
                    break

    def _extraire_capital(self, texte: str, info: InfoEntreprise):
        """Extrait le capital social."""
        m = PATTERNS_JURIDIQUES["capital"].search(texte)
        if m:
            val = m.group(1).replace(" ", "").replace(",", ".")
            try:
                info.capital_social = Decimal(val)
                info.champs_extraits.append("capital_social")
            except Exception:
                pass

        if PATTERNS_JURIDIQUES["capital_variable"].search(texte):
            info.capital_variable = True

    def _extraire_adresse(self, texte: str, info: InfoEntreprise):
        """Extrait l'adresse du siege social."""
        m = PATTERNS_JURIDIQUES["adresse_siege"].search(texte)
        if m:
            info.adresse = m.group(1).strip()[:300]
            info.champs_extraits.append("adresse")

        # Code postal + ville
        m = PATTERNS_JURIDIQUES["code_postal_ville"].search(texte)
        if m:
            info.code_postal = m.group(1)
            info.ville = m.group(2).strip()
            info.champs_extraits.append("ville")

    def _extraire_activite(self, texte: str, info: InfoEntreprise):
        """Extrait le code NAF et l'objet social."""
        m = PATTERNS_JURIDIQUES["code_naf"].search(texte)
        if m:
            info.code_naf = m.group(1)
            info.champs_extraits.append("code_naf")

        m = PATTERNS_JURIDIQUES["activite"].search(texte)
        if m:
            info.activite_principale = m.group(1).strip()[:500]
            if not info.objet_social:
                info.objet_social = info.activite_principale

        # Objet social dans les statuts (souvent plus long)
        objet_match = re.search(
            r"(?:objet\s*social|objet\s*de\s*la\s*soci[ée]t[ée])\s*[:\s]*(.*?)(?=\n\s*(?:Article|ARTICLE|\d+[°.)]\s|Si[èe]ge|Dur[ée]e))",
            texte, re.IGNORECASE | re.DOTALL,
        )
        if objet_match:
            info.objet_social = objet_match.group(1).strip()[:1000]
            info.champs_extraits.append("objet_social")

    def _extraire_dates(self, texte: str, info: InfoEntreprise):
        """Extrait les dates cles."""
        m = PATTERNS_JURIDIQUES["date_immatriculation"].search(texte)
        if m:
            d = self._parser_date_fr(m.group(1))
            if d:
                info.date_immatriculation = d
                info.champs_extraits.append("date_immatriculation")

        m = PATTERNS_JURIDIQUES["date_creation"].search(texte)
        if m:
            d = self._parser_date_fr(m.group(1))
            if d:
                info.date_creation = d
                info.champs_extraits.append("date_creation")

        m = PATTERNS_JURIDIQUES["duree"].search(texte)
        if m:
            try:
                info.duree_societe = int(m.group(1))
            except ValueError:
                pass

        m = PATTERNS_JURIDIQUES["cloture_exercice"].search(texte)
        if m:
            info.date_cloture_exercice = m.group(1).strip()
            info.champs_extraits.append("cloture_exercice")

    def _extraire_dirigeants(self, texte: str, info: InfoEntreprise):
        """Extrait les dirigeants et mandataires sociaux."""
        for pattern_key, fonction in [
            ("gerant", "Gerant"),
            ("president", "President"),
            ("directeur_general", "Directeur General"),
        ]:
            m = PATTERNS_JURIDIQUES[pattern_key].search(texte)
            if m:
                nom_complet = m.group(1).strip()
                # Nettoyer le prefixe (M., Mme, etc.)
                nom_complet = re.sub(r'^M(?:me|r|lle)?\.?\s*', '', nom_complet).strip()
                if nom_complet and len(nom_complet) > 2:
                    parts = nom_complet.split()
                    dirigeant = Dirigeant(
                        nom=parts[-1] if parts else nom_complet,
                        prenom=" ".join(parts[:-1]) if len(parts) > 1 else "",
                        fonction=fonction,
                    )
                    info.dirigeants.append(dirigeant)

        if info.dirigeants:
            info.champs_extraits.append("dirigeants")

    def _extraire_effectif_convention(self, texte: str, info: InfoEntreprise):
        """Extrait effectif et convention collective."""
        m = PATTERNS_JURIDIQUES["effectif"].search(texte)
        if m:
            try:
                info.effectif = int(m.group(1))
                info.champs_extraits.append("effectif")
            except ValueError:
                pass

        m = PATTERNS_JURIDIQUES["convention_collective"].search(texte)
        if m:
            info.convention_collective_idcc = m.group(1)
            info.convention_collective_titre = m.group(2).strip()
            info.champs_extraits.append("convention_collective")

    def _evaluer_extraction(self, info: InfoEntreprise):
        """Evalue la qualite de l'extraction et liste les champs manquants."""
        champs_essentiels = [
            ("siren", "SIREN"),
            ("raison_sociale", "Raison sociale"),
            ("forme_juridique", "Forme juridique"),
            ("adresse", "Adresse siege"),
            ("ville", "Ville"),
            ("code_naf", "Code NAF"),
        ]

        for champ, libelle in champs_essentiels:
            if champ not in info.champs_extraits:
                info.champs_manquants.append(libelle)

        total_champs = len(champs_essentiels)
        extraits = total_champs - len(info.champs_manquants)
        info.confiance_extraction = round(extraits / total_champs, 2) if total_champs else 0

    def _parser_date_fr(self, texte_date: str) -> Optional[date]:
        """Parse une date en format francais."""
        mois_fr = {
            "janvier": 1, "fevrier": 2, "février": 2, "mars": 3,
            "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
            "aout": 8, "août": 8, "septembre": 9, "octobre": 10,
            "novembre": 11, "decembre": 12, "décembre": 12,
        }

        # Format JJ/MM/AAAA ou JJ-MM-AAAA
        m = re.match(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", texte_date.strip())
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

        # Format JJ mois AAAA
        m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", texte_date.strip())
        if m:
            mois = mois_fr.get(m.group(2).lower())
            if mois:
                try:
                    return date(int(m.group(3)), mois, int(m.group(1)))
                except ValueError:
                    pass

        return None

    def info_to_dict(self, info: InfoEntreprise) -> dict:
        """Convertit un InfoEntreprise en dictionnaire serialisable."""
        return {
            "siren": info.siren,
            "siret": info.siret,
            "rcs": info.rcs,
            "numero_tva": info.numero_tva,
            "raison_sociale": info.raison_sociale,
            "nom_commercial": info.nom_commercial,
            "forme_juridique": info.forme_juridique,
            "forme_juridique_code": info.forme_juridique_code,
            "capital_social": float(info.capital_social),
            "capital_variable": info.capital_variable,
            "adresse": info.adresse,
            "code_postal": info.code_postal,
            "ville": info.ville,
            "objet_social": info.objet_social[:500] if info.objet_social else "",
            "code_naf": info.code_naf,
            "activite_principale": info.activite_principale[:200] if info.activite_principale else "",
            "date_immatriculation": info.date_immatriculation.isoformat() if info.date_immatriculation else None,
            "date_creation": info.date_creation.isoformat() if info.date_creation else None,
            "date_cloture_exercice": info.date_cloture_exercice,
            "duree_societe": info.duree_societe,
            "dirigeants": [
                {"nom": d.nom, "prenom": d.prenom, "fonction": d.fonction}
                for d in info.dirigeants
            ],
            "convention_collective_idcc": info.convention_collective_idcc,
            "convention_collective_titre": info.convention_collective_titre,
            "effectif": info.effectif,
            "type_document_source": info.type_document_source,
            "confiance_extraction": info.confiance_extraction,
            "champs_extraits": info.champs_extraits,
            "champs_manquants": info.champs_manquants,
        }
