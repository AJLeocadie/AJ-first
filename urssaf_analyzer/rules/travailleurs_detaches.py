"""Reglementation travailleurs detaches et salaries etrangers.

Sources juridiques :
- Directive 96/71/CE (detachement initial)
- Directive 2018/957 (revision - egalite de traitement)
- Reglement CE 883/2004 (coordination securite sociale)
- CT art. L.1261-1 a L.1265-1 (transposition francaise)
- CT art. R.1263-1 a R.1263-22 (declarations, obligations)
- CESEDA art. L.421-1 a L.421-35 (titres de sejour)
- CSS art. L.114-15-1 (carte BTP)
- Circ. DGT 2008/17 (obligations employeurs etrangers)

Accords bilateraux de securite sociale :
- Reglement CE 883/2004 (UE/EEE/Suisse)
- Conventions bilaterales (pays tiers)
"""

from decimal import Decimal
from typing import Optional


# ===================================================================
# DETACHEMENT INTRA-UE/EEE/SUISSE
# Directive 96/71/CE revisee par 2018/957
# Reglement CE 883/2004 (coordination SS)
# ===================================================================

DETACHEMENT_UE = {
    "base_legale": {
        "directive": "Directive 96/71/CE revisee par Directive 2018/957",
        "reglement_ss": "Reglement CE 883/2004",
        "transposition_fr": "CT art. L.1261-1 a L.1265-1",
        "decret": "Decret 2017-1070 / Decret 2019-555",
    },
    "duree_maximale": {
        "standard": 12,  # mois
        "extension": 6,  # mois (sur notification motivee)
        "total_max": 18,  # mois
        "note": "Au-dela de 18 mois : le salarie releve integralement du droit francais (sauf SS si certificat A1 maintenu)",
    },
    "certificat_a1": {
        "description": "Formulaire A1 delivre par l Etat d origine attestant l affiliation SS dans ce pays",
        "effet": "Le salarie detache reste affilie a la securite sociale de son pays d origine",
        "duree_max": "24 mois (renouvelable par accord entre organismes)",
        "delivre_par": "Organisme de securite sociale du pays d envoi",
        "obligation": "L employeur doit presenter le A1 a l URSSAF ou a l inspection du travail sur demande",
    },
    "noyau_dur": {
        "description": "Regles imperatives du droit francais applicables a tout travailleur detache en France",
        "ref": "CT art. L.1262-4",
        "regles": {
            "remuneration_minimale": {
                "regle": "SMIC ou salaire minimum conventionnel si superieur",
                "ref": "CT art. L.3231-1 / CCN applicable",
                "note": "Depuis la Directive 2018/957 : egalite de remuneration complete (pas seulement le minimum)",
            },
            "duree_travail": {
                "regle": "35h/semaine, durees maximales (10h/jour, 48h/semaine, 44h sur 12 semaines)",
                "ref": "CT art. L.3121-18 a L.3121-22",
                "heures_sup": "Majoration 25% (8 premieres), 50% (suivantes)",
            },
            "repos": {
                "regle": "11h consecutives de repos quotidien, 35h hebdomadaire (24h + 11h)",
                "ref": "CT art. L.3131-1, L.3132-2",
            },
            "conges_payes": {
                "regle": "2.5 jours ouvrables par mois de travail effectif",
                "ref": "CT art. L.3141-3",
            },
            "egalite_hommes_femmes": {
                "regle": "Egalite de remuneration et de traitement",
                "ref": "CT art. L.1142-1 a L.1142-10",
            },
            "sante_securite": {
                "regle": "Regles francaises de sante et securite au travail",
                "ref": "CT art. L.4111-1 et suivants",
            },
            "travail_illegal": {
                "regle": "Interdiction du travail dissimule, du marchandage et du pret illicite",
                "ref": "CT art. L.8211-1, L.8231-1, L.8241-1",
            },
            "non_discrimination": {
                "regle": "Principe de non-discrimination",
                "ref": "CT art. L.1132-1",
            },
            "protection_maternite": {
                "regle": "Interdiction de licenciement, conge maternite",
                "ref": "CT art. L.1225-1 et suivants",
            },
            "age_minimum": {
                "regle": "16 ans (derogations possibles pour apprentissage)",
                "ref": "CT art. L.4153-1",
            },
        },
    },
    "obligations_employeur": {
        "declaration_sipsi": {
            "description": "Declaration prealable de detachement via le teleservice SIPSI",
            "delai": "Avant le debut de la prestation",
            "contenu": [
                "Identite de l employeur (denomination, adresse, forme juridique)",
                "Adresse du lieu de prestation en France",
                "Identite du representant en France",
                "Date de debut et date de fin previsionnelle",
                "Identite des salaries detaches (nom, prenom, date de naissance, nationalite)",
                "Qualification professionnelle des salaries",
                "Taux horaire de remuneration brute applique",
                "Designation de l organisme de securite sociale (pays d origine)",
            ],
            "ref": "CT art. R.1263-4 a R.1263-8",
            "sanction_defaut": "Amende administrative: 4000 EUR/salarie (8000 EUR en recidive), plafond 500000 EUR",
        },
        "representant_france": {
            "description": "Designation obligatoire d un representant en France",
            "role": [
                "Liaison avec l inspection du travail et l URSSAF",
                "Conservation des documents obligatoires",
                "Point de contact en cas de controle",
            ],
            "ref": "CT art. L.1262-2-1",
            "sanction_defaut": "Amende administrative: 4000 EUR/salarie",
        },
        "documents_obligatoires": {
            "description": "Documents a conserver sur le lieu de travail ou a presenter sur demande",
            "documents": [
                "Certificat A1 (attestation securite sociale pays d origine)",
                "Contrat de travail (traduit en francais)",
                "Bulletins de paie (ou document equivalent)",
                "Releve d heures (debut, fin, duree travail quotidien)",
                "Justificatif du paiement du salaire",
                "Attestation d examen medical (si travaux dangereux)",
                "Copie de la designation du representant en France",
            ],
            "ref": "CT art. R.1263-1 / R.1263-12",
        },
        "carte_btp": {
            "description": "Carte d identification professionnelle obligatoire dans le BTP",
            "applicable": "Salaries detaches dans le secteur du batiment et travaux publics",
            "demande": "Via le teleservice carte-btp.fr avant le debut de la mission",
            "ref": "CSS art. L.114-15-1 / CT art. L.8291-1",
            "sanction_defaut": "Amende: 2000 EUR/salarie, 4000 EUR en recidive",
        },
        "vigilance_donneur_ordre": {
            "description": "Le maitre d ouvrage ou donneur d ordre doit verifier les obligations du prestataire etranger",
            "verifications": [
                "Declaration SIPSI effectuee",
                "Certificat A1 valide",
                "Carte BTP (si BTP)",
                "Paiement du SMIC / minimum conventionnel",
            ],
            "ref": "CT art. L.1262-4-1, L.8222-1",
            "sanction": "Responsabilite solidaire pour les impots, cotisations, salaires (CT art. L.8222-2)",
        },
    },
    "sanctions": {
        "defaut_declaration_sipsi": {
            "montant": "4000 EUR par salarie detache (8000 EUR en recidive)",
            "plafond": "500000 EUR au total",
            "ref": "CT art. L.1264-3",
        },
        "non_respect_noyau_dur": {
            "montant": "Jusqu a 4000 EUR par salarie et par manquement",
            "ref": "CT art. L.1264-1",
        },
        "suspension_prestation": {
            "description": "La DREETS peut ordonner la suspension de la prestation de services",
            "conditions": "Manquements graves et repetes aux regles du noyau dur",
            "duree": "Jusqu a 1 mois",
            "ref": "CT art. L.1263-4",
        },
        "travail_dissimule": {
            "description": "Si le detachement masque une relation d emploi permanente en France",
            "sanction_penale": "3 ans d emprisonnement + 45000 EUR d amende",
            "ref": "CT art. L.8224-1",
        },
    },
}


