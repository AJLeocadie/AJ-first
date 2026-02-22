"""Parseur pour les fichiers PDF (bulletins de paie, factures, contrats, livres de paie, attestations, bordereaux).

Detecte automatiquement le type de document via analyse du contenu
et extrait les donnees structurees (employes, cotisations, montants).
"""

import re
import calendar
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import (
    Document, Declaration, Cotisation, Employe, Employeur, DateRange,
)
from urssaf_analyzer.config.constants import ContributionType
from urssaf_analyzer.parsers.base_parser import BaseParser
from urssaf_analyzer.utils.number_utils import parser_montant

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


# ============================================================
# DOCUMENT TYPE CLASSIFICATION KEYWORDS
# ============================================================

_KW_BULLETIN = [
    "bulletin de paie", "bulletin de salaire", "fiche de paie",
    "net a payer", "net à payer", "net imposable",
    "salaire brut", "salaire de base", "brut mensuel",
    "cotisations salariales", "cotisations patronales",
    "retenue salariale", "part salariale", "part patronale",
    "heures travaillees", "heures travaillées",
    "convention collective", "emploi", "classification",
    "conges payes", "congés payés", "cumul brut", "cumul net",
    "prelevement a la source", "prélèvement à la source",
    "indemnite transport", "indemnité transport",
    "titres restaurant", "tickets restaurant",
    "mutuelle", "prevoyance", "prévoyance",
]

_KW_FACTURE = [
    "facture", "invoice", "montant ht", "montant ttc",
    "tva", "t.v.a", "hors taxe", "toutes taxes",
    "conditions de reglement", "conditions de règlement",
    "bon de commande", "numero de facture", "numéro de facture",
    "date de facture", "echeance", "échéance",
    "reglement", "règlement", "rib", "iban",
    "reference client", "référence client",
    "designation", "désignation", "quantite", "quantité",
    "prix unitaire", "remise",
]

_KW_CONTRAT = [
    "contrat de travail", "contrat a duree", "contrat à durée",
    "cdi", "cdd", "contrat d apprentissage", "contrat d'apprentissage",
    "contrat de professionnalisation",
    "article l.", "article r.", "code du travail",
    "periode d essai", "période d'essai",
    "rupture conventionnelle", "licenciement",
    "remuneration mensuelle", "rémunération mensuelle",
    "temps complet", "temps partiel",
    "fait a", "fait à", "en deux exemplaires",
    "l employeur", "l'employeur", "le salarie", "le salarié",
]

_KW_LDP = [
    "livre de paie", "livre de paye",
    "recapitulatif", "récapitulatif",
    "etat recapitulatif", "état récapitulatif",
    "total general", "total général",
    "total etablissement", "total établissement",
    "masse salariale", "effectif total",
    "bordereau recapitulatif", "bordereau récapitulatif",
]

_KW_INTERESSEMENT = [
    "interessement", "intéressement",
    "participation aux resultats", "participation aux résultats",
    "accord d interessement", "accord d'intéressement",
    "accord de participation",
    "supplement d interessement", "supplément d'intéressement",
    "plan d epargne", "plan d'épargne",
    "pee", "perco", "percol",
]

_KW_ATTESTATION = [
    "attestation employeur", "attestation de travail",
    "attestation pole emploi", "attestation pôle emploi",
    "attestation france travail",
    "certificat de travail",
    "solde de tout compte",
    "recu pour solde", "reçu pour solde",
]

_KW_ACCORD = [
    "accord d entreprise", "accord d'entreprise",
    "accord collectif", "accord de branche",
    "negociation annuelle", "négociation annuelle",
    "nao", "accord salarial",
    "accord de methode", "accord de méthode",
    "accord egalite", "accord égalité",
    "accord temps de travail", "amenagement du temps",
    "accord teletravail", "accord télétravail",
    "accord seniors", "accord gpec", "gpec",
    "qualite de vie au travail", "qvt", "qvct",
    "droit a la deconnexion", "penibilite", "pénibilité",
    "protocole d accord", "protocole d'accord",
    "avenant a l accord", "avenant à l'accord",
]

_KW_PV_AG = [
    "proces verbal", "procès verbal", "procès-verbal",
    "assemblee generale", "assemblée générale",
    "assemblee extraordinaire", "assemblée extraordinaire",
    "assemblee ordinaire", "assemblée ordinaire",
    "deliberation", "délibération",
    "resolution", "résolution",
    "quorum", "vote", "unanimite", "unanimité",
    "ordre du jour", "convocation",
    "approbation des comptes", "affectation du resultat",
    "nomination", "revocation", "révocation",
    "commissaire aux comptes",
]

_KW_CONTRAT_SERVICE = [
    "contrat de prestation", "contrat de service",
    "prestation de services", "prestataire",
    "cahier des charges", "bon de commande",
    "sous-traitance", "sous traitance",
    "obligation de resultat", "obligation de résultat",
    "obligation de moyens",
    "penalites de retard", "pénalités de retard",
    "clause de confidentialite", "clause de confidentialité",
    "clause de non-concurrence",
    "conditions generales", "conditions générales",
    "cgv", "cgu",
]

# ============================================================
# COMPREHENSIVE DOCUMENT TYPES - Fiscal / Social / Juridique / Comptable
# ============================================================

# --- FISCAL ---
_KW_LIASSE_FISCALE = [
    "liasse fiscale", "cerfa 2050", "cerfa 2051", "cerfa 2052",
    "cerfa 2053", "cerfa 2054", "cerfa 2055", "cerfa 2056",
    "cerfa 2057", "cerfa 2058", "cerfa 2059",
    "formulaire 2050", "formulaire 2065", "formulaire 2031",
    "declaration de resultats", "déclaration de résultats",
    "imprime fiscal", "imprimé fiscal",
    "regime reel", "régime réel", "regime simplifie", "régime simplifié",
    "bic", "bnc", "ba ",
    "annexe 2050", "annexe 2051",
    "actif immobilise", "actif immobilisé", "amortissements",
    "provisions", "etat des immobilisations",
]

_KW_DECLARATION_TVA = [
    "declaration de tva", "déclaration de tva",
    "ca3", "ca 3", "ca12", "ca 12",
    "cerfa 3310", "cerfa 3517",
    "formulaire ca3", "formulaire ca12",
    "tva collectee", "tva collectée", "tva deductible", "tva déductible",
    "credit de tva", "crédit de tva", "tva nette",
    "tva a reverser", "tva à reverser",
    "tva intracommunautaire", "autoliquidation",
    "regime reel normal", "regime simplifie",
]

_KW_DECLARATION_IS = [
    "impot sur les societes", "impôt sur les sociétés",
    "declaration is", "déclaration is",
    "cerfa 2065", "formulaire 2065",
    "resultat fiscal", "résultat fiscal",
    "benefice imposable", "bénéfice imposable",
    "deficit reportable", "déficit reportable",
    "acompte is", "solde is",
    "contribution sociale", "contribution additionnelle",
    "taux normal", "taux reduit", "taux réduit",
]

_KW_DAS2 = [
    "das2", "das 2", "declaration des honoraires",
    "déclaration des honoraires",
    "honoraires commissions", "droits auteur",
    "vacations remuneration", "redevances",
    "cerfa 10144", "formulaire das2",
    "honoraires et vacations",
    "beneficiaire des versements", "bénéficiaire des versements",
]

_KW_TAXE_SALAIRES = [
    "taxe sur les salaires", "cerfa 2502",
    "formulaire 2502", "declaration taxe salaires",
    "déclaration taxe salaires",
    "base imposable taxe salaires",
    "taux majore", "taux majoré",
    "franchise taxe salaires",
]

_KW_CFE_CVAE = [
    "cfe", "cvae", "contribution fonciere",
    "contribution economique territoriale",
    "contribution foncière", "contribution économique territoriale",
    "cotisation fonciere", "cotisation foncière",
    "valeur ajoutee", "valeur ajoutée",
    "cerfa 1447", "avis cfe",
    "avis d imposition cfe", "avis d imposition cvae",
]

_KW_FEC = [
    "fichier des ecritures comptables", "fichier des écritures comptables",
    "fec ", "journal comptable",
    "article l 47 a", "norme fec",
    "ecritures comptables", "écritures comptables",
    "grand livre", "balance generale", "balance générale",
    "export comptable", "plan comptable",
]

# --- COMPTABLE ---
_KW_BILAN = [
    "bilan", "actif du bilan", "passif du bilan",
    "comptes annuels", "exercice clos", "exercice clos le",
    "total actif", "total passif",
    "capitaux propres", "immobilisations",
    "dettes", "creances", "créances",
    "fonds propres", "resultat de l exercice",
    "total du bilan",
]

_KW_COMPTE_RESULTAT = [
    "compte de resultat", "compte de résultat",
    "produits d exploitation", "charges d exploitation",
    "produits financiers", "charges financieres", "charges financières",
    "produits exceptionnels", "charges exceptionnelles",
    "resultat d exploitation", "résultat d'exploitation",
    "resultat courant", "résultat courant",
    "chiffre d affaires", "chiffre d'affaires",
    "resultat net", "résultat net",
    "excedent brut", "excédent brut",
]

_KW_RAPPORT_CAC = [
    "commissaire aux comptes", "rapport du commissaire",
    "certification des comptes", "opinion d audit",
    "rapport general", "rapport général",
    "rapport special", "rapport spécial",
    "rapport de gestion", "diligences",
    "verification", "vérification",
    "image fidele", "image fidèle",
    "normes d exercice professionnel",
    "compagnie nationale",
]

_KW_RAPPORT_GESTION = [
    "rapport de gestion", "rapport annuel",
    "compte rendu de gestion", "rapport du gerant",
    "rapport du gérant", "rapport du directoire",
    "rapport du conseil d administration",
    "activite de l exercice", "activité de l'exercice",
    "evolution de l activite", "évolution de l'activité",
    "faits marquants", "evenements posterieurs",
    "perspectives", "strategie",
]

_KW_BUDGET = [
    "budget previsionnel", "budget prévisionnel",
    "prevision budgetaire", "prévision budgétaire",
    "plan de tresorerie", "plan de trésorerie",
    "previsionnel", "prévisionnel",
    "business plan", "plan d affaires",
    "compte de resultat previsionnel",
    "plan de financement",
    "tableau de bord",
]

# --- SOCIAL / RH ---
_KW_DPAE = [
    "dpae", "declaration prealable", "déclaration préalable",
    "declaration prealable a l embauche",
    "déclaration préalable à l'embauche",
    "cerfa 14738", "due ",
    "declaration unique d embauche",
    "déclaration unique d'embauche",
]

_KW_REGISTRE_PERSONNEL = [
    "registre unique du personnel", "registre du personnel",
    "registre des entrees et sorties",
    "registre des entrées et sorties",
    "article l1221-13", "l.1221-13",
    "effectif de l entreprise", "effectif de l'entreprise",
    "listing du personnel", "liste du personnel",
    "tableau des effectifs",
]

_KW_DUERP = [
    "document unique", "duerp", "duer",
    "evaluation des risques", "évaluation des risques",
    "risques professionnels",
    "unite de travail", "unité de travail",
    "facteurs de penibilite", "facteurs de pénibilité",
    "plan de prevention", "plan de prévention",
    "article r4121", "article l4121",
]

_KW_REGLEMENT_INTERIEUR = [
    "reglement interieur", "règlement intérieur",
    "dispositions generales", "discipline",
    "sanctions disciplinaires",
    "hygiene et securite", "hygiène et sécurité",
    "droit de la defense", "droit de la défense",
    "article l1321", "l.1321",
    "entree en vigueur", "entrée en vigueur",
    "inspection du travail",
]

_KW_AVENANT = [
    "avenant au contrat", "avenant n",
    "modification du contrat", "modification contractuelle",
    "avenant de travail",
    "clause modificative",
    "il est convenu ce qui suit",
    "les parties conviennent",
    "en complement", "en complément",
    "modification de la remuneration",
    "modification de la rémunération",
    "changement de poste", "mutation",
]

_KW_BILAN_SOCIAL = [
    "bilan social", "indicateurs sociaux",
    "article l2312-30", "l.2312-30",
    "emploi et remuneration", "emploi et rémunération",
    "conditions de travail", "formation professionnelle",
    "relations professionnelles",
    "effectif moyen", "repartition par age",
    "turnover", "absenteisme", "absentéisme",
    "accidents du travail",
]

_KW_NOTE_FRAIS = [
    "note de frais", "etat de frais", "état de frais",
    "frais de deplacement", "frais de déplacement",
    "frais de mission", "frais de representation",
    "frais de représentation",
    "indemnites kilometriques", "indemnités kilométriques",
    "frais de repas", "frais d hebergement",
    "frais d'hébergement",
    "justificatifs de depenses", "justificatifs de dépenses",
    "remboursement de frais",
]

# --- JURIDIQUE ---
_KW_STATUTS = [
    "statuts de la societe", "statuts de la société",
    "statuts constitutifs", "statuts mis a jour",
    "objet social", "denomination sociale", "dénomination sociale",
    "siege social", "siège social",
    "capital social", "parts sociales", "actions",
    "gerant", "gérant", "president", "président",
    "associe", "associé", "actionnaire",
    "duree de la societe", "durée de la société",
    "exercice social", "repartition des benefices",
    "cession de parts",
]

