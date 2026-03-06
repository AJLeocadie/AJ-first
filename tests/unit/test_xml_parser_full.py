"""Comprehensive tests for XMLParser to improve coverage beyond 59%."""

import os
import tempfile
from decimal import Decimal
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement

import pytest

from urssaf_analyzer.config.constants import ContributionType
from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import Document
from urssaf_analyzer.parsers.xml_parser import XMLParser


@pytest.fixture
def parser():
    return XMLParser()


@pytest.fixture
def doc():
    return Document(id="test-doc-123")


def _write_xml(content: str) -> Path:
    """Write XML content to a temporary file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return Path(f.name)


# =====================================================================
# 1. peut_traiter
# =====================================================================

class TestPeutTraiter:

    def test_xml_extension(self, parser):
        assert parser.peut_traiter(Path("fichier.xml")) is True

    def test_xml_uppercase(self, parser):
        assert parser.peut_traiter(Path("fichier.XML")) is True

    def test_xml_mixed_case(self, parser):
        assert parser.peut_traiter(Path("fichier.Xml")) is True

    def test_pdf_extension(self, parser):
        assert parser.peut_traiter(Path("fichier.pdf")) is False

    def test_csv_extension(self, parser):
        assert parser.peut_traiter(Path("fichier.csv")) is False

    def test_no_extension(self, parser):
        assert parser.peut_traiter(Path("fichier")) is False

    def test_xml_in_directory_name(self, parser):
        assert parser.peut_traiter(Path("/some/xml_dir/file.txt")) is False

    def test_double_extension(self, parser):
        assert parser.peut_traiter(Path("fichier.old.xml")) is True

    def test_xlsx_extension(self, parser):
        assert parser.peut_traiter(Path("fichier.xlsx")) is False


# =====================================================================
# 2. extraire_metadata
# =====================================================================

class TestExtraireMetadata:

    def test_valid_xml(self, parser):
        path = _write_xml('<?xml version="1.0"?><root attr1="val1"><child/><child/></root>')
        try:
            meta = parser.extraire_metadata(path)
            assert meta["format"] == "xml"
            assert meta["racine"] == "root"
            assert meta["nb_elements"] == 3  # root + 2 children
            assert meta["attributs_racine"] == {"attr1": "val1"}
        finally:
            os.unlink(path)

    def test_invalid_xml(self, parser):
        path = _write_xml("this is not xml at all <><>")
        try:
            meta = parser.extraire_metadata(path)
            assert meta["format"] == "xml"
            assert "erreur" in meta
        finally:
            os.unlink(path)

    def test_empty_root(self, parser):
        path = _write_xml('<?xml version="1.0"?><racine/>')
        try:
            meta = parser.extraire_metadata(path)
            assert meta["racine"] == "racine"
            assert meta["nb_elements"] == 1
            assert meta["attributs_racine"] == {}
        finally:
            os.unlink(path)


# =====================================================================
# 3. parser - DSN-like XML
# =====================================================================

class TestParserDSN:

    def test_dsn_with_cotisations_and_employes(self, parser, doc):
        xml = """<?xml version="1.0"?>
        <dsn_envoi>
            <declaration_sociale>
                <cotisation>
                    <base_brute>3000.00</base_brute>
                    <taux_patronal>13.00</taux_patronal>
                    <montant_patronal>390.00</montant_patronal>
                    <type_cotisation>maladie</type_cotisation>
                </cotisation>
                <salarie>
                    <nir>1 85 01 75 123 456 78</nir>
                    <nom_famille>Dupont</nom_famille>
                    <prenom>Jean</prenom>
                </salarie>
                <info_employeur>
                    <siret>12345678901234</siret>
                    <raison_sociale>ACME Corp</raison_sociale>
                    <effectif>50</effectif>
                </info_employeur>
            </declaration_sociale>
        </dsn_envoi>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) >= 1
            # Find the declaration with cotisations
            d = [x for x in declarations if x.cotisations][0]
            assert d.type_declaration == "XML/DSN"
            assert len(d.cotisations) >= 1
            assert len(d.employes) >= 1
            assert d.effectif_declare >= 1
            # masse_salariale_brute set from cotisations
            assert d.masse_salariale_brute > 0
        finally:
            os.unlink(path)

    def test_dsn_root_tag(self, parser, doc):
        """DSN detection via root tag containing 'dsn'."""
        xml = """<?xml version="1.0"?><DSN><declaration>
            <cotisation><base>1000</base><montant>100</montant></cotisation>
        </declaration></DSN>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) >= 1
            assert declarations[0].type_declaration == "XML/DSN"
        finally:
            os.unlink(path)

    def test_dsn_no_cotisations_no_employes(self, parser, doc):
        """DSN with declaration but no cotisations or employes yields no declarations."""
        xml = """<?xml version="1.0"?><dsn><declaration><info>test</info></declaration></dsn>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert declarations == []
        finally:
            os.unlink(path)

    def test_dsn_with_contribution_tag(self, parser, doc):
        """Tag containing 'contribution' is treated as cotisation."""
        xml = """<?xml version="1.0"?><dsn><declaration>
            <contribution><assiette>2000</assiette><montant>200</montant></contribution>
        </declaration></dsn>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) == 1
            assert len(declarations[0].cotisations) >= 1
        finally:
            os.unlink(path)

    def test_dsn_with_individu_tag(self, parser, doc):
        """Tag containing 'individu' is treated as employe."""
        xml = """<?xml version="1.0"?><dsn><declaration>
            <individu><nom>Martin</nom></individu>
            <cotisation><base>100</base></cotisation>
        </declaration></dsn>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) >= 1
            assert any(e.nom == "Martin" for d in declarations for e in d.employes)
        finally:
            os.unlink(path)

    def test_dsn_with_entreprise_tag(self, parser, doc):
        """Tag containing 'entreprise' is treated as employeur."""
        xml = """<?xml version="1.0"?><dsn><declaration>
            <entreprise><siret>98765432109876</siret></entreprise>
            <cotisation><base>500</base></cotisation>
        </declaration></dsn>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) >= 1
            # At least one declaration should have the employeur
            found = any(d.employeur and d.employeur.siret == "98765432109876" for d in declarations)
            assert found
        finally:
            os.unlink(path)


# =====================================================================
# 4. parser - Bordereau XML
# =====================================================================

class TestParserBordereau:

    def test_bordereau_with_lignes(self, parser, doc):
        xml = """<?xml version="1.0"?><bordereau>
            <ligne><base>5000</base><montant>650</montant></ligne>
            <ligne><base>3000</base><montant>390</montant></ligne>
        </bordereau>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) == 1
            assert declarations[0].type_declaration == "XML/Bordereau"
            assert len(declarations[0].cotisations) == 2
            assert declarations[0].masse_salariale_brute == Decimal("5000") + Decimal("3000")
        finally:
            os.unlink(path)

    def test_ducs_root_tag(self, parser, doc):
        """Root tag containing 'ducs' triggers bordereau parsing."""
        xml = """<?xml version="1.0"?><ducs_envoi>
            <cotisation><base>1000</base><montant>130</montant></cotisation>
        </ducs_envoi>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) == 1
            assert declarations[0].type_declaration == "XML/Bordereau"
        finally:
            os.unlink(path)

    def test_bordereau_empty_no_cotisations(self, parser, doc):
        xml = """<?xml version="1.0"?><bordereau><info>nothing</info></bordereau>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert declarations == []
        finally:
            os.unlink(path)


