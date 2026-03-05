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
- S60 : Fin de contrat (signalement)
- S65 : Autre suspension (conge maternite, paternite, etc.)
- S70 : Changement de situation
- S78 : Base assujettie (detaillee)
- S79 : Composant de base assujettie
- S81 : Cotisation individuelle
- S89 : Total versement OPS

Compatible NEODeS Phase 3 (norme en vigueur 2024-2026).
Supporte les fichiers generes par SAGE, CIEL, EBP, ADP, Silae, CEGID, PayFit.
"""

import logging
import re
from decimal import Decimal
from datetime import date
from pathlib import Path
from typing import Any
import defusedxml.ElementTree as ET

from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import (
    Document, Declaration, Cotisation, Employe, Employeur, DateRange,
)
from urssaf_analyzer.config.constants import ContributionType
from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.utils.date_utils import parser_date
from urssaf_analyzer.utils.number_utils import parser_montant, valider_siret, valider_siren
from urssaf_analyzer.utils.validators import valider_nir, valider_bloc_dsn, ParseLog

logger = logging.getLogger(__name__)


# Mapping des codes DSN vers les types de cotisations
# Codes CTP (Codes Types de Personnel) - couverture etendue NEODeS Phase 3
CTP_MAPPING = {
    # Maladie / Maternite / Invalidite / Deces
    "100": ContributionType.MALADIE,                    # RG cas general
    "101": ContributionType.MALADIE,                    # RG cas general - complement
    "110": ContributionType.MALADIE,                    # Maladie Alsace-Moselle
    "112": ContributionType.MALADIE,                    # Maladie complementaire Alsace-Moselle
    "114": ContributionType.MALADIE,                    # Maladie deplafonnee (complement)
    "120": ContributionType.MALADIE,                    # IJ maladie
    "430": ContributionType.MALADIE,                    # Maladie artistes
    "432": ContributionType.MALADIE,                    # Maladie artistes complement
    # Vieillesse
    "260": ContributionType.VIEILLESSE_PLAFONNEE,       # Vieillesse plafonnee
    "261": ContributionType.VIEILLESSE_PLAFONNEE,       # Vieillesse plafonnee complement
    "262": ContributionType.VIEILLESSE_DEPLAFONNEE,     # Vieillesse deplafonnee
    "263": ContributionType.VIEILLESSE_DEPLAFONNEE,     # Vieillesse deplafonnee complement
    "280": ContributionType.VIEILLESSE_PLAFONNEE,       # Vieillesse plaf. fonctionnaire
    "282": ContributionType.VIEILLESSE_DEPLAFONNEE,     # Vieillesse deplaf. fonctionnaire
    # Allocations familiales
    "332": ContributionType.ALLOCATIONS_FAMILIALES,     # Alloc. familiales taux normal
    "334": ContributionType.ALLOCATIONS_FAMILIALES,     # AF taux reduit (< 3.5 SMIC)
    "336": ContributionType.ALLOCATIONS_FAMILIALES,     # AF employeur etranger
    # AT/MP
    "452": ContributionType.ACCIDENT_TRAVAIL,           # AT/MP taux bureau
    "454": ContributionType.ACCIDENT_TRAVAIL,           # AT/MP taux atelier
    "456": ContributionType.ACCIDENT_TRAVAIL,           # AT/MP taux specifique
    "458": ContributionType.ACCIDENT_TRAVAIL,           # AT/MP taux collectivites
    # CSG / CRDS
    "004": ContributionType.CSG_NON_DEDUCTIBLE,         # CSG non deductible
    "012": ContributionType.CSG_DEDUCTIBLE,             # CSG deductible
    "014": ContributionType.CSG_DEDUCTIBLE,             # CSG deductible - revenus remplacement
    "018": ContributionType.CRDS,                       # CRDS
    # Chomage / AGS
    "772": ContributionType.ASSURANCE_CHOMAGE,          # Chomage cas general
    "774": ContributionType.ASSURANCE_CHOMAGE,          # Chomage CDD usage
    "776": ContributionType.ASSURANCE_CHOMAGE,          # Chomage intermittents
    "937": ContributionType.AGS,                        # AGS
    "938": ContributionType.AGS,                        # AGS complement
    # FNAL
    "236": ContributionType.FNAL,                       # FNAL <= 50 salaries (0.10%)
    "238": ContributionType.FNAL,                       # FNAL > 50 salaries (0.50%)
    # Formation professionnelle / Apprentissage
    "971": ContributionType.FORMATION_PROFESSIONNELLE,  # Formation pro < 11 sal (0.55%)
    "973": ContributionType.FORMATION_PROFESSIONNELLE,  # Formation pro >= 11 sal (1%)
    "975": ContributionType.FORMATION_PROFESSIONNELLE,  # Formation pro CDD (1%)
    "951": ContributionType.TAXE_APPRENTISSAGE,         # Taxe apprentissage (0.68%)
    "953": ContributionType.TAXE_APPRENTISSAGE,         # TA fraction principale
    "955": ContributionType.TAXE_APPRENTISSAGE,         # TA solde liberatoire
    "957": ContributionType.TAXE_APPRENTISSAGE,         # TA Alsace-Moselle
    "959": ContributionType.TAXE_APPRENTISSAGE,         # Contribution suppl. apprentissage
    # Retraite complementaire AGIRC-ARRCO
    "063": ContributionType.RETRAITE_COMPLEMENTAIRE_T1, # Agirc-Arrco T1 taux appel
    "064": ContributionType.RETRAITE_COMPLEMENTAIRE_T1, # Agirc-Arrco T1 complement
    "065": ContributionType.RETRAITE_COMPLEMENTAIRE_T2, # Agirc-Arrco T2 taux appel
    "066": ContributionType.RETRAITE_COMPLEMENTAIRE_T2, # Agirc-Arrco T2 complement
    # CEG / CET
    "067": ContributionType.CEG_T1,                     # CEG T1
    "068": ContributionType.CEG_T1,                     # CEG T1 complement
    "069": ContributionType.CEG_T2,                     # CEG T2
    "070": ContributionType.CEG_T2,                     # CEG T2 complement
    "071": ContributionType.CET,                        # CET
    "072": ContributionType.CET,                        # CET complement
    # APEC
    "073": ContributionType.APEC,                       # APEC cadres
    "074": ContributionType.APEC,                       # APEC complement
    # Prevoyance / Mutuelle
    "090": ContributionType.PREVOYANCE_CADRE,           # Prevoyance cadres (art. 7)
    "091": ContributionType.PREVOYANCE_CADRE,           # Prevoyance cadres complement
    "092": ContributionType.PREVOYANCE_NON_CADRE,       # Prevoyance non-cadres
    "093": ContributionType.PREVOYANCE_NON_CADRE,       # Prevoyance non-cadres complement
    "094": ContributionType.MUTUELLE_OBLIGATOIRE,       # Complementaire sante ANI
    "095": ContributionType.MUTUELLE_OBLIGATOIRE,       # Complementaire sante complement
    # Transport
    "900": ContributionType.VERSEMENT_MOBILITE,         # Versement mobilite
    "901": ContributionType.VERSEMENT_MOBILITE,         # Versement mobilite additionnel
    # Reduction / Exonerations
    "668": ContributionType.LOI_FILLON,                 # Reduction Fillon (ancienne)
    "671": ContributionType.LOI_FILLON,                 # Reduction generale
    "673": ContributionType.LOI_FILLON,                 # Red. generale complement
    # Contribution Dialogue Social
    "027": ContributionType.MALADIE,                    # Contrib. Dialogue Social
    # Penibilite / C2P (Compte Professionnel de Prevention)
    "085": ContributionType.MALADIE,                    # Penibilite mono-exposition
    "087": ContributionType.MALADIE,                    # Penibilite poly-exposition
    # GUSO (Guichet Unique du Spectacle Occasionnel)
    "810": ContributionType.MALADIE,                    # GUSO maladie
    "812": ContributionType.VIEILLESSE_PLAFONNEE,       # GUSO vieillesse
    "815": ContributionType.ASSURANCE_CHOMAGE,          # GUSO chomage
    # Artistes / Intermittents
    "750": ContributionType.ASSURANCE_CHOMAGE,          # Chomage intermittents
    "752": ContributionType.MALADIE,                    # Conges spectacles
}

# Motifs d'arret de travail (S44.G00.44.002)
MOTIFS_ARRET = {
    "01": "maladie",
    "02": "maternite",
    "03": "paternite",
    "04": "accident_travail",
    "05": "maladie_professionnelle",
    "06": "temps_partiel_therapeutique",
    "07": "conge_proche_aidant",
}

# Nature du contrat (S21.G00.40.007)
NATURES_CONTRAT = {
    "01": "CDI",
    "02": "CDD",
    "03": "Contrat de mission (interim)",
    "04": "Contrat d'apprentissage",
    "05": "Contrat initiative emploi (CUI-CIE)",
    "07": "Contrat accompagnement dans l'emploi (CUI-CAE)",
    "08": "Contrat d'acces a l'emploi DOM",
    "09": "Contrat a duree indeterminee intermittent",
    "10": "Contrat de professionnalisation",
    "29": "Convention de stage",
    "32": "Contrat avenir",
    "50": "CDI intérimaire",
    "60": "Contrat de mission engagement volontaire",
    "70": "CDI de chantier",
    "80": "Mandat social",
    "81": "Mandat d'elu",
    "82": "Contrat de soutien et d'aide par le travail (ESAT)",
    "89": "VRP multicartes",
    "91": "CDD senior",
    "92": "CDD a objet defini",
    "93": "CDI de projet",
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
        self._verifier_taille_fichier(chemin)
        contenu = self._lire_fichier(chemin)

        if contenu.strip().startswith("<?xml") or contenu.strip().startswith("<"):
            return self._parser_dsn_xml(contenu, document.id)
        else:
            return self._parser_dsn_texte(contenu, document.id)

    def _lire_fichier(self, chemin: Path) -> str:
        """Lit le fichier DSN avec detection d'encodage."""
        for encoding in ("utf-8", "utf-8-sig", "cp1252", "iso-8859-1", "iso-8859-15", "latin-1"):
            try:
                with open(chemin, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise ParseError(f"Impossible de decoder le fichier DSN {chemin}")

    def _parser_dsn_texte(self, contenu: str, doc_id: str) -> list[Declaration]:
        """Parse un fichier DSN au format texte structure."""
        parse_log = ParseLog("DSNParser", doc_id)
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

        if not donnees:
            raise ParseError("Aucun bloc DSN detecte dans le fichier")

        # Valider les donnees critiques
        self._valider_donnees_dsn(donnees, parse_log)

        # Extraire les informations de la declaration
        employeur = self._extraire_employeur_texte(donnees, doc_id, parse_log)
        employes = self._extraire_employes_texte(donnees, doc_id, parse_log)
        cotisations = self._extraire_cotisations_texte(donnees, doc_id)
        periode = self._extraire_periode_texte(donnees)

        # Extraire les arrets de travail (S44)
        arrets = self._extraire_arrets_travail(donnees)

        # Extraire les contrats (S40)
        contrats = self._extraire_contrats(donnees)

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

        # Extraire CCN/IDCC et code NAF depuis les blocs DSN
        idcc_vals = donnees.get("S21.G00.40.017", [])
        idcc_detecte = idcc_vals[0] if idcc_vals else ""
        naf_val = self._get_val(donnees, "S21.G00.06.005")
        if not naf_val:
            naf_val = self._get_val(donnees, "S20.G00.05.003")

        if employeur and naf_val:
            employeur.code_naf = naf_val

        # Ajouter metadata
        declaration.metadata = getattr(declaration, "metadata", {}) or {}
        declaration.metadata["type_document"] = "declaration_dsn"
        if idcc_detecte:
            declaration.metadata["idcc"] = idcc_detecte
        if naf_val:
            declaration.metadata["code_naf"] = naf_val
        if arrets:
            declaration.metadata["arrets_travail"] = arrets
        if contrats:
            declaration.metadata["contrats"] = contrats

        # S89 - Total versement OPS (totaux declares)
        s89_totaux = self._extraire_totaux_s89(donnees)
        if s89_totaux:
            declaration.reference = declaration.reference or ""
            declaration.metadata["s89_total_cotisations"] = float(s89_totaux.get("total_cotisations", 0))
            declaration.metadata["s89_total_brut"] = float(s89_totaux.get("total_brut", 0))

            # Reconciliation S89 vs S81
            if cotisations:
                total_s81 = sum(float(c.montant_patronal) for c in cotisations)
                ecart = abs(total_s81 - s89_totaux["total_cotisations"])
                declaration.metadata["s89_reconciliation"] = {
                    "total_s81": round(total_s81, 2),
                    "total_s89": s89_totaux["total_cotisations"],
                    "ecart": round(ecart, 2),
                    "reconcilie": ecart < 1.0,  # Tolerance 1 EUR
                }
                if ecart >= 1.0:
                    parse_log.warning(0, "s89", f"Ecart S89/S81: {ecart:.2f} EUR")

        # Compter les blocs presents
        blocs_presents = set()
        for cle in donnees:
            blocs_presents.add(cle[:3])
        declaration.metadata["blocs_presents"] = sorted(blocs_presents)

        if parse_log.has_errors or parse_log.warnings:
            declaration.metadata["parse_log"] = parse_log.to_dict()

        return [declaration]

    def _valider_donnees_dsn(self, donnees: dict, parse_log: ParseLog) -> None:
        """Valide les donnees critiques de la DSN."""
        # Valider SIREN
        siren = self._get_val(donnees, "S20.G00.05.001")
        if siren:
            if not valider_siren(siren):
                parse_log.warning(0, "siren", f"SIREN invalide (Luhn): {siren}")

        # Valider SIRET
        siret = self._get_val(donnees, "S21.G00.06.001")
        if siret:
            if not valider_siret(siret):
                parse_log.warning(0, "siret", f"SIRET invalide (Luhn): {siret}")

        # Valider les NIR des employes
        for prefix in ("S21.G00.30", "S30.G00.30"):
            nirs = donnees.get(f"{prefix}.001", [])
            for i, nir in enumerate(nirs):
                if nir:
                    v = valider_nir(nir)
                    if not v.valide:
                        parse_log.warning(0, "nir", f"Employe {i+1}: {v.message}", nir)

    def _extraire_employeur_texte(self, donnees: dict, doc_id: str,
                                   parse_log: ParseLog | None = None) -> Employeur | None:
        """Extrait l'employeur depuis les blocs S10/S20/S21."""
        emp = Employeur(source_document_id=doc_id)

        siren = self._get_val(donnees, "S10.G00.01.001")
        if siren and len(siren) == 9:
            emp.siren = siren

        if not emp.siren:
            siren_s20 = self._get_val(donnees, "S20.G00.05.001")
            if siren_s20 and len(siren_s20) == 9:
                emp.siren = siren_s20

        siret = self._get_val(donnees, "S21.G00.06.001")
        if siret and len(siret) >= 14:
            emp.siret = siret
            if not emp.siren:
                emp.siren = siret[:9]

        raison = self._get_val(donnees, "S21.G00.06.002")
        if not raison:
            raison = self._get_val(donnees, "S20.G00.05.002")
        if raison:
            emp.raison_sociale = raison

        effectif = self._get_val(donnees, "S21.G00.11.001")
        if effectif:
            try:
                emp.effectif = int(effectif)
            except ValueError:
                if parse_log:
                    parse_log.warning(0, "effectif", f"Effectif non numerique: {effectif}")

        return emp if emp.siren or emp.siret else None

    def _extraire_employes_texte(self, donnees: dict, doc_id: str,
                                  parse_log: ParseLog | None = None) -> list[Employe]:
        """Extrait les employes depuis les blocs S21.G00.30 ou S30.G00.30."""
        employes = []
        nirs_vus = set()

        for prefix in ("S21.G00.30", "S30.G00.30"):
            nirs = donnees.get(f"{prefix}.001", [])
            noms = donnees.get(f"{prefix}.002", [])
            prenoms = donnees.get(f"{prefix}.004", [])
            dates_naissance = donnees.get(f"{prefix}.006", [])

            for i, nir in enumerate(nirs):
                if nir and nir not in nirs_vus:
                    nirs_vus.add(nir)

                    # Valider et normaliser le NIR
                    v = valider_nir(nir)
                    nir_normalise = v.valeur_corrigee if v.valide else nir

                    emp = Employe(
                        nir=nir_normalise,
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

        for prefix in ("S21.G00.81", "S81.G00.81"):
            codes = donnees.get(f"{prefix}.001", [])
            bases = donnees.get(f"{prefix}.003", [])
            taux_list = donnees.get(f"{prefix}.004", [])
            montants = donnees.get(f"{prefix}.005", [])

            max_len = max(len(codes), len(bases), len(taux_list), len(montants), 0)
            for i in range(max_len):
                c = Cotisation(source_document_id=doc_id)

                code_ctp = ""
                if i < len(codes) and codes[i]:
                    code_ctp = codes[i]
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
                    # Stocker le code CTP dans les metadata pour traçabilité
                    if code_ctp and not hasattr(c, 'metadata'):
                        c.metadata = {}
                    if code_ctp:
                        c.metadata = getattr(c, 'metadata', {}) or {}
                        c.metadata["code_ctp"] = code_ctp
                    cotisations.append(c)

            if cotisations:
                break

        # Fallback S78 (bases assujetties)
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

        # Fallback S51 (remuneration)
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

    def _extraire_arrets_travail(self, donnees: dict) -> list[dict]:
        """Extrait les arrets de travail depuis les blocs S44."""
        arrets = []
        for prefix in ("S21.G00.44", "S44.G00.44"):
            dates_debut = donnees.get(f"{prefix}.001", [])
            motifs = donnees.get(f"{prefix}.002", [])
            dates_fin = donnees.get(f"{prefix}.003", [])
            dates_reprise = donnees.get(f"{prefix}.009", [])

            for i in range(len(dates_debut)):
                arret = {
                    "date_debut": dates_debut[i] if i < len(dates_debut) else "",
                    "motif_code": motifs[i] if i < len(motifs) else "",
                    "motif_libelle": MOTIFS_ARRET.get(
                        motifs[i] if i < len(motifs) else "", "inconnu"
                    ),
                }
                if i < len(dates_fin) and dates_fin[i]:
                    arret["date_fin"] = dates_fin[i]
                if i < len(dates_reprise) and dates_reprise[i]:
                    arret["date_reprise"] = dates_reprise[i]
                arrets.append(arret)
            if arrets:
                break
        return arrets

    def _extraire_contrats(self, donnees: dict) -> list[dict]:
        """Extrait les informations de contrats depuis les blocs S40."""
        contrats = []
        for prefix in ("S21.G00.40",):
            dates_debut = donnees.get(f"{prefix}.001", [])
            natures = donnees.get(f"{prefix}.007", [])
            statuts = donnees.get(f"{prefix}.026", [])
            quotites = donnees.get(f"{prefix}.013", [])

            for i in range(len(dates_debut)):
                nature_code = natures[i] if i < len(natures) else ""
                contrat = {
                    "date_debut": dates_debut[i] if i < len(dates_debut) else "",
                    "nature_code": nature_code,
                    "nature_libelle": NATURES_CONTRAT.get(nature_code, "inconnu"),
                }
                if i < len(statuts) and statuts[i]:
                    contrat["statut"] = statuts[i]
                if i < len(quotites) and quotites[i]:
                    contrat["quotite_travail"] = quotites[i]
                contrats.append(contrat)
        return contrats

    def _extraire_totaux_s89(self, donnees: dict) -> dict | None:
        """Extrait les totaux declares dans le bloc S89 (Total versement OPS)."""
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

        from urssaf_analyzer.parsers.xml_parser import XMLParser
        xml_parser = XMLParser()

        doc = Document(id=doc_id)
        declarations = xml_parser._parser_dsn_structure(root, doc_id)
        for d in declarations:
            d.type_declaration = "DSN/XML"
        return declarations

    @staticmethod
    def _get_val(donnees: dict, cle: str) -> str | None:
        """Retourne la premiere valeur pour une cle DSN."""
        vals = donnees.get(cle, [])
        return vals[0] if vals else None
