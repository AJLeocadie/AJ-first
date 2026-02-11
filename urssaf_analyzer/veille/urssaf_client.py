"""Client pour l'API Open Data URSSAF.

Interroge le portail open.urssaf.fr pour :
- Recuperer les taux de cotisations a jour
- Suivre les baremes et plafonds
- Consulter les donnees de versement mobilite
- Alimenter les alertes de veille

API : https://open.urssaf.fr/api/explore/v2.1/
Documentation : https://api.gouv.fr/les-api/api-open-data-urssaf
"""

import json
import logging
from datetime import date, datetime
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

logger = logging.getLogger("urssaf_analyzer.veille.urssaf")

# Endpoint principal
API_BASE = "https://open.urssaf.fr/api/explore/v2.1"

# Jeux de donnees connus
DATASETS = {
    "versement_mobilite": "taux-de-versement-mobilite",
    "exonerations": "exos-secteur-prive-tranche-ent",
    "effectifs_salaries": "effectifs-salaries",
    "masse_salariale": "masse-salariale",
    "auto_entrepreneurs": "auto-entrepreneurs-par-activite",
    "taux_impayes": "taux-d-impayes",
}

# Pages URSSAF.fr pour les baremes (scraping structure, pas API)
PAGES_BAREMES = {
    "secteur_prive": "https://www.urssaf.fr/accueil/outils-documentation/taux-baremes/taux-cotisations-secteur-prive.html",
    "secteur_public": "https://www.urssaf.fr/accueil/outils-documentation/taux-baremes/taux-cotisations-secteur-public.html",
    "baremes_2026": "https://www.urssaf.fr/accueil/actualites/baremes-smic-plafonds-an-fp.html",
    "nouveautes_2026": "https://www.urssaf.fr/accueil/actualites/informations-nouvelle-annee.html",
}


class URSSAFOpenDataClient:
    """Client pour interroger l'API Open Data URSSAF."""

    def __init__(self):
        self.api_base = API_BASE

    def _get(self, dataset: str, params: dict = None) -> Optional[dict]:
        """Effectue une requete GET sur l'API."""
        url = f"{self.api_base}/catalog/datasets/{dataset}/records"
        if params:
            url += "?" + urlencode(params)

        req = Request(url)
        req.add_header("Accept", "application/json")

        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            logger.error("API URSSAF %s : %s", dataset, e.code)
            return None
        except URLError as e:
            logger.error("Erreur reseau URSSAF: %s", e)
            return None

    def get_taux_versement_mobilite(
        self, code_commune: str = None, limit: int = 20
    ) -> list[dict]:
        """Recupere les taux de versement mobilite."""
        params = {"limit": str(limit), "order_by": "date_effet DESC"}
        if code_commune:
            params["where"] = f'code_commune="{code_commune}"'

        result = self._get(DATASETS["versement_mobilite"], params)
        if not result:
            return []

        return [
            {
                "commune": r.get("record", {}).get("fields", {}).get("libelle_commune", ""),
                "code_commune": r.get("record", {}).get("fields", {}).get("code_commune", ""),
                "taux_vm": r.get("record", {}).get("fields", {}).get("taux_vm", 0),
                "taux_vma": r.get("record", {}).get("fields", {}).get("taux_vma", 0),
                "date_effet": r.get("record", {}).get("fields", {}).get("date_effet", ""),
            }
            for r in result.get("records", [])
        ]

    def get_exonerations(self, annee: int = None, limit: int = 50) -> list[dict]:
        """Recupere les donnees d'exonerations."""
        params = {"limit": str(limit)}
        if annee:
            params["where"] = f"annee={annee}"

        result = self._get(DATASETS["exonerations"], params)
        if not result:
            return []

        return [
            r.get("record", {}).get("fields", {})
            for r in result.get("records", [])
        ]

    def get_datasets_catalogue(self) -> list[dict]:
        """Liste les jeux de donnees disponibles."""
        url = f"{self.api_base}/catalog/datasets?limit=50"
        req = Request(url)
        req.add_header("Accept", "application/json")

        try:
            with urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                return [
                    {
                        "id": ds.get("dataset", {}).get("dataset_id", ""),
                        "titre": ds.get("dataset", {}).get("metas", {}).get("default", {}).get("title", ""),
                        "description": ds.get("dataset", {}).get("metas", {}).get("default", {}).get("description", "")[:200],
                    }
                    for ds in result.get("datasets", [])
                ]
        except (URLError, HTTPError) as e:
            logger.error("Erreur catalogue URSSAF: %s", e)
            return []