_KW_KBIS = [
    "k bis", "kbis", "k-bis",
    "extrait du registre", "registre du commerce",
    "registre du commerce et des societes",
    "registre du commerce et des sociétés",
    "rcs ", "greffe du tribunal",
    "immatriculation", "numero d identification",
    "numéro d'identification",
    "forme juridique", "date d immatriculation",
]

_KW_BAIL = [
    "bail commercial", "bail professionnel",
    "contrat de bail", "contrat de location",
    "loyer mensuel", "loyer trimestriel",
    "depot de garantie", "dépôt de garantie",
    "bailleur", "preneur", "locataire",
    "clause resolutoire", "clause résolutoire",
    "etat des lieux", "état des lieux",
    "revision du loyer", "révision du loyer",
    "tacite reconduction",
    "article l145", "code de commerce",
]

_KW_ASSURANCE = [
    "police d assurance", "police d'assurance",
    "contrat d assurance", "contrat d'assurance",
    "responsabilite civile", "responsabilité civile",
    "multirisque", "rc professionnelle",
    "prime d assurance", "prime d'assurance",
    "cotisation annuelle", "garantie",
    "franchise", "sinistre", "indemnisation",
    "assureur", "souscripteur",
    "conditions particulieres", "conditions particulières",
]

_KW_RELEVE_BANCAIRE = [
    "releve de compte", "relevé de compte",
    "releve bancaire", "relevé bancaire",
    "solde debiteur", "solde débiteur",
    "solde crediteur", "solde créditeur",
    "ancien solde", "nouveau solde",
    "date de valeur", "libelle de l operation",
    "virement", "prelevement", "prélèvement",
    "cheque", "chèque", "carte bancaire",
    "agios", "frais bancaires",
]

_KW_DEVIS = [
    "devis", "proposition commerciale",
    "offre de prix", "estimation",
    "devis n", "validite du devis", "validité du devis",
    "sous reserve", "sous réserve",
    "bon pour accord",
    "prix unitaire", "montant total",
]

_KW_AVOIR = [
    "avoir", "note de credit", "note de crédit",
    "facture d avoir", "facture d'avoir",
    "avoir n", "credit note",
    "remboursement", "annulation de facture",
    "ristourne", "retour marchandise",
]

_KW_BON_COMMANDE = [
    "bon de commande", "purchase order",
    "commande n", "reference commande", "référence commande",
    "date de commande", "date de livraison",
    "conditions de livraison",
    "accusé de reception", "accusé de réception",
]

_KW_CERFA = [
    "cerfa n", "cerfa no", "formulaire cerfa",
    "republique francaise", "république française",
    "ministere", "ministère",
    "direction generale des finances",
    "direction générale des finances",
    "service des impots", "service des impôts",
    "centre des finances publiques",
]

_KW_RELEVE_FRAIS_GENERAUX = [
    "releve de frais generaux", "relevé de frais généraux",
    "cerfa 2067", "formulaire 2067",
    "remunerations les plus elevees",
    "rémunérations les plus élevées",
    "frais de voyage", "depenses de reception",
    "dépenses de réception",
    "cadeaux", "frais generaux", "frais généraux",
]

_KW_AVIS_IMPOSITION = [
    "avis d imposition", "avis d'imposition",
    "impot sur le revenu", "impôt sur le revenu",
    "taxe fonciere", "taxe foncière",
    "taxe d habitation", "taxe d'habitation",
    "revenu fiscal de reference", "revenu fiscal de référence",
    "prelevement a la source", "prélèvement à la source",
    "direction generale des finances publiques",
    "direction générale des finances publiques",
    "centre des finances publiques",
    "impots.gouv", "impôts.gouv",
]

_KW_BORDEREAU_URSSAF = [
    "bordereau urssaf", "appel de cotisations",
    "avis de paiement urssaf", "cotisations dues",
    "bordereau recapitulatif de cotisations",
    "bordereau récapitulatif de cotisations",
    "versement des cotisations",
    "compte employeur", "compte cotisant",
    "net-entreprises", "urssaf.fr",
    "siret employeur", "code type personnel",
    "ctp ", "declaration unifiee",
    "déclaration unifiée", "ducs",
]

# --- SOCIAL / RH (compléments) ---

_KW_RUPTURE_CONVENTIONNELLE = [
    "rupture conventionnelle", "cerfa 14598",
    "homologation", "convention de rupture",
    "indemnite specifique", "indemnité spécifique",
    "indemnite de rupture", "indemnité de rupture",
    "delai de retractation", "délai de rétractation",
    "direction regionale", "direccte", "dreets",
    "formulaire de rupture conventionnelle",
    "article l1237-11", "l.1237-11",
    "commun accord", "consentement mutuel",
]

_KW_CSE = [
    "comite social et economique", "comité social et économique",
    "comite social", "comité social",
    "cse ", "c.s.e.",
    "comite d entreprise", "comité d'entreprise",
    "delegation du personnel", "délégation du personnel",
    "chsct", "cssct",
    "reunion cse", "réunion cse",
    "budget fonctionnement", "budget activites sociales",
    "budget activités sociales",
    "secretaire du cse", "secrétaire du cse",
    "tresorier du cse", "trésorier du cse",
    "ordre du jour cse", "proces verbal cse",
    "procès verbal cse", "pv cse",
    "activites sociales et culturelles",
    "activités sociales et culturelles",
    "expert cse", "droit d alerte",
    "consultation cse", "information consultation",
]

_KW_FRANCE_TRAVAIL = [
    "france travail", "pole emploi", "pôle emploi",
    "allocation d aide au retour a l emploi",
    "allocation d'aide au retour à l'emploi",
    "are ", "a.r.e.",
    "demandeur d emploi", "demandeur d'emploi",
    "inscription comme demandeur",
    "radiation", "cessation d inscription",
    "attestation employeur destinee",
    "attestation employeur destinée",
    "convention de reclassement",
    "contrat de securisation professionnelle",
    "contrat de sécurisation professionnelle",
    "csp ", "aide au reclassement",
    "homologation licenciement",
    "autorisation de licenciement",
    "inspection du travail",
]

_KW_MEDECINE_TRAVAIL = [
    "medecine du travail", "médecine du travail",
    "avis d aptitude", "avis d'aptitude",
    "avis d inaptitude", "avis d'inaptitude",
    "visite medicale", "visite médicale",
    "visite d information et de prevention",
    "visite d'information et de prévention",
    "visite de reprise", "visite de pre-reprise",
    "visite de pré-reprise",
    "medecin du travail", "médecin du travail",
    "apte", "inapte", "aptitude",
    "service de sante au travail",
    "service de santé au travail",
    "article r4624", "article l4624",
    "suivi individuel", "surveillance medicale",
    "surveillance médicale",
]

_KW_EPARGNE_SALARIALE = [
    "plan d epargne entreprise", "plan d'épargne entreprise",
    "pee ", "p.e.e.",
    "plan d epargne retraite", "plan d'épargne retraite",
    "perco", "percol", "per collectif",
    "per obligatoire", "pero",
    "abondement", "versement employeur",
    "deblocage anticipe", "déblocage anticipé",
    "cas de deblocage", "cas de déblocage",
    "teneur de comptes", "gestionnaire d epargne",
    "gestionnaire d'épargne",
    "fcpe", "fonds commun de placement",
    "article l3332", "l.3332",
    "article l3334", "l.3334",
    "interessement verse", "intéressement versé",
    "supplement d interessement", "supplément d'intéressement",
    "plafond d abondement", "plafond d'abondement",
]

_KW_LICENCIEMENT = [
    "lettre de licenciement", "notification de licenciement",
    "licenciement pour motif", "licenciement economique",
    "licenciement économique",
    "licenciement pour faute", "faute grave", "faute lourde",
    "cause reelle et serieuse", "cause réelle et sérieuse",
    "preavis", "préavis", "indemnite de licenciement",
    "indemnité de licenciement",
    "entretien prealable", "entretien préalable",
    "article l1232", "l.1232",
    "article l1233", "l.1233",
    "plan de sauvegarde", "pse ",
]

_KW_FORMATION = [
    "plan de formation", "plan de developpement",
    "plan de développement",
    "attestation de formation", "certificat de formation",
    "compte personnel de formation", "cpf",
    "organisme de formation", "action de formation",
    "convention de formation",
    "bilan de competences", "bilan de compétences",
    "validation des acquis", "vae ",
    "qualiopi", "datadock",
    "programme de formation", "feuille de presence",
    "feuille de présence",
    "article l6311", "l.6311",
]

_KW_MUTUELLE_PREVOYANCE = [
    "contrat de mutuelle", "contrat de prevoyance",
    "contrat de prévoyance",
    "complementaire sante", "complémentaire santé",
    "garantie frais de sante", "garantie frais de santé",
    "decision unilaterale", "décision unilatérale",
    "due employeur", "accord collectif mutuelle",
    "portabilite", "portabilité",
    "article l911-1", "l.911-1",
    "garantie deces", "garantie décès",
    "garantie incapacite", "garantie incapacité",
    "garantie invalidite", "garantie invalidité",
    "indemnites journalieres", "indemnités journalières",
    "organisme assureur",
]

_KW_LETTRE_MISSION = [
    "lettre de mission", "mission d audit",
    "mission d'audit", "mission de revision",
    "mission de révision", "expert comptable",
    "expert-comptable", "ordre des experts",
    "diligences professionnelles",
    "normes professionnelles",
    "honoraires de l expert", "responsabilite de l expert",
]

_KW_DSN = [
    "declaration sociale nominative", "déclaration sociale nominative",
    "dsn mensuelle", "dsn evenementielle", "dsn événementielle",
    "norme neodes", "norme néodès", "bloc s21",
    "s21.g00", "s20.g00", "declaration dsn",
    "dsn phase 3", "dsn signalement", "arret de travail",
    "fin de contrat", "reprise anticipee",
    "cahier technique dsn", "numero de declaration",
]


# ============================================================
# EXTRACTION REGEX PATTERNS
# ============================================================

# Employee identification
_RE_NOM_PRENOM = re.compile(
    r"(?:nom\s*(?:et\s*)?prenom|nom\s*prenom|salari[eé])\s*[:\s]*"
    r"([A-Z\u00C0-\u00FF][A-Za-z\u00C0-\u00FF\s-]+)",
    re.IGNORECASE,
)
_RE_NOM = re.compile(
    r"(?:nom|NOM)\s*[:\s]+\s*([A-Z\u00C0-\u00FF][A-Z\u00C0-\u00FF\s'-]+)",
    re.IGNORECASE,
)
_RE_PRENOM = re.compile(
    r"(?:pr[eé]nom|PRENOM)\s*[:\s]+\s*([A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF'-]+)",
    re.IGNORECASE,
)
_RE_NIR = re.compile(
    r"\b([12]\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2})\b",
)
_RE_SIRET = re.compile(r"SIRET\s*[:\s]*(\d[\d\s]{12}\d)", re.IGNORECASE)
_RE_SIREN = re.compile(r"SIREN\s*[:\s]*(\d{9})", re.IGNORECASE)
_RE_NAF = re.compile(r"(?:NAF|APE)\s*[:\s]*(\d{4}[A-Z])", re.IGNORECASE)

# Employee status
_RE_CADRE = re.compile(r"\bcadre\b", re.IGNORECASE)
_RE_APPRENTI = re.compile(r"(?:apprenti|apprentissage|alternance|alternant|contrat\s*pro)", re.IGNORECASE)
_RE_EMPLOI = re.compile(r"(?:emploi|poste|fonction|qualification)\s*[:\s]+\s*(.+?)(?:\n|$)", re.IGNORECASE)
_RE_CLASSIFICATION = re.compile(r"(?:classification|coefficient|echelon|niveau)\s*[:\s]+\s*(.+?)(?:\n|$)", re.IGNORECASE)

# Amounts
_RE_BRUT = re.compile(
    r"(?:salaire\s*brut|remuneration\s*brut|brut\s*mensuel|total\s*brut|brut\s*du\s*mois"
    r"|brut\s*soumis|remun[eé]ration\s*brut)"
    r"\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_NET_A_PAYER = re.compile(
    r"(?:net\s*[aà]\s*payer|net\s*pay[eé]|montant\s*net\s*vers[eé])"
    r"\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_NET_IMPOSABLE = re.compile(
    r"(?:net\s*imposable|net\s*fiscal|cumul\s*net\s*imposable)"
    r"\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_NET_AVANT_IMPOT = re.compile(
    r"(?:net\s*avant\s*imp[oô]t|net\s*avant\s*pr[eé]l[eè]vement)"
    r"\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_TOTAL_PATRONAL = re.compile(
    r"total\s+(?:cotisations?\s+)?(?:patronales?|employeur)\s*[:\s]*([\d\s,.]+)",
    re.IGNORECASE,
)
_RE_TOTAL_SALARIAL = re.compile(
    r"total\s+(?:cotisations?\s+)?(?:salariales?|salari[eé])\s*[:\s]*([\d\s,.]+)",
    re.IGNORECASE,
)

