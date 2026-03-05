"""Client pour l'API Legifrance (DILA/PISTE).

Permet de :
- Rechercher des textes legislatifs par mots-cles et date
- Consulter les articles du Code de la Securite Sociale
- Recuperer les modifications recentes impactant les cotisations
- Detecter les changements de legislation par annee

API Documentation : https://api.gouv.fr/les-api/DILA_api_Legifrance
Production : https://api.piste.gouv.fr/dila/legifrance/lf-engine-app
Auth : OAuth 2.0 via https://oauth.piste.gouv.fr/api/oauth/token
"""

import json
import logging
import time
from datetime import datetime, date
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

logger = logging.getLogger("urssaf_analyzer.veille.legifrance")

# Endpoints PISTE
TOKEN_URL = "https://oauth.piste.gouv.fr/api/oauth/token"
API_BASE = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app"

# Sandbox (pour tests sans credentials)
SANDBOX_TOKEN_URL = "https://sandbox-oauth.aife.economie.gouv.fr/api/oauth/token"
SANDBOX_API_BASE = "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app"

# Codes pertinents pour l'URSSAF
CODES_URSSAF = [
    "LEGITEXT000006073189",  # Code de la Securite Sociale (CSS)
    "LEGITEXT000006069577",  # Code General des Impots (CGI)
    "LEGITEXT000006072050",  # Code du Travail
]

# Mots-cles de veille URSSAF
MOTS_CLES_VEILLE = [
    "cotisations sociales",
    "URSSAF",
    "plafond securite sociale",
    "CSG CRDS",
    "reduction generale",
    "allégements cotisations",
    "travail dissimule",
    "declaration sociale nominative",
    "DSN",
    "assiette cotisations",
    "taux cotisation",
    "ACRE",
    "auto-entrepreneur cotisations",
    "exoneration cotisations",
]


