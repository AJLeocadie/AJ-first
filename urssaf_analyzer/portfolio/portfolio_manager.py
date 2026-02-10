"""Gestionnaire de portefeuille d'entreprises.

Permet de :
- Gerer les profils utilisateurs (creation, authentification)
- Gerer un portefeuille d'entreprises par profil
- Associer les analyses aux entreprises
- Suivre l'historique des analyses
- Generer des tableaux de bord par entreprise
"""

import hashlib
import secrets
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from urssaf_analyzer.database.db_manager import Database


class PortfolioManager:
    """Gestionnaire de portefeuille d'entreprises et profils."""

    def __init__(self, db: Database):
        self.db = db

    # ============================
    # GESTION DES PROFILS
    # ============================

    def creer_profil(
        self, nom: str, prenom: str, email: str, mot_de_passe: str,
        role: str = "analyste",
    ) -> dict:
        """Cree un nouveau profil utilisateur."""
        profil_id = str(uuid.uuid4())
        pwd_hash = self._hash_password(mot_de_passe)

        self.db.execute(
            """INSERT INTO profils (id, nom, prenom, email, role, mot_de_passe_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (profil_id, nom, prenom, email, role, pwd_hash),
        )
        return self.get_profil(profil_id)

    def authentifier(self, email: str, mot_de_passe: str) -> Optional[dict]:
        """Authentifie un utilisateur. Retourne le profil si valide."""
        rows = self.db.execute(
            "SELECT * FROM profils WHERE email = ? AND actif = 1", (email,)
        )
        if not rows:
            return None
        profil = dict(rows[0])
        if not self._verify_password(mot_de_passe, profil["mot_de_passe_hash"]):
            return None
        # Mettre a jour derniere connexion
        self.db.execute(
            "UPDATE profils SET derniere_connexion = datetime('now') WHERE id = ?",
            (profil["id"],),
        )
        del profil["mot_de_passe_hash"]
        return profil

    def get_profil(self, profil_id: str) -> Optional[dict]:
        rows = self.db.execute(
            "SELECT id, nom, prenom, email, role, date_creation, derniere_connexion, actif "
            "FROM profils WHERE id = ?",
            (profil_id,),
        )
        return dict(rows[0]) if rows else None

    def lister_profils(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, nom, prenom, email, role, date_creation, actif FROM profils ORDER BY nom"
        )
        return [dict(r) for r in rows]

    # ============================
    # GESTION DES ENTREPRISES
    # ============================

    def ajouter_entreprise(
        self,
        siret: str,
        raison_sociale: str,
        *,
        forme_juridique: str = "",
        code_naf: str = "",
        effectif: int = 0,
        taux_at: float = 0.0208,
        convention_collective: str = "",
        adresse: str = "",
        code_postal: str = "",
        ville: str = "",
        notes: str = "",
    ) -> dict:
        """Ajoute une entreprise au referentiel."""
        entreprise_id = str(uuid.uuid4())
        siren = siret[:9] if len(siret) >= 9 else siret

        self.db.execute(
            """INSERT INTO entreprises
               (id, siret, siren, raison_sociale, forme_juridique, code_naf,
                effectif, taux_at, convention_collective, adresse, code_postal,
                ville, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entreprise_id, siret, siren, raison_sociale, forme_juridique,
                code_naf, effectif, taux_at, convention_collective,
                adresse, code_postal, ville, notes,
            ),
        )
        return self.get_entreprise(entreprise_id)

    def get_entreprise(self, entreprise_id: str) -> Optional[dict]:
        rows = self.db.execute(
            "SELECT * FROM entreprises WHERE id = ?", (entreprise_id,)
        )
        return dict(rows[0]) if rows else None

    def get_entreprise_par_siret(self, siret: str) -> Optional[dict]:
        rows = self.db.execute(
            "SELECT * FROM entreprises WHERE siret = ?", (siret,)
        )
        return dict(rows[0]) if rows else None

    def modifier_entreprise(self, entreprise_id: str, **kwargs) -> Optional[dict]:
        """Modifie les champs specifies d'une entreprise."""
        champs_autorises = {
            "raison_sociale", "forme_juridique", "code_naf", "effectif",
            "taux_at", "convention_collective", "adresse", "code_postal",
            "ville", "notes",
        }
        updates = {k: v for k, v in kwargs.items() if k in champs_autorises}
        if not updates:
            return self.get_entreprise(entreprise_id)

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [entreprise_id]
        self.db.execute(
            f"UPDATE entreprises SET {set_clause} WHERE id = ?", tuple(values)
        )
        return self.get_entreprise(entreprise_id)

    def supprimer_entreprise(self, entreprise_id: str) -> None:
        self.db.execute(
            "UPDATE entreprises SET actif = 0 WHERE id = ?", (entreprise_id,)
        )

    def lister_entreprises(self, actif_seulement: bool = True) -> list[dict]:
        if actif_seulement:
            rows = self.db.execute(
                "SELECT * FROM entreprises WHERE actif = 1 ORDER BY raison_sociale"
            )
        else:
            rows = self.db.execute("SELECT * FROM entreprises ORDER BY raison_sociale")
        return [dict(r) for r in rows]

    def rechercher_entreprises(self, terme: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM entreprises
               WHERE actif = 1 AND (
                   raison_sociale LIKE ? OR siret LIKE ? OR siren LIKE ? OR ville LIKE ?
               ) ORDER BY raison_sociale""",
            (f"%{terme}%", f"%{terme}%", f"%{terme}%", f"%{terme}%"),
        )
        return [dict(r) for r in rows]

    # ============================
    # PORTEFEUILLE (profil <-> entreprises)
    # ============================

    def assigner_entreprise(
        self, profil_id: str, entreprise_id: str, role: str = "gestionnaire"
    ) -> None:
        """Assigne une entreprise au portefeuille d'un profil."""
        self.db.execute(
            """INSERT OR IGNORE INTO portefeuille (profil_id, entreprise_id, role_sur_entreprise)
               VALUES (?, ?, ?)""",
            (profil_id, entreprise_id, role),
        )

    def retirer_entreprise_portefeuille(self, profil_id: str, entreprise_id: str) -> None:
        self.db.execute(
            "DELETE FROM portefeuille WHERE profil_id = ? AND entreprise_id = ?",
            (profil_id, entreprise_id),
        )

    def get_portefeuille(self, profil_id: str) -> list[dict]:
        """Retourne les entreprises du portefeuille d'un profil."""
        rows = self.db.execute(
            """SELECT e.*, p.role_sur_entreprise, p.date_ajout as date_ajout_portefeuille
               FROM entreprises e
               JOIN portefeuille p ON e.id = p.entreprise_id
               WHERE p.profil_id = ? AND e.actif = 1
               ORDER BY e.raison_sociale""",
            (profil_id,),
        )
        return [dict(r) for r in rows]

    # ============================
    # HISTORIQUE DES ANALYSES
    # ============================

    def enregistrer_analyse(
        self,
        entreprise_id: str = None,
        profil_id: str = None,
        nb_documents: int = 0,
        nb_findings: int = 0,
        score_risque: int = 0,
        impact_financier: float = 0,
        chemin_rapport: str = "",
        format_rapport: str = "html",
        duree_secondes: float = 0,
        resume: str = "",
    ) -> str:
        """Enregistre une analyse dans l'historique."""
        analyse_id = str(uuid.uuid4())
        self.db.execute(
            """INSERT INTO analyses
               (id, entreprise_id, profil_id, nb_documents, nb_findings,
                score_risque, impact_financier, chemin_rapport, format_rapport,
                duree_secondes, resume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                analyse_id, entreprise_id, profil_id, nb_documents,
                nb_findings, score_risque, impact_financier, chemin_rapport,
                format_rapport, duree_secondes, resume,
            ),
        )
        return analyse_id

    def get_historique_analyses(
        self, entreprise_id: str = None, profil_id: str = None, limit: int = 50
    ) -> list[dict]:
        """Retourne l'historique des analyses."""
        if entreprise_id:
            rows = self.db.execute(
                """SELECT a.*, e.raison_sociale FROM analyses a
                   LEFT JOIN entreprises e ON a.entreprise_id = e.id
                   WHERE a.entreprise_id = ? ORDER BY a.date_analyse DESC LIMIT ?""",
                (entreprise_id, limit),
            )
        elif profil_id:
            rows = self.db.execute(
                """SELECT a.*, e.raison_sociale FROM analyses a
                   LEFT JOIN entreprises e ON a.entreprise_id = e.id
                   WHERE a.profil_id = ? ORDER BY a.date_analyse DESC LIMIT ?""",
                (profil_id, limit),
            )
        else:
            rows = self.db.execute(
                """SELECT a.*, e.raison_sociale FROM analyses a
                   LEFT JOIN entreprises e ON a.entreprise_id = e.id
                   ORDER BY a.date_analyse DESC LIMIT ?""",
                (limit,),
            )
        return [dict(r) for r in rows]

    def get_dashboard_entreprise(self, entreprise_id: str) -> dict:
        """Genere un tableau de bord pour une entreprise."""
        entreprise = self.get_entreprise(entreprise_id)
        if not entreprise:
            return {}

        analyses = self.get_historique_analyses(entreprise_id=entreprise_id, limit=12)

        # Statistiques
        nb_analyses = len(analyses)
        dernier_score = analyses[0]["score_risque"] if analyses else 0
        score_moyen = (
            sum(a["score_risque"] for a in analyses) / nb_analyses
            if nb_analyses > 0 else 0
        )
        impact_total = sum(a["impact_financier"] or 0 for a in analyses)
        findings_total = sum(a["nb_findings"] for a in analyses)

        # Evolution du score
        evolution_score = []
        for a in reversed(analyses[:12]):
            evolution_score.append({
                "date": a["date_analyse"],
                "score": a["score_risque"],
                "findings": a["nb_findings"],
            })

        return {
            "entreprise": entreprise,
            "statistiques": {
                "nb_analyses": nb_analyses,
                "dernier_score_risque": dernier_score,
                "score_moyen": round(score_moyen, 1),
                "impact_financier_cumule": round(impact_total, 2),
                "findings_cumules": findings_total,
            },
            "evolution_score": evolution_score,
            "dernieres_analyses": analyses[:5],
        }

    # ============================
    # UTILITAIRES
    # ============================

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
        return f"{salt}:{h.hex()}"

    @staticmethod
    def _verify_password(password: str, stored_hash: str) -> bool:
        try:
            salt, h = stored_hash.split(":")
            expected = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), 100_000
            )
            return expected.hex() == h
        except (ValueError, AttributeError):
            return False
