"""Tests exhaustifs du module de chaine de preuve (proof_chain.py).

Couverture cible : 80%+ sur proof_chain.py
Marqueurs : securite, reproductibilite (ISO 27001, NF Z42-013)
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.security.proof_chain import (
    ProofChain,
    ScoreProofRecord,
    ConstantsVersioner,
    _sha256,
    _utc_now,
    CONSERVATION_FISCALE,
    CONSERVATION_SOCIALE,
    CONSERVATION_PROBANTE,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_chain(tmp_path):
    """Cree une ProofChain dans un repertoire temporaire."""
    return ProofChain(tmp_path / "proof" / "chain.jsonl")


# ──────────────────────────────────────────────
# Tests utilitaires
# ──────────────────────────────────────────────

class TestUtilitaires:
    """Tests des fonctions utilitaires."""

    def test_sha256_deterministe(self):
        """SHA-256 du meme contenu doit produire le meme hash."""
        assert _sha256("hello") == _sha256("hello")

    def test_sha256_longueur(self):
        """SHA-256 produit un hash de 64 caracteres hexadecimaux."""
        h = _sha256("test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_sha256_differents(self):
        """Contenus differents donnent des hashes differents."""
        assert _sha256("a") != _sha256("b")

    def test_sha256_chaine_vide(self):
        """SHA-256 d'une chaine vide est bien defini."""
        h = _sha256("")
        assert len(h) == 64

    def test_utc_now_format_iso(self):
        """L'horodatage est au format ISO 8601 avec fuseau."""
        ts = _utc_now()
        assert "T" in ts
        assert "+" in ts or "Z" in ts or "UTC" in ts


class TestConstantes:
    """Tests des constantes de conservation."""

    def test_conservation_fiscale(self):
        assert CONSERVATION_FISCALE == 6

    def test_conservation_sociale(self):
        assert CONSERVATION_SOCIALE == 5

    def test_conservation_probante(self):
        assert CONSERVATION_PROBANTE == 10


# ──────────────────────────────────────────────
# Tests ProofChain
# ──────────────────────────────────────────────

class TestProofChainCreation:
    """Tests de creation et initialisation de la chaine."""

    def test_creation_repertoire(self, tmp_path):
        """La chaine cree automatiquement les repertoires parents."""
        chain = ProofChain(tmp_path / "deep" / "nested" / "chain.jsonl")
        assert (tmp_path / "deep" / "nested").is_dir()

    def test_genesis_hash(self):
        """Le hash initial est compose de 64 zeros."""
        assert ProofChain.GENESIS_HASH == "0" * 64
        assert len(ProofChain.GENESIS_HASH) == 64

    def test_chaine_vide_verify(self, tmp_path):
        """Une chaine vide est valide."""
        chain = _make_chain(tmp_path)
        result = chain.verify()
        assert result["valid"] is True
        assert result["entries"] == 0
        assert result["first_invalid"] is None

    def test_chaine_vide_get_entries(self, tmp_path):
        """Lecture d'une chaine inexistante retourne une liste vide."""
        chain = _make_chain(tmp_path)
        assert chain.get_entries() == []

    def test_chaine_vide_get_last(self, tmp_path):
        """Derniere entree d'une chaine vide est None."""
        chain = _make_chain(tmp_path)
        assert chain._get_last_entry() is None


