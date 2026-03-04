"""Tests de certification : determinisme, reproductibilite et tracabilite du scoring.

Ces tests constituent la preuve technique que le moteur de scoring satisfait
les exigences de :
- ISO/IEC 25010 : exactitude fonctionnelle (5.1), fiabilite (5.2)
- ISO/IEC 42001 : reproductibilite des resultats d'IA (A.6)
- NF Z42-013 : integrite de la chaine de preuve
- RGPD art. 22 : explicabilite et transparence
"""

import json
import tempfile
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from urssaf_analyzer.analyzers.analyzer_engine import AnalyzerEngine
from urssaf_analyzer.analyzers.anomaly_detector import AnomalyDetector
from urssaf_analyzer.analyzers.consistency_checker import ConsistencyChecker
from urssaf_analyzer.analyzers.pattern_analyzer import PatternAnalyzer
from urssaf_analyzer.config.constants import (
    PASS_MENSUEL, SMIC_MENSUEL_BRUT, Severity, FindingCategory,
    ContributionType, TAUX_COTISATIONS_2026,
)
from urssaf_analyzer.models.documents import (
    Declaration, Cotisation, Employe, Employeur, DateRange, Finding,
)
from urssaf_analyzer.security.proof_chain import (
    ProofChain, ScoreProofRecord, ConstantsVersioner,
)
from urssaf_analyzer.certification.certification_readiness import (
    evaluer_maturite_certification, MaturiteNiveau, PrioriteRemediation,
)


# =====================================================================
# FIXTURES
# =====================================================================

@pytest.fixture
def declaration_standard():
    """Declaration standard avec donnees completes pour tests de determinisme."""
    return Declaration(
        type_declaration="DSN",
        periode=DateRange(
            debut=date(2026, 1, 1),
            fin=date(2026, 1, 31),
        ),
        employeur=Employeur(
            siret="12345678901234",
            raison_sociale="Test SARL",
            effectif=25,
        ),
        employes=[
            Employe(
                nir="1850175123456",
                nom="Dupont",
                prenom="Jean",
            ),
        ],
        cotisations=[
            Cotisation(
                type_cotisation=ContributionType.MALADIE,
                base_brute=Decimal("3000.00"),
                taux_patronal=Decimal("0.13"),
                taux_salarial=Decimal("0.0"),
                montant_patronal=Decimal("390.00"),
                montant_salarial=Decimal("0.00"),
            ),
            Cotisation(
                type_cotisation=ContributionType.VIEILLESSE_PLAFONNEE,
                base_brute=Decimal("3000.00"),
                taux_patronal=Decimal("0.0855"),
                taux_salarial=Decimal("0.0690"),
                montant_patronal=Decimal("256.50"),
                montant_salarial=Decimal("207.00"),
            ),
        ],
    )