# =====================================================================
# 5. parser - Generic XML
# =====================================================================

class TestParserGenerique:

    def test_generic_xml_with_cotisations(self, parser, doc):
        xml = """<?xml version="1.0"?><data>
            <item><base>2000</base><montant>260</montant></item>
        </data>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) == 1
            assert declarations[0].type_declaration == "XML"
        finally:
            os.unlink(path)

    def test_generic_xml_no_cotisations(self, parser, doc):
        xml = """<?xml version="1.0"?><data><item><name>test</name></item></data>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert declarations == []
        finally:
            os.unlink(path)

    def test_generic_xml_zero_base_and_montant_skipped(self, parser, doc):
        """Generic parser skips cotisations where base_brute=0 and montant_patronal=0."""
        xml = """<?xml version="1.0"?><data>
            <cotisation><taux>5</taux><code>maladie</code></cotisation>
        </data>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            # taux alone sets found=True but base_brute=0 and montant_patronal=0 -> skipped
            assert declarations == []
        finally:
            os.unlink(path)


# =====================================================================
# 6. parser - ParseError on invalid XML
# =====================================================================

class TestParserInvalidXML:

    def test_parse_error_raised(self, parser, doc):
        path = _write_xml("<<<not xml>>>")
        try:
            with pytest.raises(ParseError, match="XML invalide"):
                parser.parser(path, doc)
        finally:
            os.unlink(path)


# =====================================================================
# 7. _strip_namespaces
# =====================================================================

class TestStripNamespaces:

    def test_strip_tag_namespace(self, parser):
        root = Element("{http://example.com/ns}root")
        child = SubElement(root, "{http://example.com/ns}child")
        parser._strip_namespaces(root)
        assert root.tag == "root"
        assert child.tag == "child"

    def test_strip_attribute_namespace(self, parser):
        root = Element("root")
        root.set("{http://example.com/ns}attr", "value")
        parser._strip_namespaces(root)
        assert "attr" in root.attrib
        assert root.attrib["attr"] == "value"

    def test_no_namespace_unchanged(self, parser):
        root = Element("plain")
        SubElement(root, "child")
        parser._strip_namespaces(root)
        assert root.tag == "plain"

    def test_xml_with_namespaces_parsed(self, parser, doc):
        """End-to-end: namespaced XML is still parsed correctly."""
        xml = """<?xml version="1.0"?>
        <ns:bordereau xmlns:ns="http://urssaf.fr/schema">
            <ns:cotisation>
                <ns:base>4000</ns:base>
                <ns:montant>520</ns:montant>
            </ns:cotisation>
        </ns:bordereau>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) == 1
            assert declarations[0].type_declaration == "XML/Bordereau"
        finally:
            os.unlink(path)