# ===================================================================
# TRAVAILLEURS ETRANGERS (HORS DETACHEMENT)
# CESEDA art. L.421-1 et suivants
# ===================================================================

TRAVAILLEURS_ETRANGERS = {
    "base_legale": {
        "ceseda": "Code de l entree et du sejour des etrangers et du droit d asile",
        "code_travail": "CT art. L.8251-1 a L.8256-8",
    },
    "categories": {
        "ue_eee_suisse": {
            "pays": "27 Etats UE + Norvege, Islande, Liechtenstein + Suisse",
            "autorisation_travail": "Non requise (libre circulation des travailleurs)",
            "titre_sejour": "Non requis pour un sejour < 3 mois. Au-dela: carte de sejour 'citoyen UE' (de plein droit)",
            "ref": "TFUE art. 45 / CESEDA art. L.233-1",
        },
        "hors_ue_titre_sejour": {
            "description": "Ressortissants de pays tiers necessitant un titre de sejour avec autorisation de travail",
            "titres_autorisant_travail": [
                "Carte de sejour temporaire 'salarie' (1 an, renouvelable)",
                "Carte de sejour pluriannuelle 'passeport talent' (4 ans)",
                "Carte de sejour 'travailleur saisonnier' (3 ans, 6 mois/an max)",
                "Carte de sejour 'salarie detache ICT' (intra-company transfer, 3 ans)",
                "Carte de sejour 'etudiant' (autorisation de travail limitee a 964h/an)",
                "Carte de resident (10 ans, plein droit de travailler)",
                "Visa long sejour valant titre de sejour (VLS-TS)",
                "Autorisation provisoire de sejour (APS) avec autorisation de travail",
                "Carte de sejour 'vie privee et familiale' (autorisation de plein droit)",
            ],
            "ref": "CESEDA art. L.421-1 a L.421-35",
        },
        "passeport_talent": {
            "categories": [
                "Salarie qualifie (remuneration >= 1.8 SMIC annuel)",
                "Chercheur",
                "Artiste-interprete",
                "Projet economique innovant (start-up)",
                "Investisseur",
                "Mandataire social",
                "Profession artistique et culturelle",
                "Renommee internationale",
                "Carte bleue europeenne (salaire >= 1.5 SMIC median)",
            ],
            "duree": "4 ans, renouvelable",
            "avantage": "Procedure simplifiee, pas d opposabilite emploi",
            "ref": "CESEDA art. L.421-9 a L.421-27",
        },
    },
    "obligations_employeur": {
        "verification_prealable": {
            "description": "Avant toute embauche, verifier le droit au travail du salarie etranger",
            "delai": "Au moins 2 jours ouvrables avant l embauche",
            "moyen": "Demande de verification aupres de la prefecture du lieu d embauche",
            "ref": "CT art. L.5221-8 / CT art. R.5221-41",
            "sanction_defaut": "Contribution speciale OFII + sanctions penales",
        },
        "dpae": {
            "description": "Declaration prealable a l embauche : obligatoire comme tout salarie",
            "ref": "CSS art. L.1221-10",
        },
        "taxe_ofii": {
            "description": "Contribution speciale due par l employeur pour l embauche d un travailleur etranger",
            "montant": {
                "cdi_ou_cdd_12_plus": "55% du salaire mensuel brut verse (plafond: 2.5 SMIC mensuel)",
                "cdd_3_a_12_mois": "Montant proportionnel a la duree",
                "cdd_moins_3_mois": "Forfait 74 EUR (saisonnier)",
                "passeport_talent": "Exonere",
                "etudiant": "Exonere",
            },
            "ref": "CESEDA art. L.436-10",
        },
        "contribution_speciale_travail_illegal": {
            "description": "Sanction financiere si l employeur a employe un etranger sans titre de travail",
            "montant": "5000 fois le taux horaire du minimum garanti (environ 20000 EUR par salarie)",
            "majorations": {
                "recidive": "Montant double",
                "mineur": "Montant triple",
                "pluralite": "+50% par salarie supplementaire",
            },
            "ref": "CESEDA art. L.8253-1",
        },
    },
    "securite_sociale": {
        "principe": "Affiliation au regime francais de securite sociale des leur embauche en France",
        "exceptions": [
            "Salarie detache avec certificat A1 (UE/EEE) ou certificat de detachement (convention bilaterale)",
            "Travailleur frontalier (regles specifiques selon convention)",
        ],
        "ref": "CSS art. L.311-2, R.311-1",
    },
}


