"""Table des taux AT/MP (Accidents du Travail / Maladies Professionnelles) par code NAF.

Ref:
- CSS art. L242-5 a L242-7 (tarification)
- Arrete du 24/12/2025 fixant les taux collectifs AT/MP 2026
- CARSAT / CRAMIF : taux par activite
- boss.gouv.fr : baremes AT/MP

Le taux AT/MP varie selon :
1. La taille de l'entreprise (collectif / mixte / individuel)
   - < 20 salaries : taux collectif du secteur d activite (code NAF)
   - 20-149 salaries : taux mixte (collectif + individuel)
   - >= 150 salaries : taux individuel (sinistralite propre)
2. Le code NAF (APE) de l'entreprise
3. L'historique de sinistralite (3 dernieres annees connues)

Cette table contient les taux collectifs 2026 par code NAF/APE.
Pour les entreprises >= 20 salaries, le taux reel depend de la sinistralite.
"""

from decimal import Decimal


# ===================================================================
# TAUX COLLECTIFS AT/MP 2026 PAR CODE NAF (SECTION + DIVISION)
# Format: code_naf -> taux en %
# Source: Arrete annuel taux collectifs AT/MP
# ===================================================================

TAUX_ATMP_PAR_NAF: dict[str, Decimal] = {
    # ---------------------------------------------------------------
    # A - AGRICULTURE, SYLVICULTURE, PECHE (regime general uniquement)
    # Note: la plupart releve du regime MSA, pas du general
    # ---------------------------------------------------------------
    "01": Decimal("0.0320"),   # Culture et production animale
    "02": Decimal("0.0500"),   # Sylviculture et exploitation forestiere
    "03": Decimal("0.0280"),   # Peche et aquaculture

    # ---------------------------------------------------------------
    # B - INDUSTRIES EXTRACTIVES
    # ---------------------------------------------------------------
    "05": Decimal("0.0380"),   # Extraction de houille et lignite
    "06": Decimal("0.0120"),   # Extraction d hydrocarbures
    "07": Decimal("0.0380"),   # Extraction de minerais metalliques
    "08": Decimal("0.0450"),   # Autres industries extractives
    "09": Decimal("0.0200"),   # Services de soutien aux industries extractives

    # ---------------------------------------------------------------
    # C - INDUSTRIE MANUFACTURIERE
    # ---------------------------------------------------------------
    "10": Decimal("0.0350"),   # Industries alimentaires
    "10.1": Decimal("0.0280"), # Transformation et conservation de viande
    "10.7": Decimal("0.0300"), # Fabrication de produits de boulangerie-patisserie
    "11": Decimal("0.0250"),   # Fabrication de boissons
    "12": Decimal("0.0150"),   # Fabrication de produits a base de tabac
    "13": Decimal("0.0250"),   # Fabrication de textiles
    "14": Decimal("0.0200"),   # Industrie de l habillement
    "15": Decimal("0.0350"),   # Industrie du cuir et de la chaussure
    "16": Decimal("0.0550"),   # Travail du bois et fabrication d articles en bois
    "17": Decimal("0.0250"),   # Industrie du papier et du carton
    "18": Decimal("0.0200"),   # Imprimerie et reproduction d enregistrements
    "19": Decimal("0.0180"),   # Cokefaction et raffinage
    "20": Decimal("0.0200"),   # Industrie chimique
    "21": Decimal("0.0120"),   # Industrie pharmaceutique
    "22": Decimal("0.0300"),   # Fabrication de produits en caoutchouc et plastique
    "23": Decimal("0.0400"),   # Fabrication d autres produits mineraux non metalliques
    "24": Decimal("0.0380"),   # Metallurgie
    "25": Decimal("0.0380"),   # Fabrication de produits metalliques
    "26": Decimal("0.0120"),   # Fabrication de produits informatiques et electroniques
    "27": Decimal("0.0180"),   # Fabrication d equipements electriques
    "28": Decimal("0.0250"),   # Fabrication de machines et equipements
    "29": Decimal("0.0300"),   # Industrie automobile
    "30": Decimal("0.0280"),   # Fabrication d autres materiels de transport
    "31": Decimal("0.0350"),   # Fabrication de meubles
    "32": Decimal("0.0200"),   # Autres industries manufacturieres
    "33": Decimal("0.0300"),   # Reparation et installation de machines

    # ---------------------------------------------------------------
    # D - PRODUCTION ET DISTRIBUTION D ELECTRICITE, GAZ, VAPEUR
    # ---------------------------------------------------------------
    "35": Decimal("0.0150"),   # Production et distribution electricite, gaz

    # ---------------------------------------------------------------
    # E - PRODUCTION ET DISTRIBUTION D EAU, ASSAINISSEMENT, DECHETS
    # ---------------------------------------------------------------
    "36": Decimal("0.0200"),   # Captage, traitement, distribution d eau
    "37": Decimal("0.0350"),   # Collecte et traitement des eaux usees
    "38": Decimal("0.0400"),   # Collecte, traitement et elimination des dechets
    "39": Decimal("0.0300"),   # Depollution et autres services de gestion des dechets

    # ---------------------------------------------------------------
    # F - CONSTRUCTION
    # ---------------------------------------------------------------
    "41": Decimal("0.0450"),   # Construction de batiments
    "42": Decimal("0.0500"),   # Genie civil
    "43": Decimal("0.0550"),   # Travaux de construction specialises
    "43.1": Decimal("0.0600"), # Demolition et preparation des sites
    "43.2": Decimal("0.0550"), # Travaux d installation electrique, plomberie
    "43.3": Decimal("0.0500"), # Travaux de finition
    "43.9": Decimal("0.0580"), # Autres travaux de construction specialises

    # ---------------------------------------------------------------
    # G - COMMERCE, REPARATION D AUTOMOBILES ET MOTOCYCLES
    # ---------------------------------------------------------------
    "45": Decimal("0.0250"),   # Commerce et reparation d automobiles
    "46": Decimal("0.0200"),   # Commerce de gros
    "47": Decimal("0.0250"),   # Commerce de detail
    "47.1": Decimal("0.0220"), # Commerce de detail en magasin non specialise
    "47.7": Decimal("0.0200"), # Autres commerces de detail en magasin specialise

    # ---------------------------------------------------------------
    # H - TRANSPORTS ET ENTREPOSAGE
    # ---------------------------------------------------------------
    "49": Decimal("0.0350"),   # Transports terrestres et transport par conduites
    "49.1": Decimal("0.0180"), # Transport ferroviaire interurbain de voyageurs
    "49.3": Decimal("0.0250"), # Autres transports terrestres de voyageurs
    "49.4": Decimal("0.0400"), # Transports routiers de fret
    "50": Decimal("0.0280"),   # Transports par eau
    "51": Decimal("0.0150"),   # Transports aeriens
    "52": Decimal("0.0350"),   # Entreposage et services auxiliaires des transports
    "53": Decimal("0.0300"),   # Activites de poste et de courrier

    # ---------------------------------------------------------------
    # I - HEBERGEMENT ET RESTAURATION
    # ---------------------------------------------------------------
    "55": Decimal("0.0250"),   # Hebergement
    "56": Decimal("0.0300"),   # Restauration
    "56.1": Decimal("0.0300"), # Restaurants et services de restauration mobile
    "56.3": Decimal("0.0250"), # Debits de boissons

    # ---------------------------------------------------------------
    # J - INFORMATION ET COMMUNICATION
    # ---------------------------------------------------------------
    "58": Decimal("0.0100"),   # Edition
    "59": Decimal("0.0150"),   # Production de films, video, programmes tele
    "60": Decimal("0.0120"),   # Programmation et diffusion
    "61": Decimal("0.0080"),   # Telecommunications
    "62": Decimal("0.0080"),   # Programmation, conseil et autres activites informatiques
    "63": Decimal("0.0080"),   # Services d information

    # ---------------------------------------------------------------
    # K - ACTIVITES FINANCIERES ET D ASSURANCE
    # ---------------------------------------------------------------
    "64": Decimal("0.0080"),   # Activites des services financiers
    "65": Decimal("0.0080"),   # Assurance
    "66": Decimal("0.0080"),   # Activites auxiliaires de services financiers

    # ---------------------------------------------------------------
    # L - ACTIVITES IMMOBILIERES
    # ---------------------------------------------------------------
    "68": Decimal("0.0150"),   # Activites immobilieres

    # ---------------------------------------------------------------
    # M - ACTIVITES SPECIALISEES, SCIENTIFIQUES ET TECHNIQUES
    # ---------------------------------------------------------------
    "69": Decimal("0.0100"),   # Activites juridiques et comptables
    "70": Decimal("0.0100"),   # Activites des sieges sociaux, conseil de gestion
    "71": Decimal("0.0120"),   # Activites d architecture et d ingenierie
    "72": Decimal("0.0100"),   # Recherche-developpement scientifique
    "73": Decimal("0.0100"),   # Publicite et etudes de marche
    "74": Decimal("0.0120"),   # Autres activites specialisees
    "75": Decimal("0.0150"),   # Activites veterinaires

    # ---------------------------------------------------------------
    # N - ACTIVITES DE SERVICES ADMINISTRATIFS ET DE SOUTIEN
    # ---------------------------------------------------------------
    "77": Decimal("0.0200"),   # Activites de location et location-bail
    "78": Decimal("0.0350"),   # Activites liees a l emploi (interim)
    "79": Decimal("0.0120"),   # Activites des agences de voyage
    "80": Decimal("0.0200"),   # Enquetes et securite
    "81": Decimal("0.0350"),   # Services relatifs aux batiments et amenagement paysager
    "81.2": Decimal("0.0350"), # Activites de nettoyage
    "82": Decimal("0.0150"),   # Activites administratives et autres activites de soutien

    # ---------------------------------------------------------------
    # O - ADMINISTRATION PUBLIQUE (regime general si contractuels)
    # ---------------------------------------------------------------
    "84": Decimal("0.0150"),   # Administration publique et defense

    # ---------------------------------------------------------------
    # P - ENSEIGNEMENT
    # ---------------------------------------------------------------
    "85": Decimal("0.0120"),   # Enseignement

    # ---------------------------------------------------------------
    # Q - SANTE HUMAINE ET ACTION SOCIALE
    # ---------------------------------------------------------------
    "86": Decimal("0.0200"),   # Activites pour la sante humaine
    "86.1": Decimal("0.0200"), # Activites hospitalieres
    "86.2": Decimal("0.0150"), # Activites de medecins et de dentistes
    "86.9": Decimal("0.0180"), # Autres activites pour la sante humaine
    "87": Decimal("0.0350"),   # Hebergement medico-social et social
    "88": Decimal("0.0280"),   # Action sociale sans hebergement

    # ---------------------------------------------------------------
    # R - ARTS, SPECTACLES ET ACTIVITES RECREATIVES
    # ---------------------------------------------------------------
    "90": Decimal("0.0200"),   # Activites creatives, artistiques et de spectacle
    "91": Decimal("0.0150"),   # Bibliotheques, archives, musees
    "92": Decimal("0.0120"),   # Organisation de jeux de hasard
    "93": Decimal("0.0250"),   # Activites sportives, recreatives et de loisirs

    # ---------------------------------------------------------------
    # S - AUTRES ACTIVITES DE SERVICES
    # ---------------------------------------------------------------
    "94": Decimal("0.0120"),   # Activites des organisations associatives
    "95": Decimal("0.0200"),   # Reparation d ordinateurs et de biens personnels
    "96": Decimal("0.0180"),   # Autres services personnels
    "96.0": Decimal("0.0180"), # Dont coiffure
    "96.02": Decimal("0.0150"), # Coiffure et soins de beaute
    "96.09": Decimal("0.0150"), # Autres services personnels

    # ---------------------------------------------------------------
    # T - ACTIVITES DES MENAGES EN TANT QU EMPLOYEURS
    # ---------------------------------------------------------------
    "97": Decimal("0.0150"),   # Activites des menages en tant qu employeurs de personnel domestique

    # ---------------------------------------------------------------
    # U - ACTIVITES EXTRA-TERRITORIALES
    # ---------------------------------------------------------------
    "99": Decimal("0.0100"),   # Activites des organisations et organismes extra-territoriaux
}