# Employer name
_RE_RAISON_SOCIALE = re.compile(
    r"(?:raison\s*sociale|soci[eé]t[eé]|entreprise|employeur)\s*[:\s]+\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)

# Period
_RE_PERIODE_MOIS_ANNEE = re.compile(
    r"(?:p[eé]riode|mois|paie\s*du|bulletin\s*du|mois\s*de)\s*[:\s]*"
    r"(\d{1,2})\s*[/.\-]\s*(\d{4})",
    re.IGNORECASE,
)
_RE_PERIODE_TEXTE = re.compile(
    r"(?:p[eé]riode|mois|paie\s*du|bulletin\s*du|mois\s*de)\s*[:\s]*"
    r"(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre)"
    r"\s*(\d{4})",
    re.IGNORECASE,
)
_MOIS_MAP = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}
_RE_DATE_VIREMENT = re.compile(
    r"(?:date\s*(?:de\s*)?(?:virement|paiement|versement|r[eè]glement))\s*[:\s]*"
    r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})",
    re.IGNORECASE,
)

# Date embauche
_RE_DATE_EMBAUCHE = re.compile(
    r"(?:date\s*(?:d\s*)?(?:entr[eé]e|embauche|d[eé]but))\s*[:\s]*"
    r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})",
    re.IGNORECASE,
)