class LegifranceClient:
    """Client pour interroger l'API Legifrance via PISTE."""

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        sandbox: bool = True,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.sandbox = sandbox
        self._token: Optional[str] = None
        self._token_expiry: float = 0

        if sandbox:
            self.token_url = SANDBOX_TOKEN_URL
            self.api_base = SANDBOX_API_BASE
        else:
            self.token_url = TOKEN_URL
            self.api_base = API_BASE

    def _get_token(self) -> Optional[str]:
        """Obtient un token OAuth2 via client_credentials."""
        if self._token and time.time() < self._token_expiry:
            return self._token

        if not self.client_id or not self.client_secret:
            logger.warning(
                "Credentials Legifrance non configurees. "
                "Mode hors-ligne avec donnees pre-chargees."
            )
            return None

        data = urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "openid",
        }).encode("utf-8")

        req = Request(self.token_url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                self._token = result["access_token"]
                self._token_expiry = time.time() + result.get("expires_in", 3600) - 60
                return self._token
        except (URLError, HTTPError, KeyError) as e:
            logger.error("Echec obtention token Legifrance: %s", e)
            return None

    def _api_request(self, endpoint: str, payload: dict) -> Optional[dict]:
        """Effectue une requete POST a l'API Legifrance."""
        token = self._get_token()
        if not token:
            return None

        url = f"{self.api_base}/{endpoint}"
        data = json.dumps(payload).encode("utf-8")

        req = Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")

        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.error("API Legifrance %s : %s - %s", endpoint, e.code, body[:200])
            return None
        except URLError as e:
            logger.error("Erreur reseau Legifrance: %s", e)
            return None

    def rechercher_textes(
        self,
        mots_cles: str,
        date_debut: Optional[date] = None,
        date_fin: Optional[date] = None,
        nb_resultats: int = 10,
    ) -> list[dict]:
        """Recherche des textes legislatifs par mots-cles."""
        payload = {
            "recherche": {
                "champs": [
                    {"typeChamp": "ALL", "criteres": [
                        {"typeRecherche": "EXACTE", "valeur": mots_cles, "operateur": "ET"}
                    ]}
                ],
                "filtres": [
                    {"facette": "NOM_CODE", "valeurs": [
                        "Code de la sécurité sociale",
                        "Code du travail",
                        "Code général des impôts",
                    ]}
                ],
                "pageNumber": 1,
                "pageSize": nb_resultats,
                "sort": "PERTINENCE",
                "typePagination": "DEFAUT",
            },
            "fond": "CODE_DATE",
        }

        if date_debut:
            payload["recherche"]["filtres"].append({
                "facette": "DATE_VERSION",
                "dates": {
                    "start": date_debut.isoformat() + "T00:00:00.000",
                    "end": (date_fin or date.today()).isoformat() + "T23:59:59.999",
                },
            })

        result = self._api_request("search", payload)
        if not result:
            return []

        textes = []
        for item in result.get("results", []):
            textes.append({
                "titre": item.get("titles", {}).get("titreLong", ""),
                "reference": item.get("id", ""),
                "type": item.get("nature", ""),
                "date_publication": item.get("datePubli", ""),
                "url": f"https://www.legifrance.gouv.fr/codes/id/{item.get('id', '')}",
                "extrait": item.get("highlights", {}).get("titre", [""])[0],
            })
        return textes

    def consulter_article_css(self, id_article: str) -> Optional[dict]:
        """Consulte un article du Code de la Securite Sociale."""
        payload = {"id": id_article}
        result = self._api_request("consult/getArticle", payload)
        if not result:
            return None
        article = result.get("article", {})
        return {
            "id": article.get("id", ""),
            "numero": article.get("num", ""),
            "titre": article.get("intOrdre", ""),
            "texte": article.get("texte", ""),
            "date_debut": article.get("dateDebut", ""),
            "date_fin": article.get("dateFin", ""),
            "etat": article.get("etat", ""),
        }

    def lister_modifications_code(
        self, code_id: str = "LEGITEXT000006073189", date_depuis: Optional[date] = None
    ) -> list[dict]:
        """Liste les modifications recentes d'un code."""
        payload = {
            "textId": code_id,
            "date": (date_depuis or date.today()).strftime("%Y-%m-%d"),
        }
        result = self._api_request("consult/code/tableMatieres", payload)
        if not result:
            return []

        modifications = []
        sections = result.get("sections", [])
        self._extraire_articles_modifies(sections, modifications, date_depuis)
        return modifications

    def _extraire_articles_modifies(
        self, sections: list, modifications: list, date_depuis: Optional[date]
    ):
        """Parcourt recursivement les sections pour trouver les articles modifies."""
        for section in sections:
            articles = section.get("articles", [])
            for art in articles:
                date_debut = art.get("dateDebut")
                if date_debut and date_depuis:
                    try:
                        dt = datetime.fromisoformat(date_debut.replace("Z", "")).date()
                        if dt >= date_depuis:
                            modifications.append({
                                "id": art.get("id", ""),
                                "numero": art.get("num", ""),
                                "titre": section.get("titre", ""),
                                "date_debut": date_debut,
                                "etat": art.get("etat", ""),
                            })
                    except ValueError:
                        pass
            # Recurser dans les sous-sections
            sous_sections = section.get("sections", [])
            if sous_sections:
                self._extraire_articles_modifies(sous_sections, modifications, date_depuis)

    def veille_mensuelle(self, annee: int, mois: int) -> list[dict]:
        """Execute une veille mensuelle sur les textes relatifs aux cotisations."""
        import calendar
        date_debut = date(annee, mois, 1)
        dernier_jour = calendar.monthrange(annee, mois)[1]
        date_fin = date(annee, mois, dernier_jour)

        resultats = []
        for mot_cle in MOTS_CLES_VEILLE[:5]:  # Limiter les appels API
            textes = self.rechercher_textes(
                mot_cle, date_debut=date_debut, date_fin=date_fin, nb_resultats=5
            )
            for t in textes:
                t["mot_cle_veille"] = mot_cle
                if t not in resultats:
                    resultats.append(t)

        return resultats


# --- Donnees pre-chargees (mode hors-ligne) ---

ARTICLES_CSS_COTISATIONS = {
    2020: {
        "description": "Legislation cotisations sociales 2020 - Reforme assurance chomage et Covid-19",
        "textes_cles": [
            {
                "reference": "Art. L241-13 CSS",
                "titre": "Reduction generale des cotisations patronales (Fillon)",
                "resume": "Extension aux cotisations de retraite complementaire depuis le 1er janvier 2019. Parametre T = 0.3205 (< 50 sal.) ou 0.3245 (>= 50 sal.).",
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000041469040",
            },
            {
                "reference": "Ordonnance 2020-312",
                "titre": "Mesures d'urgence Covid-19 - Report de cotisations",
                "resume": "Report des echeances URSSAF pour les employeurs impactes par la crise sanitaire.",
                "url": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000041746313",
            },
            {
                "reference": "Decret 2019-797 (modifie)",
                "titre": "Reforme de l'assurance chomage - Bonus-malus",
                "resume": "Introduction du bonus-malus sur les cotisations chomage pour les entreprises de 11 salaries et plus dans certains secteurs.",
                "url": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000038829574",
            },
        ],
    },
    2021: {
        "description": "Legislation cotisations sociales 2021 - Aides embauche et prolongation mesures Covid",
        "textes_cles": [
            {
                "reference": "Decret 2021-94",
                "titre": "Aide a l'embauche des jeunes de moins de 26 ans",
                "resume": "Aide de 4 000 EUR pour l'embauche d'un jeune de moins de 26 ans en CDI ou CDD de plus de 3 mois, remunere jusqu'a 2 SMIC.",
                "url": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000043034903",
            },
            {
                "reference": "Art. L6243-2 CT (modifie)",
                "titre": "Aide exceptionnelle aux employeurs d'apprentis",
                "resume": "Aide unique de 5 000 EUR (mineur) ou 8 000 EUR (majeur) pour la 1ere annee du contrat d'apprentissage.",
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000037385842",
            },
            {
                "reference": "LFSS 2021 art. 9",
                "titre": "Prolongation des exonerations Covid",
                "resume": "Prolongation des dispositifs d'exoneration et d'aide au paiement des cotisations pour les secteurs proteges (S1/S1bis).",
                "url": "https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000042665307",
            },
        ],
    },
    2022: {
        "description": "Legislation cotisations sociales 2022 - Hausse SMIC et mesures pouvoir d'achat",
        "textes_cles": [
            {
                "reference": "Decret 2022-1608",
                "titre": "PASS 2022 et SMIC - revalorisations successives",
                "resume": "SMIC revalorise 3 fois en 2022 (janv., mai, aout) en raison de l'inflation. PASS inchange a 41 136 EUR.",
                "url": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000046771180",
            },
            {
                "reference": "Loi 2022-1158 art. 1",
                "titre": "Loi pouvoir d'achat - PPV (Prime de Partage de la Valeur)",
                "resume": "Remplacement de la PEPA par la PPV. Exoneration de cotisations et d'impot sous conditions (plafond 3 000 EUR ou 6 000 EUR).",
                "url": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000046186723",
            },
            {
                "reference": "Art. L241-17 CSS",
                "titre": "Exoneration heures supplementaires (TEPA)",
                "resume": "Reduction de cotisations salariales sur les heures supplementaires (11,31%) et exoneration IR dans la limite de 7 500 EUR/an.",
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000037949929",
            },
        ],
    },
    2023: {
        "description": "Legislation cotisations sociales 2023 - Hausse PASS et reforme retraites",
        "textes_cles": [
            {
                "reference": "Decret 2022-1608",
                "titre": "PASS 2023 - Revalorisation historique (+6.9%)",
                "resume": "PASS annuel porte a 43 992 EUR (mensuel 3 666 EUR). Plus forte hausse depuis 20 ans, impact direct sur les cotisations plafonnees.",
                "url": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000046771180",
            },
            {
                "reference": "Loi 2023-270",
                "titre": "Reforme des retraites - Report age legal",
                "resume": "Age legal de depart progressivement porte a 64 ans. Acceleration du calendrier Touraine (43 annuites). Impact sur les cotisations vieillesse.",
                "url": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000047466357",
            },
            {
                "reference": "LFSS 2023 art. 10",
                "titre": "Aide unique apprentissage 6 000 EUR",
                "resume": "Aide unique de 6 000 EUR pour tout contrat d'apprentissage, quel que soit l'age de l'apprenti et le niveau du diplome (prolongee en 2024).",
                "url": "https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000046796753",
            },
        ],
    },
    2024: {
        "description": "Legislation cotisations sociales 2024",
        "textes_cles": [
            {
                "reference": "Art. L241-1 CSS",
                "titre": "Cotisations d'assurance maladie",
                "resume": "Base et taux des cotisations maladie",
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000038834122",
            },
            {
                "reference": "Art. L241-6 CSS",
                "titre": "Cotisations allocations familiales",
                "resume": "Base et taux des cotisations AF",
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000038834098",
            },
            {
                "reference": "Art. L241-13 CSS",
                "titre": "Reduction generale des cotisations patronales",
                "resume": "Mecanisme de la reduction Fillon avant RGDU",
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000041469040",
            },
        ],
    },
    2025: {
        "description": "Legislation cotisations sociales 2025 - Reforme assiette independants",
        "textes_cles": [
            {
                "reference": "Art. L131-6 CSS (modifie)",
                "titre": "Nouvelle assiette sociale des travailleurs independants",
                "resume": "Reforme de l'assiette de calcul - application retroactive en 2026",
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006740102",
            },
            {
                "reference": "Art. L613-7 CSS",
                "titre": "Cotisations micro-entrepreneurs",
                "resume": "Evolution des taux pour les auto-entrepreneurs",
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000037948893",
            },
        ],
    },
    2026: {
        "description": "Legislation cotisations sociales 2026 - RGDU et nouveaux taux",
        "textes_cles": [
            {
                "reference": "Art. L241-13 CSS (refonte)",
                "titre": "Reduction Generale Degressive Unique (RGDU)",
                "resume": (
                    "Fusion RGD + reductions maladie/AF en une reduction unique. "
                    "Seuil porte a 3 SMIC. Application au 01/01/2026."
                ),
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000041469040",
            },
            {
                "reference": "Art. L241-3 CSS",
                "titre": "Cotisation vieillesse deplafonnee - hausse taux patronal",
                "resume": "Taux patronal passe de 2.02% a 2.11% au 01/01/2026",
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006742050",
            },
            {
                "reference": "Art. D242-2-1 CSS",
                "titre": "Taux moyen AT/MP abaisse",
                "resume": "Taux moyen national AT/MP de 2.12% a 2.08% en 2026",
                "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006736111",
            },
            {
                "reference": "Decret n° 2025-XXX",
                "titre": "PASS 2026 - Plafond Annuel Securite Sociale",
                "resume": "PASS annuel fixe a 48 060 EUR, mensuel 4 005 EUR",
                "url": "https://www.urssaf.fr/accueil/actualites/baremes-smic-plafonds-an-fp.html",
            },
            {
                "reference": "Decret n° 2025-XXX",
                "titre": "SMIC 2026",
                "resume": "SMIC horaire brut a 12.02 EUR, mensuel 1 823.03 EUR",
                "url": "https://www.urssaf.fr/accueil/actualites/baremes-smic-plafonds-an-fp.html",
            },
            {
                "reference": "Art. L161-1-1 CSS (modifie)",
                "titre": "Prelevement a la source par les plateformes",
                "resume": (
                    "Debut avril 2026 pour 8 plateformes volontaires. "
                    "Generalisation obligatoire prevue au 01/01/2027."
                ),
                "url": "https://www.urssaf.fr/en/accueil/actualites/ae-prelevement-source-plateforme.html",
            },
            {
                "reference": "Art. L131-6-4 CSS (modifie)",
                "titre": "Reforme ACRE - reduction a 25%",
                "resume": (
                    "Reduction ACRE limitee a 25% pour les micro-entreprises "
                    "creees a partir du 01/07/2026."
                ),
                "url": "https://www.jaimelapaperasse.com/reforme-acre-2026-autoentrepreneur/",
            },
            {
                "reference": "Art. R243-14 CSS",
                "titre": "DSN de substitution",
                "resume": (
                    "A partir de mars 2026, l'URSSAF peut corriger "
                    "directement les erreurs DSN non rectifiees."
                ),
                "url": "https://formation.lefebvre-dalloz.fr/actualite/dsn-2026-les-dernieres-evolutions",
            },
        ],
    },
}


def get_legislation_par_annee(annee: int) -> dict:
    """Retourne la legislation applicable pour une annee donnee."""
    if annee in ARTICLES_CSS_COTISATIONS:
        return ARTICLES_CSS_COTISATIONS[annee]
    # Annee non repertoriee : retourner la plus recente connue
    annees_connues = sorted(ARTICLES_CSS_COTISATIONS.keys())
    for a in reversed(annees_connues):
        if a <= annee:
            return ARTICLES_CSS_COTISATIONS[a]
    return ARTICLES_CSS_COTISATIONS[annees_connues[-1]]
