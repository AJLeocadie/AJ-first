"""Regimes speciaux : GUSO, AGESSA/MDA, spectacle, artistes-auteurs.

GUSO (Guichet Unique du Spectacle Occasionnel) :
- Ref: Code du travail art. L7122-22 a L7122-26
- Employeurs occasionnels du spectacle vivant
- Gestion simplifiee des cotisations sociales

AGESSA / MDA (Maison des Artistes) :
- Ref: CSS art. L382-1 a L382-14 (artistes-auteurs)
- LFSS 2019 : fusion AGESSA/MDA dans le regime general
- Cotisations specifiques artistes-auteurs

Conventions collectives :
- Base IDCC (Identifiant de Convention Collective)
- Specificites par branche
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class RegimeSpecial(str, Enum):
    """Regimes sociaux specifiques."""
    REGIME_GENERAL = "regime_general"
    GUSO = "guso"
    ARTISTES_AUTEURS = "artistes_auteurs"
    INTERMITTENT_SPECTACLE = "intermittent_spectacle"
    PROFESSION_LIBERALE = "profession_liberale"
    MICRO_ENTREPRENEUR = "micro_entrepreneur"
    TNS = "travailleur_non_salarie"
    AGRICOLE = "agricole"
    MARIN = "marin"
    MINES = "mines"
    CLERCS_NOTAIRES = "clercs_notaires"


@dataclass
class ConventionCollective:
    """Convention collective nationale."""
    idcc: str  # Identifiant de Convention Collective
    titre: str
    brochure: str = ""  # N° brochure JO
    code_naf_principaux: list[str] = field(default_factory=list)
    salaire_minimum: dict = field(default_factory=dict)  # Par niveau/echelon
    specificites: list[str] = field(default_factory=list)
    taux_prevoyance: Optional[Decimal] = None
    taux_mutuelle_part_patronale: Optional[Decimal] = None


# ===================================================================
# CONVENTIONS COLLECTIVES PRINCIPALES
# ===================================================================

CONVENTIONS_COLLECTIVES = {
    # Commerce
    "2216": ConventionCollective(
        idcc="2216", titre="Commerce de detail et de gros a predominance alimentaire",
        brochure="3305",
        code_naf_principaux=["4711B", "4711C", "4711D"],
        specificites=["Prime annuelle (13e mois)", "Majoration dimanche 20%"],
    ),
    "3251": ConventionCollective(
        idcc="3251", titre="Convention collective nationale du commerce de detail alimentaire non specialise",
        specificites=["Prime d'anciennete"],
    ),

    # BTP
    "1596": ConventionCollective(
        idcc="1596", titre="Batiment - Ouvriers (entreprises > 10 salaries)",
        brochure="3258",
        code_naf_principaux=["4120A", "4120B", "4211Z"],
        specificites=["Conges intemperies", "Indemnite de trajet", "Panier repas",
                       "Caisse conges payes BTP (CIBTP)"],
        taux_prevoyance=Decimal("0.015"),
    ),
    "1597": ConventionCollective(
        idcc="1597", titre="Batiment - Ouvriers (entreprises <= 10 salaries)",
        brochure="3193",
    ),
    "3248": ConventionCollective(
        idcc="3248", titre="Metallurgie",
        specificites=["Classification unique", "Prime d'anciennete progressive"],
    ),

    # Services
    "1486": ConventionCollective(
        idcc="1486", titre="Bureaux d'etudes techniques, cabinets d'ingenieurs-conseils (SYNTEC)",
        brochure="3018",
        code_naf_principaux=["6201Z", "6202A", "7112B"],
        specificites=["Forfait jours cadres", "Prime vacances 10% conges"],
        taux_prevoyance=Decimal("0.015"),
    ),
    "2098": ConventionCollective(
        idcc="2098", titre="Prestataires de services dans le domaine du tertiaire",
        specificites=["Indemnite teletravail"],
    ),

    # Restauration / Hotellerie
    "1979": ConventionCollective(
        idcc="1979", titre="Hotels, cafes, restaurants (HCR)",
        brochure="3292",
        code_naf_principaux=["5510Z", "5610A", "5630Z"],
        specificites=["Avantages en nature nourriture", "Indemnite compensatrice nourriture",
                       "13e mois apres 1 an", "Majoration heures nuit 15%"],
    ),

    # Sante
    "29": ConventionCollective(
        idcc="29", titre="Hospitalisation privee (FHP)",
        specificites=["Prime de dimanche/ferie", "Indemnite de sujetion"],
    ),

    # Transport
    "16": ConventionCollective(
        idcc="16", titre="Transports routiers et activites auxiliaires du transport",
        brochure="3085",
        specificites=["Heures d'equivalence", "Indemnite de repas",
                       "Repos compensateur", "Formation FIMO/FCO"],
    ),

    # Spectacle
    "3090": ConventionCollective(
        idcc="3090", titre="Entreprises du secteur prive du spectacle vivant",
        specificites=["GUSO possible pour occasionnels",
                       "Intermittents : annexes VIII et X Unedic",
                       "Conges spectacles (Audiens)"],
    ),
    "2642": ConventionCollective(
        idcc="2642", titre="Production audiovisuelle",
        specificites=["Intermittents annexe VIII/X", "Droits d'auteur"],
    ),

    # Agriculture
    "7024": ConventionCollective(
        idcc="7024", titre="Convention collective des exploitations agricoles",
        specificites=["MSA (pas URSSAF)", "TESA simplifie"],
    ),

    # Enseignement
    "3220": ConventionCollective(
        idcc="3220", titre="Enseignement prive hors contrat",
        specificites=["Grilles de classification specifiques"],
    ),

    # Immobilier
    "1527": ConventionCollective(
        idcc="1527", titre="Immobilier (administrateurs de biens, agences immobilieres)",
        specificites=["Prime de 13e mois", "Commission sur ventes"],
    ),

    # Securite
    "1351": ConventionCollective(
        idcc="1351", titre="Prevention et securite",
        specificites=["Primes de risque", "Heures de nuit", "Prime habillement"],
    ),
}


# ===================================================================
# GUSO - GUICHET UNIQUE DU SPECTACLE OCCASIONNEL
# ===================================================================

@dataclass
class ParametresGUSO:
    """Parametres de cotisations GUSO 2026."""
    # Cotisations securite sociale
    maladie_patronal: Decimal = Decimal("0.13")
    vieillesse_plafonnee_patronal: Decimal = Decimal("0.0855")
    vieillesse_plafonnee_salarial: Decimal = Decimal("0.069")
    vieillesse_deplafonnee_patronal: Decimal = Decimal("0.0211")
    vieillesse_deplafonnee_salarial: Decimal = Decimal("0.024")
    allocations_familiales: Decimal = Decimal("0.0525")
    accident_travail: Decimal = Decimal("0.0175")  # Taux collectif spectacle

    # CSG/CRDS
    csg_deductible: Decimal = Decimal("0.068")
    csg_non_deductible: Decimal = Decimal("0.024")
    crds: Decimal = Decimal("0.005")
    abattement_csg: Decimal = Decimal("0.9825")

    # Chomage (spectacle : annexes VIII et X)
    chomage_patronal: Decimal = Decimal("0.0405")
    ags: Decimal = Decimal("0.0015")

    # Retraite complementaire (Audiens)
    retraite_t1_patronal: Decimal = Decimal("0.0472")
    retraite_t1_salarial: Decimal = Decimal("0.0315")
    ceg_t1_patronal: Decimal = Decimal("0.0129")
    ceg_t1_salarial: Decimal = Decimal("0.0086")

    # Prevoyance (Audiens)
    prevoyance_patronal: Decimal = Decimal("0.012")
    prevoyance_salarial: Decimal = Decimal("0.004")

    # Conges spectacles (Audiens)
    conges_spectacles: Decimal = Decimal("0.155")  # 15.5% patronal

    # Medecine du travail (CMB)
    medecine_travail: Decimal = Decimal("0.005")

    # Formation professionnelle (AFDAS)
    formation_afdas: Decimal = Decimal("0.02")  # 2% masse salariale


GUSO_2026 = ParametresGUSO()


def calculer_cotisations_guso(
    salaire_brut: Decimal,
    nb_heures: Decimal = Decimal("8"),
    pass_mensuel: Decimal = Decimal("4005"),
) -> dict:
    """Calcule les cotisations pour une prestation GUSO.

    Le GUSO simplifie les declarations pour les employeurs
    occasionnels du spectacle vivant.
    """
    g = GUSO_2026

    # Proratiser le PASS au nombre d'heures (base 151.67h)
    pass_prorata = pass_mensuel * nb_heures / Decimal("151.67")
    assiette_plafonnee = min(salaire_brut, pass_prorata)
    assiette_csg = salaire_brut * g.abattement_csg

    lignes = []

    # Securite sociale
    lignes.append({
        "libelle": "Maladie",
        "assiette": float(salaire_brut),
        "taux_patronal": float(g.maladie_patronal),
        "taux_salarial": 0,
        "montant_patronal": float(salaire_brut * g.maladie_patronal),
        "montant_salarial": 0,
    })
    lignes.append({
        "libelle": "Vieillesse plafonnee",
        "assiette": float(assiette_plafonnee),
        "taux_patronal": float(g.vieillesse_plafonnee_patronal),
        "taux_salarial": float(g.vieillesse_plafonnee_salarial),
        "montant_patronal": float(assiette_plafonnee * g.vieillesse_plafonnee_patronal),
        "montant_salarial": float(assiette_plafonnee * g.vieillesse_plafonnee_salarial),
    })
    lignes.append({
        "libelle": "Vieillesse deplafonnee",
        "assiette": float(salaire_brut),
        "taux_patronal": float(g.vieillesse_deplafonnee_patronal),
        "taux_salarial": float(g.vieillesse_deplafonnee_salarial),
        "montant_patronal": float(salaire_brut * g.vieillesse_deplafonnee_patronal),
        "montant_salarial": float(salaire_brut * g.vieillesse_deplafonnee_salarial),
    })
    lignes.append({
        "libelle": "Allocations familiales",
        "assiette": float(salaire_brut),
        "taux_patronal": float(g.allocations_familiales),
        "taux_salarial": 0,
        "montant_patronal": float(salaire_brut * g.allocations_familiales),
        "montant_salarial": 0,
    })
    lignes.append({
        "libelle": "Accident du travail (spectacle)",
        "assiette": float(salaire_brut),
        "taux_patronal": float(g.accident_travail),
        "taux_salarial": 0,
        "montant_patronal": float(salaire_brut * g.accident_travail),
        "montant_salarial": 0,
    })

    # CSG/CRDS
    lignes.append({
        "libelle": "CSG deductible",
        "assiette": float(assiette_csg),
        "taux_patronal": 0,
        "taux_salarial": float(g.csg_deductible),
        "montant_patronal": 0,
        "montant_salarial": float(assiette_csg * g.csg_deductible),
    })
    lignes.append({
        "libelle": "CSG non deductible",
        "assiette": float(assiette_csg),
        "taux_patronal": 0,
        "taux_salarial": float(g.csg_non_deductible),
        "montant_patronal": 0,
        "montant_salarial": float(assiette_csg * g.csg_non_deductible),
    })
    lignes.append({
        "libelle": "CRDS",
        "assiette": float(assiette_csg),
        "taux_patronal": 0,
        "taux_salarial": float(g.crds),
        "montant_patronal": 0,
        "montant_salarial": float(assiette_csg * g.crds),
    })

    # Chomage
    lignes.append({
        "libelle": "Assurance chomage (spectacle)",
        "assiette": float(salaire_brut),
        "taux_patronal": float(g.chomage_patronal),
        "taux_salarial": 0,
        "montant_patronal": float(salaire_brut * g.chomage_patronal),
        "montant_salarial": 0,
    })
    lignes.append({
        "libelle": "AGS",
        "assiette": float(salaire_brut),
        "taux_patronal": float(g.ags),
        "taux_salarial": 0,
        "montant_patronal": float(salaire_brut * g.ags),
        "montant_salarial": 0,
    })

    # Retraite complementaire (Audiens)
    lignes.append({
        "libelle": "Retraite complementaire T1 (Audiens)",
        "assiette": float(assiette_plafonnee),
        "taux_patronal": float(g.retraite_t1_patronal),
        "taux_salarial": float(g.retraite_t1_salarial),
        "montant_patronal": float(assiette_plafonnee * g.retraite_t1_patronal),
        "montant_salarial": float(assiette_plafonnee * g.retraite_t1_salarial),
    })
    lignes.append({
        "libelle": "CEG T1 (Audiens)",
        "assiette": float(assiette_plafonnee),
        "taux_patronal": float(g.ceg_t1_patronal),
        "taux_salarial": float(g.ceg_t1_salarial),
        "montant_patronal": float(assiette_plafonnee * g.ceg_t1_patronal),
        "montant_salarial": float(assiette_plafonnee * g.ceg_t1_salarial),
    })

    # Prevoyance
    lignes.append({
        "libelle": "Prevoyance (Audiens)",
        "assiette": float(salaire_brut),
        "taux_patronal": float(g.prevoyance_patronal),
        "taux_salarial": float(g.prevoyance_salarial),
        "montant_patronal": float(salaire_brut * g.prevoyance_patronal),
        "montant_salarial": float(salaire_brut * g.prevoyance_salarial),
    })

    # Conges spectacles
    lignes.append({
        "libelle": "Conges spectacles (Audiens)",
        "assiette": float(salaire_brut),
        "taux_patronal": float(g.conges_spectacles),
        "taux_salarial": 0,
        "montant_patronal": float(salaire_brut * g.conges_spectacles),
        "montant_salarial": 0,
    })

    # Formation AFDAS
    lignes.append({
        "libelle": "Formation professionnelle (AFDAS)",
        "assiette": float(salaire_brut),
        "taux_patronal": float(g.formation_afdas),
        "taux_salarial": 0,
        "montant_patronal": float(salaire_brut * g.formation_afdas),
        "montant_salarial": 0,
    })

    # Medecine du travail
    lignes.append({
        "libelle": "Medecine du travail (CMB)",
        "assiette": float(salaire_brut),
        "taux_patronal": float(g.medecine_travail),
        "taux_salarial": 0,
        "montant_patronal": float(salaire_brut * g.medecine_travail),
        "montant_salarial": 0,
    })

    total_patronal = sum(l["montant_patronal"] for l in lignes)
    total_salarial = sum(l["montant_salarial"] for l in lignes)
    net_a_payer = float(salaire_brut) - total_salarial
    cout_total = float(salaire_brut) + total_patronal

    return {
        "regime": "GUSO",
        "salaire_brut": float(salaire_brut),
        "nb_heures": float(nb_heures),
        "lignes": lignes,
        "total_patronal": round(total_patronal, 2),
        "total_salarial": round(total_salarial, 2),
        "net_a_payer": round(net_a_payer, 2),
        "cout_total_employeur": round(cout_total, 2),
        "taux_charges_patronal_pct": round(total_patronal / float(salaire_brut) * 100, 2),
    }


# ===================================================================
# ARTISTES-AUTEURS (ex-AGESSA / MDA)
# ===================================================================

@dataclass
class ParametresArtistesAuteurs:
    """Cotisations artistes-auteurs 2026 (regime general depuis 2019)."""
    # Vieillesse de base
    vieillesse_plafonnee: Decimal = Decimal("0.069")  # 6.90%
    vieillesse_deplafonnee: Decimal = Decimal("0.004")  # 0.40%

    # CSG / CRDS
    csg_deductible: Decimal = Decimal("0.068")
    csg_non_deductible: Decimal = Decimal("0.024")
    crds: Decimal = Decimal("0.005")
    abattement_csg: Decimal = Decimal("0.9825")

    # CFP (Contribution Formation Professionnelle)
    cfp: Decimal = Decimal("0.0035")  # 0.35%

    # Diffuseur (part precomptee par le diffuseur)
    diffuseur_vieillesse_plafonnee: Decimal = Decimal("0.0855")
    diffuseur_vieillesse_deplafonnee: Decimal = Decimal("0.0211")
    diffuseur_contribution_formation: Decimal = Decimal("0.01")  # 1%

    # IRCEC (retraite complementaire artistes)
    ircec_raap: Decimal = Decimal("0.08")  # 8% RAAP
    ircec_seuil_affiliation: Decimal = Decimal("9720")  # ~900 SMIC horaire


ARTISTES_AUTEURS_2026 = ParametresArtistesAuteurs()


def calculer_cotisations_artistes_auteurs(
    revenus_bruts: Decimal,
    est_bda: bool = True,  # BDA (droits d'auteur) vs TA (traitements et salaires)
    frais_reels: Optional[Decimal] = None,
    pass_annuel: Decimal = Decimal("48060"),
) -> dict:
    """Calcule les cotisations sociales pour un artiste-auteur.

    Args:
        revenus_bruts: Revenus bruts HT (droits d'auteur ou honoraires)
        est_bda: True si revenus en BDA (benefices non commerciaux),
                 False si TA (traitements et salaires)
        frais_reels: Montant frais reels (si None, abattement forfaitaire)
        pass_annuel: Plafond annuel de securite sociale
    """
    aa = ARTISTES_AUTEURS_2026

    # Assiette sociale
    if frais_reels is not None:
        assiette = revenus_bruts - frais_reels
    else:
        # Abattement forfaitaire pour frais professionnels
        if est_bda:
            assiette = revenus_bruts  # Pas d'abattement en BDA (frais deduits)
        else:
            assiette = revenus_bruts  # En TA, abattement fait dans la declaration

    assiette = max(assiette, Decimal("0"))
    assiette_plafonnee = min(assiette, pass_annuel)
    assiette_csg = assiette * aa.abattement_csg

    lignes = []

    # Cotisations auteur
    lignes.append({
        "libelle": "Vieillesse plafonnee (auteur)",
        "assiette": float(assiette_plafonnee),
        "taux": float(aa.vieillesse_plafonnee),
        "montant": float(assiette_plafonnee * aa.vieillesse_plafonnee),
    })
    lignes.append({
        "libelle": "Vieillesse deplafonnee (auteur)",
        "assiette": float(assiette),
        "taux": float(aa.vieillesse_deplafonnee),
        "montant": float(assiette * aa.vieillesse_deplafonnee),
    })
    lignes.append({
        "libelle": "CSG deductible",
        "assiette": float(assiette_csg),
        "taux": float(aa.csg_deductible),
        "montant": float(assiette_csg * aa.csg_deductible),
    })
    lignes.append({
        "libelle": "CSG non deductible",
        "assiette": float(assiette_csg),
        "taux": float(aa.csg_non_deductible),
        "montant": float(assiette_csg * aa.csg_non_deductible),
    })
    lignes.append({
        "libelle": "CRDS",
        "assiette": float(assiette_csg),
        "taux": float(aa.crds),
        "montant": float(assiette_csg * aa.crds),
    })
    lignes.append({
        "libelle": "CFP (formation professionnelle)",
        "assiette": float(assiette),
        "taux": float(aa.cfp),
        "montant": float(assiette * aa.cfp),
    })

    # IRCEC (si revenus > seuil)
    if assiette > aa.ircec_seuil_affiliation:
        lignes.append({
            "libelle": "IRCEC - RAAP (retraite complementaire)",
            "assiette": float(assiette),
            "taux": float(aa.ircec_raap),
            "montant": float(assiette * aa.ircec_raap),
        })

    # Part diffuseur (precomptee)
    part_diffuseur = []
    part_diffuseur.append({
        "libelle": "Vieillesse plafonnee (diffuseur)",
        "assiette": float(assiette_plafonnee),
        "taux": float(aa.diffuseur_vieillesse_plafonnee),
        "montant": float(assiette_plafonnee * aa.diffuseur_vieillesse_plafonnee),
    })
    part_diffuseur.append({
        "libelle": "Vieillesse deplafonnee (diffuseur)",
        "assiette": float(assiette),
        "taux": float(aa.diffuseur_vieillesse_deplafonnee),
        "montant": float(assiette * aa.diffuseur_vieillesse_deplafonnee),
    })
    part_diffuseur.append({
        "libelle": "Formation (diffuseur)",
        "assiette": float(assiette),
        "taux": float(aa.diffuseur_contribution_formation),
        "montant": float(assiette * aa.diffuseur_contribution_formation),
    })

    total_auteur = sum(l["montant"] for l in lignes)
    total_diffuseur = sum(l["montant"] for l in part_diffuseur)
    net_apres_cotisations = float(assiette) - total_auteur

    return {
        "regime": "Artistes-auteurs (ex-AGESSA/MDA)",
        "type_revenu": "BDA" if est_bda else "TA",
        "revenus_bruts": float(revenus_bruts),
        "assiette_sociale": float(assiette),
        "cotisations_auteur": lignes,
        "cotisations_diffuseur": part_diffuseur,
        "total_cotisations_auteur": round(total_auteur, 2),
        "total_cotisations_diffuseur": round(total_diffuseur, 2),
        "net_apres_cotisations": round(net_apres_cotisations, 2),
        "taux_cotisations_auteur_pct": round(total_auteur / float(assiette) * 100, 2) if assiette else 0,
    }


def get_convention_collective(idcc: str) -> Optional[ConventionCollective]:
    """Retourne une convention collective par son IDCC."""
    return CONVENTIONS_COLLECTIVES.get(idcc)


def rechercher_conventions(terme: str) -> list[ConventionCollective]:
    """Recherche des conventions collectives par mot-cle."""
    terme_lower = terme.lower()
    resultats = []
    for cc in CONVENTIONS_COLLECTIVES.values():
        if (terme_lower in cc.titre.lower() or
            terme_lower in cc.idcc or
            any(terme_lower in s.lower() for s in cc.specificites)):
            resultats.append(cc)
    return resultats


def lister_conventions() -> list[dict]:
    """Liste toutes les conventions collectives disponibles."""
    return [
        {
            "idcc": cc.idcc,
            "titre": cc.titre,
            "brochure": cc.brochure,
            "nb_specificites": len(cc.specificites),
        }
        for cc in CONVENTIONS_COLLECTIVES.values()
    ]
