"""Parseur pour les fichiers XML (declarations, bordereaux URSSAF)."""

from decimal import Decimal
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


class XMLParser(BaseParser):
    """Parse les fichiers XML generiques."""

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() == ".xml"

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        try:
            tree = ET.parse(chemin)
            root = tree.getroot()
            return {
                "format": "xml",
                "racine": root.tag,
                "nb_elements": len(list(root.iter())),
                "attributs_racine": root.attrib,
            }
        except ET.ParseError as e:
            return {"format": "xml", "erreur": str(e)}

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        try:
            tree = ET.parse(chemin)
        except ET.ParseError as e:
            raise ParseError(f"XML invalide dans {chemin}: {e}") from e

        root = tree.getroot()
        # Nettoyer les namespaces
        self._strip_namespaces(root)

        declarations = []

        # Tenter de detecter le type de document XML
        if self._est_dsn_like(root):
            declarations.extend(self._parser_dsn_structure(root, document.id))
        elif self._est_bordereau(root):
            declarations.extend(self._parser_bordereau(root, document.id))
        else:
            # Parsing generique
            declarations.extend(self._parser_generique(root, document.id))

        return declarations

    def _strip_namespaces(self, root: ET.Element) -> None:
        """Supprime les namespaces XML pour simplifier le parsing."""
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]
            for key in list(elem.attrib.keys()):
                if "}" in key:
                    new_key = key.split("}", 1)[1]
                    elem.attrib[new_key] = elem.attrib.pop(key)

    def _est_dsn_like(self, root: ET.Element) -> bool:
        tag = root.tag.lower()
        return "dsn" in tag or "declaration_sociale" in tag

    def _est_bordereau(self, root: ET.Element) -> bool:
        tag = root.tag.lower()
        return "bordereau" in tag or "ducs" in tag

    def _parser_dsn_structure(self, root: ET.Element, doc_id: str) -> list[Declaration]:
        """Parse une structure DSN-like en XML."""
        declarations = []
        # Chercher les blocs de declaration
        for decl_elem in root.iter():
            if "declaration" in decl_elem.tag.lower():
                cotisations = []
                employes = []
                employeur = None

                for child in decl_elem.iter():
                    tag = child.tag.lower()
                    if "cotisation" in tag or "contribution" in tag:
                        c = self._parser_element_cotisation(child, doc_id)
                        if c:
                            cotisations.append(c)
                    elif "salarie" in tag or "employe" in tag or "individu" in tag:
                        e = self._parser_element_employe(child, doc_id)
                        if e:
                            employes.append(e)
                    elif "employeur" in tag or "entreprise" in tag:
                        employeur = self._parser_element_employeur(child, doc_id)

                if cotisations or employes:
                    d = Declaration(
                        type_declaration="XML/DSN",
                        cotisations=cotisations,
                        employes=employes,
                        employeur=employeur,
                        effectif_declare=len(employes),
                        source_document_id=doc_id,
                    )
                    if cotisations:
                        d.masse_salariale_brute = sum(c.base_brute for c in cotisations)
                    declarations.append(d)
        return declarations

    def _parser_bordereau(self, root: ET.Element, doc_id: str) -> list[Declaration]:
        """Parse un bordereau de cotisations."""
        cotisations = []
        for elem in root.iter():
            tag = elem.tag.lower()
            if "ligne" in tag or "cotisation" in tag:
                c = self._parser_element_cotisation(elem, doc_id)
                if c:
                    cotisations.append(c)

        if cotisations:
            return [Declaration(
                type_declaration="XML/Bordereau",
                cotisations=cotisations,
                source_document_id=doc_id,
                masse_salariale_brute=sum(c.base_brute for c in cotisations),
            )]
        return []

    def _parser_generique(self, root: ET.Element, doc_id: str) -> list[Declaration]:
        """Parsing generique : cherche des patterns de cotisations dans tout le XML."""
        cotisations = []
        for elem in root.iter():
            c = self._parser_element_cotisation(elem, doc_id)
            if c and (c.base_brute > 0 or c.montant_patronal > 0):
                cotisations.append(c)

        if cotisations:
            return [Declaration(
                type_declaration="XML",
                cotisations=cotisations,
                source_document_id=doc_id,
            )]
        return []

    def _parser_element_cotisation(self, elem: ET.Element, doc_id: str) -> Cotisation | None:
        """Extrait une cotisation depuis un element XML."""
        c = Cotisation(source_document_id=doc_id)
        found = False

        for child in elem:
            tag = child.tag.lower()
            text = (child.text or "").strip()
            if not text:
                continue

            if any(k in tag for k in ["base", "assiette", "brut"]):
                c.base_brute = parser_montant(text)
                c.assiette = c.base_brute
                found = True
            elif any(k in tag for k in ["taux"]):
                val = parser_montant(text)
                if val > 1:
                    val = val / 100
                if "salar" in tag:
                    c.taux_salarial = val
                else:
                    c.taux_patronal = val
                found = True
            elif any(k in tag for k in ["montant", "total"]):
                val = parser_montant(text)
                if "salar" in tag:
                    c.montant_salarial = val
                else:
                    c.montant_patronal = val
                found = True
            elif any(k in tag for k in ["type", "code", "libell"]):
                c.type_cotisation = self._mapper_type(text)

        # Verifier aussi les attributs
        for attr, val in elem.attrib.items():
            attr_l = attr.lower()
            if "montant" in attr_l:
                c.montant_patronal = parser_montant(val)
                found = True
            elif "base" in attr_l or "assiette" in attr_l:
                c.base_brute = parser_montant(val)
                c.assiette = c.base_brute
                found = True

        return c if found else None

    def _parser_element_employe(self, elem: ET.Element, doc_id: str) -> Employe | None:
        e = Employe(source_document_id=doc_id)
        found = False
        for child in elem:
            tag = child.tag.lower()
            text = (child.text or "").strip()
            if not text:
                continue
            if "nir" in tag or "nss" in tag:
                e.nir = text.replace(" ", "")
                found = True
            elif "nom" in tag:
                e.nom = text
                found = True
            elif "prenom" in tag:
                e.prenom = text
                found = True
        return e if found else None

    def _parser_element_employeur(self, elem: ET.Element, doc_id: str) -> Employeur | None:
        emp = Employeur(source_document_id=doc_id)
        for child in elem:
            tag = child.tag.lower()
            text = (child.text or "").strip()
            if not text:
                continue
            if "siret" in tag:
                emp.siret = text
            elif "siren" in tag:
                emp.siren = text
            elif "raison" in tag or "nom" in tag:
                emp.raison_sociale = text
            elif "effectif" in tag:
                try:
                    emp.effectif = int(text)
                except ValueError:
                    pass
        return emp if emp.siret or emp.raison_sociale else None

    @staticmethod
    def _mapper_type(valeur: str) -> ContributionType:
        v = valeur.lower()
        for pattern, ct in {
            "maladie": ContributionType.MALADIE,
            "vieillesse": ContributionType.VIEILLESSE_PLAFONNEE,
            "familial": ContributionType.ALLOCATIONS_FAMILIALES,
            "at": ContributionType.ACCIDENT_TRAVAIL,
            "csg": ContributionType.CSG_DEDUCTIBLE,
            "crds": ContributionType.CRDS,
            "chomage": ContributionType.ASSURANCE_CHOMAGE,
        }.items():
            if pattern in v:
                return ct
        return ContributionType.MALADIE