# ===================================================================
# CONVENTIONS BILATERALES DE SECURITE SOCIALE
# Ref: CSS art. L.767-1 / conventions internationales
# ===================================================================

CONVENTIONS_BILATERALES = {
    "description": "Accords bilateraux entre la France et des pays tiers en matiere de securite sociale",
    "effet": "Eviter la double cotisation et garantir la portabilite des droits acquis",
    "pays_couverts": {
        # Maghreb
        "algerie": {
            "convention": "Convention franco-algerienne du 1er octobre 1980",
            "couverture": ["maladie", "maternite", "vieillesse", "invalidite", "at_mp", "deces", "allocations_familiales"],
            "totalisation_periodes": True,
            "detachement_max_mois": 36,
            "formulaire": "SE 350-01 a SE 350-07",
        },
        "maroc": {
            "convention": "Convention franco-marocaine du 22 octobre 2007 (revisee)",
            "couverture": ["maladie", "maternite", "vieillesse", "invalidite", "at_mp", "deces"],
            "totalisation_periodes": True,
            "detachement_max_mois": 36,
            "formulaire": "SE 350-01 a SE 350-07",
        },
        "tunisie": {
            "convention": "Convention franco-tunisienne du 26 juin 2003",
            "couverture": ["maladie", "maternite", "vieillesse", "invalidite", "at_mp", "deces"],
            "totalisation_periodes": True,
            "detachement_max_mois": 36,
            "formulaire": "SE 350-01 a SE 350-07",
        },
        # Afrique subsaharienne
        "senegal": {
            "convention": "Convention franco-senegalaise du 29 mars 1974",
            "couverture": ["vieillesse", "at_mp"],
            "totalisation_periodes": True,
            "detachement_max_mois": 24,
        },
        "mali": {
            "convention": "Convention franco-malienne du 12 juin 1979",
            "couverture": ["vieillesse", "at_mp", "allocations_familiales"],
            "totalisation_periodes": True,
            "detachement_max_mois": 24,
        },
        "cameroun": {
            "convention": "Convention franco-camerounaise du 5 novembre 1990",
            "couverture": ["vieillesse", "at_mp"],
            "totalisation_periodes": True,
            "detachement_max_mois": 24,
        },
        # Amerique
        "etats_unis": {
            "convention": "Convention franco-americaine du 2 mars 1987",
            "couverture": ["vieillesse"],
            "totalisation_periodes": True,
            "detachement_max_mois": 60,
            "formulaire": "SSA-USA/FR 6",
        },
        "canada": {
            "convention": "Entente franco-canadienne du 14 mars 2013",
            "couverture": ["vieillesse", "invalidite", "deces"],
            "totalisation_periodes": True,
            "detachement_max_mois": 60,
            "formulaire": "SE 401-Q",
        },
        "quebec": {
            "convention": "Entente France-Quebec du 17 decembre 2003",
            "couverture": ["vieillesse", "invalidite", "deces", "maladie", "maternite", "at_mp"],
            "totalisation_periodes": True,
            "detachement_max_mois": 60,
        },
        "bresil": {
            "convention": "Accord franco-bresilien du 15 decembre 2011",
            "couverture": ["vieillesse", "invalidite"],
            "totalisation_periodes": True,
            "detachement_max_mois": 24,
        },
        # Asie
        "japon": {
            "convention": "Convention franco-japonaise du 25 fevrier 2005",
            "couverture": ["vieillesse"],
            "totalisation_periodes": True,
            "detachement_max_mois": 60,
        },
        "coree_du_sud": {
            "convention": "Convention franco-coreenne du 6 decembre 2006",
            "couverture": ["vieillesse"],
            "totalisation_periodes": True,
            "detachement_max_mois": 60,
        },
        "inde": {
            "convention": "Convention franco-indienne du 30 septembre 2008",
            "couverture": ["vieillesse"],
            "totalisation_periodes": True,
            "detachement_max_mois": 60,
        },
        "chine": {
            "convention": "Accord franco-chinois du 31 octobre 2015 (en vigueur 2019)",
            "couverture": ["vieillesse"],
            "totalisation_periodes": False,
            "detachement_max_mois": 60,
            "note": "Dispense mutuelle de cotisations retraite pendant le detachement",
        },
        # Europe hors UE
        "turquie": {
            "convention": "Convention franco-turque du 20 janvier 1972 (revisee 2014)",
            "couverture": ["maladie", "maternite", "vieillesse", "invalidite", "at_mp", "deces"],
            "totalisation_periodes": True,
            "detachement_max_mois": 36,
        },
        "royaume_uni": {
            "convention": "Protocole post-Brexit : accord de commerce et de cooperation UE-UK (TCA 2020)",
            "couverture": ["vieillesse", "maladie", "maternite", "chomage", "at_mp"],
            "totalisation_periodes": True,
            "detachement_max_mois": 24,
            "note": "Depuis le Brexit, le Royaume-Uni n est plus couvert par le reglement CE 883/2004. L accord TCA prevoit des regles de coordination specifiques.",
        },
        "suisse": {
            "convention": "Accord UE-Suisse du 21 juin 1999 (ALCP) - application du reglement CE 883/2004",
            "couverture": ["vieillesse", "maladie", "maternite", "chomage", "at_mp", "invalidite", "allocations_familiales"],
            "totalisation_periodes": True,
            "detachement_max_mois": 24,
            "formulaire": "Formulaire A1 (meme systeme que UE)",
        },
        # Autres
        "israel": {
            "convention": "Convention franco-israelienne du 17 decembre 1965 (revisee)",
            "couverture": ["vieillesse", "invalidite", "at_mp"],
            "totalisation_periodes": True,
            "detachement_max_mois": 36,
        },
    },
}


