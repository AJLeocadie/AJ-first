"""Parseur specialise pour les fichiers DSN (Declaration Sociale Nominative).

La DSN est un fichier structure (texte ou XML) avec des blocs :
- S10 : Emetteur de la declaration
- S20 : Entreprise
- S21 : Etablissement / Periode
- S30 : Identification du salarie
- S40 : Contrat
- S41 : Changements de contrat
- S43 : Bases assujetties (assiettes de cotisations)
- S44 : Arret de travail
- S48 : Versement OPS (cotisations individuelles)
- S51 : Remuneration
- S78 : Base assujettie (detaillee)
- S79 : Composant de base assujettie
- S81 : Cotisation individuelle
- S89 : Total versement OPS
"""

import re
from decimal import Decimal
from datetime import date
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import (
    Document, Declaration, Cotisation, Employe, Employeur, DateRange,
)
from urssaf_analyzer.config.constants import ContributionType
from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.utils.date_utils import parser_date
from urssaf_analyzer.utils.number_utils import parser_montant


# Mapping des codes DSN vers les types de cotisations
# Codes CTP (Codes Types de Personnel) les plus courants
CTP_MAPPING = {
    "100": ContributionType.MALADIE,                    # RG cas general
    "260": ContributionType.VIEILLESSE_PLAFONNEE,       # Vieillesse plafonnee
    "262": ContributionType.VIEILLESSE_DEPLAFONNEE,     # Vieillesse deplafonnee
    "332": ContributionType.ALLOCATIONS_FAMILIALES,     # Alloc. familiales
    "452": ContributionType.ACCIDENT_TRAVAIL,           # AT/MP
    "012": ContributionType.CSG_DEDUCTIBLE,             # CSG
    "018": ContributionType.CRDS,                       # CRDS
    "772": ContributionType.ASSURANCE_CHOMAGE,          # Chomage
    "937": ContributionType.AGS,                        # AGS
    "236": ContributionType.FNAL,                       # FNAL
    "971": ContributionType.FORMATION_PROFESSIONNELLE,  # Formation pro
}

# Pattern pour les lignes DSN en format texte structure
# Accepte virgule ou espace comme separateur entre cle et valeur
DSN_LINE_PATTERN = re.compile(r"^S(\d{2})\.G(\d{2})\.(\d{2})\.(\d{3})[,\s]+'([^']*)'", re.MULTILINE)