class TestProofChainAppend:
    """Tests d'ajout d'entrees a la chaine."""

    def test_append_premiere_entree(self, tmp_path):
        """La premiere entree a seq=1 et prev_hash=GENESIS."""
        chain = _make_chain(tmp_path)
        entry = chain.append("test_event", {"key": "value"})

        assert entry["seq"] == 1
        assert entry["type"] == "test_event"
        assert entry["payload"] == {"key": "value"}
        assert entry["prev_hash"] == ProofChain.GENESIS_HASH
        assert "hash" in entry
        assert "timestamp" in entry

    def test_append_sequence_auto_increment(self, tmp_path):
        """Les sequences s'auto-incrementent correctement."""
        chain = _make_chain(tmp_path)
        e1 = chain.append("evt1", {"n": 1})
        e2 = chain.append("evt2", {"n": 2})
        e3 = chain.append("evt3", {"n": 3})

        assert e1["seq"] == 1
        assert e2["seq"] == 2
        assert e3["seq"] == 3

    def test_append_chainage_hashes(self, tmp_path):
        """Chaque entree reference le hash de la precedente."""
        chain = _make_chain(tmp_path)
        e1 = chain.append("evt1", {"n": 1})
        e2 = chain.append("evt2", {"n": 2})
        e3 = chain.append("evt3", {"n": 3})

        assert e1["prev_hash"] == ProofChain.GENESIS_HASH
        assert e2["prev_hash"] == e1["hash"]
        assert e3["prev_hash"] == e2["hash"]

    def test_append_hash_unique(self, tmp_path):
        """Chaque entree a un hash unique."""
        chain = _make_chain(tmp_path)
        entries = [chain.append("evt", {"n": i}) for i in range(5)]
        hashes = [e["hash"] for e in entries]
        assert len(set(hashes)) == 5

    def test_append_hash_calculable(self, tmp_path):
        """Le hash de l'entree est recalculable independamment."""
        chain = _make_chain(tmp_path)
        entry = chain.append("test", {"data": "abc"})
        recalculated = chain._compute_hash(entry)
        assert entry["hash"] == recalculated

    def test_append_payload_complexe(self, tmp_path):
        """Supporte les payloads avec structures imbriquees."""
        chain = _make_chain(tmp_path)
        payload = {
            "scores": {"urssaf": 75, "dgfip": 80},
            "constats": [{"titre": "Test", "severite": "HAUTE"}],
            "nested": {"a": {"b": {"c": 42}}},
        }
        entry = chain.append("score_calcul", payload)
        assert entry["payload"] == payload

    def test_append_payload_unicode(self, tmp_path):
        """Supporte les caracteres Unicode (accents francais)."""
        chain = _make_chain(tmp_path)
        payload = {"titre": "Ecart de regularisation", "detail": "conformite"}
        entry = chain.append("constat", payload)
        assert entry["payload"]["titre"] == "Ecart de regularisation"

    def test_append_persistance_fichier(self, tmp_path):
        """Les entrees sont bien persistees dans le fichier."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"n": 1})
        chain.append("evt2", {"n": 2})

        # Relire le fichier brut
        lines = chain.chain_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            entry = json.loads(line)
            assert "seq" in entry
            assert "hash" in entry


class TestProofChainVerify:
    """Tests de verification d'integrite de la chaine."""

    def test_verify_chaine_valide(self, tmp_path):
        """Une chaine non alteree est valide."""
        chain = _make_chain(tmp_path)
        for i in range(10):
            chain.append(f"evt_{i}", {"index": i})

        result = chain.verify()
        assert result["valid"] is True
        assert result["entries"] == 10
        assert result["first_invalid"] is None

    def test_verify_detecte_alteration_payload(self, tmp_path):
        """La modification d'un payload est detectee."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"original": True})
        chain.append("evt2", {"n": 2})

        # Alterer la premiere entree
        lines = chain.chain_path.read_text(encoding="utf-8").strip().split("\n")
        entry = json.loads(lines[0])
        entry["payload"]["original"] = False  # Modification !
        lines[0] = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        chain.chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = chain.verify()
        assert result["valid"] is False
        assert result["first_invalid"] == 1

    def test_verify_detecte_alteration_hash(self, tmp_path):
        """La modification directe d'un hash est detectee."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"n": 1})

        lines = chain.chain_path.read_text(encoding="utf-8").strip().split("\n")
        entry = json.loads(lines[0])
        entry["hash"] = "a" * 64  # Faux hash
        lines[0] = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        chain.chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = chain.verify()
        assert result["valid"] is False

    def test_verify_detecte_rupture_chainage(self, tmp_path):
        """La modification du prev_hash d'une entree rompt la chaine."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"n": 1})
        chain.append("evt2", {"n": 2})
        chain.append("evt3", {"n": 3})

        lines = chain.chain_path.read_text(encoding="utf-8").strip().split("\n")
        entry = json.loads(lines[1])  # 2eme entree
        entry["prev_hash"] = "b" * 64  # Mauvais chainage
        lines[1] = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        chain.chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = chain.verify()
        assert result["valid"] is False
        assert result["first_invalid"] == 2  # Ligne 2

    def test_verify_detecte_suppression_entree(self, tmp_path):
        """La suppression d'une entree intermediaire est detectee."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"n": 1})
        chain.append("evt2", {"n": 2})
        chain.append("evt3", {"n": 3})

        # Supprimer la 2eme entree
        lines = chain.chain_path.read_text(encoding="utf-8").strip().split("\n")
        del lines[1]
        chain.chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = chain.verify()
        assert result["valid"] is False

    def test_verify_detecte_json_invalide(self, tmp_path):
        """Un JSON malformate est detecte."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"n": 1})

        # Corrompre le fichier
        chain.chain_path.write_text("{invalid json}\n", encoding="utf-8")

        result = chain.verify()
        assert result["valid"] is False
        assert "JSON invalide" in result["detail"]

    def test_verify_ignore_lignes_vides(self, tmp_path):
        """Les lignes vides dans le fichier sont ignorees."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"n": 1})

        # Ajouter des lignes vides
        content = chain.chain_path.read_text(encoding="utf-8")
        chain.chain_path.write_text("\n\n" + content + "\n\n", encoding="utf-8")

        result = chain.verify()
        assert result["valid"] is True
        assert result["entries"] == 1

    def test_verify_message_detail(self, tmp_path):
        """Le detail de verification contient le nombre d'entrees."""
        chain = _make_chain(tmp_path)
        for i in range(5):
            chain.append(f"evt_{i}", {"i": i})

        result = chain.verify()
        assert "5 entrees verifiees" in result["detail"]