# --- Baremes pre-charges par annee ---

BAREMES_PAR_ANNEE = {
    2024: {
        # Plafonds
        "pass_annuel": 46368.00,
        "pass_mensuel": 3864.00,
        "smic_horaire": 11.65,
        "smic_mensuel": 1766.92,
        # Cotisations SS
        "taux_maladie_patronal": 0.13,
        "taux_maladie_patronal_reduit": 0.07,
        "seuil_maladie_reduit_smic": 2.5,
        "taux_vieillesse_plafonnee_patronal": 0.0855,
        "taux_vieillesse_plafonnee_salarial": 0.069,
        "taux_vieillesse_deplafonnee_patronal": 0.0202,
        "taux_vieillesse_deplafonnee_salarial": 0.004,
        "taux_af_patronal": 0.0525,
        "taux_af_patronal_reduit": 0.0325,
        "taux_at_moyen": 0.0212,
        # CSG/CRDS
        "taux_csg_deductible": 0.068,
        "taux_csg_non_deductible": 0.024,
        "taux_crds": 0.005,
        "assiette_csg_crds_pct": 0.9825,
        # URSSAF contributions
        "taux_fnal_moins_50": 0.001,
        "taux_fnal_50_plus": 0.005,
        "taux_csa": 0.003,
        "taux_dialogue_social": 0.00016,
        # Chomage
        "taux_chomage_patronal": 0.0405,
        "taux_ags": 0.0015,
        # Retraite AGIRC-ARRCO
        "taux_rc_t1_patronal": 0.0472,
        "taux_rc_t1_salarial": 0.0315,
        "taux_rc_t2_patronal": 0.1229,
        "taux_rc_t2_salarial": 0.0864,
        "taux_ceg_t1_patronal": 0.0129,
        "taux_ceg_t1_salarial": 0.0086,
        "taux_ceg_t2_patronal": 0.0162,
        "taux_ceg_t2_salarial": 0.0108,
        "taux_cet_patronal": 0.0021,
        "taux_cet_salarial": 0.0014,
        "taux_apec_patronal": 0.000036,
        "taux_apec_salarial": 0.000024,
        # Formation / Apprentissage
        "taux_formation_moins_11": 0.0055,
        "taux_formation_11_plus": 0.01,
        "taux_taxe_apprentissage": 0.0068,
        "taux_cpf_cdd": 0.01,
        # Construction
        "taux_peec": 0.0045,
        # Prevoyance cadre
        "taux_prevoyance_cadre_min": 0.015,
        # Reduction
        "seuil_rgd_smic": 1.6,
    },
    2025: {
        # Plafonds
        "pass_annuel": 47100.00,
        "pass_mensuel": 3925.00,
        "smic_horaire": 11.88,
        "smic_mensuel": 1801.80,
        # Cotisations SS
        "taux_maladie_patronal": 0.13,
        "taux_maladie_patronal_reduit": 0.07,
        "seuil_maladie_reduit_smic": 2.5,
        "taux_vieillesse_plafonnee_patronal": 0.0855,
        "taux_vieillesse_plafonnee_salarial": 0.069,
        "taux_vieillesse_deplafonnee_patronal": 0.0202,
        "taux_vieillesse_deplafonnee_salarial": 0.004,
        "taux_af_patronal": 0.0525,
        "taux_af_patronal_reduit": 0.0325,
        "taux_at_moyen": 0.0212,
        # CSG/CRDS
        "taux_csg_deductible": 0.068,
        "taux_csg_non_deductible": 0.024,
        "taux_crds": 0.005,
        "assiette_csg_crds_pct": 0.9825,
        # URSSAF contributions
        "taux_fnal_moins_50": 0.001,
        "taux_fnal_50_plus": 0.005,
        "taux_csa": 0.003,
        "taux_dialogue_social": 0.00016,
        # Chomage
        "taux_chomage_patronal": 0.0405,
        "taux_ags": 0.0015,
        # Retraite AGIRC-ARRCO
        "taux_rc_t1_patronal": 0.0472,
        "taux_rc_t1_salarial": 0.0315,
        "taux_rc_t2_patronal": 0.1229,
        "taux_rc_t2_salarial": 0.0864,
        "taux_ceg_t1_patronal": 0.0129,
        "taux_ceg_t1_salarial": 0.0086,
        "taux_ceg_t2_patronal": 0.0162,
        "taux_ceg_t2_salarial": 0.0108,
        "taux_cet_patronal": 0.0021,
        "taux_cet_salarial": 0.0014,
        "taux_apec_patronal": 0.000036,
        "taux_apec_salarial": 0.000024,
        # Formation / Apprentissage
        "taux_formation_moins_11": 0.0055,
        "taux_formation_11_plus": 0.01,
        "taux_taxe_apprentissage": 0.0068,
        "taux_cpf_cdd": 0.01,
        # Construction
        "taux_peec": 0.0045,
        # Prevoyance
        "taux_prevoyance_cadre_min": 0.015,
        # Reduction
        "seuil_rgd_smic": 1.6,
    },
    2026: {
        # Plafonds
        "pass_annuel": 48060.00,
        "pass_mensuel": 4005.00,
        "pass_journalier": 185.00,
        "smic_horaire": 12.02,
        "smic_mensuel": 1823.03,
        # Cotisations SS
        "taux_maladie_patronal": 0.13,
        "taux_maladie_patronal_reduit": 0.07,
        "seuil_maladie_reduit_smic": 2.5,
        "taux_maladie_alsace_moselle_salarial": 0.013,
        "taux_vieillesse_plafonnee_patronal": 0.0855,
        "taux_vieillesse_plafonnee_salarial": 0.069,
        "taux_vieillesse_deplafonnee_patronal": 0.0211,
        "taux_vieillesse_deplafonnee_salarial": 0.024,
        "taux_af_patronal": 0.0525,
        "taux_af_patronal_reduit": 0.0325,
        "seuil_af_reduit_smic": 3.5,
        "taux_at_moyen": 0.0208,
        "taux_at_min": 0.009,
        "taux_at_max": 0.06,
        # CSG/CRDS
        "taux_csg_deductible": 0.068,
        "taux_csg_non_deductible": 0.024,
        "taux_crds": 0.005,
        "assiette_csg_crds_pct": 0.9825,
        # URSSAF contributions
        "taux_fnal_moins_50": 0.001,
        "taux_fnal_50_plus": 0.005,
        "taux_csa": 0.003,
        "taux_versement_mobilite_moyen": 0.0175,
        "taux_versement_mobilite_idf_max": 0.032,
        "taux_versement_mobilite_province_max": 0.02,
        "seuil_vm_effectif": 11,
        "taux_dialogue_social": 0.00016,
        # Chomage
        "taux_chomage_patronal": 0.0405,
        "taux_chomage_bonus_malus_min": 0.03,
        "taux_chomage_bonus_malus_max": 0.0505,
        "plafond_chomage_pass": 4,
        "taux_ags": 0.0015,
        "plafond_ags_pass": 4,
        # Retraite complementaire AGIRC-ARRCO
        "taux_rc_t1_patronal": 0.0472,
        "taux_rc_t1_salarial": 0.0315,
        "taux_rc_t1_total": 0.0787,
        "taux_rc_t2_patronal": 0.1229,
        "taux_rc_t2_salarial": 0.0864,
        "taux_rc_t2_total": 0.2159,
        "taux_ceg_t1_patronal": 0.0129,
        "taux_ceg_t1_salarial": 0.0086,
        "taux_ceg_t1_total": 0.0215,
        "taux_ceg_t2_patronal": 0.0162,
        "taux_ceg_t2_salarial": 0.0108,
        "taux_ceg_t2_total": 0.027,
        "taux_cet_patronal": 0.0021,
        "taux_cet_salarial": 0.0014,
        "taux_cet_total": 0.0035,
        "taux_apec_patronal": 0.000036,
        "taux_apec_salarial": 0.000024,
        "taux_apec_total": 0.00006,
        # Formation / Apprentissage
        "taux_formation_moins_11": 0.0055,
        "taux_formation_11_plus": 0.01,
        "taux_taxe_apprentissage": 0.0068,
        "taux_taxe_apprentissage_solde": 0.0009,
        "taux_cpf_cdd": 0.01,
        "taux_csa_apprentissage_250_plus": 0.0005,
        # Construction (PEEC / Action Logement)
        "taux_peec": 0.0045,
        "seuil_peec_effectif": 20,
        # Prevoyance
        "taux_prevoyance_cadre_min": 0.015,
        # Forfait social
        "taux_forfait_social": 0.20,
        "taux_forfait_social_prevoyance": 0.08,
        "taux_forfait_social_pereco": 0.16,
        "taux_forfait_social_pere": 0.10,
        # Taxe sur les salaires
        "taux_taxe_salaires_normal": 0.0425,
        "taux_taxe_salaires_majore_1": 0.085,
        "taux_taxe_salaires_majore_2": 0.136,
        "seuil_taxe_salaires_1": 8573,
        "seuil_taxe_salaires_2": 17114,
        # Reduction
        "seuil_rgdu_smic": 3.0,
        "rgdu_taux_max_moins_50": 0.3194,
        "rgdu_taux_max_50_plus": 0.3234,
        # ACRE
        "acre_reduction_pct": 0.25,
        "acre_date_application": "2026-07-01",
    },
}