# ===================================================================
# CONTROLES ET POINTS D AUDIT
# ===================================================================

def verifier_conformite_detachement(
    nationalite: str = "",
    pays_employeur: str = "",
    a1_present: bool = False,
    sipsi_declare: bool = False,
    duree_mois: int = 0,
    remuneration_brute: Decimal = Decimal("0"),
    secteur_btp: bool = False,
    carte_btp: bool = False,
) -> dict:
    """Verifie la conformite d un detachement et liste les anomalies."""
    from urssaf_analyzer.config.constants import SMIC_MENSUEL_BRUT

    anomalies = []
    alertes = []

    # 1. Declaration SIPSI
    if not sipsi_declare:
        anomalies.append({
            "type": "non_conformite",
            "description": "Declaration SIPSI non effectuee",
            "ref": "CT art. R.1263-4",
            "sanction": "Amende 4000 EUR/salarie",
            "gravite": "critique",
        })

    # 2. Certificat A1
    if not a1_present:
        anomalies.append({
            "type": "non_conformite",
            "description": "Certificat A1 (ou equivalent convention bilaterale) non presente",
            "ref": "Reglement CE 883/2004 art. 12 / Convention bilaterale applicable",
            "consequence": "Le salarie pourrait devoir etre affilie au regime francais",
            "gravite": "majeur",
        })

    # 3. Duree de detachement
    if duree_mois > 18:
        anomalies.append({
            "type": "depassement_duree",
            "description": f"Duree de detachement ({duree_mois} mois) depasse la limite de 18 mois",
            "ref": "Directive 2018/957 art. 3 / CT art. L.1262-4",
            "consequence": "Le droit du travail francais s applique integralement",
            "gravite": "majeur",
        })
    elif duree_mois > 12:
        alertes.append({
            "type": "alerte_duree",
            "description": f"Duree de detachement ({duree_mois} mois) depasse 12 mois - extension necessaire",
            "ref": "Directive 2018/957 art. 3",
            "action": "Notification motivee a la DREETS pour extension a 18 mois",
        })

    # 4. Remuneration minimale (SMIC)
    if remuneration_brute > 0 and remuneration_brute < SMIC_MENSUEL_BRUT:
        anomalies.append({
            "type": "remuneration_insuffisante",
            "description": f"Remuneration brute ({float(remuneration_brute):.2f} EUR) inferieure au SMIC ({float(SMIC_MENSUEL_BRUT):.2f} EUR)",
            "ref": "CT art. L.1262-4 / CT art. L.3231-1",
            "sanction": "Amende 4000 EUR/salarie",
            "gravite": "critique",
        })

    # 5. Carte BTP
    if secteur_btp and not carte_btp:
        anomalies.append({
            "type": "non_conformite",
            "description": "Carte BTP non demandee pour un salarie detache dans le BTP",
            "ref": "CSS art. L.114-15-1 / CT art. L.8291-1",
            "sanction": "Amende 2000 EUR/salarie",
            "gravite": "important",
        })

    conforme = len(anomalies) == 0

    return {
        "conforme": conforme,
        "nb_anomalies": len(anomalies),
        "nb_alertes": len(alertes),
        "anomalies": anomalies,
        "alertes": alertes,
        "recommandations": [
            "Conserver le certificat A1 sur le lieu de travail",
            "Tenir un registre des heures de travail",
            "Conserver les bulletins de paie (ou equivalent) traduits en francais",
            "Designer un representant en France (CT art. L.1262-2-1)",
        ] if not conforme else [],
    }


