"""Chaine de preuve numerique pour tracabilite inviolable des scores.

Architecture conforme aux exigences probatoires francaises :
- Art. 1366 Code civil : ecrit electronique identifiable et integre
- Art. 1367 Code civil : signature electronique
- Reglement eIDAS (UE 910/2014) : horodatage et integrite
- NF Z42-013 (AFNOR) : archivage electronique a valeur probante
- Art. L102 B LPF : conservation 6 ans (fiscal)
- Art. L243-16 CSS : conservation 5 ans (social)
- RGPD art. 22 : transparence des decisions automatisees

Principe : chaque evenement est scelle par un hash SHA-256 chaine
(hash de l'entree N = SHA256(contenu_N + hash_N-1)), formant une
blockchain simplifiee ou toute modification retroactive est detectable.
"""

import hashlib
import json
import fcntl
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Durees de conservation legales (en annees)
CONSERVATION_FISCALE = 6   # Art. L102 B LPF
CONSERVATION_SOCIALE = 5   # Art. L243-16 CSS
CONSERVATION_PROBANTE = 10  # NF Z42-013 recommandation


def _utc_now() -> str:
    """Horodatage UTC ISO 8601 avec fuseau horaire."""
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: str) -> str:
    """Calcule le SHA-256 d'une chaine UTF-8."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class ProofChain:
    """Chaine de preuve cryptographique append-only.

    Chaque entree contient :
    - seq          : numero de sequence (auto-increment)
    - timestamp    : horodatage UTC ISO 8601
    - type         : type d'evenement
    - payload      : donnees de l'evenement
    - prev_hash    : hash de l'entree precedente (chaine)
    - hash         : SHA-256(json(seq + timestamp + type + payload + prev_hash))

    Le fichier est au format JSON Lines (un objet JSON par ligne).
    Toute modification d'une entree passee invalide la chaine.
    """

    GENESIS_HASH = "0" * 64  # Hash initial de la chaine

    def __init__(self, chain_path: Path):
        self.chain_path = chain_path
        self.lock_path = chain_path.with_suffix(".lock")
        chain_path.parent.mkdir(parents=True, exist_ok=True)

    def _compute_hash(self, entry: dict) -> str:
        """Calcule le hash d'une entree (sans le champ 'hash' lui-meme)."""
        canonical = json.dumps({
            "seq": entry["seq"],
            "timestamp": entry["timestamp"],
            "type": entry["type"],
            "payload": entry["payload"],
            "prev_hash": entry["prev_hash"],
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return _sha256(canonical)

    def _get_last_entry(self) -> Optional[dict]:
        """Recupere la derniere entree de la chaine."""
        if not self.chain_path.exists():
            return None
        last_line = None
        with open(self.chain_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped
        if not last_line:
            return None
        return json.loads(last_line)

    def append(self, event_type: str, payload: dict) -> dict:
        """Ajoute une entree scellee a la chaine (thread-safe).

        Returns:
            L'entree complete avec hash et sequence.
        """
        with open(self.lock_path, "a+") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                last = self._get_last_entry()
                prev_hash = last["hash"] if last else self.GENESIS_HASH
                seq = (last["seq"] + 1) if last else 1

                entry = {
                    "seq": seq,
                    "timestamp": _utc_now(),
                    "type": event_type,
                    "payload": payload,
                    "prev_hash": prev_hash,
                }
                entry["hash"] = self._compute_hash(entry)

                line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
                with open(self.chain_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")

                return entry
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def verify(self) -> dict:
        """Verifie l'integrite de toute la chaine.

        Returns:
            {"valid": bool, "entries": int, "first_invalid": int|None, "detail": str}
        """
        if not self.chain_path.exists():
            return {"valid": True, "entries": 0, "first_invalid": None,
                    "detail": "Chaine vide"}

        prev_hash = self.GENESIS_HASH
        count = 0

        with open(self.chain_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                count += 1
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    return {"valid": False, "entries": count,
                            "first_invalid": line_no,
                            "detail": f"Ligne {line_no}: JSON invalide"}

                # Verifier le chainage
                if entry.get("prev_hash") != prev_hash:
                    return {"valid": False, "entries": count,
                            "first_invalid": line_no,
                            "detail": f"Ligne {line_no}: rupture de chainage "
                                      f"(prev_hash attendu={prev_hash[:16]}..., "
                                      f"trouve={entry.get('prev_hash', '?')[:16]}...)"}

                # Verifier le hash de l'entree
                expected_hash = self._compute_hash(entry)
                if entry.get("hash") != expected_hash:
                    return {"valid": False, "entries": count,
                            "first_invalid": line_no,
                            "detail": f"Ligne {line_no}: hash invalide "
                                      f"(calcule={expected_hash[:16]}..., "
                                      f"stocke={entry.get('hash', '?')[:16]}...)"}

                prev_hash = entry["hash"]

        return {"valid": True, "entries": count, "first_invalid": None,
                "detail": f"Chaine integre : {count} entrees verifiees"}

    def get_entries(self, event_type: str = None, limit: int = 100) -> list[dict]:
        """Lit les entrees de la chaine, optionnellement filtrees par type."""
        if not self.chain_path.exists():
            return []
        entries = []
        with open(self.chain_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                entry = json.loads(stripped)
                if event_type is None or entry.get("type") == event_type:
                    entries.append(entry)
        if limit:
            entries = entries[-limit:]
        return entries

    def get_entry_by_seq(self, seq: int) -> Optional[dict]:
        """Recupere une entree par son numero de sequence."""
        if not self.chain_path.exists():
            return None
        with open(self.chain_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                entry = json.loads(stripped)
                if entry.get("seq") == seq:
                    return entry
        return None


class ScoreProofRecord:
    """Enregistrement de preuve pour un calcul de score.

    Capture TOUS les elements necessaires a la reconstitution :
    - Documents d'entree (hashes)
    - Version du moteur et des constantes
    - Constats detectes (findings)
    - Parametres de calcul (Wk, Wmax, Fc, Npoints)
    - Score resultant par domaine et global
    - References legales applicables
    """

    @staticmethod
    def create(
        session_id: str,
        documents: list[dict],
        constats: list[dict],
        scores: dict,
        version_moteur: str,
        version_constantes: str,
        operateur: str = "",
        references_legales: dict = None,
    ) -> dict:
        """Cree un enregistrement de preuve complet pour un score."""

        # Hash des documents d'entree
        doc_hashes = []
        for doc in documents:
            doc_hashes.append({
                "nom": doc.get("nom_fichier", doc.get("nom", "")),
                "sha256": doc.get("sha256", doc.get("hash_sha256", "")),
                "taille": doc.get("taille_octets", doc.get("taille", 0)),
            })

        # Snapshot des constats avec leur severite
        constats_snapshot = []
        for c in constats:
            constats_snapshot.append({
                "titre": c.get("titre", ""),
                "categorie": c.get("categorie", ""),
                "severite": c.get("severite", ""),
                "reference_legale": c.get("reference_legale", ""),
                "montant_impact": float(c.get("montant_impact", 0) or 0),
                "detecte_par": c.get("detecte_par", ""),
            })

        # Parametres de calcul par domaine
        params_calcul = {}
        for domaine in ["urssaf", "fiscal", "cdc"]:
            sc = scores.get(domaine, {})
            params_calcul[domaine] = {
                "score": sc.get("score", 0),
                "grade": sc.get("grade", ""),
                "totalW": sc.get("totalW", 0),
                "Wmax": sc.get("Wmax", 0),
                "Sbrut": sc.get("Sbrut", 0),
                "Fc": sc.get("Fc", 0),
                "Npoints": sc.get("Npoints", 0),
                "nb_constats": sc.get("nb_critiques", 0) + sc.get("nb_hautes", 0)
                               + sc.get("nb_moyennes", 0) + sc.get("nb_basses", 0),
            }

        score_global = scores.get("global", {})

        record = {
            "session_id": session_id,
            "date_calcul": _utc_now(),
            "operateur": operateur,
            "version_moteur": version_moteur,
            "version_constantes": version_constantes,
            "formule": "S = max(0, 100 * (1 - Sigma(Wk) / Wmax)) * (0.5 + 0.5 * Fc)",
            "poids_severite": {"critique": 4, "haute": 3, "moyenne": 2, "faible": 1},
            "documents_entree": doc_hashes,
            "nb_documents": len(doc_hashes),
            "constats": constats_snapshot,
            "nb_constats": len(constats_snapshot),
            "parametres_calcul": params_calcul,
            "score_global": {
                "score": score_global.get("score", 0),
                "grade": score_global.get("grade", ""),
                "methode_ponderation": "Nk/Somme_Nk (proportionnelle)",
            },
            "references_legales_applicables": references_legales or {},
            "avertissement": (
                "SCORE PROVISOIRE - Outil d'aide a la decision, non decision "
                "automatisee (art. 22 RGPD). Score indicatif non opposable. "
                "Constats de type pattern_suspect = indicateurs statistiques "
                "non probants (art. L243-7 CSS). Soumis a procedure "
                "contradictoire (art. L121-1 CRPA). Validation humaine requise "
                "avant utilisation a des fins decisionnelles (art. 22(3) RGPD)."
            ),
        }

        # Hash de l'enregistrement complet pour integrite
        record["record_hash"] = _sha256(
            json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        )

        return record


class ConstantsVersioner:
    """Versionne les constantes reglementaires pour reconstitution a posteriori.

    A chaque modification des taux/seuils, un snapshot est scelle dans la
    chaine de preuve, permettant de retrouver les constantes applicables
    a la date d'un calcul donne.
    """

    @staticmethod
    def snapshot_constants() -> dict:
        """Cree un snapshot des constantes reglementaires actuelles."""
        from urssaf_analyzer.config.constants import (
            PASS_ANNUEL, PASS_MENSUEL, SMIC_HORAIRE_BRUT, SMIC_MENSUEL_BRUT,
            RGDU_SEUIL_SMIC_MULTIPLE, RGDU_TAUX_MAX_MOINS_50, RGDU_TAUX_MAX_50_PLUS,
            TOLERANCE_MONTANT, TOLERANCE_TAUX,
            SEUIL_NOMBRES_RONDS_PCT, SEUIL_BENFORD_CHI2, SEUIL_OUTLIER_IQR,
            TAUX_COTISATIONS_2026,
        )

        # Serialiser les taux (Decimal -> str pour JSON)
        taux_snapshot = {}
        for key, val in TAUX_COTISATIONS_2026.items():
            taux_entry = {}
            for k, v in val.items():
                taux_entry[k] = str(v) if hasattr(v, "quantize") else v
            taux_snapshot[key.value if hasattr(key, "value") else str(key)] = taux_entry

        snapshot = {
            "date_snapshot": _utc_now(),
            "plafonds": {
                "PASS_ANNUEL": str(PASS_ANNUEL),
                "PASS_MENSUEL": str(PASS_MENSUEL),
            },
            "smic": {
                "SMIC_HORAIRE_BRUT": str(SMIC_HORAIRE_BRUT),
                "SMIC_MENSUEL_BRUT": str(SMIC_MENSUEL_BRUT),
            },
            "rgdu": {
                "seuil_smic_multiple": str(RGDU_SEUIL_SMIC_MULTIPLE),
                "taux_max_moins_50": str(RGDU_TAUX_MAX_MOINS_50),
                "taux_max_50_plus": str(RGDU_TAUX_MAX_50_PLUS),
            },
            "tolerances": {
                "TOLERANCE_MONTANT": str(TOLERANCE_MONTANT),
                "TOLERANCE_TAUX": str(TOLERANCE_TAUX),
            },
            "seuils_patterns": {
                "SEUIL_NOMBRES_RONDS_PCT": str(SEUIL_NOMBRES_RONDS_PCT),
                "SEUIL_BENFORD_CHI2": str(SEUIL_BENFORD_CHI2),
                "SEUIL_OUTLIER_IQR": str(SEUIL_OUTLIER_IQR),
            },
            "taux_cotisations": taux_snapshot,
        }

        snapshot["snapshot_hash"] = _sha256(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        )

        return snapshot

    @staticmethod
    def snapshot_legal_references(annee: int = 2026) -> dict:
        """Cree un snapshot des references legales applicables."""
        from urssaf_analyzer.veille.legifrance_client import get_legislation_par_annee
        legislation = get_legislation_par_annee(annee)
        return {
            "annee": annee,
            "date_snapshot": _utc_now(),
            "legislation": legislation,
        }