# =====================================================================
# 8. _parser_element_cotisation
# =====================================================================

class TestParserElementCotisation:

    def test_with_children(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "base_brute").text = "3000.00"
        SubElement(elem, "taux_patronal").text = "13.00"
        SubElement(elem, "montant_patronal").text = "390.00"

        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.base_brute == Decimal("3000.00")
        assert c.assiette == Decimal("3000.00")
        assert c.taux_patronal == Decimal("0.13")
        assert c.montant_patronal == Decimal("390.00")

    def test_with_attributes(self, parser):
        elem = Element("cotisation", montant="500.00", base="2000.00")
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.montant_patronal == Decimal("500.00")
        assert c.base_brute == Decimal("2000.00")
        assert c.assiette == Decimal("2000.00")

    def test_attribute_assiette(self, parser):
        elem = Element("cotisation", assiette="1500.00")
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.base_brute == Decimal("1500.00")

    def test_taux_conversion_over_1(self, parser):
        """Taux > 1 are divided by 100 (e.g., 13.0 -> 0.13)."""
        elem = Element("cotisation")
        SubElement(elem, "taux").text = "13.00"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.taux_patronal == Decimal("0.13")

    def test_taux_already_decimal(self, parser):
        """Taux <= 1 kept as-is."""
        elem = Element("cotisation")
        SubElement(elem, "taux").text = "0.13"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.taux_patronal == Decimal("0.13")

    def test_taux_salarial(self, parser):
        """Tag containing both 'taux' and 'salar' goes to taux_salarial."""
        elem = Element("cotisation")
        SubElement(elem, "taux_salarial").text = "7.50"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.taux_salarial == Decimal("0.075")

    def test_montant_salarial(self, parser):
        """Tag containing both 'montant' and 'salar' goes to montant_salarial."""
        elem = Element("cotisation")
        SubElement(elem, "montant_salarial").text = "150.00"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.montant_salarial == Decimal("150.00")

    def test_type_cotisation_mapping(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "base").text = "1000"
        SubElement(elem, "type").text = "vieillesse"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.type_cotisation == ContributionType.VIEILLESSE_PLAFONNEE

    def test_code_tag_for_type(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "base").text = "1000"
        SubElement(elem, "code").text = "csg"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c.type_cotisation == ContributionType.CSG_DEDUCTIBLE

    def test_libelle_tag_for_type(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "base").text = "1000"
        SubElement(elem, "libelle_cotisation").text = "chomage"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c.type_cotisation == ContributionType.ASSURANCE_CHOMAGE

    def test_no_matching_children_returns_none(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "description").text = "something"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is None

    def test_empty_text_children_skipped(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "base").text = ""
        SubElement(elem, "montant").text = "   "
        SubElement(elem, "taux").text = None
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is None

    def test_assiette_tag(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "assiette").text = "4500"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.base_brute == Decimal("4500")
        assert c.assiette == Decimal("4500")

    def test_brut_tag(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "salaire_brut").text = "3500"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.base_brute == Decimal("3500")

    def test_total_tag(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "total").text = "200"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.montant_patronal == Decimal("200")

    def test_total_salarial_tag(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "total_salarial").text = "75"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.montant_salarial == Decimal("75")

    def test_source_document_id_set(self, parser):
        elem = Element("cotisation")
        SubElement(elem, "base").text = "1000"
        c = parser._parser_element_cotisation(elem, "my-doc-id")
        assert c.source_document_id == "my-doc-id"