def determiner_regime_applicable(
    nationalite: str = "",
    pays_residence: str = "",
    pays_employeur: str = "",
    lieu_travail: str = "france",
    certificat_a1: bool = False,
    convention_bilaterale: bool = False,
) -> dict:
    """Determine quel regime de securite sociale s applique."""

    pays_ue = [
        "allemagne", "autriche", "belgique", "bulgarie", "chypre", "croatie",
        "danemark", "espagne", "estonie", "finlande", "grece", "hongrie",
        "irlande", "italie", "lettonie", "lituanie", "luxembourg", "malte",
        "pays-bas", "pologne", "portugal", "republique_tcheque", "roumanie",
        "slovaquie", "slovenie", "suede",
    ]
    pays_eee = pays_ue + ["norvege", "islande", "liechtenstein"]
    pays_eee_suisse = pays_eee + ["suisse"]

    pays_emp = pays_employeur.lower().replace(" ", "_").replace("-", "_")
    pays_res = pays_residence.lower().replace(" ", "_").replace("-", "_")

    # Cas 1: Emploi en France par un employeur francais
    if pays_emp in ("france", "fr", ""):
        return {
            "regime": "regime_general_france",
            "cotisations_en_france": True,
            "note": "Salarie embauche par un employeur francais = regime general (ou MSA si agricole)",
        }

    # Cas 2: Detachement intra-UE/EEE/Suisse avec certificat A1
    if pays_emp in pays_eee_suisse and certificat_a1:
        return {
            "regime": f"regime_{pays_emp}",
            "cotisations_en_france": False,
            "cotisations_dans": pays_emp,
            "note": f"Certificat A1 valide : cotisations dans le pays d origine ({pays_emp}). Le noyau dur du droit du travail francais s applique.",
            "ref": "Reglement CE 883/2004 art. 12",
        }

    # Cas 3: Detachement intra-UE/EEE/Suisse SANS certificat A1
    if pays_emp in pays_eee_suisse and not certificat_a1:
        return {
            "regime": "regime_general_france",
            "cotisations_en_france": True,
            "note": f"Pas de certificat A1 : le salarie doit etre affilie au regime francais. L employeur ({pays_emp}) doit s immatriculer aupres de l URSSAF.",
            "alerte": "ALERTE: Sans certificat A1, l employeur etranger doit cotiser en France",
            "ref": "CSS art. L.311-2",
        }

    # Cas 4: Pays avec convention bilaterale
    conventions = CONVENTIONS_BILATERALES["pays_couverts"]
    pays_emp_clean = pays_emp.replace("_", " ")
    conv = None
    for code, data in conventions.items():
        if code in pays_emp or pays_emp in code:
            conv = data
            break

    if conv and convention_bilaterale:
        return {
            "regime": f"regime_{pays_emp}",
            "cotisations_en_france": False,
            "cotisations_dans": pays_emp,
            "convention": conv["convention"],
            "couverture": conv["couverture"],
            "note": f"Convention bilaterale applicable. Detachement max: {conv['detachement_max_mois']} mois.",
            "ref": conv["convention"],
        }

    # Cas 5: Pays tiers sans convention ou sans certificat
    return {
        "regime": "regime_general_france",
        "cotisations_en_france": True,
        "note": "Pas de convention bilaterale applicable ou pas de certificat de detachement : cotisations en France obligatoires.",
        "convention_existante": conv is not None,
        "ref": "CSS art. L.311-2",
    }