# Facture amounts
_RE_MONTANT_HT = re.compile(
    r"(?:montant|total)\s*(?:hors\s*taxe|ht|h\.t\.?)\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_MONTANT_TVA = re.compile(
    r"(?:montant|total)\s*(?:tva|t\.v\.a\.?)\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)
_RE_MONTANT_TTC = re.compile(
    r"(?:montant|total|net\s*[aà]\s*payer)\s*(?:ttc|t\.t\.c\.?|toutes\s*taxes)\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)

# Contrat fields
_RE_TYPE_CONTRAT = re.compile(
    r"contrat\s*(?:[aà]\s*dur[eé]e\s*)?(ind[eé]termin[eé]e|d[eé]termin[eé]e|cdi|cdd)",
    re.IGNORECASE,
)
_RE_REMUNERATION = re.compile(
    r"(?:r[eé]mun[eé]ration|salaire)\s*(?:mensuel(?:le)?|annuel(?:le)?|brut(?:e)?)?\s*[:\s]?\s*([\d\s]+[.,]\d{2})",
    re.IGNORECASE,
)

# Cotisation line patterns (for table rows in bulletins)
_COTISATION_PATTERNS = [
    (re.compile(r"maladie", re.I), ContributionType.MALADIE),
    (re.compile(r"vieillesse\s*plaf", re.I), ContributionType.VIEILLESSE_PLAFONNEE),
    (re.compile(r"vieillesse\s*d[eé]plaf", re.I), ContributionType.VIEILLESSE_DEPLAFONNEE),
    (re.compile(r"vieillesse(?!\s*(?:plaf|d[eé]plaf))", re.I), ContributionType.VIEILLESSE_PLAFONNEE),
    (re.compile(r"alloc.*famil", re.I), ContributionType.ALLOCATIONS_FAMILIALES),
    (re.compile(r"accident.*travail|at[/.]?mp", re.I), ContributionType.ACCIDENT_TRAVAIL),
    (re.compile(r"csg\s*d[eé]duct", re.I), ContributionType.CSG_DEDUCTIBLE),
    (re.compile(r"csg\s*(?:non|imp)", re.I), ContributionType.CSG_NON_DEDUCTIBLE),
    (re.compile(r"csg(?!\s*(?:d[eé]duct|non|imp))", re.I), ContributionType.CSG_DEDUCTIBLE),
    (re.compile(r"crds", re.I), ContributionType.CRDS),
    (re.compile(r"ch[oô]mage|assurance\s*ch", re.I), ContributionType.ASSURANCE_CHOMAGE),
    (re.compile(r"\bags\b", re.I), ContributionType.AGS),
    (re.compile(r"retraite\s*compl.*t1|agirc.*t1|arrco.*t1", re.I), ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
    (re.compile(r"retraite\s*compl.*t2|agirc.*t2|arrco.*t2", re.I), ContributionType.RETRAITE_COMPLEMENTAIRE_T2),
    (re.compile(r"retraite\s*compl|agirc|arrco|compl[eé]mentaire", re.I), ContributionType.RETRAITE_COMPLEMENTAIRE_T1),
    (re.compile(r"fnal", re.I), ContributionType.FNAL),
    (re.compile(r"formation\s*pro", re.I), ContributionType.FORMATION_PROFESSIONNELLE),
    (re.compile(r"taxe\s*apprenti", re.I), ContributionType.TAXE_APPRENTISSAGE),
    (re.compile(r"transport|mobilit[eé]|versement\s*mobilit", re.I), ContributionType.VERSEMENT_MOBILITE),
    (re.compile(r"pr[eé]voyance", re.I), ContributionType.PREVOYANCE_CADRE),
    (re.compile(r"mutuelle|compl[eé]mentaire\s*sant[eé]", re.I), ContributionType.PREVOYANCE_NON_CADRE),
]

_RE_MONTANT_NUM = re.compile(r"([\d\s]+[.,]\d{2})")


def _parse_montant_local(s: str) -> Decimal:
    """Parse un montant texte en Decimal."""
    s = s.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def _count_keywords(texte_lower: str, keywords: list[str]) -> int:
    """Compte le nombre de mots-cles trouves dans le texte."""
    return sum(1 for kw in keywords if kw in texte_lower)


class PDFParser(BaseParser):
    """Parse les fichiers PDF avec detection automatique du type de document."""

    def peut_traiter(self, chemin: Path) -> bool:
        return chemin.suffix.lower() == ".pdf"

    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        if not HAS_PDFPLUMBER:
            return {"format": "pdf", "erreur": "pdfplumber non installe"}
        try:
            with pdfplumber.open(chemin) as pdf:
                return {
                    "format": "pdf",
                    "nb_pages": len(pdf.pages),
                    "metadata_pdf": pdf.metadata or {},
                }
        except Exception as e:
            return {"format": "pdf", "erreur": str(e)}

    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        if not HAS_PDFPLUMBER:
            raise ParseError("pdfplumber n'est pas installe. Installer avec: pip install pdfplumber")

        try:
            with pdfplumber.open(chemin) as pdf:
                texte_complet = ""
                tableaux = []
                for page in pdf.pages:
                    texte_complet += (page.extract_text() or "") + "\n"
                    tables = page.extract_tables()
                    if tables:
                        tableaux.extend(tables)
        except Exception as e:
            raise ParseError(f"Impossible de lire le PDF {chemin}: {e}") from e

        if not texte_complet.strip():
            return []

        # Detect document type from content
        doc_type = self._detecter_type_document(texte_complet, chemin.name)

        if doc_type == "bulletin":
            return self._parser_bulletin(texte_complet, tableaux, document)
        elif doc_type == "livre_de_paie":
            return self._parser_livre_de_paie(texte_complet, tableaux, document)
        elif doc_type == "facture":
            return self._parser_facture(texte_complet, document)
        elif doc_type == "contrat":
            return self._parser_contrat(texte_complet, document)
        elif doc_type == "interessement":
            return self._parser_interessement(texte_complet, document)
        elif doc_type == "attestation":
            return self._parser_attestation(texte_complet, document)
        elif doc_type == "accord":
            return self._parser_accord(texte_complet, document)
        elif doc_type == "pv_ag":
            return self._parser_pv_ag(texte_complet, document)
        elif doc_type == "contrat_service":
            return self._parser_contrat_service(texte_complet, document)
        # --- Fiscal ---
        elif doc_type in ("liasse_fiscale", "declaration_tva", "declaration_is", "das2",
                          "taxe_salaires", "cfe_cvae", "fec", "releve_frais_generaux",
                          "avis_imposition", "bordereau_urssaf"):
            return self._parser_fiscal(texte_complet, document, doc_type)
        # --- Comptable ---
        elif doc_type in ("bilan", "compte_resultat", "rapport_cac", "rapport_gestion", "budget"):
            return self._parser_comptable(texte_complet, document, doc_type)
        # --- Social / RH ---
        elif doc_type in ("dpae", "registre_personnel", "duerp", "reglement_interieur",
                          "avenant", "bilan_social", "rupture_conventionnelle",
                          "cse", "france_travail", "medecine_travail",
                          "epargne_salariale", "licenciement", "formation",
                          "mutuelle_prevoyance", "dsn"):
            return self._parser_social_rh(texte_complet, document, doc_type)
        # --- Juridique ---
        elif doc_type in ("statuts", "kbis", "bail", "assurance", "lettre_mission"):
            return self._parser_juridique(texte_complet, document, doc_type)
        # --- Commercial ---
        elif doc_type in ("devis", "avoir", "bon_commande", "note_frais",
                          "releve_bancaire", "cerfa"):
            return self._parser_commercial(texte_complet, document, doc_type)
        else:
            return self._parser_generique(texte_complet, tableaux, document)

    def _detecter_type_document(self, texte: str, filename: str = "") -> str:
        """Detecte le type de document via analyse du contenu et du nom de fichier."""
        texte_lower = texte.lower()
        fname_lower = filename.lower()

        # All document type keyword lists
        _ALL_KW = {
            "bulletin": _KW_BULLETIN,
            "facture": _KW_FACTURE,
            "contrat": _KW_CONTRAT,
            "livre_de_paie": _KW_LDP,
            "interessement": _KW_INTERESSEMENT,
            "attestation": _KW_ATTESTATION,
            "accord": _KW_ACCORD,
            "pv_ag": _KW_PV_AG,
            "contrat_service": _KW_CONTRAT_SERVICE,
            # Fiscal
            "liasse_fiscale": _KW_LIASSE_FISCALE,
            "declaration_tva": _KW_DECLARATION_TVA,
            "declaration_is": _KW_DECLARATION_IS,
            "das2": _KW_DAS2,
            "taxe_salaires": _KW_TAXE_SALAIRES,
            "cfe_cvae": _KW_CFE_CVAE,
            "fec": _KW_FEC,
            "releve_frais_generaux": _KW_RELEVE_FRAIS_GENERAUX,
            "avis_imposition": _KW_AVIS_IMPOSITION,
            "bordereau_urssaf": _KW_BORDEREAU_URSSAF,
            # Comptable
            "bilan": _KW_BILAN,
            "compte_resultat": _KW_COMPTE_RESULTAT,
            "rapport_cac": _KW_RAPPORT_CAC,
            "rapport_gestion": _KW_RAPPORT_GESTION,
            "budget": _KW_BUDGET,
            # Social / RH
            "dpae": _KW_DPAE,
            "registre_personnel": _KW_REGISTRE_PERSONNEL,
            "duerp": _KW_DUERP,
            "reglement_interieur": _KW_REGLEMENT_INTERIEUR,
            "avenant": _KW_AVENANT,
            "bilan_social": _KW_BILAN_SOCIAL,
            "note_frais": _KW_NOTE_FRAIS,
            "rupture_conventionnelle": _KW_RUPTURE_CONVENTIONNELLE,
            "cse": _KW_CSE,
            "france_travail": _KW_FRANCE_TRAVAIL,
            "medecine_travail": _KW_MEDECINE_TRAVAIL,
            "epargne_salariale": _KW_EPARGNE_SALARIALE,
            "licenciement": _KW_LICENCIEMENT,
            "formation": _KW_FORMATION,
            "mutuelle_prevoyance": _KW_MUTUELLE_PREVOYANCE,
            "dsn": _KW_DSN,
            # Juridique
            "statuts": _KW_STATUTS,
            "kbis": _KW_KBIS,
            "bail": _KW_BAIL,
            "assurance": _KW_ASSURANCE,
            "releve_bancaire": _KW_RELEVE_BANCAIRE,
            # Commercial
            "devis": _KW_DEVIS,
            "avoir": _KW_AVOIR,
            "bon_commande": _KW_BON_COMMANDE,
            "cerfa": _KW_CERFA,
            "lettre_mission": _KW_LETTRE_MISSION,
        }

        scores = {k: _count_keywords(texte_lower, v) for k, v in _ALL_KW.items()}

        # Filename hints (strong boost)
        fname_hints = {
            "bulletin": ["bulletin", "paie", "salaire", "fiche_paie", "bp_", "bul_"],
            "facture": ["facture", "invoice", "fac_", "fact_"],
            "contrat": ["contrat_travail", "cdi", "cdd", "embauche"],
            "livre_de_paie": ["livre_de_paie", "ldp", "recapitulatif", "recap"],
            "interessement": ["interessement", "participation", "epargne", "pee"],
            "attestation": ["attestation", "certificat", "solde"],
            "accord": ["accord", "nao", "gpec", "qvt", "negociation"],
            "pv_ag": ["pv_ag", "proces_verbal", "assemblee", "ag_"],
            "contrat_service": ["prestation", "sous_traitance", "cgv"],
            # Fiscal
            "liasse_fiscale": ["liasse", "2050", "2051", "2065", "2031"],
            "declaration_tva": ["tva", "ca3", "ca12", "3310"],
            "declaration_is": ["is_", "impot_societes", "2065"],
            "das2": ["das2", "honoraires"],
            "taxe_salaires": ["taxe_salaires", "2502"],
            "cfe_cvae": ["cfe", "cvae", "cet_"],
            "fec": ["fec_", "ecritures_comptables"],
            "releve_frais_generaux": ["frais_generaux", "2067"],
            "avis_imposition": ["avis_imposition", "impot_revenu", "taxe_fonciere"],
            "bordereau_urssaf": ["bordereau_urssaf", "appel_cotisation", "urssaf_"],
            # Comptable
            "bilan": ["bilan", "comptes_annuels"],
            "compte_resultat": ["compte_resultat", "resultat"],
            "rapport_cac": ["rapport_cac", "commissaire", "certification"],
            "rapport_gestion": ["rapport_gestion", "rapport_annuel"],
            "budget": ["budget", "previsionnel", "business_plan"],
            # Social / RH
            "dpae": ["dpae", "due_"],
            "registre_personnel": ["registre", "personnel", "effectif"],
            "duerp": ["duerp", "duer", "document_unique", "risques"],
            "reglement_interieur": ["reglement_interieur", "ri_"],
            "avenant": ["avenant"],
            "bilan_social": ["bilan_social"],
            "note_frais": ["note_frais", "frais_deplacement", "ndf"],
            "rupture_conventionnelle": ["rupture_conv", "rc_", "homologation"],
            "cse": ["cse_", "pv_cse", "comite_social", "reunion_cse"],
            "france_travail": ["france_travail", "pole_emploi", "are_", "attestation_ft"],
            "medecine_travail": ["medecine_travail", "avis_aptitude", "visite_med"],
            "epargne_salariale": ["pee_", "perco_", "per_", "epargne_", "abondement"],
            "licenciement": ["licenciement", "lettre_licenciement", "pse_"],
            "formation": ["formation_", "cpf_", "plan_formation", "attestation_form"],
            "mutuelle_prevoyance": ["mutuelle_", "prevoyance_", "complementaire_sante"],
            "dsn": ["dsn_", "dsn_mensuelle", "dsn_event", "declaration_sociale"],
            # Juridique
            "statuts": ["statuts", "statut_"],
            "kbis": ["kbis", "k_bis", "extrait_rcs"],
            "bail": ["bail", "location"],
            "assurance": ["assurance", "police_", "rc_pro"],
            "releve_bancaire": ["releve_bancaire", "releve_compte"],
            # Commercial
            "devis": ["devis", "proposition"],
            "avoir": ["avoir", "credit_note"],
            "bon_commande": ["bon_commande", "commande", "bc_"],
            "cerfa": ["cerfa"],
            "lettre_mission": ["lettre_mission", "mission_"],
        }
        for doc_type, hints in fname_hints.items():
            if any(h in fname_lower for h in hints):
                scores[doc_type] += 5

        # Pick highest score (minimum 2 to classify)
        best_type = max(scores, key=scores.get)
        if scores[best_type] >= 2:
            return best_type

        # Fallback heuristics
        if _RE_BRUT.search(texte) and (_RE_NET_A_PAYER.search(texte) or _RE_NET_IMPOSABLE.search(texte)):
            return "bulletin"
        if _RE_MONTANT_HT.search(texte) and _RE_MONTANT_TTC.search(texte):
            return "facture"
        if _RE_TYPE_CONTRAT.search(texte):
            return "contrat"

        return "inconnu"

    # ============================================================
    # BULLETIN DE PAIE
    # ============================================================

    def _parser_bulletin(self, texte: str, tableaux: list, document: Document) -> list[Declaration]:
        """Parse un bulletin de paie avec extraction complete."""
        doc_id = document.id

        # --- Employeur ---
        employeur = self._extraire_employeur(texte, doc_id)

        # --- Employe ---
        emp = self._extraire_employe(texte, doc_id)

        # --- Brut / Net ---
        brut = Decimal("0")
        m = _RE_BRUT.search(texte)
        if m:
            brut = _parse_montant_local(m.group(1))

        net_a_payer = Decimal("0")
        m = _RE_NET_A_PAYER.search(texte)
        if m:
            net_a_payer = _parse_montant_local(m.group(1))

        net_imposable = Decimal("0")
        m = _RE_NET_IMPOSABLE.search(texte)
        if m:
            net_imposable = _parse_montant_local(m.group(1))

        net_avant_impot = Decimal("0")
        m = _RE_NET_AVANT_IMPOT.search(texte)
        if m:
            net_avant_impot = _parse_montant_local(m.group(1))

        total_patronal = Decimal("0")
        m = _RE_TOTAL_PATRONAL.search(texte)
        if m:
            total_patronal = parser_montant(m.group(1))

        total_salarial = Decimal("0")
        m = _RE_TOTAL_SALARIAL.search(texte)
        if m:
            total_salarial = parser_montant(m.group(1))

        # --- Periode ---
        periode = self._extraire_periode(texte)

        # --- Date de virement ---
        date_virement = None
        m = _RE_DATE_VIREMENT.search(texte)
        if m:
            try:
                date_virement = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except (ValueError, TypeError):
                pass

        # --- Date embauche ---
        m = _RE_DATE_EMBAUCHE.search(texte)
        if m:
            try:
                emp.date_embauche = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except (ValueError, TypeError):
                pass

        # --- Fallback nom depuis le nom de fichier ---
        if not emp.nom and document.nom_fichier:
            stem = Path(document.nom_fichier).stem
            parts = re.split(r'[_\-\s]+', stem)
            excluded_fn = {"bulletin", "paie", "salaire", "fiche", "bp", "bs",
                           "pdf", "janv", "fev", "mars", "avr", "mai", "juin",
                           "juil", "aout", "sept", "oct", "nov", "dec"}
            for p in parts:
                if (len(p) >= 3 and p.isalpha()
                        and p.lower() not in excluded_fn
                        and not p.isdigit()):
                    emp.nom = p.upper()
                    break

        # --- Cotisations ---
        cotisations = self._extraire_cotisations_bulletin(texte, tableaux, doc_id, emp.id, brut)

        # If no cotisations found from text/tables but we have total amounts, create synthetic ones
        if not cotisations and (total_patronal > 0 or total_salarial > 0 or brut > 0):
            cotisations = self._generer_cotisations_synthetiques(
                brut, total_patronal, total_salarial, doc_id, emp.id, periode,
            )

        # --- Masse salariale ---
        if brut <= 0 and cotisations:
            brut = max(c.base_brute for c in cotisations)

        # If still no brut but net_a_payer is known, estimate brut
        if brut <= 0 and net_a_payer > 0:
            brut = Decimal(str(round(float(net_a_payer) / 0.78, 2)))

        # Store metadata
        metadata = {
            "type_document": "bulletin_de_paie",
            "net_a_payer": float(net_a_payer),
            "net_imposable": float(net_imposable),
            "net_avant_impot": float(net_avant_impot),
            "total_patronal": float(total_patronal),
            "total_salarial": float(total_salarial),
        }
        if date_virement:
            metadata["date_virement"] = date_virement.isoformat()

        decl = Declaration(
            type_declaration="bulletin",
            reference=document.nom_fichier,
            periode=periode,
            employeur=employeur,
            employes=[emp],
            cotisations=cotisations,
            masse_salariale_brute=brut,
            effectif_declare=1,
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    # ============================================================
    # LIVRE DE PAIE / RECAPITULATIF
    # ============================================================

    def _parser_livre_de_paie(self, texte: str, tableaux: list, document: Document) -> list[Declaration]:
        """Parse un livre de paie ou recapitulatif multi-salaries."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)
        periode = self._extraire_periode(texte)

        # Extract multiple employees from tables or text
        employes = []
        cotisations_all = []

        # Try extracting from tables first
        for table in tableaux:
            if len(table) < 2:
                continue
            header = [str(c).lower().strip() if c else "" for c in table[0]]

            # Detect employee name column
            col_nom = col_brut = col_net = col_pat = col_sal = -1
            for i, h in enumerate(header):
                if any(kw in h for kw in ["nom", "salari", "employ"]):
                    col_nom = i
                elif any(kw in h for kw in ["brut"]):
                    col_brut = i
                elif any(kw in h for kw in ["net"]):
                    col_net = i
                elif any(kw in h for kw in ["patronal", "employeur"]):
                    col_pat = i
                elif any(kw in h for kw in ["salarial", "salari"]):
                    col_sal = i

            if col_nom < 0:
                continue

            for row in table[1:]:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue
                if col_nom < len(row) and row[col_nom]:
                    nom_complet = str(row[col_nom]).strip()
                    if not nom_complet or nom_complet.lower() in ("total", "totaux", "sous-total"):
                        continue
                    parts = nom_complet.split(None, 1)
                    emp = Employe(
                        nom=parts[0] if parts else nom_complet,
                        prenom=parts[1] if len(parts) > 1 else "",
                        source_document_id=doc_id,
                    )
                    employes.append(emp)

                    brut_val = Decimal("0")
                    if col_brut >= 0 and col_brut < len(row) and row[col_brut]:
                        brut_val = parser_montant(str(row[col_brut]))

                    if brut_val > 0:
                        cot = Cotisation(
                            type_cotisation=ContributionType.MALADIE,
                            base_brute=brut_val,
                            assiette=brut_val,
                            employe_id=emp.id,
                            source_document_id=doc_id,
                        )
                        if col_pat >= 0 and col_pat < len(row) and row[col_pat]:
                            cot.montant_patronal = parser_montant(str(row[col_pat]))
                        if col_sal >= 0 and col_sal < len(row) and row[col_sal]:
                            cot.montant_salarial = parser_montant(str(row[col_sal]))
                        cotisations_all.append(cot)

        # Fallback: try regex-based multi-employee extraction
        if not employes:
            nirs = list(_RE_NIR.finditer(texte))
            bruts = list(_RE_BRUT.finditer(texte))
            if nirs:
                for m in nirs:
                    emp = Employe(
                        nir=m.group(1).replace(" ", ""),
                        source_document_id=doc_id,
                    )
                    employes.append(emp)
            elif bruts and len(bruts) > 1:
                for i, m in enumerate(bruts):
                    emp = Employe(
                        nom=f"Salarie {i + 1}",
                        source_document_id=doc_id,
                    )
                    brut = _parse_montant_local(m.group(1))
                    cot = Cotisation(
                        type_cotisation=ContributionType.MALADIE,
                        base_brute=brut,
                        assiette=brut,
                        employe_id=emp.id,
                        source_document_id=doc_id,
                    )
                    employes.append(emp)
                    cotisations_all.append(cot)

        # Extract overall cotisations from tables
        cotisations_all.extend(self._extraire_cotisations_tableaux_generiques(tableaux, doc_id))

        # Total masse salariale
        masse = Decimal("0")
        m = re.search(
            r"(?:masse\s*salariale|total\s*(?:g[eé]n[eé]ral|brut))\s*[:\s]*([\d\s]+[.,]\d{2})",
            texte, re.IGNORECASE,
        )
        if m:
            masse = _parse_montant_local(m.group(1))
        elif cotisations_all:
            masse = sum(c.base_brute for c in cotisations_all)

        decl = Declaration(
            type_declaration="livre_de_paie",
            reference=document.nom_fichier,
            periode=periode,
            employeur=employeur,
            employes=employes,
            cotisations=cotisations_all,
            masse_salariale_brute=masse,
            effectif_declare=len(employes),
            source_document_id=doc_id,
            metadata={"type_document": "livre_de_paie"},
        )
        return [decl]

    # ============================================================
    # FACTURE
    # ============================================================

    def _parser_facture(self, texte: str, document: Document) -> list[Declaration]:
        """Parse une facture (achat ou vente)."""
        doc_id = document.id

        montant_ht = Decimal("0")
        m = _RE_MONTANT_HT.search(texte)
        if m:
            montant_ht = _parse_montant_local(m.group(1))

        montant_tva = Decimal("0")
        m = _RE_MONTANT_TVA.search(texte)
        if m:
            montant_tva = _parse_montant_local(m.group(1))

        montant_ttc = Decimal("0")
        m = _RE_MONTANT_TTC.search(texte)
        if m:
            montant_ttc = _parse_montant_local(m.group(1))

        # Try to detect if it's a purchase or sale invoice
        texte_lower = texte.lower()
        is_achat = "facture d'achat" in texte_lower or "fournisseur" in texte_lower
        type_facture = "facture_achat" if is_achat else "facture_vente"

        employeur = self._extraire_employeur(texte, doc_id)

        # Extract the supplier/client name
        m = re.search(
            r"(?:fournisseur|client|destinataire|adresse[eé]\s*[aà])\s*[:\s]+\s*(.+?)(?:\n|$)",
            texte, re.IGNORECASE,
        )
        tiers_nom = m.group(1).strip() if m else ""

        # Extract facture number
        m = re.search(
            r"(?:facture|invoice)\s*(?:n[°o]?|numero|#)\s*[:\s]?\s*([A-Z0-9][\w-]+)",
            texte, re.IGNORECASE,
        )
        num_facture = m.group(1).strip() if m else ""

        decl = Declaration(
            type_declaration="facture",
            reference=num_facture or document.nom_fichier,
            employeur=employeur,
            masse_salariale_brute=Decimal("0"),
            source_document_id=doc_id,
            metadata={
                "type_document": type_facture,
                "montant_ht": float(montant_ht),
                "montant_tva": float(montant_tva),
                "montant_ttc": float(montant_ttc),
                "tiers": tiers_nom,
                "numero_facture": num_facture,
            },
        )
        return [decl]

    # ============================================================
    # CONTRAT DE TRAVAIL
    # ============================================================

    def _parser_contrat(self, texte: str, document: Document) -> list[Declaration]:
        """Parse un contrat de travail."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)
        emp = self._extraire_employe(texte, doc_id)

        # Type de contrat
        type_contrat = "CDI"
        m = _RE_TYPE_CONTRAT.search(texte)
        if m:
            val = m.group(1).lower()
            if "indetermin" in val or "cdi" in val:
                type_contrat = "CDI"
            elif "determin" in val or "cdd" in val:
                type_contrat = "CDD"

        # Remuneration
        brut = Decimal("0")
        m = _RE_REMUNERATION.search(texte)
        if m:
            brut = _parse_montant_local(m.group(1))
        if brut <= 0:
            m = _RE_BRUT.search(texte)
            if m:
                brut = _parse_montant_local(m.group(1))

        # Date embauche
        m = _RE_DATE_EMBAUCHE.search(texte)
        if m:
            try:
                emp.date_embauche = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except (ValueError, TypeError):
                pass

        decl = Declaration(
            type_declaration="contrat",
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[emp],
            masse_salariale_brute=brut,
            effectif_declare=1,
            source_document_id=doc_id,
            metadata={
                "type_document": "contrat_de_travail",
                "type_contrat": type_contrat,
                "remuneration_brute": float(brut),
            },
        )
        return [decl]

    # ============================================================
    # ACCORD D'INTERESSEMENT / PARTICIPATION
    # ============================================================

    def _parser_interessement(self, texte: str, document: Document) -> list[Declaration]:
        """Parse un accord d'interessement ou participation."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)

        texte_lower = texte.lower()
        is_participation = "participation" in texte_lower and "interessement" not in texte_lower
        type_accord = "participation" if is_participation else "interessement"

        decl = Declaration(
            type_declaration=type_accord,
            reference=document.nom_fichier,
            employeur=employeur,
            source_document_id=doc_id,
            metadata={"type_document": f"accord_{type_accord}"},
        )
        return [decl]

    # ============================================================
    # ATTESTATION
    # ============================================================

    def _parser_attestation(self, texte: str, document: Document) -> list[Declaration]:
        """Parse une attestation employeur ou certificat de travail."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)
        emp = self._extraire_employe(texte, doc_id)

        brut = Decimal("0")
        m = _RE_BRUT.search(texte)
        if m:
            brut = _parse_montant_local(m.group(1))

        decl = Declaration(
            type_declaration="attestation",
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[emp] if emp.nom else [],
            masse_salariale_brute=brut,
            source_document_id=doc_id,
            metadata={"type_document": "attestation"},
        )
        return [decl]

    # ============================================================
    # GENERIQUE (FALLBACK)
    # ============================================================

    def _parser_generique(self, texte: str, tableaux: list, document: Document) -> list[Declaration]:
        """Parsing generique quand le type de document n'est pas determine."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)
        emp = self._extraire_employe(texte, doc_id)
        periode = self._extraire_periode(texte)

        cotisations = self._extraire_cotisations_bulletin(texte, tableaux, doc_id, emp.id if emp.nom else "", Decimal("0"))
        cotisations.extend(self._extraire_cotisations_tableaux_generiques(tableaux, doc_id))

        brut = Decimal("0")
        m = _RE_BRUT.search(texte)
        if m:
            brut = _parse_montant_local(m.group(1))
        elif cotisations:
            brut = max(c.base_brute for c in cotisations)

        employes = [emp] if (emp.nom or emp.nir) else []

        decl = Declaration(
            type_declaration="PDF",
            reference=document.nom_fichier,
            periode=periode,
            employeur=employeur,
            employes=employes,
            cotisations=cotisations,
            masse_salariale_brute=brut,
            effectif_declare=len(employes),
            source_document_id=doc_id,
            metadata={"type_document": "inconnu"},
        )
        return [decl]

    # ============================================================
    # ACCORD D'ENTREPRISE
    # ============================================================

    def _parser_accord(self, texte: str, document: Document) -> list[Declaration]:
        """Parse un accord d'entreprise (NAO, GPEC, QVT, teletravail, etc.)."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)

        # Extract accord specifics
        texte_lower = texte.lower()
        accord_type = "accord_entreprise"
        if "nao" in texte_lower or "negociation annuelle" in texte_lower:
            accord_type = "accord_nao"
        elif "gpec" in texte_lower or "gestion previsionnelle" in texte_lower:
            accord_type = "accord_gpec"
        elif "teletravail" in texte_lower or "télétravail" in texte_lower:
            accord_type = "accord_teletravail"
        elif "egalite" in texte_lower or "égalité" in texte_lower:
            accord_type = "accord_egalite"
        elif "temps de travail" in texte_lower or "amenagement" in texte_lower:
            accord_type = "accord_temps_travail"
        elif "interessement" in texte_lower or "intéressement" in texte_lower:
            accord_type = "accord_interessement"
        elif "participation" in texte_lower:
            accord_type = "accord_participation"

        # Extract convention collective reference
        ccn = ""
        m = re.search(r"(?:convention collective|ccn|idcc)\s*[:\s]*([^\n,;]+)", texte, re.IGNORECASE)
        if m:
            ccn = m.group(1).strip()[:100]

        # Extract date
        date_accord = ""
        m = re.search(r"(?:fait le|signe le|en date du|le)\s+(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
        if m:
            date_accord = m.group(1)

        # Extract signataires
        signataires = []
        for m in re.finditer(r"(?:pour|signe par|represente par)\s+([A-Z\u00C0-\u00FF][A-Za-z\u00C0-\u00FF\s-]+)", texte):
            sig = m.group(1).strip()[:60]
            if sig and sig not in signataires:
                signataires.append(sig)

        metadata = {
            "type_document": accord_type,
            "convention_collective": ccn,
            "date_accord": date_accord,
            "signataires": signataires,
        }

        decl = Declaration(
            type_declaration="accord",
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[],
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    # ============================================================
    # PV D'ASSEMBLEE GENERALE
    # ============================================================

    def _parser_pv_ag(self, texte: str, document: Document) -> list[Declaration]:
        """Parse un proces-verbal d'assemblee generale."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)

        texte_lower = texte.lower()
        ag_type = "pv_ag"
        if "extraordinaire" in texte_lower:
            ag_type = "pv_age"
        elif "ordinaire" in texte_lower:
            ag_type = "pv_ago"

        # Extract date
        date_ag = ""
        m = re.search(r"(?:tenue le|en date du|du)\s+(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
        if m:
            date_ag = m.group(1)

        # Extract resolutions
        resolutions = []
        for m in re.finditer(r"(?:resolution|résolution)\s*(?:n[°o]?\s*)?(\d+)", texte, re.IGNORECASE):
            resolutions.append(int(m.group(1)))

        # Extract key financial info
        resultat = Decimal("0")
        m = re.search(r"(?:resultat|résultat|benefice|bénéfice|perte)\s*(?:de l exercice|net)?\s*[:\s]*(-?[\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
        if m:
            resultat = _parse_montant_local(m.group(1))

        dividendes = Decimal("0")
        m = re.search(r"(?:dividende|distribution)\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
        if m:
            dividendes = _parse_montant_local(m.group(1))

        metadata = {
            "type_document": ag_type,
            "date_ag": date_ag,
            "nb_resolutions": len(resolutions),
            "resolutions": resolutions[:20],
            "resultat_exercice": float(resultat),
            "dividendes": float(dividendes),
        }

        decl = Declaration(
            type_declaration="pv_ag",
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[],
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    # ============================================================
    # CONTRAT DE PRESTATION / SERVICE
    # ============================================================

    def _parser_contrat_service(self, texte: str, document: Document) -> list[Declaration]:
        """Parse un contrat de prestation de services."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)

        # Extract prestataire info
        prestataire = ""
        m = re.search(r"(?:prestataire|fournisseur|sous.?traitant)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
        if m:
            prestataire = m.group(1).strip()[:100]

        # Extract montant
        montant = Decimal("0")
        m = re.search(r"(?:montant|prix|forfait|cout|coût)\s*(?:global|total|ht)?\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
        if m:
            montant = _parse_montant_local(m.group(1))

        # Extract duree
        duree = ""
        m = re.search(r"(?:duree|durée|pour une duree|pour une durée)\s*(?:de|d)?\s*([^\n,;.]+)", texte, re.IGNORECASE)
        if m:
            duree = m.group(1).strip()[:60]

        # Extract objet
        objet = ""
        m = re.search(r"(?:objet|a pour objet)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
        if m:
            objet = m.group(1).strip()[:200]

        metadata = {
            "type_document": "contrat_service",
            "prestataire": prestataire,
            "montant_ht": float(montant),
            "duree": duree,
            "objet": objet,
        }

        decl = Declaration(
            type_declaration="contrat_service",
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[],
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    # ============================================================
    # FISCAL (liasse, TVA, IS, DAS2, taxe salaires, CFE/CVAE, FEC, frais generaux)
    # ============================================================

    def _parser_fiscal(self, texte: str, document: Document, doc_type: str) -> list[Declaration]:
        """Parse un document fiscal (liasse, declaration TVA/IS, DAS2, etc.)."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)
        texte_lower = texte.lower()

        metadata = {"type_document": doc_type}

        # Extract common fiscal fields
        # Exercice
        m = re.search(r"(?:exercice|periode|année)\s*(?:du|clos)?\s*[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\s*(?:au|a|à)\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
        if m:
            metadata["exercice_debut"] = m.group(1)
            metadata["exercice_fin"] = m.group(2)

        # Cerfa number
        m = re.search(r"cerfa\s*(?:n[°o]?)?\s*(\d{4,5})", texte, re.IGNORECASE)
        if m:
            metadata["cerfa_numero"] = m.group(1)

        # Main amounts
        for label, key in [
            (r"(?:resultat|résultat)\s*(?:fiscal|net|de l exercice)", "resultat"),
            (r"(?:chiffre\s*d\s*affaires|ca\s*net)", "chiffre_affaires"),
            (r"(?:total\s*actif|actif\s*total)", "total_actif"),
            (r"(?:total\s*passif|passif\s*total)", "total_passif"),
            (r"(?:benefice|bénéfice)\s*(?:imposable|fiscal)?", "benefice"),
            (r"(?:deficit|déficit)\s*(?:reportable)?", "deficit"),
            (r"(?:tva\s*collectee|tva\s*collectée)", "tva_collectee"),
            (r"(?:tva\s*deductible|tva\s*déductible)", "tva_deductible"),
            (r"(?:tva\s*nette|tva\s*a\s*payer|tva\s*à\s*payer)", "tva_nette"),
            (r"(?:credit\s*de\s*tva|crédit\s*de\s*tva)", "credit_tva"),
            (r"(?:base\s*imposable)", "base_imposable"),
            (r"(?:montant\s*de\s*l\s*impot|montant\s*de\s*l\s*impôt|impot\s*du|impôt\s*dû)", "montant_impot"),
        ]:
            m = re.search(label + r"\s*[:\s]*([\-]?[\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata[key] = float(_parse_montant_local(m.group(1)))

        # Avis d'imposition specific
        if doc_type == "avis_imposition":
            m = re.search(r"(?:revenu\s*fiscal\s*de\s*reference|revenu\s*fiscal\s*de\s*référence)\s*[:\s]*([\d\s]+(?:[.,]\d+)?)", texte, re.IGNORECASE)
            if m:
                metadata["revenu_fiscal_reference"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:montant\s*de\s*l\s*impot|montant\s*de\s*l\s*impôt|montant\s*net\s*a\s*payer)\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["montant_impot"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:annee|année|revenus\s*de\s*l\s*annee|revenus\s*de\s*l\s*année)\s*[:\s]*(\d{4})", texte, re.IGNORECASE)
            if m:
                metadata["annee_revenus"] = m.group(1)

        # Bordereau URSSAF specific
        if doc_type == "bordereau_urssaf":
            m = re.search(r"(?:total\s*des\s*cotisations|cotisations\s*dues|montant\s*a\s*payer|montant\s*à\s*payer)\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["total_cotisations"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:periode|période)\s*(?:d\s*emploi)?\s*[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\s*(?:au|a|à)\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
            if m:
                metadata["periode_debut"] = m.group(1)
                metadata["periode_fin"] = m.group(2)
            ctps = re.findall(r"(?:ctp|code\s*type)\s*(\d{3,4})", texte, re.IGNORECASE)
            metadata["codes_ctp"] = list(set(ctps))[:20]

        # DAS2 specific: count beneficiaires
        if doc_type == "das2":
            beneficiaires = re.findall(r"(?:beneficiaire|bénéficiaire)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            metadata["nb_beneficiaires"] = len(beneficiaires)
            total_hon = re.search(r"(?:total\s*(?:des\s*)?honoraires|total\s*verse|total\s*versé)\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if total_hon:
                metadata["total_honoraires"] = float(_parse_montant_local(total_hon.group(1)))

        decl = Declaration(
            type_declaration=doc_type,
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[],
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    # ============================================================
    # COMPTABLE (bilan, compte de resultat, rapport CAC/gestion, budget)
    # ============================================================

    def _parser_comptable(self, texte: str, document: Document, doc_type: str) -> list[Declaration]:
        """Parse un document comptable (bilan, compte de resultat, rapport, budget)."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)

        metadata = {"type_document": doc_type}

        # Exercice
        m = re.search(r"(?:exercice|periode|année)\s*(?:du|clos)?\s*[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
        if m:
            metadata["exercice"] = m.group(1)

        # Key financial amounts
        for label, key in [
            (r"(?:total\s*actif|actif\s*total)", "total_actif"),
            (r"(?:total\s*passif|passif\s*total)", "total_passif"),
            (r"(?:capitaux\s*propres|fonds\s*propres)", "capitaux_propres"),
            (r"(?:resultat\s*net|résultat\s*net)", "resultat_net"),
            (r"(?:resultat\s*d\s*exploitation|résultat\s*d\s*exploitation)", "resultat_exploitation"),
            (r"(?:chiffre\s*d\s*affaires|chiffre\s*d'affaires)", "chiffre_affaires"),
            (r"(?:excedent\s*brut|excédent\s*brut|ebe|ebitda)", "ebe"),
            (r"(?:endettement|dettes\s*financieres|dettes\s*financières)", "endettement"),
            (r"(?:tresorerie|trésorerie)\s*(?:nette)?", "tresorerie"),
            (r"(?:dividende|distribution)", "dividendes"),
        ]:
            m = re.search(label + r"\s*[:\s]*([\-]?[\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata[key] = float(_parse_montant_local(m.group(1)))

        # Rapport CAC: opinion
        if doc_type == "rapport_cac":
            if "certifie" in texte.lower() or "certifié" in texte.lower():
                if "reserve" in texte.lower() or "réserve" in texte.lower():
                    metadata["opinion"] = "certification_avec_reserves"
                elif "refus" in texte.lower():
                    metadata["opinion"] = "refus_de_certifier"
                else:
                    metadata["opinion"] = "certification_sans_reserve"

        decl = Declaration(
            type_declaration=doc_type,
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[],
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    # ============================================================
    # SOCIAL / RH (DPAE, registre, DUERP, reglement interieur, avenant, bilan social)
    # ============================================================

    def _parser_social_rh(self, texte: str, document: Document, doc_type: str) -> list[Declaration]:
        """Parse un document social/RH."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)

        metadata = {"type_document": doc_type}
        employes = []

        if doc_type == "dpae":
            emp = self._extraire_employe(texte, doc_id)
            if emp.nom or emp.nir:
                employes.append(emp)
            m = re.search(r"(?:date\s*(?:d\s*)?embauche|date\s*d\s*entree|date\s*d\s*entrée)\s*[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
            if m:
                metadata["date_embauche"] = m.group(1)
            m = _RE_TYPE_CONTRAT.search(texte)
            if m:
                metadata["type_contrat"] = m.group(1).upper()

        elif doc_type == "registre_personnel":
            # Try to count listed employees
            nirs = list(_RE_NIR.finditer(texte))
            noms = list(re.finditer(r"(?:^|\n)\s*\d+\s*[|.)\s]+\s*([A-Z\u00C0-\u00FF]{2,})\s+([A-Za-z\u00C0-\u00FF]+)", texte))
            for m in noms[:50]:
                emp = Employe(nom=m.group(1).strip(), prenom=m.group(2).strip(), source_document_id=doc_id)
                employes.append(emp)
            if not employes and nirs:
                for m in nirs[:50]:
                    emp = Employe(nir=m.group(1).replace(" ", ""), source_document_id=doc_id)
                    employes.append(emp)
            metadata["effectif_detecte"] = len(employes)

        elif doc_type == "avenant":
            emp = self._extraire_employe(texte, doc_id)
            if emp.nom or emp.nir:
                employes.append(emp)
            m = re.search(r"(?:avenant\s*n[°o]?\s*)(\d+)", texte, re.IGNORECASE)
            if m:
                metadata["numero_avenant"] = m.group(1)
            m = _RE_REMUNERATION.search(texte)
            if m:
                metadata["nouvelle_remuneration"] = float(_parse_montant_local(m.group(1)))

        elif doc_type == "duerp":
            # Count risk units
            unites = re.findall(r"(?:unite|unité)\s*(?:de\s*)?travail\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            metadata["nb_unites_travail"] = len(unites)
            risques = re.findall(r"(?:risque|danger)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            metadata["nb_risques_identifies"] = len(risques)

        elif doc_type == "bilan_social":
            # Extract key indicators
            for label, key in [
                (r"effectif\s*moyen", "effectif_moyen"),
                (r"(?:taux\s*d\s*)?absenteisme|absentéisme", "taux_absenteisme"),
                (r"(?:taux\s*de\s*)?turnover|rotation", "taux_turnover"),
                (r"accidents?\s*(?:du\s*)?travail", "nb_at"),
            ]:
                m = re.search(label + r"\s*[:\s]*([\d\s]+(?:[.,]\d+)?)", texte, re.IGNORECASE)
                if m:
                    try:
                        metadata[key] = float(m.group(1).replace(" ", "").replace(",", "."))
                    except ValueError:
                        pass

        elif doc_type == "rupture_conventionnelle":
            emp = self._extraire_employe(texte, doc_id)
            if emp.nom or emp.nir:
                employes.append(emp)
            m = re.search(r"(?:indemnite|indemnité)\s*(?:specifique|spécifique|de\s*rupture)?\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["indemnite_rupture"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:date\s*(?:de\s*)?(?:rupture|fin\s*(?:du\s*)?contrat))\s*[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
            if m:
                metadata["date_rupture"] = m.group(1)
            m = re.search(r"(?:anciennete|ancienneté)\s*[:\s]*([^\n,;]+)", texte, re.IGNORECASE)
            if m:
                metadata["anciennete"] = m.group(1).strip()[:60]
            metadata["homologuee"] = "homologation" in texte.lower() or "homologuee" in texte.lower() or "homologuée" in texte.lower()

        elif doc_type == "cse":
            texte_lower = texte.lower()
            cse_type = "pv_cse"
            if "budget" in texte_lower:
                cse_type = "budget_cse"
            elif "rapport" in texte_lower and "activit" in texte_lower:
                cse_type = "rapport_cse"
            elif "election" in texte_lower or "élection" in texte_lower:
                cse_type = "elections_cse"
            metadata["sous_type"] = cse_type
            m = re.search(r"(?:reunion|réunion)\s*(?:du|en\s*date\s*du)\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
            if m:
                metadata["date_reunion"] = m.group(1)
            # Participants count
            participants = re.findall(r"(?:present|présent|membre)\s*[:\s]*([A-Z\u00C0-\u00FF][A-Za-z\u00C0-\u00FF\s-]+)", texte)
            metadata["nb_participants"] = len(set(p.strip()[:50] for p in participants))
            # Deliberations
            deliberations = re.findall(r"(?:deliberation|délibération|resolution|résolution|point\s*\d+)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            metadata["nb_deliberations"] = len(deliberations)
            # Budgets
            for label, key in [
                (r"budget\s*(?:de\s*)?fonctionnement", "budget_fonctionnement"),
                (r"(?:budget\s*)?activites?\s*sociales|(?:budget\s*)?asc", "budget_asc"),
            ]:
                m = re.search(label + r"\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
                if m:
                    metadata[key] = float(_parse_montant_local(m.group(1)))

        elif doc_type == "france_travail":
            emp = self._extraire_employe(texte, doc_id)
            if emp.nom or emp.nir:
                employes.append(emp)
            texte_lower = texte.lower()
            ft_type = "decision_france_travail"
            if "are" in texte_lower or "allocation" in texte_lower:
                ft_type = "attestation_are"
            elif "radiation" in texte_lower:
                ft_type = "radiation"
            elif "inscription" in texte_lower:
                ft_type = "inscription"
            elif "autorisation" in texte_lower and "licenciement" in texte_lower:
                ft_type = "autorisation_licenciement"
            elif "contrat de securisation" in texte_lower or "csp" in texte_lower:
                ft_type = "csp"
            metadata["sous_type"] = ft_type
            m = re.search(r"(?:montant\s*(?:journalier|mensuel|de\s*l\s*allocation))\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["montant_allocation"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:date\s*(?:d\s*)?effet|a\s*compter\s*du)\s*[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
            if m:
                metadata["date_effet"] = m.group(1)

        elif doc_type == "medecine_travail":
            emp = self._extraire_employe(texte, doc_id)
            if emp.nom or emp.nir:
                employes.append(emp)
            texte_lower = texte.lower()
            if "inapt" in texte_lower:
                metadata["resultat"] = "inapte"
            elif "apte" in texte_lower:
                if "restriction" in texte_lower or "amenagement" in texte_lower or "aménagement" in texte_lower:
                    metadata["resultat"] = "apte_avec_restrictions"
                else:
                    metadata["resultat"] = "apte"
            visite_type = "visite_medicale"
            if "reprise" in texte_lower:
                visite_type = "visite_reprise"
            elif "pre-reprise" in texte_lower or "pré-reprise" in texte_lower:
                visite_type = "visite_pre_reprise"
            elif "embauche" in texte_lower:
                visite_type = "visite_embauche"
            elif "information et de prevention" in texte_lower or "information et de prévention" in texte_lower:
                visite_type = "vip"
            metadata["type_visite"] = visite_type
            m = re.search(r"(?:date\s*(?:de\s*la\s*)?visite|examine le|examiné le)\s*[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
            if m:
                metadata["date_visite"] = m.group(1)
            m = re.search(r"(?:medecin|médecin|docteur|dr\.?)\s*[:\s]*([A-Z\u00C0-\u00FF][A-Za-z\u00C0-\u00FF\s-]+)", texte)
            if m:
                metadata["medecin"] = m.group(1).strip()[:60]

        elif doc_type == "epargne_salariale":
            texte_lower = texte.lower()
            plan_type = "epargne_salariale"
            if "pee" in texte_lower or "plan d epargne entreprise" in texte_lower or "plan d'épargne entreprise" in texte_lower:
                plan_type = "pee"
            elif "perco" in texte_lower or "percol" in texte_lower:
                plan_type = "perco"
            elif "per collectif" in texte_lower or "per obligatoire" in texte_lower:
                plan_type = "per"
            metadata["type_plan"] = plan_type
            m = re.search(r"(?:abondement)\s*(?:maximum|max|plafond)?\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["abondement_max"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:gestionnaire|teneur\s*de\s*comptes?)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            if m:
                metadata["gestionnaire"] = m.group(1).strip()[:80]

        elif doc_type == "licenciement":
            emp = self._extraire_employe(texte, doc_id)
            if emp.nom or emp.nir:
                employes.append(emp)
            texte_lower = texte.lower()
            motif = "personnel"
            if "economique" in texte_lower or "économique" in texte_lower:
                motif = "economique"
            elif "faute lourde" in texte_lower:
                motif = "faute_lourde"
            elif "faute grave" in texte_lower:
                motif = "faute_grave"
            elif "insuffisance" in texte_lower:
                motif = "insuffisance"
            metadata["motif"] = motif
            m = re.search(r"(?:indemnite|indemnité)\s*(?:de\s*)?(?:licenciement|rupture)\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["indemnite_licenciement"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:preavis|préavis)\s*[:\s]*([^\n,;.]+)", texte, re.IGNORECASE)
            if m:
                metadata["preavis"] = m.group(1).strip()[:60]
            m = re.search(r"(?:date\s*(?:de\s*)?(?:notification|fin\s*(?:du\s*)?contrat))\s*[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
            if m:
                metadata["date_notification"] = m.group(1)

        elif doc_type == "formation":
            texte_lower = texte.lower()
            form_type = "formation"
            if "attestation" in texte_lower:
                form_type = "attestation_formation"
            elif "bilan de competences" in texte_lower or "bilan de compétences" in texte_lower:
                form_type = "bilan_competences"
            elif "vae" in texte_lower or "validation des acquis" in texte_lower:
                form_type = "vae"
            elif "plan de formation" in texte_lower or "plan de developpement" in texte_lower:
                form_type = "plan_formation"
            metadata["sous_type"] = form_type
            m = re.search(r"(?:duree|durée)\s*(?:de\s*la\s*formation)?\s*[:\s]*([^\n,;.]+)", texte, re.IGNORECASE)
            if m:
                metadata["duree"] = m.group(1).strip()[:60]
            m = re.search(r"(?:organisme)\s*(?:de\s*formation)?\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            if m:
                metadata["organisme"] = m.group(1).strip()[:80]
            emp = self._extraire_employe(texte, doc_id)
            if emp.nom or emp.nir:
                employes.append(emp)

        elif doc_type == "dsn":
            texte_lower = texte.lower()
            dsn_type = "dsn_mensuelle"
            if "evenementielle" in texte_lower or "événementielle" in texte_lower or "signalement" in texte_lower:
                dsn_type = "dsn_evenementielle"
            elif "fin de contrat" in texte_lower:
                dsn_type = "dsn_fin_contrat"
            elif "arret" in texte_lower or "arrêt" in texte_lower:
                dsn_type = "dsn_arret_travail"
            metadata["sous_type"] = dsn_type
            # Extract DSN period
            m = re.search(r"(?:periode|période|mois)\s*[:\s]*(\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
            if m:
                metadata["periode"] = m.group(1)
            # Extract block references S21.G00
            blocs = re.findall(r"(S2[01]\.G\d{2}\.\d{2}\.\d{3})", texte)
            if blocs:
                metadata["blocs_dsn"] = list(set(blocs))[:20]
            # Extract effectif
            m = re.search(r"(?:effectif|salaries|salariés)\s*[:\s]*(\d+)", texte, re.IGNORECASE)
            if m:
                metadata["effectif"] = int(m.group(1))
            # Extract NIRs
            nirs = list(_RE_NIR.finditer(texte))
            for m_nir in nirs[:50]:
                emp = Employe(nir=m_nir.group(1).replace(" ", ""), source_document_id=doc_id)
                employes.append(emp)
            metadata["nb_salaries_dsn"] = len(employes)

        elif doc_type == "mutuelle_prevoyance":
            texte_lower = texte.lower()
            mp_type = "mutuelle"
            if "prevoyance" in texte_lower or "prévoyance" in texte_lower:
                mp_type = "prevoyance"
            elif "decision unilaterale" in texte_lower or "décision unilatérale" in texte_lower:
                mp_type = "due_mutuelle"
            metadata["sous_type"] = mp_type
            m = re.search(r"(?:organisme|assureur|compagnie)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            if m:
                metadata["organisme"] = m.group(1).strip()[:80]
            m = re.search(r"(?:cotisation|prime)\s*(?:mensuelle|annuelle)?\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["cotisation"] = float(_parse_montant_local(m.group(1)))
            # Taux de prise en charge employeur
            m = re.search(r"(?:employeur|patronal)\s*[:\s]*(\d+)\s*%", texte, re.IGNORECASE)
            if m:
                metadata["part_employeur_pct"] = int(m.group(1))

        brut = Decimal("0")
        if doc_type in ("dpae", "avenant", "rupture_conventionnelle", "licenciement"):
            m = _RE_BRUT.search(texte)
            if m:
                brut = _parse_montant_local(m.group(1))
            elif doc_type == "avenant":
                m = _RE_REMUNERATION.search(texte)
                if m:
                    brut = _parse_montant_local(m.group(1))

        decl = Declaration(
            type_declaration=doc_type,
            reference=document.nom_fichier,
            employeur=employeur,
            employes=employes,
            masse_salariale_brute=brut,
            effectif_declare=len(employes),
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    # ============================================================
    # JURIDIQUE (statuts, Kbis, bail, assurance, lettre de mission)
    # ============================================================

    def _parser_juridique(self, texte: str, document: Document, doc_type: str) -> list[Declaration]:
        """Parse un document juridique."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)

        metadata = {"type_document": doc_type}

        if doc_type == "statuts":
            m = re.search(r"(?:denomination|dénomination)\s*(?:sociale)?\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            if m:
                metadata["denomination"] = m.group(1).strip()[:100]
            m = re.search(r"(?:capital\s*social)\s*[:\s]*([\d\s]+(?:[.,]\d+)?)\s*(?:euros|EUR|€)", texte, re.IGNORECASE)
            if m:
                metadata["capital_social"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:objet\s*social)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            if m:
                metadata["objet_social"] = m.group(1).strip()[:200]
            m = re.search(r"(?:siege\s*social|siège\s*social)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            if m:
                metadata["siege_social"] = m.group(1).strip()[:150]
            # Forme juridique
            m = re.search(r"(?:sarl|sas|sa |eurl|sci|snc|sasu|societe\s*[aà]\s*responsabilite|société\s*[aà]\s*responsabilité|societe\s*anonyme|société\s*anonyme|societe\s*par\s*actions|société\s*par\s*actions)", texte, re.IGNORECASE)
            if m:
                metadata["forme_juridique"] = m.group(0).strip().upper()

        elif doc_type == "kbis":
            m = re.search(r"(?:rcs|r\.c\.s\.?)\s*(?:de\s*)?([^\n,]+)", texte, re.IGNORECASE)
            if m:
                metadata["rcs"] = m.group(1).strip()[:60]
            m = re.search(r"(?:date\s*d\s*immatriculation)\s*[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})", texte, re.IGNORECASE)
            if m:
                metadata["date_immatriculation"] = m.group(1)
            m = re.search(r"(?:forme\s*juridique)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            if m:
                metadata["forme_juridique"] = m.group(1).strip()[:60]

        elif doc_type == "bail":
            m = re.search(r"(?:loyer)\s*(?:mensuel|trimestriel|annuel)?\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["loyer"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:duree|durée)\s*(?:du\s*bail)?\s*[:\s]*([^\n,;.]+)", texte, re.IGNORECASE)
            if m:
                metadata["duree_bail"] = m.group(1).strip()[:60]
            m = re.search(r"(?:depot\s*de\s*garantie|dépôt\s*de\s*garantie)\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["depot_garantie"] = float(_parse_montant_local(m.group(1)))

        elif doc_type == "assurance":
            m = re.search(r"(?:prime)\s*(?:annuelle|mensuelle)?\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["prime"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:franchise)\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["franchise"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:assureur|compagnie)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            if m:
                metadata["assureur"] = m.group(1).strip()[:80]

        elif doc_type == "lettre_mission":
            m = re.search(r"(?:expert[\s-]?comptable|cabinet)\s*[:\s]*([^\n]+)", texte, re.IGNORECASE)
            if m:
                metadata["cabinet"] = m.group(1).strip()[:80]
            m = re.search(r"(?:honoraires)\s*(?:annuels?)?\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["honoraires"] = float(_parse_montant_local(m.group(1)))

        decl = Declaration(
            type_declaration=doc_type,
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[],
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    # ============================================================
    # COMMERCIAL (devis, avoir, bon de commande, note de frais, releve bancaire, cerfa)
    # ============================================================

    def _parser_commercial(self, texte: str, document: Document, doc_type: str) -> list[Declaration]:
        """Parse un document commercial."""
        doc_id = document.id
        employeur = self._extraire_employeur(texte, doc_id)

        metadata = {"type_document": doc_type}

        # Common: montant HT/TTC/TVA
        m = _RE_MONTANT_HT.search(texte)
        if m:
            metadata["montant_ht"] = float(_parse_montant_local(m.group(1)))
        m = _RE_MONTANT_TVA.search(texte)
        if m:
            metadata["montant_tva"] = float(_parse_montant_local(m.group(1)))
        m = _RE_MONTANT_TTC.search(texte)
        if m:
            metadata["montant_ttc"] = float(_parse_montant_local(m.group(1)))

        if doc_type == "note_frais":
            emp = self._extraire_employe(texte, doc_id)
            employes = [emp] if (emp.nom or emp.nir) else []
            # Total frais
            m = re.search(r"(?:total|montant\s*total)\s*(?:des\s*frais)?\s*[:\s]*([\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["total_frais"] = float(_parse_montant_local(m.group(1)))

            decl = Declaration(
                type_declaration=doc_type,
                reference=document.nom_fichier,
                employeur=employeur,
                employes=employes,
                source_document_id=doc_id,
                metadata=metadata,
            )
            return [decl]

        elif doc_type == "releve_bancaire":
            # Extract soldes
            m = re.search(r"(?:ancien\s*solde|solde\s*(?:au|en)\s*debut|solde\s*initial)\s*[:\s]*([\-]?[\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["solde_initial"] = float(_parse_montant_local(m.group(1)))
            m = re.search(r"(?:nouveau\s*solde|solde\s*(?:au|en)\s*fin|solde\s*final)\s*[:\s]*([\-]?[\d\s]+[.,]\d{2})", texte, re.IGNORECASE)
            if m:
                metadata["solde_final"] = float(_parse_montant_local(m.group(1)))
            # Count operations
            ops = re.findall(r"\d{2}[/.-]\d{2}[/.-]\d{2,4}\s+.+?\s+[\-]?[\d\s]+[.,]\d{2}", texte)
            metadata["nb_operations"] = len(ops)

        elif doc_type == "devis":
            m = re.search(r"(?:devis|proposition)\s*(?:n[°o]?\s*)?[:\s]*([A-Z0-9][\w\-]+)", texte, re.IGNORECASE)
            if m:
                metadata["numero_devis"] = m.group(1)
            m = re.search(r"(?:validite|validité)\s*[:\s]*([^\n,;]+)", texte, re.IGNORECASE)
            if m:
                metadata["validite"] = m.group(1).strip()[:40]

        elif doc_type == "avoir":
            m = re.search(r"(?:avoir|credit\s*note)\s*(?:n[°o]?\s*)?[:\s]*([A-Z0-9][\w\-]+)", texte, re.IGNORECASE)
            if m:
                metadata["numero_avoir"] = m.group(1)
            m = re.search(r"(?:facture\s*(?:d\s*)?origine|reference\s*facture|référence\s*facture)\s*[:\s]*([A-Z0-9][\w\-]+)", texte, re.IGNORECASE)
            if m:
                metadata["facture_origine"] = m.group(1)

        elif doc_type == "bon_commande":
            m = re.search(r"(?:commande|bon\s*de\s*commande)\s*(?:n[°o]?\s*)?[:\s]*([A-Z0-9][\w\-]+)", texte, re.IGNORECASE)
            if m:
                metadata["numero_commande"] = m.group(1)

        elif doc_type == "cerfa":
            m = re.search(r"cerfa\s*(?:n[°o]?\s*)?(\d{4,5}(?:\*\d+)?)", texte, re.IGNORECASE)
            if m:
                metadata["cerfa_numero"] = m.group(1)
            m = re.search(r"(?:annee|année|exercice)\s*[:\s]*(\d{4})", texte, re.IGNORECASE)
            if m:
                metadata["annee"] = m.group(1)

        decl = Declaration(
            type_declaration=doc_type,
            reference=document.nom_fichier,
            employeur=employeur,
            employes=[],
            source_document_id=doc_id,
            metadata=metadata,
        )
        return [decl]

    # ============================================================
    # SHARED EXTRACTION HELPERS
    # ============================================================

    def _extraire_employeur(self, texte: str, doc_id: str) -> Employeur:
        """Extrait les informations de l'employeur."""
        employeur = Employeur(source_document_id=doc_id)

        m = _RE_SIRET.search(texte)
        if m:
            siret = m.group(1).replace(" ", "")
            employeur.siret = siret
            employeur.siren = siret[:9]
        else:
            m = _RE_SIREN.search(texte)
            if m:
                employeur.siren = m.group(1)

        m = _RE_RAISON_SOCIALE.search(texte)
        if m:
            employeur.raison_sociale = m.group(1).strip()[:100]

        m = _RE_NAF.search(texte)
        if m:
            employeur.code_naf = m.group(1)

        return employeur

    def _extraire_employe(self, texte: str, doc_id: str) -> Employe:
        """Extrait les informations du salarie."""
        emp = Employe(source_document_id=doc_id)

        # NIR
        m = _RE_NIR.search(texte)
        if m:
            emp.nir = m.group(1).replace(" ", "")

        # Try combined nom+prenom first
        m = _RE_NOM_PRENOM.search(texte)
        if m:
            full = m.group(1).strip()
            parts = full.split(None, 1)
            if len(parts) >= 2:
                emp.nom = parts[0].strip()
                emp.prenom = parts[1].strip()
            else:
                emp.nom = full
        else:
            # Try separate nom and prenom
            m = _RE_NOM.search(texte)
            if m:
                emp.nom = m.group(1).strip()
            m = _RE_PRENOM.search(texte)
            if m:
                emp.prenom = m.group(1).strip()

        # If no name found, try to infer from text patterns
        if not emp.nom:
            # Pattern: "M./Mme/Mr LASTNAME Firstname"
            m = re.search(
                r"(?:M\.|Mme|Mr|Mlle|Madame|Monsieur)\s+([A-Z\u00C0-\u00FF][A-Z\u00C0-\u00FF'-]+)"
                r"\s+([A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF'-]+)",
                texte,
            )
            if m:
                emp.nom = m.group(1).strip()
                emp.prenom = m.group(2).strip()

        # Pattern: "Matricule: xxx" followed by "LASTNAME Firstname" on next line
        if not emp.nom:
            m = re.search(
                r"(?:matricule|n[°o]\s*salari[eé]|identifiant)\s*[:\s]*\w+\s*\n\s*"
                r"([A-Z\u00C0-\u00FF]{2,})\s+([A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF'-]+)",
                texte, re.IGNORECASE,
            )
            if m:
                emp.nom = m.group(1).strip()
                emp.prenom = m.group(2).strip()

        # Pattern: near "bulletin" or "paie", look for "LASTNAME Firstname" (all-caps last, title-case first)
        if not emp.nom:
            m = re.search(
                r"(?:bulletin|paie|salaire).{0,100}?"
                r"([A-Z\u00C0-\u00FF]{2,}[A-Z\u00C0-\u00FF'-]*)\s+"
                r"([A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF'-]{2,})",
                texte, re.IGNORECASE | re.DOTALL,
            )
            if m:
                cand_nom = m.group(1).strip()
                cand_prenom = m.group(2).strip()
                # Exclude false positives (common words)
                excluded = {"BULLETIN", "SALAIRE", "PAIE", "FICHE", "TOTAL", "BRUT",
                            "SECURITE", "SOCIALE", "SALARIALE", "PATRONALE", "EMPLOI",
                            "PERIODE", "MOIS", "ENTREPRISE", "SIRET", "SIREN", "CODE",
                            "MONTANT", "NET", "PAYER", "COTISATION", "BASE", "TAUX"}
                if cand_nom.upper() not in excluded and len(cand_nom) >= 2:
                    emp.nom = cand_nom
                    emp.prenom = cand_prenom

        # Statut
        if _RE_APPRENTI.search(texte):
            emp.statut = "apprenti"
        elif _RE_CADRE.search(texte):
            emp.statut = "cadre"
        else:
            emp.statut = "non-cadre"

        # Emploi / poste
        m = _RE_EMPLOI.search(texte)
        if m:
            emp.convention_collective = m.group(1).strip()[:80]

        return emp

    def _extraire_periode(self, texte: str) -> Optional[DateRange]:
        """Extrait la periode du document."""
        # Try MM/YYYY format
        m = _RE_PERIODE_MOIS_ANNEE.search(texte)
        if m:
            try:
                mois = int(m.group(1))
                annee = int(m.group(2))
                if 1 <= mois <= 12 and 2000 <= annee <= 2030:
                    debut = date(annee, mois, 1)
                    fin = date(annee, mois, calendar.monthrange(annee, mois)[1])
                    return DateRange(debut=debut, fin=fin)
            except (ValueError, TypeError):
                pass

        # Try "mois de XXXXX YYYY" format
        m = _RE_PERIODE_TEXTE.search(texte)
        if m:
            mois_str = m.group(1).lower()
            mois = _MOIS_MAP.get(mois_str)
            annee = int(m.group(2))
            if mois and 2000 <= annee <= 2030:
                try:
                    debut = date(annee, mois, 1)
                    fin = date(annee, mois, calendar.monthrange(annee, mois)[1])
                    return DateRange(debut=debut, fin=fin)
                except (ValueError, TypeError):
                    pass

        return None

    def _extraire_cotisations_bulletin(
        self, texte: str, tableaux: list, doc_id: str, emp_id: str, brut: Decimal,
    ) -> list[Cotisation]:
        """Extrait les cotisations d'un bulletin de paie (texte + tableaux)."""
        cotisations = []
        seen_types = set()

        # 1. Try table-based extraction (more reliable)
        for table in tableaux:
            if len(table) < 2:
                continue
            header = [str(c).lower().strip() if c else "" for c in table[0]]

            # Find column indices
            col_type = col_base = col_taux_p = col_taux_s = col_mt_p = col_mt_s = -1
            for i, h in enumerate(header):
                if any(kw in h for kw in ["libell", "type", "cotisation", "designation", "d\xe9signation", "rubrique"]):
                    col_type = i
                elif any(kw in h for kw in ["base", "assiette", "brut"]):
                    col_base = i
                elif "taux" in h and ("patron" in h or "employ" in h or "part p" in h):
                    col_taux_p = i
                elif "taux" in h and ("salari" in h or "part s" in h):
                    col_taux_s = i
                elif "taux" in h and col_taux_p < 0:
                    col_taux_p = i
                elif any(kw in h for kw in ["montant", "part"]) and ("patron" in h or "employ" in h):
                    col_mt_p = i
                elif any(kw in h for kw in ["montant", "part"]) and ("salari" in h):
                    col_mt_s = i
                elif "montant" in h and col_mt_p < 0:
                    col_mt_p = i

            if col_type < 0:
                continue

            for row in table[1:]:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue
                if col_type >= len(row) or not row[col_type]:
                    continue
                label = str(row[col_type]).lower().strip()
                if not label or label in ("total", "totaux", "sous-total"):
                    continue

                ct = None
                for pattern, ctype in _COTISATION_PATTERNS:
                    if pattern.search(label):
                        ct = ctype
                        break
                if ct is None:
                    continue
                if ct.value in seen_types:
                    continue
                seen_types.add(ct.value)

                c = Cotisation(
                    type_cotisation=ct,
                    employe_id=emp_id,
                    source_document_id=doc_id,
                )
                if col_base >= 0 and col_base < len(row) and row[col_base]:
                    c.base_brute = parser_montant(str(row[col_base]))
                    c.assiette = c.base_brute
                elif brut > 0:
                    c.base_brute = brut
                    c.assiette = brut
                if col_taux_p >= 0 and col_taux_p < len(row) and row[col_taux_p]:
                    c.taux_patronal = parser_montant(str(row[col_taux_p]))
                    if c.taux_patronal > 1:
                        c.taux_patronal = c.taux_patronal / 100
                if col_taux_s >= 0 and col_taux_s < len(row) and row[col_taux_s]:
                    c.taux_salarial = parser_montant(str(row[col_taux_s]))
                    if c.taux_salarial > 1:
                        c.taux_salarial = c.taux_salarial / 100
                if col_mt_p >= 0 and col_mt_p < len(row) and row[col_mt_p]:
                    c.montant_patronal = parser_montant(str(row[col_mt_p]))
                if col_mt_s >= 0 and col_mt_s < len(row) and row[col_mt_s]:
                    c.montant_salarial = parser_montant(str(row[col_mt_s]))
                if c.base_brute > 0 or c.montant_patronal > 0 or c.montant_salarial > 0:
                    cotisations.append(c)

        # 2. Text-based extraction (fallback or complement)
        lignes = texte.split("\n")
        for ligne in lignes:
            for pattern, ct in _COTISATION_PATTERNS:
                if ct.value in seen_types:
                    continue
                if pattern.search(ligne):
                    montants = _RE_MONTANT_NUM.findall(ligne)
                    if montants:
                        vals = [_parse_montant_local(m) for m in montants]
                        base = brut if brut > 0 else (vals[0] if vals else Decimal("0"))

                        c = Cotisation(
                            type_cotisation=ct,
                            base_brute=base,
                            assiette=base,
                            employe_id=emp_id,
                            source_document_id=doc_id,
                        )

                        if len(vals) >= 5:
                            # base, taux_p, montant_p, taux_s, montant_s
                            c.base_brute = vals[0]
                            c.assiette = vals[0]
                            c.taux_patronal = vals[1] if vals[1] < 1 else vals[1] / 100
                            c.montant_patronal = vals[2]
                            c.taux_salarial = vals[3] if vals[3] < 1 else vals[3] / 100
                            c.montant_salarial = vals[4]
                        elif len(vals) >= 4:
                            # base, taux, montant_p, montant_s
                            c.base_brute = vals[0]
                            c.assiette = vals[0]
                            c.taux_patronal = vals[1] if vals[1] < 1 else vals[1] / 100
                            c.montant_patronal = vals[2]
                            c.montant_salarial = vals[3]
                        elif len(vals) >= 3:
                            c.base_brute = vals[0]
                            c.assiette = vals[0]
                            c.taux_patronal = vals[1] if vals[1] < 1 else vals[1] / 100
                            c.montant_patronal = vals[2]
                        elif len(vals) >= 2:
                            c.montant_patronal = vals[-1]
                        elif len(vals) == 1:
                            c.montant_patronal = vals[0]

                        seen_types.add(ct.value)
                        cotisations.append(c)
                    break

        return cotisations

    def _extraire_cotisations_tableaux_generiques(self, tableaux: list, doc_id: str) -> list[Cotisation]:
        """Extrait les cotisations depuis les tableaux detectes dans le PDF (methode generique)."""
        cotisations = []
        for table in tableaux:
            if len(table) < 2:
                continue
            header = [str(c).lower().strip() if c else "" for c in table[0]]
            col_type = col_base = col_taux = col_montant = -1

            for i, h in enumerate(header):
                if any(kw in h for kw in ["libell", "type", "cotisation", "designation"]):
                    col_type = i
                elif any(kw in h for kw in ["base", "assiette", "brut"]):
                    col_base = i
                elif any(kw in h for kw in ["taux", "%"]):
                    col_taux = i
                elif any(kw in h for kw in ["montant", "total", "part"]):
                    col_montant = i

            if col_base < 0 and col_montant < 0:
                continue

            for row in table[1:]:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue
                try:
                    c = Cotisation(source_document_id=doc_id)
                    if col_base >= 0 and col_base < len(row) and row[col_base]:
                        c.base_brute = parser_montant(str(row[col_base]))
                        c.assiette = c.base_brute
                    if col_taux >= 0 and col_taux < len(row) and row[col_taux]:
                        c.taux_patronal = parser_montant(str(row[col_taux]))
                        if c.taux_patronal > 1:
                            c.taux_patronal = c.taux_patronal / 100
                    if col_montant >= 0 and col_montant < len(row) and row[col_montant]:
                        c.montant_patronal = parser_montant(str(row[col_montant]))
                    if col_type >= 0 and col_type < len(row) and row[col_type]:
                        type_str = str(row[col_type]).lower()
                        for pattern, ct in _COTISATION_PATTERNS:
                            if pattern.search(type_str):
                                c.type_cotisation = ct
                                break
                    if c.base_brute > 0 or c.montant_patronal > 0:
                        cotisations.append(c)
                except (ValueError, TypeError, IndexError):
                    continue
        return cotisations

    def _generer_cotisations_synthetiques(
        self, brut: Decimal, total_pat: Decimal, total_sal: Decimal,
        doc_id: str, emp_id: str, periode: Optional[DateRange],
    ) -> list[Cotisation]:
        """Genere des cotisations synthetiques a partir des totaux connus."""
        if brut <= 0:
            return []

        cotisations = []
        # Repartition standard des cotisations patronales
        repartition_pat = [
            (ContributionType.MALADIE, Decimal("0.070")),
            (ContributionType.VIEILLESSE_PLAFONNEE, Decimal("0.0855")),
            (ContributionType.VIEILLESSE_DEPLAFONNEE, Decimal("0.019")),
            (ContributionType.ALLOCATIONS_FAMILIALES, Decimal("0.0345")),
            (ContributionType.ASSURANCE_CHOMAGE, Decimal("0.0405")),
            (ContributionType.RETRAITE_COMPLEMENTAIRE_T1, Decimal("0.0472")),
        ]
        repartition_sal = [
            (ContributionType.MALADIE, Decimal("0")),
            (ContributionType.VIEILLESSE_PLAFONNEE, Decimal("0.0690")),
            (ContributionType.VIEILLESSE_DEPLAFONNEE, Decimal("0.004")),
            (ContributionType.CSG_DEDUCTIBLE, Decimal("0.0680")),
            (ContributionType.CRDS, Decimal("0.005")),
            (ContributionType.RETRAITE_COMPLEMENTAIRE_T1, Decimal("0.0315")),
        ]

        # Merge repartitions
        types_done = set()
        for ct_pat, taux_p in repartition_pat:
            taux_s = Decimal("0")
            for ct_sal, ts in repartition_sal:
                if ct_sal == ct_pat:
                    taux_s = ts
                    break
            mt_p = round(brut * taux_p, 2) if total_pat > 0 else Decimal("0")
            mt_s = round(brut * taux_s, 2) if total_sal > 0 else Decimal("0")
            cotisations.append(Cotisation(
                type_cotisation=ct_pat,
                base_brute=brut, assiette=brut,
                taux_patronal=taux_p, taux_salarial=taux_s,
                montant_patronal=mt_p, montant_salarial=mt_s,
                employe_id=emp_id, source_document_id=doc_id,
                periode=periode,
            ))
            types_done.add(ct_pat)

        # Add salary-only contributions not in patronal list
        for ct_sal, taux_s in repartition_sal:
            if ct_sal not in types_done:
                mt_s = round(brut * taux_s, 2)
                cotisations.append(Cotisation(
                    type_cotisation=ct_sal,
                    base_brute=brut, assiette=brut,
                    taux_salarial=taux_s,
                    montant_salarial=mt_s,
                    employe_id=emp_id, source_document_id=doc_id,
                    periode=periode,
                ))

        return cotisations
