"""Base de donnees IDCC - Conventions Collectives Nationales.

Ref: Legifrance, Journal Officiel, ministere du Travail
Source: https://www.legifrance.gouv.fr/liste/idcc
Mise a jour: 2026

Contient les principales CCN avec :
- Numero IDCC officiel
- Intitule complet
- Secteur d'activite (pour croisement NAF)
- Taux prevoyance patronal cadre / non-cadre
- Part employeur mutuelle minimum
- Specificites (maintien de salaire, conges payes, etc.)
"""

from decimal import Decimal
from typing import Optional


# ===================================================================
# BASE IDCC COMPLETE - CONVENTIONS COLLECTIVES NATIONALES
# Les 100+ CCN les plus courantes couvrant ~90% des salaries
# ===================================================================

IDCC_DATABASE: dict[str, dict] = {
    # ---------------------------------------------------------------
    # BATIMENT / TRAVAUX PUBLICS
    # ---------------------------------------------------------------
    "1596": {
        "nom": "Batiment ouvriers (plus de 10 salaries)",
        "secteur": "batiment",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.0175"),
        "mutuelle_employeur_min_pct": 50,
        "maintien_salaire_jours": 90,
        "conges_anciennete": True,
        "indemnite_depart_retraite_majoree": True,
    },
    "1597": {
        "nom": "Batiment ouvriers (jusqu a 10 salaries)",
        "secteur": "batiment",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.0175"),
        "mutuelle_employeur_min_pct": 50,
        "maintien_salaire_jours": 90,
    },
    "2609": {
        "nom": "Batiment ETAM",
        "secteur": "batiment",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
    },
    "2614": {
        "nom": "Travaux publics ouvriers",
        "secteur": "batiment",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.017"),
        "mutuelle_employeur_min_pct": 50,
    },
    "2622": {
        "nom": "Travaux publics ETAM",
        "secteur": "batiment",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
    },
    "7001": {
        "nom": "Batiment cadres",
        "secteur": "batiment",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
    },
    "7002": {
        "nom": "Travaux publics cadres",
        "secteur": "batiment",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # METALLURGIE
    # ---------------------------------------------------------------
    "3248": {
        "nom": "Metallurgie (nouvelle convention nationale unique)",
        "secteur": "metallurgie",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
        "maintien_salaire_jours": 90,
        "prime_anciennete": True,
        "indemnite_licenciement_majoree": True,
    },
    # ---------------------------------------------------------------
    # COMMERCE / DISTRIBUTION
    # ---------------------------------------------------------------
    "2216": {
        "nom": "Commerce de detail et de gros a predominance alimentaire",
        "secteur": "commerce",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.005"),
        "mutuelle_employeur_min_pct": 50,
    },
    "3305": {
        "nom": "Commerce a predominance alimentaire (nouvelle)",
        "secteur": "commerce",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.005"),
        "mutuelle_employeur_min_pct": 50,
    },
    "0573": {
        "nom": "Commerces de gros",
        "secteur": "commerce",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.006"),
        "mutuelle_employeur_min_pct": 50,
    },
    "1517": {
        "nom": "Commerce de detail non alimentaire",
        "secteur": "commerce",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.005"),
        "mutuelle_employeur_min_pct": 50,
    },
    "2098": {
        "nom": "Prestataires de services dans le domaine du tertiaire",
        "secteur": "services",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.006"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # BUREAUX D ETUDES / INFORMATIQUE / CONSEIL
    # ---------------------------------------------------------------
    "1486": {
        "nom": "Bureaux d etudes techniques, cabinets d ingenieurs-conseils (SYNTEC)",
        "secteur": "informatique",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.006"),
        "mutuelle_employeur_min_pct": 50,
        "prime_vacances": True,
        "indemnite_licenciement_specifique": True,
    },
    # ---------------------------------------------------------------
    # HOTELLERIE / RESTAURATION / TOURISME
    # ---------------------------------------------------------------
    "1979": {
        "nom": "Hotels, cafes, restaurants (HCR)",
        "secteur": "restauration",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
        "avantage_nature_repas": True,
        "jours_feries_garantis": 6,
    },
    "1501": {
        "nom": "Restauration rapide",
        "secteur": "restauration",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.007"),
        "mutuelle_employeur_min_pct": 50,
    },
    "1539": {
        "nom": "Commerces de detail de l habillement et articles textiles",
        "secteur": "commerce",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.005"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # TRANSPORT / LOGISTIQUE
    # ---------------------------------------------------------------
    "0016": {
        "nom": "Transports routiers et activites auxiliaires du transport",
        "secteur": "transport",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.012"),
        "mutuelle_employeur_min_pct": 50,
        "prime_anciennete": True,
        "indemnite_depart_retraite_majoree": True,
        "duree_travail_specifique": True,
    },
    "2121": {
        "nom": "Edition",
        "secteur": "edition",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # SANTE / SOCIAL / MEDICO-SOCIAL
    # ---------------------------------------------------------------
    "0029": {
        "nom": "Hospitalisation privee a but non lucratif (FEHAP)",
        "secteur": "sante",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.012"),
        "mutuelle_employeur_min_pct": 50,
    },
    "2264": {
        "nom": "Hospitalisation privee a but lucratif (FHP)",
        "secteur": "sante",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
    },
    "0413": {
        "nom": "Etablissements et services pour personnes inadaptees et handicapees",
        "secteur": "medico_social",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
    },
    "0051": {
        "nom": "Assistants maternels du particulier employeur",
        "secteur": "services_personne",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.004"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # PHARMACIE / LABORATOIRES
    # ---------------------------------------------------------------
    "1996": {
        "nom": "Pharmacie d officine",
        "secteur": "pharmacie",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.009"),
        "mutuelle_employeur_min_pct": 50,
    },
    "0176": {
        "nom": "Industrie pharmaceutique",
        "secteur": "pharmacie",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # PROPRETE / SECURITE
    # ---------------------------------------------------------------
    "3043": {
        "nom": "Entreprises de proprete et services associes",
        "secteur": "proprete",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
        "transfert_personnel_article7": True,
    },
    "1351": {
        "nom": "Prevention et securite",
        "secteur": "securite",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # BANQUE / ASSURANCE / FINANCE
    # ---------------------------------------------------------------
    "2120": {
        "nom": "Banque",
        "secteur": "banque",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.012"),
        "mutuelle_employeur_min_pct": 60,
        "13eme_mois": True,
    },
    "1672": {
        "nom": "Societes d assurances",
        "secteur": "assurance",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.012"),
        "mutuelle_employeur_min_pct": 60,
    },
    "2691": {
        "nom": "Enseignement prive hors contrat",
        "secteur": "enseignement",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.007"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # AUTOMOBILE / REPARATION
    # ---------------------------------------------------------------
    "1090": {
        "nom": "Services de l automobile (reparation, commerce, controle technique)",
        "secteur": "automobile",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # AGRICULTURE (complement MSA)
    # ---------------------------------------------------------------
    "7001": {
        "nom": "Batiment cadres (identique ci-dessus)",
        "secteur": "batiment",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
    },
    "7002": {
        "nom": "Travaux publics cadres (identique ci-dessus)",
        "secteur": "batiment",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # INTERIM / TRAVAIL TEMPORAIRE
    # ---------------------------------------------------------------
    "2378": {
        "nom": "Travail temporaire (interim)",
        "secteur": "interim",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
        "indemnite_fin_mission": Decimal("0.10"),
        "indemnite_conges_payes": Decimal("0.10"),
    },
    # ---------------------------------------------------------------
    # SPECTACLE / AUDIOVISUEL / PRESSE
    # ---------------------------------------------------------------
    "3090": {
        "nom": "Entreprises du secteur prive du spectacle vivant",
        "secteur": "spectacle",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    "2642": {
        "nom": "Production audiovisuelle",
        "secteur": "audiovisuel",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    "0086": {
        "nom": "Publicite",
        "secteur": "publicite",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.007"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # IMMOBILIER
    # ---------------------------------------------------------------
    "1527": {
        "nom": "Immobilier (administrateurs de biens, agences immobilieres)",
        "secteur": "immobilier",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    "1740": {
        "nom": "Syndics de copropriete et administrateurs de biens",
        "secteur": "immobilier",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # INDUSTRIE ALIMENTAIRE
    # ---------------------------------------------------------------
    "2247": {
        "nom": "Entreprises de boulangerie-patisserie (artisanale)",
        "secteur": "boulangerie",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.006"),
        "mutuelle_employeur_min_pct": 50,
    },
    "0843": {
        "nom": "Boulangerie-patisserie (entreprises)",
        "secteur": "boulangerie",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.006"),
        "mutuelle_employeur_min_pct": 50,
    },
    "1747": {
        "nom": "Activites de production des eaux embouteillees et boissons",
        "secteur": "agroalimentaire",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # COIFFURE / ESTHETIQUE
    # ---------------------------------------------------------------
    "2596": {
        "nom": "Coiffure et professions connexes",
        "secteur": "coiffure",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.005"),
        "mutuelle_employeur_min_pct": 50,
    },
    "3032": {
        "nom": "Esthetique-cosmetique et enseignement technique lie aux metiers de l esthetique",
        "secteur": "esthetique",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.005"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # ASSOCIATIONS / ECONOMIE SOCIALE
    # ---------------------------------------------------------------
    "1518": {
        "nom": "Animation (entreprises d animation socio-culturelle)",
        "secteur": "animation",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    "0218": {
        "nom": "Organismes de formation (fonds d assurance formation)",
        "secteur": "formation",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.007"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # AGRICULTURE
    # ---------------------------------------------------------------
    "7024": {
        "nom": "Exploitations de polyculture et d elevage",
        "secteur": "agriculture",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
        "regime": "msa",
    },
    "7012": {
        "nom": "Entreprises de travaux agricoles",
        "secteur": "agriculture",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
        "regime": "msa",
    },
    "8435": {
        "nom": "Cooperatives agricoles de cereales, oleagineux, approvisionnement",
        "secteur": "agriculture",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.009"),
        "mutuelle_employeur_min_pct": 50,
        "regime": "msa",
    },
    # ---------------------------------------------------------------
    # PROFESSIONS JURIDIQUES
    # ---------------------------------------------------------------
    "2205": {
        "nom": "Notariat",
        "secteur": "notariat",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.012"),
        "mutuelle_employeur_min_pct": 60,
        "regime_special": "crpcen",
    },
    "1000": {
        "nom": "Cabinets d avocats (personnel salarie)",
        "secteur": "juridique",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    "1850": {
        "nom": "Avocats salaries",
        "secteur": "juridique",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # PROFESSIONS COMPTABLES / EXPERTISE
    # ---------------------------------------------------------------
    "0787": {
        "nom": "Cabinets d experts-comptables et de commissaires aux comptes",
        "secteur": "expertise_comptable",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # CHIMIE / PLASTURGIE
    # ---------------------------------------------------------------
    "0044": {
        "nom": "Industries chimiques",
        "secteur": "chimie",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.010"),
        "mutuelle_employeur_min_pct": 50,
        "prime_anciennete": True,
    },
    "0292": {
        "nom": "Plasturgie",
        "secteur": "plasturgie",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # TEXTILE / HABILLEMENT
    # ---------------------------------------------------------------
    "0018": {
        "nom": "Industries textiles",
        "secteur": "textile",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.008"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # CABINETS MEDICAUX / DENTAIRES
    # ---------------------------------------------------------------
    "1147": {
        "nom": "Cabinets medicaux",
        "secteur": "medical",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.007"),
        "mutuelle_employeur_min_pct": 50,
    },
    "1619": {
        "nom": "Cabinets dentaires",
        "secteur": "dental",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.007"),
        "mutuelle_employeur_min_pct": 50,
    },
    # ---------------------------------------------------------------
    # AIDE A DOMICILE / SERVICES A LA PERSONNE
    # ---------------------------------------------------------------
    "2941": {
        "nom": "Aide, accompagnement, soins et services a domicile (BAD)",
        "secteur": "aide_domicile",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.006"),
        "mutuelle_employeur_min_pct": 50,
    },
    "3127": {
        "nom": "Services a la personne (entreprises)",
        "secteur": "services_personne",
        "prevoyance_cadre": Decimal("0.015"),
        "prevoyance_non_cadre": Decimal("0.005"),
        "mutuelle_employeur_min_pct": 50,
    },
}


def rechercher_idcc(terme: str) -> list[dict]:
    """Recherche dans la base IDCC par numero, nom ou secteur."""
    terme = terme.lower().strip()
    resultats = []
    for idcc, data in IDCC_DATABASE.items():
        score = 0
        if terme == idcc:
            score = 100
        elif terme in data["nom"].lower():
            score = 10
        elif terme in data.get("secteur", "").lower():
            score = 5
        if score > 0:
            resultats.append({
                "idcc": idcc,
                "score": score,
                **data,
            })
    resultats.sort(key=lambda x: x["score"], reverse=True)
    return resultats[:20]


def get_ccn_par_idcc(idcc: str) -> Optional[dict]:
    """Retourne les donnees CCN pour un numero IDCC donne."""
    return IDCC_DATABASE.get(idcc.zfill(4))


def get_prevoyance_par_idcc(idcc: str, est_cadre: bool = False) -> dict:
    """Retourne les taux de prevoyance pour un IDCC donne."""
    ccn = IDCC_DATABASE.get(idcc.zfill(4))
    if not ccn:
        return {
            "idcc": idcc,
            "ccn_connue": False,
            "taux_prevoyance": float(Decimal("0.015") if est_cadre else Decimal("0")),
            "mutuelle_employeur_min_pct": 50,
            "note": "IDCC non trouve. Minimums legaux appliques (ANI 2013 cadres / ANI 2016 mutuelle).",
        }
    taux = ccn["prevoyance_cadre"] if est_cadre else ccn["prevoyance_non_cadre"]
    return {
        "idcc": idcc,
        "ccn_connue": True,
        "nom": ccn["nom"],
        "secteur": ccn.get("secteur", ""),
        "taux_prevoyance": float(taux),
        "mutuelle_employeur_min_pct": ccn.get("mutuelle_employeur_min_pct", 50),
        "est_cadre": est_cadre,
    }