# =====================================================================
# 9. _parser_element_employe
# =====================================================================

class TestParserElementEmploye:

    def test_full_employe_nir_and_nom(self, parser):
        """Test NIR parsing (spaces removed) and nom extraction."""
        elem = Element("salarie")
        SubElement(elem, "nir").text = "1 85 01 75 123 456 78"
        SubElement(elem, "nom").text = "Dupont"
        e = parser._parser_element_employe(elem, "doc1")
        assert e is not None
        # NIR spaces removed
        assert " " not in e.nir
        assert e.nir == "185017512345678"
        assert e.nom == "Dupont"

    def test_nss_tag(self, parser):
        elem = Element("individu")
        SubElement(elem, "nss").text = "2930299123456"
        e = parser._parser_element_employe(elem, "doc1")
        assert e is not None
        assert e.nir == "2930299123456"

    def test_empty_children(self, parser):
        elem = Element("salarie")
        SubElement(elem, "nir").text = ""
        SubElement(elem, "nom").text = "   "
        SubElement(elem, "prenom").text = None
        e = parser._parser_element_employe(elem, "doc1")
        assert e is None

    def test_prenom_tag_matches_nom_branch(self, parser):
        """The tag 'prenom' contains substring 'nom', so it hits the nom branch."""
        elem = Element("salarie")
        SubElement(elem, "prenom").text = "Jean"
        e = parser._parser_element_employe(elem, "doc1")
        assert e is not None
        # Because "nom" in "prenom" is True, the value goes to e.nom
        assert e.nom == "Jean"
        assert e.prenom == ""

    def test_nom_only(self, parser):
        elem = Element("employe")
        SubElement(elem, "nom").text = "Martin"
        e = parser._parser_element_employe(elem, "doc1")
        assert e is not None
        assert e.nom == "Martin"
        assert e.nir == ""
        assert e.prenom == ""

    def test_no_matching_children(self, parser):
        elem = Element("salarie")
        SubElement(elem, "adresse").text = "123 rue test"
        e = parser._parser_element_employe(elem, "doc1")
        assert e is None

    def test_source_document_id(self, parser):
        elem = Element("salarie")
        SubElement(elem, "nom").text = "Test"
        e = parser._parser_element_employe(elem, "my-doc")
        assert e.source_document_id == "my-doc"


# =====================================================================
# 10. _parser_element_employeur
# =====================================================================