class DSNParser(BaseParser):
    """Parse les fichiers DSN en format texte structure ou XML."""

    def peut_traiter(self, chemin: Path) -> bool:
        if chemin.suffix.lower() == ".dsn":
            return True
        # Peut aussi etre un XML DSN
        if chemin.suffix.lower() == ".xml":
            try:
                with open(chemin, "r", encoding="utf-8") as f:
                    debut = f.read(500)
                return "dsn" in debut.lower() or "S10.G00" in debut
            except Exception:
                return False
        return False

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        contenu = self._lire_fichier(chemin)
        metadata = {"format": "dsn"}

        if contenu.startswith("<?xml") or contenu.startswith("<"):
            metadata["sous_format"] = "xml"
        else:
            metadata["sous_format"] = "texte_structure"

        # Compter les blocs
        blocs = {}
        for match in DSN_LINE_PATTERN.finditer(contenu):
            bloc = f"S{match.group(1)}"
            blocs[bloc] = blocs.get(bloc, 0) + 1
        metadata["blocs"] = blocs

        return metadata

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        contenu = self._lire_fichier(chemin)

        if contenu.strip().startswith("<?xml") or contenu.strip().startswith("<"):
            return self._parser_dsn_xml(contenu, document.id)
        else:
            return self._parser_dsn_texte(contenu, document.id)

    def _lire_fichier(self, chemin: Path) -> str:
        """Lit le fichier DSN avec detection d'encodage."""
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                with open(chemin, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise ParseError(f"Impossible de decoder le fichier DSN {chemin}")

    def _parser_dsn_texte(self, contenu: str, doc_id: str) -> list[Declaration]:
        """Parse un fichier DSN au format texte structure."""
        donnees = {}
        for match in DSN_LINE_PATTERN.finditer(contenu):
            bloc = match.group(1)
            groupe = match.group(2)
            sous_groupe = match.group(3)
            numero = match.group(4)
            valeur = match.group(5)
            cle = f"S{bloc}.G{groupe}.{sous_groupe}.{numero}"
            if cle not in donnees:
                donnees[cle] = []
            donnees[cle].append(valeur)

        # Extraire les informations de la declaration
        employeur = self._extraire_employeur_texte(donnees, doc_id)
        employes = self._extraire_employes_texte(donnees, doc_id)
        cotisations = self._extraire_cotisations_texte(donnees, doc_id)
        periode = self._extraire_periode_texte(donnees)

        declaration = Declaration(
            type_declaration="DSN",
            periode=periode,
            employeur=employeur,
            employes=employes,
            cotisations=cotisations,
            effectif_declare=len(employes),
            source_document_id=doc_id,
        )

        if cotisations:
            # Masse salariale = somme des bases brutes uniques
            bases_vues = set()
            total = Decimal("0")
            for c in cotisations:
                key = (c.employe_id, str(c.base_brute))
                if key not in bases_vues:
                    bases_vues.add(key)
                    total += c.base_brute
            declaration.masse_salariale_brute = total

        # Ajouter type_document pour reconnaissance
        declaration.metadata = getattr(declaration, "metadata", {}) or {}
        declaration.metadata["type_document"] = "declaration_dsn"

        # S89 - Total versement OPS (totaux declares)
        s89_totaux = self._extraire_totaux_s89(donnees)
        if s89_totaux:
            declaration.reference = declaration.reference or ""
            declaration.metadata["s89_total_cotisations"] = float(s89_totaux.get("total_cotisations", 0))
            declaration.metadata["s89_total_brut"] = float(s89_totaux.get("total_brut", 0))

        return [declaration]

    def _extraire_employeur_texte(self, donnees: dict, doc_id: str) -> Employeur | None:
        """Extrait l'employeur depuis les blocs S10/S20/S21."""
        emp = Employeur(source_document_id=doc_id)

        # S10.G00.01.001 = SIREN de l'emetteur
        siren = self._get_val(donnees, "S10.G00.01.001")
        if siren and len(siren) == 9:
            emp.siren = siren

        # S21.G00.06.001 = SIRET de l'etablissement (14 caracteres)
        siret = self._get_val(donnees, "S21.G00.06.001")
        if siret and len(siret) >= 14:
            emp.siret = siret
            if not emp.siren:
                emp.siren = siret[:9]

        # S21.G00.06.002 = Raison sociale
        raison = self._get_val(donnees, "S21.G00.06.002")
        if raison:
            emp.raison_sociale = raison

        # S21.G00.11.001 = Effectif
        effectif = self._get_val(donnees, "S21.G00.11.001")
        if effectif:
            try:
                emp.effectif = int(effectif)
            except ValueError:
                pass

        return emp if emp.siren or emp.siret else None

    def _extraire_employes_texte(self, donnees: dict, doc_id: str) -> list[Employe]:
        """Extrait les employes depuis les blocs S21.G00.30 ou S30.G00.30."""
        employes = []
        nirs_vus = set()

        # Chercher dans les deux prefixes possibles (S21 puis S30)
        for prefix in ("S21.G00.30", "S30.G00.30"):
            nirs = donnees.get(f"{prefix}.001", [])
            noms = donnees.get(f"{prefix}.002", [])
            prenoms = donnees.get(f"{prefix}.004", [])
            dates_naissance = donnees.get(f"{prefix}.006", [])

            for i, nir in enumerate(nirs):
                if nir and nir not in nirs_vus:
                    nirs_vus.add(nir)
                    emp = Employe(
                        nir=nir,
                        nom=noms[i] if i < len(noms) else "",
                        prenom=prenoms[i] if i < len(prenoms) else "",
                        source_document_id=doc_id,
                    )
                    if i < len(dates_naissance) and dates_naissance[i]:
                        emp.date_naissance = parser_date(dates_naissance[i])
                    employes.append(emp)

        return employes

    def _extraire_cotisations_texte(self, donnees: dict, doc_id: str) -> list[Cotisation]:
        """Extrait les cotisations depuis les blocs S81/S21.G00.81 ou S78/S79."""
        cotisations = []

        # Chercher dans les deux prefixes possibles (S21 puis S81)
        for prefix in ("S21.G00.81", "S81.G00.81"):
            codes = donnees.get(f"{prefix}.001", [])
            bases = donnees.get(f"{prefix}.003", [])
            taux_list = donnees.get(f"{prefix}.004", [])
            montants = donnees.get(f"{prefix}.005", [])

            max_len = max(len(codes), len(bases), len(taux_list), len(montants), 0)
            for i in range(max_len):
                c = Cotisation(source_document_id=doc_id)

                if i < len(codes) and codes[i]:
                    c.type_cotisation = CTP_MAPPING.get(codes[i], ContributionType.MALADIE)
                if i < len(bases) and bases[i]:
                    c.base_brute = parser_montant(bases[i])
                    c.assiette = c.base_brute
                if i < len(taux_list) and taux_list[i]:
                    t = parser_montant(taux_list[i])
                    if t > 1:
                        t = t / 100
                    c.taux_patronal = t
                if i < len(montants) and montants[i]:
                    c.montant_patronal = parser_montant(montants[i])

                if c.base_brute > 0 or c.montant_patronal > 0:
                    cotisations.append(c)

            if cotisations:
                break  # Ne pas doubler si on a trouve dans S21

        # Si pas de S81/S21.G00.81, essayer S78 (bases assujetties)
        if not cotisations:
            for prefix in ("S21.G00.78", "S78.G00.78"):
                codes_78 = donnees.get(f"{prefix}.001", [])
                bases_78 = donnees.get(f"{prefix}.004", [])
                for i in range(min(len(codes_78), len(bases_78))):
                    c = Cotisation(source_document_id=doc_id)
                    c.type_cotisation = CTP_MAPPING.get(codes_78[i], ContributionType.MALADIE)
                    c.base_brute = parser_montant(bases_78[i])
                    c.assiette = c.base_brute
                    if c.base_brute > 0:
                        cotisations.append(c)
                if cotisations:
                    break

        # Extraire remuneration depuis S21.G00.51 si pas de cotisations
        # mais qu'il y a un brut declare
        if not cotisations:
            bruts = donnees.get("S21.G00.51.001", [])
            for brut_str in bruts:
                if brut_str:
                    c = Cotisation(source_document_id=doc_id)
                    c.base_brute = parser_montant(brut_str)
                    c.assiette = c.base_brute
                    c.type_cotisation = ContributionType.MALADIE
                    if c.base_brute > 0:
                        cotisations.append(c)

        return cotisations

    def _extraire_totaux_s89(self, donnees: dict) -> dict | None:
        """Extrait les totaux declares dans le bloc S89 (Total versement OPS)."""
        # S89.G00.89.001 = Montant total des cotisations
        # S89.G00.89.002 = Montant total du brut
        total_cot_str = self._get_val(donnees, "S89.G00.89.001")
        total_brut_str = self._get_val(donnees, "S89.G00.89.002")
        if total_cot_str or total_brut_str:
            return {
                "total_cotisations": float(parser_montant(total_cot_str)) if total_cot_str else 0,
                "total_brut": float(parser_montant(total_brut_str)) if total_brut_str else 0,
            }
        return None

    def _extraire_periode_texte(self, donnees: dict) -> DateRange | None:
        """Extrait la periode de la declaration."""
        import calendar

        # Essayer S20.G00.05.002 = Periode au format AAAAMM
        periode_str = self._get_val(donnees, "S20.G00.05.002")
        if periode_str and len(periode_str) == 6:
            try:
                annee = int(periode_str[:4])
                mois_num = int(periode_str[4:6])
                if 1 <= mois_num <= 12:
                    dernier_jour = calendar.monthrange(annee, mois_num)[1]
                    return DateRange(
                        debut=date(annee, mois_num, 1),
                        fin=date(annee, mois_num, dernier_jour),
                    )
            except (ValueError, OverflowError):
                pass

        # Fallback: S21.G00.06.003 = Mois de la declaration
        mois = self._get_val(donnees, "S21.G00.06.003")
        if mois:
            d = parser_date(mois)
            if d:
                dernier_jour = calendar.monthrange(d.year, d.month)[1]
                return DateRange(
                    debut=date(d.year, d.month, 1),
                    fin=date(d.year, d.month, dernier_jour),
                )
        return None

    def _parser_dsn_xml(self, contenu: str, doc_id: str) -> list[Declaration]:
        """Parse un fichier DSN au format XML."""
        try:
            root = ET.fromstring(contenu)
        except ET.ParseError as e:
            raise ParseError(f"XML DSN invalide: {e}") from e

        # Deleguer au parser XML avec contexte DSN
        from urssaf_analyzer.parsers.xml_parser import XMLParser
        xml_parser = XMLParser()

        # Creer un document temporaire
        doc = Document(id=doc_id)
        # On reutilise le parser XML qui gere les structures DSN
        # mais on requalifie la declaration
        declarations = xml_parser._parser_dsn_structure(root, doc_id)
        for d in declarations:
            d.type_declaration = "DSN/XML"
        return declarations

    @staticmethod
    def _get_val(donnees: dict, cle: str) -> str | None:
        """Retourne la premiere valeur pour une cle DSN."""
        vals = donnees.get(cle, [])
        return vals[0] if vals else None
