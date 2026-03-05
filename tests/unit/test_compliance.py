"""Tests du module compliance (verificateur de documents)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.compliance.document_checker import (
    DocumentChecker, TypeOperation, NiveauObligation,
    StatutDocument, DOCUMENTS_PAR_OPERATION,
)


class TestDocumentChecker:
    """Tests du verificateur de documents."""

    def setup_method(self):
        self.checker = DocumentChecker()

    # --- Verification operation ---

    def test_verification_sans_documents(self):
        """Sans documents fournis, rien n'est complet."""
        result = self.checker.verifier_operation(TypeOperation.COMPTABILISATION_FACTURE)
        assert result.est_complet is False
        assert result.taux_completude == 0
        assert len(result.alertes) > 0

    def test_verification_complete_facture(self):
        """Tous les documents obligatoires fournis."""
        docs = [
            "Facture originale FA-001",
            "Bon de livraison signé",
            "Bon de commande BC-001",
            "Releve bancaire mars",
            "Contrat ou devis accepte",
        ]
        result = self.checker.verifier_operation(
            TypeOperation.COMPTABILISATION_FACTURE,
            documents_fournis=docs,
        )
        assert result.est_complet is True
        assert result.taux_completude == 100.0

    def test_verification_partielle(self):
        """Seulement certains documents fournis."""
        docs = ["Facture originale FA-001"]
        result = self.checker.verifier_operation(
            TypeOperation.COMPTABILISATION_FACTURE,
            documents_fournis=docs,
        )
        # La facture est le seul obligatoire -> complet pour les obligatoires
        assert result.taux_completude > 0
        assert result.taux_completude < 100

    def test_verification_declaration_tva(self):
        result = self.checker.verifier_operation(TypeOperation.DECLARATION_TVA)
        assert result.operation == TypeOperation.DECLARATION_TVA
        assert len(result.documents_requis) > 0
        obligatoires = [d for d in result.documents_requis if d.niveau == NiveauObligation.OBLIGATOIRE]
        assert len(obligatoires) >= 3

    def test_verification_bulletin_paie(self):
        result = self.checker.verifier_operation(TypeOperation.BULLETIN_PAIE)
        assert len(result.documents_requis) >= 4
        noms = [d.nom for d in result.documents_requis]
        assert any("Contrat" in n for n in noms)
        assert any("DPAE" in n for n in noms)

    def test_verification_controle_urssaf(self):
        result = self.checker.verifier_operation(TypeOperation.CONTROLE_URSSAF)
        assert len(result.documents_requis) >= 6
        assert result.est_complet is False

    def test_verification_embauche(self):
        docs = [
            "Contrat de travail signe CDI",
            "DPAE declaration prealable",
            "Piece d'identite du salarie CNI",
            "Carte vitale attestation SS",
            "RIB du salarie",
            "Visite medicale d'embauche",
            "Adhesion mutuelle obligatoire",
        ]
        result = self.checker.verifier_operation(
            TypeOperation.EMBAUCHE_SALARIE,
            documents_fournis=docs,
        )
        assert result.est_complet is True

    def test_verification_creation_entreprise(self):
        result = self.checker.verifier_operation(TypeOperation.CREATION_ENTREPRISE)
        noms = [d.nom for d in result.documents_requis]
        assert any("Statuts" in n for n in noms)
        assert any("KBIS" in n for n in noms)

    def test_resume_generation(self):
        result = self.checker.verifier_operation(TypeOperation.COMPTABILISATION_FACTURE)
        assert result.resume != ""
        assert "manquant" in result.resume.lower() or "present" in result.resume.lower()

    # --- Verification facture ---

    def test_verifier_facture_complete(self):
        facture = {
            "numero_piece": "FA-2026-001",
            "date_piece": "2026-01-15",
            "montant_ht": 1000,
            "montant_tva": 200,
            "montant_ttc": 1200,
            "emetteur": {"nom": "Fournisseur SARL", "siret": "12345678901234"},
        }
        alertes = self.checker.verifier_facture(facture)
        assert len(alertes) == 0

    def test_verifier_facture_sans_numero(self):
        facture = {
            "date_piece": "2026-01-15",
            "montant_ht": 1000,
            "montant_ttc": 1200,
            "emetteur": {"nom": "Test"},
        }
        alertes = self.checker.verifier_facture(facture)
        assert any("Numero de facture" in a.titre for a in alertes)

    def test_verifier_facture_sans_emetteur(self):
        facture = {
            "numero_piece": "FA-001",
            "date_piece": "2026-01-15",
            "montant_ht": 1000,
            "montant_ttc": 1200,
        }
        alertes = self.checker.verifier_facture(facture)
        assert any("emetteur" in a.titre.lower() for a in alertes)

    def test_verifier_facture_incoherence_montants(self):
        facture = {
            "numero_piece": "FA-001",
            "date_piece": "2026-01-15",
            "montant_ht": 1000,
            "montant_tva": 200,
            "montant_ttc": 1500,  # HT + TVA = 1200, pas 1500
            "emetteur": {"nom": "Test"},
        }
        alertes = self.checker.verifier_facture(facture)
        assert any("Incoherence" in a.titre for a in alertes)

    def test_verifier_facture_montants_coherents(self):
        facture = {
            "numero_piece": "FA-001",
            "date_piece": "2026-01-15",
            "montant_ht": 1000,
            "montant_tva": 200,
            "montant_ttc": 1200,
            "emetteur": {"nom": "Test"},
        }
        alertes = self.checker.verifier_facture(facture)
        assert not any("Incoherence" in a.titre for a in alertes)

    # --- Verification bulletin de paie ---

    def test_verifier_bulletin_sans_contrat(self):
        alertes = self.checker.verifier_bulletin_paie(
            bulletin={},
            documents_fournis=["DPAE effectuee", "Convention collective HCR"],
        )
        assert any("contrat" in a.titre.lower() for a in alertes)

    def test_verifier_bulletin_complet(self):
        alertes = self.checker.verifier_bulletin_paie(
            bulletin={},
            documents_fournis=[
                "Contrat de travail CDI",
                "DPAE transmise",
                "Convention collective applicable",
            ],
        )
        assert len(alertes) == 0

    # --- Detection documents complementaires ---

    def test_detecter_complementaires_grosse_facture(self):
        alertes = self.checker.detecter_documents_complementaires(
            "facture_achat",
            {"montant_ttc": 5000},
        )
        assert any("Devis" in a.titre or "contrat" in a.titre.lower() for a in alertes)

    def test_detecter_complementaires_petite_facture(self):
        alertes = self.checker.detecter_documents_complementaires(
            "facture_achat",
            {"montant_ttc": 500},
        )
        # Pas de devis recommande < 1500 EUR, mais bon de reception
        assert any("reception" in a.titre.lower() for a in alertes)

    def test_detecter_complementaires_intracomm(self):
        alertes = self.checker.detecter_documents_complementaires(
            "facture_achat",
            {
                "montant_ttc": 500,
                "emetteur": {"numero_tva": "DE123456789"},
            },
        )
        assert any("intracommunautaire" in a.titre.lower() or "DEB" in a.titre for a in alertes)

    def test_detecter_complementaires_bulletin(self):
        alertes = self.checker.detecter_documents_complementaires(
            "bulletin_paie", {},
        )
        assert any("DSN" in a.titre for a in alertes)

    def test_detecter_complementaires_note_frais(self):
        alertes = self.checker.detecter_documents_complementaires(
            "note_frais", {},
        )
        assert any("justificatif" in a.titre.lower() for a in alertes)


class TestReferentielDocuments:
    """Tests du referentiel de documents."""

    def test_toutes_operations_ont_des_documents(self):
        """Verifie que chaque type d'operation a au moins un document requis."""
        for op in TypeOperation:
            if op in DOCUMENTS_PAR_OPERATION:
                assert len(DOCUMENTS_PAR_OPERATION[op]) > 0, (
                    f"Operation {op.value} n'a aucun document requis"
                )

    def test_tous_documents_ont_description(self):
        for op, docs in DOCUMENTS_PAR_OPERATION.items():
            for doc in docs:
                assert doc.description != "", (
                    f"Document '{doc.nom}' de {op.value} n'a pas de description"
                )

    def test_documents_obligatoires_existent(self):
        """Chaque operation a au moins un document obligatoire."""
        for op, docs in DOCUMENTS_PAR_OPERATION.items():
            obligatoires = [d for d in docs if d.niveau == NiveauObligation.OBLIGATOIRE]
            assert len(obligatoires) > 0, (
                f"Operation {op.value} n'a aucun document obligatoire"
            )