class TestParserElementEmployeur:

    def test_full_employeur(self, parser):
        elem = Element("employeur")
        SubElement(elem, "siret").text = "12345678901234"
        SubElement(elem, "siren").text = "123456789"
        SubElement(elem, "raison_sociale").text = "ACME Corp"
        SubElement(elem, "effectif").text = "42"
        emp = parser._parser_element_employeur(elem, "doc1")
        assert emp is not None
        assert emp.siret == "12345678901234"
        assert emp.siren == "123456789"
        assert emp.raison_sociale == "ACME Corp"
        assert emp.effectif == 42

    def test_nom_tag_as_raison_sociale(self, parser):
        elem = Element("entreprise")
        SubElement(elem, "nom_entreprise").text = "SocieteX"
        emp = parser._parser_element_employeur(elem, "doc1")
        assert emp is not None
        assert emp.raison_sociale == "SocieteX"

    def test_invalid_effectif(self, parser):
        elem = Element("employeur")
        SubElement(elem, "siret").text = "11111111111111"
        SubElement(elem, "effectif").text = "not_a_number"
        emp = parser._parser_element_employeur(elem, "doc1")
        assert emp is not None
        assert emp.effectif == 0  # default, ValueError caught

    def test_returns_none_when_no_siret_no_raison(self, parser):
        elem = Element("employeur")
        SubElement(elem, "siren").text = "123456789"
        SubElement(elem, "effectif").text = "10"
        emp = parser._parser_element_employeur(elem, "doc1")
        assert emp is None

    def test_empty_text_skipped(self, parser):
        elem = Element("employeur")
        SubElement(elem, "siret").text = ""
        SubElement(elem, "raison_sociale").text = "   "
        SubElement(elem, "nom").text = None
        emp = parser._parser_element_employeur(elem, "doc1")
        assert emp is None

    def test_siret_alone_sufficient(self, parser):
        elem = Element("employeur")
        SubElement(elem, "siret").text = "99999999999999"
        emp = parser._parser_element_employeur(elem, "doc1")
        assert emp is not None
        assert emp.siret == "99999999999999"

    def test_raison_sociale_alone_sufficient(self, parser):
        elem = Element("employeur")
        SubElement(elem, "raison_sociale").text = "Ma Boite"
        emp = parser._parser_element_employeur(elem, "doc1")
        assert emp is not None
        assert emp.raison_sociale == "Ma Boite"

    def test_source_document_id(self, parser):
        elem = Element("employeur")
        SubElement(elem, "siret").text = "11111111111111"
        emp = parser._parser_element_employeur(elem, "my-doc")
        assert emp.source_document_id == "my-doc"


# =====================================================================
# 11. _mapper_type
# =====================================================================

class TestMapperType:

    def test_maladie(self):
        assert XMLParser._mapper_type("assurance maladie") == ContributionType.MALADIE

    def test_vieillesse(self):
        assert XMLParser._mapper_type("vieillesse plafonnee") == ContributionType.VIEILLESSE_PLAFONNEE

    def test_familial(self):
        assert XMLParser._mapper_type("allocations familiales") == ContributionType.ALLOCATIONS_FAMILIALES

    def test_at(self):
        assert XMLParser._mapper_type("AT/MP") == ContributionType.ACCIDENT_TRAVAIL

    def test_csg(self):
        assert XMLParser._mapper_type("CSG deductible") == ContributionType.CSG_DEDUCTIBLE

    def test_crds(self):
        assert XMLParser._mapper_type("CRDS") == ContributionType.CRDS

    def test_chomage(self):
        assert XMLParser._mapper_type("assurance chomage") == ContributionType.ASSURANCE_CHOMAGE

    def test_unknown_defaults_to_maladie(self):
        assert XMLParser._mapper_type("something_unknown_xyz") == ContributionType.MALADIE

    def test_case_insensitive(self):
        assert XMLParser._mapper_type("MALADIE") == ContributionType.MALADIE
        assert XMLParser._mapper_type("Vieillesse") == ContributionType.VIEILLESSE_PLAFONNEE

    def test_at_in_string(self):
        """'at' is short - verify it matches within words like 'ratp' or 'format'."""
        # The pattern 'at' appears in 'format' so it matches
        assert XMLParser._mapper_type("format") == ContributionType.ACCIDENT_TRAVAIL

    def test_empty_string(self):
        assert XMLParser._mapper_type("") == ContributionType.MALADIE