class TestProofChainGetEntries:
    """Tests de lecture des entrees."""

    def test_get_entries_toutes(self, tmp_path):
        """Lecture de toutes les entrees."""
        chain = _make_chain(tmp_path)
        for i in range(5):
            chain.append("evt", {"i": i})

        entries = chain.get_entries()
        assert len(entries) == 5

    def test_get_entries_filtre_type(self, tmp_path):
        """Filtrage par type d'evenement."""
        chain = _make_chain(tmp_path)
        chain.append("score", {"s": 80})
        chain.append("validation", {"ok": True})
        chain.append("score", {"s": 75})
        chain.append("contestation", {"motif": "test"})
        chain.append("score", {"s": 90})

        scores = chain.get_entries(event_type="score")
        assert len(scores) == 3
        validations = chain.get_entries(event_type="validation")
        assert len(validations) == 1

    def test_get_entries_limite(self, tmp_path):
        """La limite retourne les N dernieres entrees."""
        chain = _make_chain(tmp_path)
        for i in range(20):
            chain.append("evt", {"i": i})

        entries = chain.get_entries(limit=5)
        assert len(entries) == 5
        # Les 5 dernieres
        assert entries[0]["payload"]["i"] == 15
        assert entries[4]["payload"]["i"] == 19

    def test_get_entries_limite_zero(self, tmp_path):
        """Limite 0 signifie pas de limite (retourne tout)."""
        chain = _make_chain(tmp_path)
        for i in range(10):
            chain.append("evt", {"i": i})

        entries = chain.get_entries(limit=0)
        assert len(entries) == 10

    def test_get_entries_chaine_vide(self, tmp_path):
        """Lecture d'une chaine inexistante retourne liste vide."""
        chain = _make_chain(tmp_path)
        assert chain.get_entries() == []
        assert chain.get_entries(event_type="score") == []

    def test_get_entry_by_seq(self, tmp_path):
        """Recuperation d'une entree par son numero de sequence."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"n": 1})
        chain.append("evt2", {"n": 2})
        chain.append("evt3", {"n": 3})

        entry = chain.get_entry_by_seq(2)
        assert entry is not None
        assert entry["type"] == "evt2"
        assert entry["payload"]["n"] == 2

    def test_get_entry_by_seq_inexistant(self, tmp_path):
        """Sequence inexistante retourne None."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"n": 1})

        assert chain.get_entry_by_seq(99) is None

    def test_get_entry_by_seq_chaine_vide(self, tmp_path):
        """Recherche dans une chaine vide retourne None."""
        chain = _make_chain(tmp_path)
        assert chain.get_entry_by_seq(1) is None