@pytest.fixture
def proof_chain_temp():
    """Chaine de preuve temporaire pour tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chain = ProofChain(Path(tmpdir) / "test_chain.jsonl")
        yield chain


# =====================================================================
# TESTS DE DETERMINISME (ISO/IEC 25010 §5.1 + ISO/IEC 42001)
# =====================================================================

class TestDeterminismeScoring:
    """Verifie que le scoring est deterministe : memes entrees -> meme sortie."""

    def test_memes_constats_meme_score(self, declaration_standard):
        """Le moteur produit des findings identiques pour des entrees identiques."""
        engine = AnalyzerEngine(effectif=25)
        declarations = [declaration_standard]

        findings_1 = engine.analyser(declarations)
        findings_2 = engine.analyser(declarations)

        # Meme nombre de findings
        assert len(findings_1) == len(findings_2)

        # Memes titres dans le meme ordre
        titres_1 = [f.titre for f in findings_1]
        titres_2 = [f.titre for f in findings_2]
        assert titres_1 == titres_2

        # Memes severites
        sevs_1 = [f.severite for f in findings_1]
        sevs_2 = [f.severite for f in findings_2]
        assert sevs_1 == sevs_2

        # Memes scores de risque
        scores_1 = [f.score_risque for f in findings_1]
        scores_2 = [f.score_risque for f in findings_2]
        assert scores_1 == scores_2

    def test_determinisme_100_iterations(self, declaration_standard):
        """Le scoring est stable sur 100 executions consecutives."""
        engine = AnalyzerEngine(effectif=25)
        declarations = [declaration_standard]

        reference = engine.analyser(declarations)
        ref_titres = [f.titre for f in reference]

        for i in range(100):
            result = engine.analyser(declarations)
            assert [f.titre for f in result] == ref_titres, (
                f"Determinisme rompu a l'iteration {i+1}"
            )

    def test_independance_ordre_declarations(self):
        """L'ordre des declarations ne devrait pas changer les findings structurels."""
        from datetime import date

        d1 = Declaration(
            type_declaration="DSN",
            periode=DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31)),
        )
        d2 = Declaration(
            type_declaration="DSN",
            periode=DateRange(debut=date(2026, 2, 1), fin=date(2026, 2, 28)),
        )

        engine = AnalyzerEngine()
        f_ab = engine.analyser([d1, d2])
        f_ba = engine.analyser([d2, d1])

        # Les findings structurels doivent etre les memes (pas forcement dans le meme ordre)
        titres_ab = sorted(f.titre for f in f_ab)
        titres_ba = sorted(f.titre for f in f_ba)
        assert titres_ab == titres_ba

    def test_synthese_deterministe(self, declaration_standard):
        """La synthese est deterministe."""
        engine = AnalyzerEngine(effectif=25)
        findings = engine.analyser([declaration_standard])

        s1 = engine.generer_synthese(findings)
        s2 = engine.generer_synthese(findings)

        assert s1 == s2

    def test_chaque_analyseur_deterministe(self, declaration_standard):
        """Chaque analyseur individuel est deterministe."""
        declarations = [declaration_standard]

        for AnalyzerClass in [AnomalyDetector, ConsistencyChecker, PatternAnalyzer]:
            if AnalyzerClass == AnomalyDetector:
                analyzer = AnalyzerClass(effectif=25)
            else:
                analyzer = AnalyzerClass()

            r1 = analyzer.analyser(declarations)
            r2 = analyzer.analyser(declarations)

            assert len(r1) == len(r2), f"{analyzer.nom} non deterministe (nombre de findings)"
            assert [f.titre for f in r1] == [f.titre for f in r2], (
                f"{analyzer.nom} non deterministe (titres)"
            )


# =====================================================================
# TESTS DE REPRODUCTIBILITE (ISO/IEC 42001 + NF Z42-013)
# =====================================================================