def get_baremes_annee(annee: int) -> dict:
    """Retourne les baremes pour une annee donnee."""
    if annee in BAREMES_PAR_ANNEE:
        return BAREMES_PAR_ANNEE[annee]
    annees = sorted(BAREMES_PAR_ANNEE.keys())
    for a in reversed(annees):
        if a <= annee:
            return BAREMES_PAR_ANNEE[a]
    return BAREMES_PAR_ANNEE[annees[-1]]


def comparer_baremes(annee1: int, annee2: int) -> list[dict]:
    """Compare les baremes entre deux annees et retourne les differences."""
    b1 = get_baremes_annee(annee1)
    b2 = get_baremes_annee(annee2)

    differences = []
    all_keys = set(b1.keys()) | set(b2.keys())

    for key in sorted(all_keys):
        v1 = b1.get(key)
        v2 = b2.get(key)
        if v1 != v2:
            differences.append({
                "parametre": key,
                f"valeur_{annee1}": v1,
                f"valeur_{annee2}": v2,
                "evolution": _decrire_evolution(v1, v2),
            })

    return differences


def _decrire_evolution(v1, v2) -> str:
    if v1 is None:
        return "nouveau"
    if v2 is None:
        return "supprime"
    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
        if v2 > v1:
            pct = ((v2 - v1) / v1) * 100 if v1 != 0 else 0
            return f"hausse +{pct:.2f}%"
        elif v2 < v1:
            pct = ((v1 - v2) / v1) * 100 if v1 != 0 else 0
            return f"baisse -{pct:.2f}%"
        return "inchange"
    return "modifie"