class TestProofChainGetLastEntry:
    """Tests de recuperation de la derniere entree."""

    def test_get_last_entry(self, tmp_path):
        """Recupere la derniere entree correctement."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"n": 1})
        chain.append("evt2", {"n": 2})
        chain.append("evt3", {"n": 3})

        last = chain._get_last_entry()
        assert last["seq"] == 3
        assert last["type"] == "evt3"

    def test_get_last_entry_fichier_vide(self, tmp_path):
        """Fichier existant mais vide retourne None."""
        chain = _make_chain(tmp_path)
        chain.chain_path.write_text("", encoding="utf-8")
        assert chain._get_last_entry() is None

    def test_get_last_entry_lignes_vides_fin(self, tmp_path):
        """Les lignes vides en fin de fichier sont ignorees."""
        chain = _make_chain(tmp_path)
        chain.append("evt1", {"n": 1})

        content = chain.chain_path.read_text(encoding="utf-8")
        chain.chain_path.write_text(content + "\n\n\n", encoding="utf-8")

        last = chain._get_last_entry()
        assert last["seq"] == 1


class TestProofChainComputeHash:
    """Tests du calcul de hash d'entree."""

    def test_compute_hash_deterministe(self, tmp_path):
        """Meme entree produit meme hash."""
        chain = _make_chain(tmp_path)
        entry = {
            "seq": 1,
            "timestamp": "2026-03-04T10:00:00+00:00",
            "type": "test",
            "payload": {"data": "abc"},
            "prev_hash": ProofChain.GENESIS_HASH,
        }
        h1 = chain._compute_hash(entry)
        h2 = chain._compute_hash(entry)
        assert h1 == h2

    def test_compute_hash_ignore_hash_field(self, tmp_path):
        """Le champ 'hash' de l'entree n'affecte pas le calcul."""
        chain = _make_chain(tmp_path)
        entry = {
            "seq": 1,
            "timestamp": "2026-03-04T10:00:00+00:00",
            "type": "test",
            "payload": {"data": "abc"},
            "prev_hash": ProofChain.GENESIS_HASH,
        }
        h1 = chain._compute_hash(entry)
        entry["hash"] = "whatever"
        h2 = chain._compute_hash(entry)
        assert h1 == h2

    def test_compute_hash_sensible_payload(self, tmp_path):
        """Modifier le payload change le hash."""
        chain = _make_chain(tmp_path)
        base = {
            "seq": 1,
            "timestamp": "2026-03-04T10:00:00+00:00",
            "type": "test",
            "prev_hash": ProofChain.GENESIS_HASH,
        }
        entry1 = {**base, "payload": {"x": 1}}
        entry2 = {**base, "payload": {"x": 2}}
        assert chain._compute_hash(entry1) != chain._compute_hash(entry2)


# ──────────────────────────────────────────────
# Tests ScoreProofRecord
# ──────────────────────────────────────────────