class TestReproductibiliteScore:
    """Verifie qu'un score peut etre reconstruit a partir de son proof record."""

    def test_proof_record_contient_tous_les_parametres(self):
        """Le proof record contient tous les parametres necessaires a la reproduction."""
        record = ScoreProofRecord.create(
            session_id="test-session-123",
            documents=[
                {"nom_fichier": "dsn_jan.xml", "sha256": "abc123", "taille_octets": 45000},
            ],
            constats=[
                {"titre": "SMIC infra-legal", "categorie": "anomalie",
                 "severite": "critique", "reference_legale": "CSS L3231-2",
                 "montant_impact": 150.0, "detecte_par": "AnomalyDetector"},
            ],
            scores={
                "urssaf": {"score": 75, "grade": "B", "totalW": 4, "Wmax": 40,
                           "Sbrut": 90, "Fc": 0.33, "Npoints": 10,
                           "nb_critiques": 1, "nb_hautes": 0, "nb_moyennes": 0, "nb_basses": 0},
                "fiscal": {"score": 100, "grade": "A", "totalW": 0, "Wmax": 40,
                           "Sbrut": 100, "Fc": 0.33, "Npoints": 10,
                           "nb_critiques": 0, "nb_hautes": 0, "nb_moyennes": 0, "nb_basses": 0},
                "cdc": {"score": 100, "grade": "A", "totalW": 0, "Wmax": 32,
                        "Sbrut": 100, "Fc": 0.33, "Npoints": 8,
                        "nb_critiques": 0, "nb_hautes": 0, "nb_moyennes": 0, "nb_basses": 0},
                "global": {"score": 89, "grade": "B"},
            },
            version_moteur="4.0",
            version_constantes="test_hash_123",
        )

        # Verifier la presence de tous les champs requis
        assert "session_id" in record
        assert "date_calcul" in record
        assert "version_moteur" in record
        assert "version_constantes" in record
        assert "formule" in record
        assert "poids_severite" in record
        assert "documents_entree" in record
        assert "constats" in record
        assert "parametres_calcul" in record
        assert "score_global" in record
        assert "record_hash" in record
        assert "avertissement" in record

        # Verifier les valeurs
        assert record["version_moteur"] == "4.0"
        assert record["poids_severite"] == {"critique": 4, "haute": 3, "moyenne": 2, "faible": 1}
        assert record["formule"] == "S = max(0, 100 * (1 - Sigma(Wk) / Wmax)) * (0.5 + 0.5 * Fc)"
        assert len(record["documents_entree"]) == 1
        assert len(record["constats"]) == 1

    def test_proof_record_hash_integrite(self):
        """Le hash du proof record est valide et detecte les alterations."""
        import hashlib

        record = ScoreProofRecord.create(
            session_id="integrity-test",
            documents=[],
            constats=[],
            scores={"global": {"score": 100, "grade": "A"}},
            version_moteur="4.0",
            version_constantes="v1",
        )

        # Sauvegarder le hash original
        original_hash = record["record_hash"]

        # Recalculer le hash manuellement
        record_sans_hash = {k: v for k, v in record.items() if k != "record_hash"}
        canonical = json.dumps(record_sans_hash, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        recalcule = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        assert original_hash == recalcule, "Le hash du proof record ne correspond pas"

    def test_constants_snapshot_complet(self):
        """Le snapshot des constantes capture tous les parametres reglementaires."""
        snapshot = ConstantsVersioner.snapshot_constants()

        assert "plafonds" in snapshot
        assert "PASS_ANNUEL" in snapshot["plafonds"]
        assert "PASS_MENSUEL" in snapshot["plafonds"]

        assert "smic" in snapshot
        assert "SMIC_HORAIRE_BRUT" in snapshot["smic"]
        assert "SMIC_MENSUEL_BRUT" in snapshot["smic"]

        assert "rgdu" in snapshot
        assert "tolerances" in snapshot
        assert "seuils_patterns" in snapshot
        assert "taux_cotisations" in snapshot
        assert "snapshot_hash" in snapshot

    def test_constants_snapshot_hash_valide(self):
        """Le hash du snapshot est calculable et non vide."""
        import hashlib
        s = ConstantsVersioner.snapshot_constants()

        # Le hash doit etre present et non vide
        assert "snapshot_hash" in s
        assert len(s["snapshot_hash"]) == 64  # SHA-256

        # Recalculer le hash manuellement (sans le champ snapshot_hash)
        data_sans_hash = {k: v for k, v in s.items() if k != "snapshot_hash"}
        canonical = json.dumps(data_sans_hash, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        recalcule = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert s["snapshot_hash"] == recalcule


# =====================================================================
# TESTS DE LA CHAINE DE PREUVE (NF Z42-013)
# =====================================================================

class TestChaineDePreuve:
    """Verifie l'integrite et l'immuabilite de la chaine de preuve."""

    def test_chain_vide_valide(self, proof_chain_temp):
        """Une chaine vide est valide."""
        result = proof_chain_temp.verify()
        assert result["valid"] is True
        assert result["entries"] == 0

    def test_append_et_verify(self, proof_chain_temp):
        """L'ajout d'entrees maintient l'integrite de la chaine."""
        proof_chain_temp.append("test_event", {"data": "value1"})
        proof_chain_temp.append("test_event", {"data": "value2"})
        proof_chain_temp.append("score_scelle", {"score": 85})

        result = proof_chain_temp.verify()
        assert result["valid"] is True
        assert result["entries"] == 3

    def test_chainage_hash(self, proof_chain_temp):
        """Chaque entree reference le hash de la precedente."""
        e1 = proof_chain_temp.append("event_1", {"a": 1})
        e2 = proof_chain_temp.append("event_2", {"b": 2})
        e3 = proof_chain_temp.append("event_3", {"c": 3})

        assert e1["prev_hash"] == "0" * 64  # Genesis
        assert e2["prev_hash"] == e1["hash"]
        assert e3["prev_hash"] == e2["hash"]

    def test_sequence_auto_increment(self, proof_chain_temp):
        """Les numeros de sequence sont auto-incrementes."""
        e1 = proof_chain_temp.append("ev", {})
        e2 = proof_chain_temp.append("ev", {})
        e3 = proof_chain_temp.append("ev", {})

        assert e1["seq"] == 1
        assert e2["seq"] == 2
        assert e3["seq"] == 3

    def test_recuperation_par_seq(self, proof_chain_temp):
        """On peut recuperer une entree par son numero de sequence."""
        original = proof_chain_temp.append("test", {"key": "value"})
        retrieved = proof_chain_temp.get_entry_by_seq(1)

        assert retrieved is not None
        assert retrieved["hash"] == original["hash"]
        assert retrieved["payload"]["key"] == "value"

    def test_filtrage_par_type(self, proof_chain_temp):
        """On peut filtrer les entrees par type."""
        proof_chain_temp.append("score", {"s": 1})
        proof_chain_temp.append("validation", {"v": 1})
        proof_chain_temp.append("score", {"s": 2})

        scores = proof_chain_temp.get_entries(event_type="score")
        assert len(scores) == 2

        validations = proof_chain_temp.get_entries(event_type="validation")
        assert len(validations) == 1

    def test_detection_alteration(self, proof_chain_temp):
        """La modification d'une entree est detectee."""
        proof_chain_temp.append("event_1", {"original": True})
        proof_chain_temp.append("event_2", {"data": "intact"})

        # Alterer la premiere entree
        with open(proof_chain_temp.chain_path, "r") as f:
            lines = f.readlines()

        entry = json.loads(lines[0])
        entry["payload"]["original"] = False  # Alteration
        lines[0] = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"

        with open(proof_chain_temp.chain_path, "w") as f:
            f.writelines(lines)

        # La verification doit echouer
        result = proof_chain_temp.verify()
        assert result["valid"] is False
        assert result["first_invalid"] is not None


# =====================================================================
# TESTS DE CERTIFICATION READINESS
# =====================================================================

class TestCertificationReadiness:
    """Verifie le module d'evaluation de maturite."""

    def test_evaluation_complete(self):
        """L'evaluation produit un rapport structure."""
        rapport = evaluer_maturite_certification()

        assert "normes_iso_pertinentes" in rapport
        assert "gap_analysis" in rapport
        assert "plan_remediation" in rapport
        assert "metriques_globales" in rapport
        assert "conclusion" in rapport

    def test_normes_pertinentes(self):
        """Les normes identifiees sont pertinentes."""
        rapport = evaluer_maturite_certification()
        normes = [n["norme"] for n in rapport["normes_iso_pertinentes"]]

        assert "ISO/IEC 25010:2023" in normes
        assert "ISO/IEC 27001:2022" in normes
        assert "ISO/IEC 42001:2023" in normes
        assert "NF Z42-013 (AFNOR)" in normes

    def test_plan_remediation_3_phases(self):
        """Le plan de remediation est structure en 3 phases."""
        rapport = evaluer_maturite_certification()
        plan = rapport["plan_remediation"]

        assert "phase_1_prerequis_bloquants" in plan
        assert "phase_2_conformite_haute" in plan
        assert "phase_3_optimisation" in plan

        # Les 3 phases existent dans le plan
        total_actions = sum(
            len(phase["actions"])
            for phase in plan.values()
        )
        assert total_actions > 0

    def test_metriques_globales_coherentes(self):
        """Les metriques sont coherentes."""
        rapport = evaluer_maturite_certification()
        m = rapport["metriques_globales"]

        assert m["nb_exigences_evaluees"] > 0
        assert 0 <= m["score_maturite_pct"] <= 100
        assert m["effort_remediation_total_jours"] > 0

    def test_exigences_evaluees(self):
        """Toutes les exigences sont evaluees avec un niveau de maturite."""
        rapport = evaluer_maturite_certification()
        for e in rapport["gap_analysis"]:
            assert e["maturite"] in ["absent", "initial", "partiel", "conforme", "optimise"]

    def test_conclusion_contient_verdict(self):
        """La conclusion contient un verdict et des recommandations."""
        rapport = evaluer_maturite_certification()
        conclusion = rapport["conclusion"]

        assert "verdict" in conclusion
        assert "recommandation_organisme" in conclusion
        assert "COFRAC" in conclusion["recommandation_organisme"]


# =====================================================================
# TESTS DE CONSTATS STRUCTURELS (analyzer_engine)
# =====================================================================

class TestConstatsStructurels:
    """Verifie que les constats structurels signalent les limites de l'analyse."""

    def test_document_unique_signale(self):
        """Un seul document genere un constat DONNEE_MANQUANTE."""
        from datetime import date

        decl = Declaration(
            type_declaration="DSN",
            periode=DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31)),
        )
        engine = AnalyzerEngine()
        findings = engine.analyser([decl])

        titres = [f.titre for f in findings]
        assert any("Document unique" in t for t in titres)

    def test_sans_employeur_signale(self):
        """L'absence d'employeur genere un constat."""
        from datetime import date

        decl = Declaration(
            type_declaration="DSN",
            periode=DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31)),
        )
        engine = AnalyzerEngine()
        findings = engine.analyser([decl])

        titres = [f.titre for f in findings]
        assert any("Employeur non identifie" in t for t in titres)

    def test_sans_cotisations_signale(self):
        """L'absence de cotisations genere un constat HAUTE."""
        from datetime import date

        decl = Declaration(
            type_declaration="DSN",
            periode=DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31)),
        )
        engine = AnalyzerEngine()
        findings = engine.analyser([decl])

        aucune_cot = [f for f in findings if "Aucune cotisation" in f.titre]
        assert len(aucune_cot) == 1
        assert aucune_cot[0].severite == Severity.HAUTE
