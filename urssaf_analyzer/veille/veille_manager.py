"""Gestionnaire de veille juridique.

Coordonne :
- La detection des annees dans les documents analyses
- L'interrogation des bases Legifrance et URSSAF
- La generation d'alertes de veille
- Le suivi mensuel de la legislation
"""

import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from urssaf_analyzer.database.db_manager import Database
from urssaf_analyzer.veille.legifrance_client import (
    LegifranceClient, get_legislation_par_annee, ARTICLES_CSS_COTISATIONS,
)
from urssaf_analyzer.veille.urssaf_client import (
    URSSAFOpenDataClient, get_baremes_annee, comparer_baremes, BAREMES_PAR_ANNEE,
)


class VeilleManager:
    """Gestionnaire central de la veille juridique."""

    def __init__(self, db: Database, legifrance_client: LegifranceClient = None):
        self.db = db
        self.legifrance = legifrance_client or LegifranceClient(sandbox=True)
        self.urssaf = URSSAFOpenDataClient()

    # --- Detection des annees dans les documents ---

    def detecter_annees_documents(self, textes_documents: list[str]) -> set[int]:
        """Detecte les annees mentionnees dans les documents analyses."""
        annees = set()
        pattern = re.compile(r"\b(20[1-3]\d)\b")
        for texte in textes_documents:
            for match in pattern.finditer(texte):
                annee = int(match.group(1))
                if 2015 <= annee <= 2035:
                    annees.add(annee)
        return annees

    # --- Veille legislative ---

    def get_veille_pour_annees(self, annees: set[int]) -> dict:
        """Retourne la veille juridique pour un ensemble d'annees."""
        veille = {
            "annees_detectees": sorted(annees),
            "legislation_applicable": {},
            "baremes": {},
            "evolutions": [],
            "alertes": [],
        }

        for annee in sorted(annees):
            # Legislation Legifrance
            legislation = get_legislation_par_annee(annee)
            veille["legislation_applicable"][annee] = legislation

            # Baremes URSSAF
            baremes = get_baremes_annee(annee)
            veille["baremes"][annee] = baremes

        # Comparaison inter-annees
        annees_triees = sorted(annees)
        for i in range(1, len(annees_triees)):
            a1 = annees_triees[i - 1]
            a2 = annees_triees[i]
            diffs = comparer_baremes(a1, a2)
            if diffs:
                veille["evolutions"].append({
                    "de": a1,
                    "a": a2,
                    "differences": diffs,
                })

                # Generer des alertes pour les changements importants
                for diff in diffs:
                    if "hausse" in diff.get("evolution", "") or "baisse" in diff.get("evolution", ""):
                        veille["alertes"].append({
                            "titre": f"Evolution {diff['parametre']} entre {a1} et {a2}",
                            "description": (
                                f"{diff['parametre']}: {diff.get(f'valeur_{a1}')} -> "
                                f"{diff.get(f'valeur_{a2}')} ({diff['evolution']})"
                            ),
                            "severite": "info",
                            "annees": [a1, a2],
                        })

        return veille

    def executer_veille_mensuelle(
        self, annee: int, mois: int, entreprise_id: str = None
    ) -> dict:
        """Execute la veille mensuelle complete."""
        resultats = {
            "periode": f"{mois:02d}/{annee}",
            "date_execution": datetime.now().isoformat(),
            "textes_legifrance": [],
            "baremes_urssaf": get_baremes_annee(annee),
            "donnees_open_data": {},
            "alertes": [],
        }

        # 1. Interroger Legifrance (si credentials configures)
        textes = self.legifrance.veille_mensuelle(annee, mois)
        resultats["textes_legifrance"] = textes

        # 2. Interroger URSSAF Open Data
        try:
            exonerations = self.urssaf.get_exonerations(annee=annee, limit=10)
            resultats["donnees_open_data"]["exonerations"] = exonerations
        except Exception:
            pass

        # 3. Generer les alertes
        legislation = get_legislation_par_annee(annee)
        for texte in legislation.get("textes_cles", []):
            resultats["alertes"].append({
                "titre": texte["titre"],
                "description": texte["resume"],
                "reference": texte["reference"],
                "url": texte["url"],
                "severite": "info",
            })

        # 4. Sauvegarder en base
        self._sauvegarder_veille(resultats, entreprise_id)

        return resultats

    def _sauvegarder_veille(self, resultats: dict, entreprise_id: str = None):
        """Sauvegarde les resultats de veille en base."""
        for texte in resultats.get("textes_legifrance", []):
            texte_id = str(uuid.uuid4())
            try:
                self.db.execute(
                    """INSERT OR IGNORE INTO veille_textes
                    (id, source, reference, titre, resume, url, date_publication,
                     annee_reference, categorie)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        texte_id, "legifrance",
                        texte.get("reference", ""),
                        texte.get("titre", ""),
                        texte.get("extrait", ""),
                        texte.get("url", ""),
                        texte.get("date_publication", ""),
                        int(resultats["periode"].split("/")[1]),
                        texte.get("type", ""),
                    ),
                )
            except Exception:
                pass

        for alerte in resultats.get("alertes", []):
            try:
                self.db.execute(
                    """INSERT INTO veille_alertes
                    (texte_id, entreprise_id, titre, description, severite)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        None, entreprise_id,
                        alerte.get("titre", ""),
                        alerte.get("description", ""),
                        alerte.get("severite", "info"),
                    ),
                )
            except Exception:
                pass

    # --- Consultation ---

    def get_alertes_recentes(self, profil_id: str = None, limit: int = 50) -> list[dict]:
        """Recupere les alertes recentes."""
        if profil_id:
            rows = self.db.execute(
                """SELECT a.*, e.raison_sociale FROM veille_alertes a
                   LEFT JOIN entreprises e ON a.entreprise_id = e.id
                   WHERE a.profil_id = ? OR a.profil_id IS NULL
                   ORDER BY a.date_alerte DESC LIMIT ?""",
                (profil_id, limit),
            )
        else:
            rows = self.db.execute(
                """SELECT a.*, e.raison_sociale FROM veille_alertes a
                   LEFT JOIN entreprises e ON a.entreprise_id = e.id
                   ORDER BY a.date_alerte DESC LIMIT ?""",
                (limit,),
            )
        return [dict(r) for r in rows]

    def get_textes_veille(self, annee: int = None, limit: int = 50) -> list[dict]:
        """Recupere les textes de veille."""
        if annee:
            rows = self.db.execute(
                "SELECT * FROM veille_textes WHERE annee_reference = ? ORDER BY date_collecte DESC LIMIT ?",
                (annee, limit),
            )
        else:
            rows = self.db.execute(
                "SELECT * FROM veille_textes ORDER BY date_collecte DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in rows]

    def marquer_alerte_lue(self, alerte_id: int) -> None:
        self.db.execute(
            "UPDATE veille_alertes SET lue = 1 WHERE id = ?", (alerte_id,)
        )

    def marquer_alerte_traitee(self, alerte_id: int) -> None:
        self.db.execute(
            "UPDATE veille_alertes SET traitee = 1, date_traitement = datetime('now') WHERE id = ?",
            (alerte_id,),
        )
