"""Analyse multi-annuelle N-5 a N.

Ref:
- CSS art. L.244-3 (prescription 3 ans cotisations)
- CT art. L.8224-1 (prescription 5 ans travail dissimule)
- LPF art. L.169 (prescription fiscale 3 ans, 6 ans si activite occulte)
- CT art. L.3245-1 (prescription salaires 3 ans)

Fonctionnalites:
1. Agregation des donnees par annee (masse salariale, effectifs, cotisations)
2. Detection de tendances inter-annuelles
3. Verification de coherence multi-periodes
4. Detection d anomalies structurelles
5. Couverture prescription (5 ans travail dissimule)
"""

from decimal import Decimal
from typing import Optional
from datetime import datetime


class AnalyseMultiAnnuelle:
    """Moteur d analyse multi-annuelle N-5 a N."""

    def __init__(self):
        self.donnees_annuelles: dict[int, dict] = {}

    def alimenter(self, annee: int, donnees: dict):
        """Ajoute ou met a jour les donnees d une annee.

        Args:
            annee: Annee (ex: 2024)
            donnees: Dictionnaire contenant :
                - masse_salariale: float
                - effectif_moyen: int
                - nb_bulletins: int
                - nb_dsn: int
                - total_cotisations_patronales: float
                - total_cotisations_salariales: float
                - nb_entrees: int (embauches)
                - nb_sorties: int (departs)
                - nb_at: int (accidents du travail)
                - nb_arrets_maladie: int
                - exonerations: float (total des exonerations obtenues)
        """
        existing = self.donnees_annuelles.get(annee, {})
        existing.update(donnees)
        existing["annee"] = annee
        self.donnees_annuelles[annee] = existing

    def alimenter_depuis_knowledge(self, knowledge_base: dict):
        """Alimente les donnees depuis la base de connaissances NormaCheck.

        Extrait les periodes, masse salariale, effectifs depuis les bulletins,
        DSN et declarations importees.
        """
        # Periodes couvertes
        periodes = knowledge_base.get("periodes_couvertes", [])
        annees_couvertes = set()
        for per in periodes:
            try:
                annee = int(per.split("-")[0])
                annees_couvertes.add(annee)
            except (ValueError, IndexError):
                continue

        # Bulletins de paie
        bulletins = knowledge_base.get("bulletins_paie", [])
        for bp in bulletins:
            per = bp.get("periode", "")
            if not per:
                continue
            try:
                annee = int(per.split("-")[0])
            except (ValueError, IndexError):
                continue

            existing = self.donnees_annuelles.get(annee, {"annee": annee})
            existing["masse_salariale"] = existing.get("masse_salariale", 0) + bp.get("masse_salariale", 0)
            existing["nb_bulletins"] = existing.get("nb_bulletins", 0) + 1
            existing["nb_salaries_bulletins"] = existing.get("nb_salaries_bulletins", 0) + bp.get("nb_salaries", 0)
            existing["total_cotisations_patronales"] = (
                existing.get("total_cotisations_patronales", 0) + bp.get("total_patronal", 0)
            )
            existing["total_cotisations_salariales"] = (
                existing.get("total_cotisations_salariales", 0) + bp.get("total_salarial", 0)
            )
            self.donnees_annuelles[annee] = existing

        # DSN
        dsn_list = knowledge_base.get("declarations_dsn", [])
        for dsn in dsn_list:
            per = dsn.get("periode", "")
            if not per:
                continue
            try:
                annee = int(per.split("-")[0])
            except (ValueError, IndexError):
                continue

            existing = self.donnees_annuelles.get(annee, {"annee": annee})
            existing["nb_dsn"] = existing.get("nb_dsn", 0) + 1
            existing["masse_salariale_dsn"] = (
                existing.get("masse_salariale_dsn", 0) + dsn.get("masse_salariale", 0)
            )
            existing["nb_salaries_dsn"] = max(
                existing.get("nb_salaries_dsn", 0), dsn.get("nb_salaries", 0)
            )
            self.donnees_annuelles[annee] = existing

        # Effectifs par periode
        effectifs = knowledge_base.get("effectifs", {})
        for per, eff in effectifs.items():
            try:
                annee = int(per.split("-")[0])
            except (ValueError, IndexError):
                continue
            existing = self.donnees_annuelles.get(annee, {"annee": annee})
            existing["effectif_moyen"] = max(existing.get("effectif_moyen", 0), eff)
            self.donnees_annuelles[annee] = existing

        # S assurer que toutes les annees couvertes existent
        for annee in annees_couvertes:
            if annee not in self.donnees_annuelles:
                self.donnees_annuelles[annee] = {"annee": annee}

    def analyser(self) -> dict:
        """Execute l analyse multi-annuelle complete.

        Retourne un rapport avec :
        - Couverture temporelle
        - Tendances
        - Anomalies inter-annuelles
        - Recommandations
        """
        if not self.donnees_annuelles:
            return {
                "couverture": {"annees": [], "complete": False},
                "tendances": [],
                "anomalies": [],
                "recommandations": ["Importez des documents de plusieurs annees pour une analyse multi-annuelle."],
            }

        annees = sorted(self.donnees_annuelles.keys())
        annee_courante = datetime.now().year
        couverture = self._analyser_couverture(annees, annee_courante)
        tendances = self._analyser_tendances(annees)
        anomalies = self._detecter_anomalies(annees)
        recommandations = self._generer_recommandations(couverture, tendances, anomalies, annee_courante)

        return {
            "couverture": couverture,
            "donnees_par_annee": {a: self.donnees_annuelles[a] for a in annees},
            "tendances": tendances,
            "anomalies": anomalies,
            "recommandations": recommandations,
        }

    def _analyser_couverture(self, annees: list[int], annee_courante: int) -> dict:
        """Analyse la couverture temporelle."""
        annee_min = min(annees)
        annee_max = max(annees)

        # Prescription travail dissimule : 5 ans
        annees_requises_td = list(range(annee_courante - 5, annee_courante + 1))
        # Prescription cotisations : 3 ans
        annees_requises_cot = list(range(annee_courante - 3, annee_courante + 1))
        # Prescription salaires : 3 ans
        annees_requises_sal = list(range(annee_courante - 3, annee_courante + 1))

        couvertes_td = [a for a in annees_requises_td if a in annees]
        couvertes_cot = [a for a in annees_requises_cot if a in annees]
        manquantes_td = [a for a in annees_requises_td if a not in annees]
        manquantes_cot = [a for a in annees_requises_cot if a not in annees]

        return {
            "annees_importees": annees,
            "annee_min": annee_min,
            "annee_max": annee_max,
            "etendue": annee_max - annee_min + 1,
            "prescription_travail_dissimule": {
                "annees_requises": annees_requises_td,
                "annees_couvertes": couvertes_td,
                "annees_manquantes": manquantes_td,
                "couverture_pct": round(len(couvertes_td) / len(annees_requises_td) * 100, 1),
                "ref": "CT art. L.8224-1 (5 ans)",
            },
            "prescription_cotisations": {
                "annees_requises": annees_requises_cot,
                "annees_couvertes": couvertes_cot,
                "annees_manquantes": manquantes_cot,
                "couverture_pct": round(len(couvertes_cot) / len(annees_requises_cot) * 100, 1),
                "ref": "CSS art. L.244-3 (3 ans)",
            },
            "complete_5_ans": len(manquantes_td) == 0,
            "complete_3_ans": len(manquantes_cot) == 0,
        }

    def _analyser_tendances(self, annees: list[int]) -> list[dict]:
        """Detecte les tendances inter-annuelles."""
        tendances = []
        if len(annees) < 2:
            return tendances

        # Tendance masse salariale
        masses = [(a, self.donnees_annuelles[a].get("masse_salariale", 0)) for a in annees
                   if self.donnees_annuelles[a].get("masse_salariale", 0) > 0]
        if len(masses) >= 2:
            premiere = masses[0][1]
            derniere = masses[-1][1]
            nb_annees = masses[-1][0] - masses[0][0]
            if nb_annees > 0 and premiere > 0:
                variation_totale = (derniere - premiere) / premiere * 100
                variation_annuelle = variation_totale / nb_annees
                tendances.append({
                    "indicateur": "masse_salariale",
                    "variation_totale_pct": round(variation_totale, 1),
                    "variation_annuelle_moyenne_pct": round(variation_annuelle, 1),
                    "premiere_annee": masses[0][0],
                    "derniere_annee": masses[-1][0],
                    "premiere_valeur": premiere,
                    "derniere_valeur": derniere,
                    "tendance": "hausse" if variation_annuelle > 2 else ("baisse" if variation_annuelle < -2 else "stable"),
                })

        # Tendance effectif
        effectifs = [(a, self.donnees_annuelles[a].get("effectif_moyen", 0)) for a in annees
                      if self.donnees_annuelles[a].get("effectif_moyen", 0) > 0]
        if len(effectifs) >= 2:
            premier = effectifs[0][1]
            dernier = effectifs[-1][1]
            nb_annees = effectifs[-1][0] - effectifs[0][0]
            if nb_annees > 0 and premier > 0:
                variation = (dernier - premier) / premier * 100
                tendances.append({
                    "indicateur": "effectif",
                    "variation_totale_pct": round(variation, 1),
                    "variation_annuelle_moyenne_pct": round(variation / nb_annees, 1),
                    "premiere_annee": effectifs[0][0],
                    "derniere_annee": effectifs[-1][0],
                    "premiere_valeur": premier,
                    "derniere_valeur": dernier,
                    "tendance": "hausse" if variation > 10 else ("baisse" if variation < -10 else "stable"),
                })

        # Tendance taux de charges
        taux_charges = []
        for a in annees:
            d = self.donnees_annuelles[a]
            masse = d.get("masse_salariale", 0)
            pat = d.get("total_cotisations_patronales", 0)
            if masse > 0 and pat > 0:
                taux_charges.append((a, round(pat / masse * 100, 2)))
        if len(taux_charges) >= 2:
            tendances.append({
                "indicateur": "taux_charges_patronales",
                "premiere_annee": taux_charges[0][0],
                "derniere_annee": taux_charges[-1][0],
                "premiere_valeur_pct": taux_charges[0][1],
                "derniere_valeur_pct": taux_charges[-1][1],
                "variation_points": round(taux_charges[-1][1] - taux_charges[0][1], 2),
                "tendance": "hausse" if taux_charges[-1][1] > taux_charges[0][1] + 1 else (
                    "baisse" if taux_charges[-1][1] < taux_charges[0][1] - 1 else "stable"
                ),
            })

        return tendances

    def _detecter_anomalies(self, annees: list[int]) -> list[dict]:
        """Detecte les anomalies inter-annuelles."""
        anomalies = []
        if len(annees) < 2:
            return anomalies

        for i in range(1, len(annees)):
            annee_prec = annees[i - 1]
            annee_curr = annees[i]
            d_prec = self.donnees_annuelles[annee_prec]
            d_curr = self.donnees_annuelles[annee_curr]

            # 1. Chute brutale de masse salariale (> 30%)
            m_prec = d_prec.get("masse_salariale", 0)
            m_curr = d_curr.get("masse_salariale", 0)
            if m_prec > 0 and m_curr > 0:
                variation = (m_curr - m_prec) / m_prec * 100
                if variation < -30:
                    anomalies.append({
                        "type": "chute_masse_salariale",
                        "gravite": "majeur",
                        "annees": [annee_prec, annee_curr],
                        "description": f"Chute de {abs(variation):.0f}% de la masse salariale entre {annee_prec} et {annee_curr}",
                        "valeurs": {"avant": m_prec, "apres": m_curr},
                        "indicateur_potentiel": "Restructuration, PSE, ou risque de travail dissimule",
                        "ref": "CT art. L.8224-1",
                    })
                elif variation > 50:
                    anomalies.append({
                        "type": "hausse_masse_salariale",
                        "gravite": "alerte",
                        "annees": [annee_prec, annee_curr],
                        "description": f"Hausse de {variation:.0f}% de la masse salariale entre {annee_prec} et {annee_curr}",
                        "valeurs": {"avant": m_prec, "apres": m_curr},
                        "indicateur_potentiel": "Croissance rapide, integration d une filiale, ou regularisation",
                    })

            # 2. Chute brutale d effectif (> 20%)
            e_prec = d_prec.get("effectif_moyen", 0)
            e_curr = d_curr.get("effectif_moyen", 0)
            if e_prec > 0 and e_curr > 0:
                variation_eff = (e_curr - e_prec) / e_prec * 100
                if variation_eff < -20:
                    anomalies.append({
                        "type": "chute_effectif",
                        "gravite": "important",
                        "annees": [annee_prec, annee_curr],
                        "description": f"Reduction de {abs(variation_eff):.0f}% de l effectif entre {annee_prec} et {annee_curr}",
                        "valeurs": {"avant": e_prec, "apres": e_curr},
                        "indicateur_potentiel": "PSE, licenciements economiques, ou externalisation",
                    })

            # 3. Incoherence masse / effectif
            if m_curr > 0 and e_curr > 0 and m_prec > 0 and e_prec > 0:
                sal_moyen_prec = m_prec / e_prec
                sal_moyen_curr = m_curr / e_curr
                if sal_moyen_prec > 0:
                    variation_sal = (sal_moyen_curr - sal_moyen_prec) / sal_moyen_prec * 100
                    if variation_sal < -15:
                        anomalies.append({
                            "type": "baisse_salaire_moyen",
                            "gravite": "alerte",
                            "annees": [annee_prec, annee_curr],
                            "description": f"Baisse de {abs(variation_sal):.0f}% du salaire moyen entre {annee_prec} et {annee_curr}",
                            "valeurs": {"avant": round(sal_moyen_prec, 0), "apres": round(sal_moyen_curr, 0)},
                            "indicateur_potentiel": "Changement de structure salariale, temps partiels, ou sous-declaration",
                        })

            # 4. Ecart croissant entre DSN et bulletins (si les deux existent)
            bp_curr = d_curr.get("nb_bulletins", 0)
            dsn_curr = d_curr.get("nb_dsn", 0)
            if bp_curr > 0 and dsn_curr > 0:
                masse_bp = d_curr.get("masse_salariale", 0)
                masse_dsn = d_curr.get("masse_salariale_dsn", 0)
                if masse_bp > 0 and masse_dsn > 0:
                    ecart_pct = abs(masse_bp - masse_dsn) / max(masse_bp, masse_dsn) * 100
                    if ecart_pct > 5:
                        anomalies.append({
                            "type": "ecart_dsn_bulletins",
                            "gravite": "important" if ecart_pct > 10 else "alerte",
                            "annees": [annee_curr],
                            "description": f"Ecart de {ecart_pct:.1f}% entre masse salariale DSN et bulletins en {annee_curr}",
                            "valeurs": {"masse_bulletins": masse_bp, "masse_dsn": masse_dsn},
                            "indicateur_potentiel": "Erreurs de saisie DSN, bulletins manquants, ou regularisations en cours",
                        })

        return anomalies

    def _generer_recommandations(
        self, couverture: dict, tendances: list, anomalies: list, annee_courante: int,
    ) -> list[str]:
        """Genere des recommandations basees sur l analyse."""
        reco = []

        # Couverture
        if not couverture["complete_5_ans"]:
            manquantes = couverture["prescription_travail_dissimule"]["annees_manquantes"]
            reco.append(
                f"Importez les documents des annees manquantes ({', '.join(str(a) for a in manquantes)}) "
                f"pour couvrir la prescription de 5 ans (travail dissimule, CT art. L.8224-1)."
            )
        if not couverture["complete_3_ans"]:
            manquantes = couverture["prescription_cotisations"]["annees_manquantes"]
            reco.append(
                f"Importez les documents des annees manquantes ({', '.join(str(a) for a in manquantes)}) "
                f"pour couvrir la prescription de 3 ans (cotisations, CSS art. L.244-3)."
            )

        # Anomalies critiques
        anomalies_critiques = [a for a in anomalies if a.get("gravite") == "majeur"]
        if anomalies_critiques:
            reco.append(
                f"{len(anomalies_critiques)} anomalie(s) majeure(s) detectee(s). "
                "Verifiez en priorite les variations de masse salariale et d effectif."
            )

        # Tendance effectif
        for t in tendances:
            if t["indicateur"] == "effectif" and t["tendance"] == "hausse":
                val = t["derniere_valeur"]
                for seuil, label in [(11, "CSE"), (20, "PEEC"), (50, "FNAL deplafonne"), (250, "CSA apprentissage")]:
                    prec = t["premiere_valeur"]
                    if prec < seuil <= val:
                        reco.append(
                            f"Passage du seuil de {seuil} salaries entre {t['premiere_annee']} et {t['derniere_annee']}. "
                            f"Verifiez les obligations liees : {label}."
                        )

        if not reco:
            reco.append("Aucune anomalie majeure detectee sur la periode analysee.")

        return reco
