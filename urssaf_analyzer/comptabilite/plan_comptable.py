"""Plan Comptable General (PCG) simplifie pour l'analyse URSSAF.

Gere :
- Le referentiel des comptes (classes 1 a 7)
- L'affectation automatique des comptes selon le type de piece
- Les comptes auxiliaires clients/fournisseurs
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ClasseCompte(str, Enum):
    CAPITAUX = "1"
    IMMOBILISATIONS = "2"
    STOCKS = "3"
    TIERS = "4"
    FINANCIERS = "5"
    CHARGES = "6"
    PRODUITS = "7"


@dataclass
class Compte:
    numero: str
    libelle: str
    classe: ClasseCompte
    parent: str = ""
    est_auxiliaire: bool = False
    actif: bool = True

    @property
    def est_debiteur(self) -> bool:
        return self.classe in (
            ClasseCompte.IMMOBILISATIONS, ClasseCompte.STOCKS,
            ClasseCompte.CHARGES, ClasseCompte.FINANCIERS,
        )


# --- Plan comptable de base ---

PCG_BASE: dict[str, str] = {
    # Classe 1 - Capitaux
    "101000": "Capital social",
    "108000": "Compte de l'exploitant",
    "110000": "Report a nouveau (solde crediteur)",
    "119000": "Report a nouveau (solde debiteur)",
    "120000": "Resultat de l'exercice (benefice)",
    "129000": "Resultat de l'exercice (perte)",
    # Classe 2 - Immobilisations
    "205000": "Concessions, brevets, licences",
    "211000": "Terrains",
    "213000": "Constructions",
    "215000": "Materiel et outillage",
    "218100": "Materiel de bureau et informatique",
    "218200": "Materiel de transport",
    "280000": "Amortissements des immobilisations incorporelles",
    "281000": "Amortissements des immobilisations corporelles",
    # Classe 3 - Stocks
    "310000": "Matieres premieres",
    "355000": "Produits finis",
    "370000": "Marchandises",
    # Classe 4 - Tiers
    "401000": "Fournisseurs",
    "401100": "Fournisseurs - Factures non parvenues",
    "404000": "Fournisseurs d'immobilisations",
    "408000": "Fournisseurs - Factures non parvenues",
    "411000": "Clients",
    "411100": "Clients - Factures a etablir",
    "416000": "Clients douteux ou litigieux",
    "418000": "Clients - Produits non encore factures",
    "421000": "Personnel - Remunerations dues",
    "425000": "Personnel - Avances et acomptes",
    "431000": "Securite sociale (URSSAF)",
    "437000": "Autres organismes sociaux",
    "437100": "Retraite complementaire (AGIRC-ARRCO)",
    "437200": "Mutuelle / Prevoyance",
    "437300": "Pole Emploi / France Travail",
    "441000": "Etat - Subventions a recevoir",
    "442000": "Etat - Impots et taxes recouvrables sur tiers",
    "443000": "Operations particulieres avec l'Etat",
    "444000": "Etat - Impot sur les benefices",
    "445100": "TVA a decaisser",
    "445200": "TVA due intracommunautaire",
    "445500": "Taxes sur le chiffre d'affaires a decaisser",
    "445620": "TVA deductible sur immobilisations",
    "445660": "TVA deductible sur autres biens et services",
    "445670": "Credit de TVA a reporter",
    "445710": "TVA collectee",
    "445800": "TVA a regulariser",
    "447000": "Autres impots, taxes et versements assimiles",
    "455000": "Associes - Comptes courants",
    "467000": "Autres comptes debiteurs ou crediteurs",
    "471000": "Compte d'attente",
    "486000": "Charges constatees d'avance",
    "487000": "Produits constates d'avance",
    # Classe 5 - Financiers
    "512000": "Banque",
    "512100": "Banque - Compte principal",
    "514000": "Cheques postaux",
    "530000": "Caisse",
    "580000": "Virements internes",
    # Classe 6 - Charges
    "601000": "Achats de matieres premieres",
    "602000": "Achats d'autres approvisionnements",
    "604000": "Achats d'etudes et prestations de services",
    "606000": "Achats non stockes de matieres et fournitures",
    "606100": "Fournitures non stockables (eau, energie)",
    "606300": "Fournitures d'entretien et petit equipement",
    "606400": "Fournitures administratives",
    "607000": "Achats de marchandises",
    "609000": "Rabais, remises, ristournes obtenus sur achats",
    "611000": "Sous-traitance generale",
    "612000": "Redevances de credit-bail",
    "613000": "Locations",
    "614000": "Charges locatives et de copropriete",
    "615000": "Entretien et reparations",
    "616000": "Primes d'assurances",
    "618000": "Divers (documentation, colloques...)",
    "621000": "Personnel exterieur a l'entreprise",
    "622000": "Remunerations d'intermediaires et honoraires",
    "622600": "Honoraires comptables",
    "622700": "Frais d'actes et de contentieux",
    "623000": "Publicite, publications, relations publiques",
    "624000": "Transports de biens et transports collectifs",
    "625000": "Deplacements, missions et receptions",
    "626000": "Frais postaux et de telecommunications",
    "627000": "Services bancaires et assimiles",
    "628000": "Divers services exterieurs",
    "631000": "Impots, taxes sur remunerations (taxe sur salaires)",
    "631200": "Taxe d'apprentissage",
    "631300": "Participation formation continue",
    "633000": "Impots, taxes sur remunerations (autres organismes)",
    "633300": "Participation a l'effort de construction",
    "635100": "Contribution economique territoriale (CET)",
    "635110": "Cotisation fonciere des entreprises (CFE)",
    "635120": "Cotisation sur la valeur ajoutee (CVAE)",
    "637000": "Autres impots, taxes et versements assimiles",
    "641000": "Remunerations du personnel",
    "641100": "Salaires, appointements",
    "641200": "Conges payes",
    "641300": "Primes et gratifications",
    "641400": "Indemnites et avantages divers",
    "645000": "Charges de securite sociale et prevoyance",
    "645100": "Cotisations URSSAF",
    "645200": "Cotisations aux mutuelles",
    "645300": "Cotisations retraite complementaire",
    "645400": "Cotisations aux assedic / France Travail",
    "646000": "Cotisations sociales personnelles de l'exploitant",
    "647000": "Autres charges sociales",
    "648000": "Autres charges de personnel",
    "651000": "Redevances pour concessions, brevets, licences",
    "654000": "Pertes sur creances irrecouvrables",
    "658000": "Charges diverses de gestion courante",
    "661000": "Charges d'interets",
    "665000": "Escomptes accordes",
    "666000": "Pertes de change",
    "671000": "Charges exceptionnelles sur operations de gestion",
    "675000": "Valeurs comptables des elements d'actifs cedes",
    "681000": "Dotations aux amortissements et provisions - Exploitation",
    "686000": "Dotations aux amortissements et provisions - Financier",
    "691000": "Participation des salaries aux resultats",
    "695000": "Impots sur les benefices",
    # Classe 7 - Produits
    "701000": "Ventes de produits finis",
    "706000": "Prestations de services",
    "707000": "Ventes de marchandises",
    "708000": "Produits des activites annexes",
    "709000": "Rabais, remises, ristournes accordes",
    "713000": "Variation des stocks",
    "721000": "Production immobilisee - Immobilisations incorporelles",
    "722000": "Production immobilisee - Immobilisations corporelles",
    "740000": "Subventions d'exploitation",
    "751000": "Redevances pour concessions, brevets",
    "758000": "Produits divers de gestion courante",
    "761000": "Produits de participations",
    "762000": "Produits des autres immobilisations financieres",
    "764000": "Revenus des valeurs mobilieres de placement",
    "765000": "Escomptes obtenus",
    "766000": "Gains de change",
    "771000": "Produits exceptionnels sur operations de gestion",
    "775000": "Produits des cessions d'elements d'actifs",
    "781000": "Reprises sur amortissements et provisions - Exploitation",
    "786000": "Reprises sur provisions - Financier",
    "791000": "Transferts de charges d'exploitation",
}


class PlanComptable:
    """Gestionnaire du plan comptable."""

    def __init__(self):
        self.comptes: dict[str, Compte] = {}
        self._charger_pcg_base()

    def _charger_pcg_base(self):
        for numero, libelle in PCG_BASE.items():
            classe = ClasseCompte(numero[0])
            self.comptes[numero] = Compte(
                numero=numero, libelle=libelle, classe=classe,
            )

    def get_compte(self, numero: str) -> Optional[Compte]:
        return self.comptes.get(numero)

    def creer_compte_auxiliaire(
        self, numero: str, libelle: str, compte_collectif: str,
    ) -> Compte:
        """Cree un compte auxiliaire (client ou fournisseur specifique)."""
        collectif = self.comptes.get(compte_collectif)
        classe = ClasseCompte(numero[0]) if collectif is None else collectif.classe
        compte = Compte(
            numero=numero, libelle=libelle, classe=classe,
            parent=compte_collectif, est_auxiliaire=True,
        )
        self.comptes[numero] = compte
        return compte

    def get_ou_creer_compte_tiers(
        self, nom_tiers: str, est_client: bool,
    ) -> str:
        """Retourne le numero de compte auxiliaire pour un tiers, le cree si besoin."""
        prefixe = "411" if est_client else "401"
        # Chercher un auxiliaire existant
        for num, cpt in self.comptes.items():
            if num.startswith(prefixe) and cpt.est_auxiliaire and cpt.libelle == nom_tiers:
                return num

        # Creer un nouveau
        existants = [
            int(n[3:]) for n in self.comptes
            if n.startswith(prefixe) and len(n) == 6 and n[3:].isdigit()
            and self.comptes[n].est_auxiliaire
        ]
        prochain = max(existants, default=0) + 1
        numero = f"{prefixe}{prochain:03d}"
        collectif = f"{prefixe}000"
        self.creer_compte_auxiliaire(numero, nom_tiers, collectif)
        return numero

    def rechercher(self, terme: str) -> list[Compte]:
        terme_lower = terme.lower()
        return [
            c for c in self.comptes.values()
            if terme_lower in c.libelle.lower() or terme_lower in c.numero
        ]

    def get_comptes_classe(self, classe: ClasseCompte) -> list[Compte]:
        return sorted(
            [c for c in self.comptes.values() if c.classe == classe],
            key=lambda c: c.numero,
        )


# --- Regles d'affectation automatique ---

REGLES_AFFECTATION = {
    # Type de document -> (compte_charge_ou_produit, sens_tiers)
    "facture_achat": {
        "compte_defaut": "607000",
        "compte_tva": "445660",
        "compte_tiers": "401000",
        "sens_tiers": "credit",
    },
    "facture_vente": {
        "compte_defaut": "707000",
        "compte_tva": "445710",
        "compte_tiers": "411000",
        "sens_tiers": "debit",
    },
    "avoir_achat": {
        "compte_defaut": "609000",
        "compte_tva": "445660",
        "compte_tiers": "401000",
        "sens_tiers": "debit",
    },
    "avoir_vente": {
        "compte_defaut": "709000",
        "compte_tva": "445710",
        "compte_tiers": "411000",
        "sens_tiers": "credit",
    },
    "bulletin_paie": {
        "compte_salaire": "641100",
        "compte_urssaf": "645100",
        "compte_retraite": "645300",
        "compte_tiers_salarie": "421000",
        "compte_tiers_urssaf": "431000",
        "compte_tiers_retraite": "437100",
    },
    "note_frais": {
        "compte_defaut": "625000",
        "compte_tva": "445660",
        "compte_tiers": "467000",
        "sens_tiers": "credit",
    },
    "bordereau_cotisation": {
        "compte_defaut": "645100",
        "compte_tiers": "431000",
        "sens_tiers": "credit",
    },
    "releve_bancaire": {
        "compte_banque": "512000",
    },
}


def determiner_compte_charge(libelle_ligne: str, type_document: str) -> str:
    """Determine le compte de charge/produit a partir du libelle d'une ligne."""
    libelle = libelle_ligne.lower()

    # Achats
    if any(m in libelle for m in ["matiere", "composant", "ingredient"]):
        return "601000"
    if any(m in libelle for m in ["fourniture", "consommable"]):
        return "606000"
    if any(m in libelle for m in ["eau", "electricite", "gaz", "energie"]):
        return "606100"
    if any(m in libelle for m in ["entretien", "reparation", "maintenance"]):
        return "615000"
    if any(m in libelle for m in ["prestation", "service", "conseil", "consulting"]):
        return "604000"
    if any(m in libelle for m in ["sous-trait", "sous trait"]):
        return "611000"
    if any(m in libelle for m in ["loyer", "location", "bail"]):
        return "613000"
    if any(m in libelle for m in ["assurance"]):
        return "616000"
    if any(m in libelle for m in ["honoraire", "comptable", "avocat", "expert"]):
        return "622000"
    if any(m in libelle for m in ["publicite", "marketing", "communication"]):
        return "623000"
    if any(m in libelle for m in ["transport", "livraison", "expedition"]):
        return "624000"
    if any(m in libelle for m in ["deplacement", "mission", "hotel", "restaurant"]):
        return "625000"
    if any(m in libelle for m in ["telephone", "internet", "telecom", "timbre", "courrier"]):
        return "626000"
    if any(m in libelle for m in ["banque", "frais bancaire", "commission bancaire"]):
        return "627000"
    if any(m in libelle for m in ["marchandise"]):
        return "607000"

    # Ventes
    if type_document in ("facture_vente", "avoir_vente"):
        if any(m in libelle for m in ["prestation", "service"]):
            return "706000"
        if any(m in libelle for m in ["produit fini"]):
            return "701000"
        return "707000"

    # Paie
    if any(m in libelle for m in ["salaire", "remuneration", "paie"]):
        return "641100"
    if any(m in libelle for m in ["urssaf", "cotisation sociale", "securite sociale"]):
        return "645100"
    if any(m in libelle for m in ["retraite", "agirc", "arrco"]):
        return "645300"
    if any(m in libelle for m in ["mutuelle", "prevoyance"]):
        return "645200"

    # Defaut selon type
    regle = REGLES_AFFECTATION.get(type_document, {})
    return regle.get("compte_defaut", "471000")