class TestScoreProofRecord:
    """Tests de l'enregistrement de preuve de score."""

    def _sample_record(self):
        """Cree un enregistrement de preuve type."""
        return ScoreProofRecord.create(
            session_id="session-test-001",
            documents=[
                {"nom_fichier": "dsn_jan.xml", "sha256": "abc123", "taille_octets": 1024},
                {"nom_fichier": "bulletin_jan.pdf", "sha256": "def456", "taille_octets": 2048},
            ],
            constats=[
                {
                    "titre": "SMIC infra-legal",
                    "categorie": "ANOMALIE",
                    "severite": "CRITIQUE",
                    "reference_legale": "Art. L3231-2 CT",
                    "montant_impact": 1500,
                    "detecte_par": "AnomalyDetector",
                },
            ],
            scores={
                "urssaf": {"score": 75, "grade": "B", "totalW": 10, "Wmax": 40,
                           "Sbrut": 75, "Fc": 1.0, "Npoints": 10,
                           "nb_critiques": 1, "nb_hautes": 0, "nb_moyennes": 0, "nb_basses": 0},
                "fiscal": {"score": 90, "grade": "A", "totalW": 2, "Wmax": 40,
                           "Sbrut": 95, "Fc": 1.0, "Npoints": 10,
                           "nb_critiques": 0, "nb_hautes": 0, "nb_moyennes": 1, "nb_basses": 0},
                "cdc": {"score": 100, "grade": "A", "totalW": 0, "Wmax": 32,
                        "Sbrut": 100, "Fc": 1.0, "Npoints": 8,
                        "nb_critiques": 0, "nb_hautes": 0, "nb_moyennes": 0, "nb_basses": 0},
                "global": {"score": 85, "grade": "B"},
            },
            version_moteur="4.0.0",
            version_constantes="sha256:abc123",
            operateur="audit_test",
        )

    def test_record_structure_complete(self):
        """Le record contient tous les champs requis."""
        record = self._sample_record()
        required_fields = [
            "session_id", "date_calcul", "operateur", "version_moteur",
            "version_constantes", "formule", "poids_severite",
            "documents_entree", "nb_documents", "constats", "nb_constats",
            "parametres_calcul", "score_global", "avertissement", "record_hash",
        ]
        for field in required_fields:
            assert field in record, f"Champ manquant: {field}"

    def test_record_formule_documentee(self):
        """La formule de calcul est incluse dans le record."""
        record = self._sample_record()
        assert "S = max(0" in record["formule"]
        assert "Wk" in record["formule"]
        assert "Fc" in record["formule"]

    def test_record_poids_severite(self):
        """Les poids de severite sont conformes a la specification."""
        record = self._sample_record()
        assert record["poids_severite"] == {
            "critique": 4, "haute": 3, "moyenne": 2, "faible": 1
        }

    def test_record_documents(self):
        """Les documents sont correctement captures."""
        record = self._sample_record()
        assert record["nb_documents"] == 2
        assert len(record["documents_entree"]) == 2
        assert record["documents_entree"][0]["nom"] == "dsn_jan.xml"
        assert record["documents_entree"][0]["sha256"] == "abc123"

    def test_record_constats(self):
        """Les constats sont captures avec leur severite."""
        record = self._sample_record()
        assert record["nb_constats"] == 1
        assert record["constats"][0]["titre"] == "SMIC infra-legal"
        assert record["constats"][0]["severite"] == "CRITIQUE"

    def test_record_parametres_calcul_par_domaine(self):
        """Les parametres de calcul sont captures par domaine."""
        record = self._sample_record()
        assert "urssaf" in record["parametres_calcul"]
        assert "fiscal" in record["parametres_calcul"]
        assert "cdc" in record["parametres_calcul"]
        urssaf = record["parametres_calcul"]["urssaf"]
        assert urssaf["score"] == 75
        assert urssaf["totalW"] == 10
        assert urssaf["Wmax"] == 40

    def test_record_score_global(self):
        """Le score global est capture."""
        record = self._sample_record()
        assert record["score_global"]["score"] == 85
        assert record["score_global"]["grade"] == "B"
        assert "proportionnelle" in record["score_global"]["methode_ponderation"].lower()

    def test_record_avertissement_rgpd(self):
        """L'avertissement art. 22 RGPD est present."""
        record = self._sample_record()
        assert "PROVISOIRE" in record["avertissement"]
        assert "art. 22 RGPD" in record["avertissement"]
        assert "aide a la decision" in record["avertissement"]

    def test_record_hash_integrite(self):
        """Le hash du record permet de verifier son integrite."""
        record = self._sample_record()
        assert len(record["record_hash"]) == 64

        # Recalculer le hash (sans le champ record_hash)
        record_copy = {k: v for k, v in record.items() if k != "record_hash"}
        recalculated = _sha256(
            json.dumps(record_copy, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        )
        assert record["record_hash"] == recalculated

    def test_record_operateur_vide(self):
        """L'operateur peut etre vide."""
        record = ScoreProofRecord.create(
            session_id="s1",
            documents=[],
            constats=[],
            scores={"global": {}},
            version_moteur="4.0",
            version_constantes="hash",
        )
        assert record["operateur"] == ""

    def test_record_references_legales(self):
        """Les references legales optionnelles sont incluses."""
        record = ScoreProofRecord.create(
            session_id="s1",
            documents=[],
            constats=[],
            scores={"global": {}},
            version_moteur="4.0",
            version_constantes="hash",
            references_legales={"css": "L243-7", "cgi": "1729"},
        )
        assert record["references_legales_applicables"]["css"] == "L243-7"

    def test_record_sans_references_legales(self):
        """Sans references legales, un dict vide est utilise."""
        record = ScoreProofRecord.create(
            session_id="s1",
            documents=[],
            constats=[],
            scores={"global": {}},
            version_moteur="4.0",
            version_constantes="hash",
        )
        assert record["references_legales_applicables"] == {}

    def test_record_constats_montant_none(self):
        """Un montant_impact None est converti en 0."""
        record = ScoreProofRecord.create(
            session_id="s1",
            documents=[],
            constats=[{"titre": "Test", "montant_impact": None}],
            scores={"global": {}},
            version_moteur="4.0",
            version_constantes="hash",
        )
        assert record["constats"][0]["montant_impact"] == 0.0

    def test_record_documents_champs_alternatifs(self):
        """Supporte les noms de champs alternatifs (nom vs nom_fichier)."""
        record = ScoreProofRecord.create(
            session_id="s1",
            documents=[{"nom": "test.csv", "hash_sha256": "xyz", "taille": 512}],
            constats=[],
            scores={"global": {}},
            version_moteur="4.0",
            version_constantes="hash",
        )
        assert record["documents_entree"][0]["nom"] == "test.csv"
        assert record["documents_entree"][0]["sha256"] == "xyz"
        assert record["documents_entree"][0]["taille"] == 512


# ──────────────────────────────────────────────
# Tests ConstantsVersioner
# ──────────────────────────────────────────────

class TestConstantsVersioner:
    """Tests du versionnement des constantes."""

    def test_snapshot_structure(self):
        """Le snapshot contient toutes les sections attendues."""
        snapshot = ConstantsVersioner.snapshot_constants()
        assert "date_snapshot" in snapshot
        assert "plafonds" in snapshot
        assert "smic" in snapshot
        assert "rgdu" in snapshot
        assert "tolerances" in snapshot
        assert "seuils_patterns" in snapshot
        assert "taux_cotisations" in snapshot
        assert "snapshot_hash" in snapshot

    def test_snapshot_plafonds(self):
        """Les plafonds sont presents et non vides."""
        snapshot = ConstantsVersioner.snapshot_constants()
        assert snapshot["plafonds"]["PASS_ANNUEL"]
        assert snapshot["plafonds"]["PASS_MENSUEL"]

    def test_snapshot_smic(self):
        """Le SMIC est present et non vide."""
        snapshot = ConstantsVersioner.snapshot_constants()
        assert snapshot["smic"]["SMIC_HORAIRE_BRUT"]
        assert snapshot["smic"]["SMIC_MENSUEL_BRUT"]

    def test_snapshot_hash_64_chars(self):
        """Le hash du snapshot fait 64 caracteres."""
        snapshot = ConstantsVersioner.snapshot_constants()
        assert len(snapshot["snapshot_hash"]) == 64

    def test_snapshot_hash_integrity(self):
        """Le hash du snapshot est recalculable."""
        snapshot = ConstantsVersioner.snapshot_constants()
        saved_hash = snapshot.pop("snapshot_hash")
        recalculated = _sha256(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        )
        assert saved_hash == recalculated

    def test_snapshot_taux_cotisations_non_vide(self):
        """Les taux de cotisations sont presents."""
        snapshot = ConstantsVersioner.snapshot_constants()
        assert len(snapshot["taux_cotisations"]) > 0


# ──────────────────────────────────────────────
# Tests integration ProofChain + ScoreProofRecord
# ──────────────────────────────────────────────

class TestProofChainIntegration:
    """Tests d'integration chaine de preuve + proof record."""

    def test_scellement_score_dans_chaine(self, tmp_path):
        """Un score peut etre scelle dans la chaine de preuve."""
        chain = _make_chain(tmp_path)
        record = ScoreProofRecord.create(
            session_id="int-test-001",
            documents=[{"nom": "test.xml", "sha256": "hash123", "taille": 100}],
            constats=[{"titre": "Test", "severite": "FAIBLE"}],
            scores={
                "urssaf": {"score": 80, "grade": "B", "totalW": 5, "Wmax": 40,
                           "Sbrut": 88, "Fc": 1.0, "Npoints": 10,
                           "nb_critiques": 0, "nb_hautes": 0, "nb_moyennes": 0, "nb_basses": 1},
                "global": {"score": 80, "grade": "B"},
            },
            version_moteur="4.0",
            version_constantes="test",
        )

        entry = chain.append("score_triple_scelle", record)
        assert entry["type"] == "score_triple_scelle"
        assert entry["payload"]["session_id"] == "int-test-001"

        # Verifier la chaine
        result = chain.verify()
        assert result["valid"] is True

    def test_workflow_complet(self, tmp_path):
        """Simule le workflow complet : score → validation → contestation."""
        chain = _make_chain(tmp_path)

        # 1. Scellement du score
        chain.append("score_triple_scelle", {
            "session_id": "wf-001",
            "score_global": 74,
            "grade": "C",
        })

        # 2. Validation humaine
        chain.append("validation_humaine_score", {
            "session_id": "wf-001",
            "operateur": "auditeur_1",
            "decision": "VALIDE",
            "justification": "Score conforme aux constats",
        })

        # 3. Contestation
        chain.append("contestation_score", {
            "session_id": "wf-001",
            "demandeur": "entreprise_xyz",
            "motif": "Taux AT conteste",
        })

        # Verification
        result = chain.verify()
        assert result["valid"] is True
        assert result["entries"] == 3

        # Filtrer par type
        scores = chain.get_entries(event_type="score_triple_scelle")
        assert len(scores) == 1
        validations = chain.get_entries(event_type="validation_humaine_score")
        assert len(validations) == 1
        contestations = chain.get_entries(event_type="contestation_score")
        assert len(contestations) == 1

    def test_snapshot_dans_chaine(self, tmp_path):
        """Un snapshot de constantes peut etre scelle dans la chaine."""
        chain = _make_chain(tmp_path)
        snapshot = ConstantsVersioner.snapshot_constants()

        entry = chain.append("snapshot_constantes", snapshot)
        assert entry["type"] == "snapshot_constantes"

        result = chain.verify()
        assert result["valid"] is True