# Taux moyen national AT/MP 2026
TAUX_ATMP_MOYEN = Decimal("0.0208")

# Majorations forfaitaires AT/MP 2026 (incluses dans le taux)
MAJORATION_TRAJET = Decimal("0.0020")     # M1 : accidents de trajet
MAJORATION_CHARGES = Decimal("0.0060")    # M2 : charges generales de la branche
MAJORATION_PENIBILITE = Decimal("0.0010") # M3 : penibilite (C2P)
MAJORATION_ECAP = Decimal("0.0005")       # M4 : compte AT/MP


def get_taux_atmp(code_naf: str, effectif: int = 0) -> dict:
    """Retourne le taux AT/MP pour un code NAF donne.

    Pour les entreprises < 20 salaries : taux collectif du secteur.
    Pour >= 20 : indique que le taux individuel peut s appliquer.

    Args:
        code_naf: Code NAF/APE (ex: "62.02A", "41.20B")
        effectif: Effectif de l entreprise
    """
    naf_clean = code_naf.replace(".", "").replace(" ", "")

    # Chercher par precision decroissante : 4 chars, 3 chars, 2 chars
    taux = None
    naf_match = ""
    for length in (4, 3, 2):
        prefix = naf_clean[:length]
        # Essayer avec point
        if length >= 3:
            prefix_dot = naf_clean[:2] + "." + naf_clean[2:length]
        else:
            prefix_dot = prefix
        if prefix_dot in TAUX_ATMP_PAR_NAF:
            taux = TAUX_ATMP_PAR_NAF[prefix_dot]
            naf_match = prefix_dot
            break
        if prefix in TAUX_ATMP_PAR_NAF:
            taux = TAUX_ATMP_PAR_NAF[prefix]
            naf_match = prefix
            break

    if taux is None:
        # Fallback : essayer les 2 premiers chiffres
        prefix2 = naf_clean[:2]
        taux = TAUX_ATMP_PAR_NAF.get(prefix2, TAUX_ATMP_MOYEN)
        naf_match = prefix2 if prefix2 in TAUX_ATMP_PAR_NAF else "moyen"

    # Mode de tarification selon effectif
    if effectif < 20:
        mode = "collectif"
        note = "Taux collectif du secteur (entreprise < 20 salaries)"
    elif effectif < 150:
        mode = "mixte"
        note = "Taux mixte : combine le taux collectif et le taux individuel (20-149 salaries)"
    else:
        mode = "individuel"
        note = "Taux individuel : base sur la sinistralite propre de l entreprise (>= 150 salaries)"

    return {
        "code_naf": code_naf,
        "naf_match": naf_match,
        "taux_collectif": float(taux),
        "taux_collectif_pct": f"{float(taux) * 100:.2f}%",
        "mode_tarification": mode,
        "effectif": effectif,
        "note": note,
        "majorations_incluses": {
            "trajet_M1": float(MAJORATION_TRAJET),
            "charges_M2": float(MAJORATION_CHARGES),
            "penibilite_M3": float(MAJORATION_PENIBILITE),
            "ecap_M4": float(MAJORATION_ECAP),
        },
    }