# =====================================================================
# 12. Edge cases
# =====================================================================

class TestEdgeCases:

    def test_deeply_nested_dsn(self, parser, doc):
        xml = """<?xml version="1.0"?><dsn><niveau1><declaration>
            <niveau2><cotisation><base>100</base><montant>10</montant></cotisation></niveau2>
            <niveau2><employe><nom>Test</nom></employe></niveau2>
        </declaration></niveau1></dsn>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) >= 1
        finally:
            os.unlink(path)

    def test_multiple_declarations_in_dsn(self, parser, doc):
        xml = """<?xml version="1.0"?><dsn>
            <declaration><cotisation><base>100</base><montant>10</montant></cotisation></declaration>
            <declaration><cotisation><base>200</base><montant>20</montant></cotisation></declaration>
        </dsn>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) >= 2
        finally:
            os.unlink(path)

    def test_bordereau_with_mixed_tags(self, parser, doc):
        """Bordereau parser picks up both 'ligne' and 'cotisation' tags."""
        xml = """<?xml version="1.0"?><bordereau>
            <ligne><base>1000</base><montant>100</montant></ligne>
            <cotisation><base>2000</base><montant>200</montant></cotisation>
        </bordereau>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) == 1
            assert len(declarations[0].cotisations) >= 2
        finally:
            os.unlink(path)

    def test_cotisation_with_only_attributes(self, parser, doc):
        """Cotisation element with only attributes, no children."""
        xml = """<?xml version="1.0"?><bordereau>
            <cotisation montant="300" base="2000"/>
        </bordereau>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) == 1
            c = declarations[0].cotisations[0]
            assert c.montant_patronal == Decimal("300")
            assert c.base_brute == Decimal("2000")
        finally:
            os.unlink(path)

    def test_dsn_masse_salariale_sum(self, parser, doc):
        """masse_salariale_brute is sum of base_brute across cotisations."""
        xml = """<?xml version="1.0"?><dsn><declaration>
            <cotisation><base>1000</base><montant>100</montant></cotisation>
            <cotisation><base>2000</base><montant>200</montant></cotisation>
        </declaration></dsn>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) >= 1
            # Find the declaration with cotisations
            for d in declarations:
                if d.cotisations:
                    assert d.masse_salariale_brute == sum(c.base_brute for c in d.cotisations)
        finally:
            os.unlink(path)

    def test_dsn_employes_only(self, parser, doc):
        """DSN with employes but no cotisations still creates a declaration."""
        xml = """<?xml version="1.0"?><dsn><declaration>
            <salarie><nom>Solo</nom></salarie>
        </declaration></dsn>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) >= 1
            found = any(d.employes for d in declarations)
            assert found
        finally:
            os.unlink(path)

    def test_strip_namespaces_multiple_levels(self, parser, doc):
        """Namespaces stripped at multiple nesting levels."""
        xml = """<?xml version="1.0"?>
        <ns:bordereau xmlns:ns="http://test.com" xmlns:sub="http://sub.com">
            <ns:ligne>
                <sub:base>1500</sub:base>
                <sub:montant>195</sub:montant>
            </ns:ligne>
        </ns:bordereau>"""
        path = _write_xml(xml)
        try:
            declarations = parser.parser(path, doc)
            assert len(declarations) == 1
        finally:
            os.unlink(path)

    def test_cotisation_taux_exactly_one(self, parser):
        """Taux of exactly 1.0 is kept as-is (not divided by 100)."""
        elem = Element("cotisation")
        SubElement(elem, "taux").text = "1.0"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.taux_patronal == Decimal("1.0")

    def test_cotisation_taux_just_over_one(self, parser):
        """Taux of 1.01 is divided by 100."""
        elem = Element("cotisation")
        SubElement(elem, "taux").text = "1.01"
        c = parser._parser_element_cotisation(elem, "doc1")
        assert c is not None
        assert c.taux_patronal == Decimal("0.0101")
