"""Verificateur de documents obligatoires et complementaires.

Detecte :
- Documents manquants pour une operation (comptabilisation, declaration, etc.)
- Pieces justificatives absentes
- Incoherences entre documents fournis
- Alertes de conformite reglementaire

Ref : Code de commerce art. L123-12 a L123-28 (obligations comptables)
      CGI art. 286 et s. (obligations fiscales)
      Code du travail art. L3243-1 et s. (bulletin de paie)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TypeOperation(str, Enum):
    """Type d'operation necessitant des documents."""
    COMPTABILISATION_FACTURE = "comptabilisation_facture"
    DECLARATION_TVA = "declaration_tva"
    BULLETIN_PAIE = "bulletin_paie"
    DECLARATION_SOCIALE = "declaration_sociale"
    BILAN_ANNUEL = "bilan_annuel"
    CONTROLE_URSSAF = "controle_urssaf"
    CREATION_ENTREPRISE = "creation_entreprise"
    EMBAUCHE_SALARIE = "embauche_salarie"
    NOTE_FRAIS = "note_frais"
    CLOTURE_EXERCICE = "cloture_exercice"
    INSCRIPTION_INDEPENDANT = "inscription_independant"


class NiveauObligation(str, Enum):
    """Niveau d'obligation du document."""
    OBLIGATOIRE = "obligatoire"
    RECOMMANDE = "recommande"
    OPTIONNEL = "optionnel"


class StatutDocument(str, Enum):
    """Statut d'un document dans le processus."""
    PRESENT = "present"
    MANQUANT = "manquant"
    INCOMPLET = "incomplet"
    NON_CONFORME = "non_conforme"


@dataclass
class DocumentRequis:
    """Document requis pour une operation."""
    nom: str
    description: str
    niveau: NiveauObligation = NiveauObligation.OBLIGATOIRE
    statut: StatutDocument = StatutDocument.MANQUANT
    reference_legale: str = ""
    alternatives: list[str] = field(default_factory=list)
    delai_conservation: str = ""


@dataclass
class AlerteDocument:
    """Alerte sur un document manquant ou non conforme."""
    titre: str
    description: str
    niveau: NiveauObligation
    operation: TypeOperation
    reference_legale: str = ""
    action_requise: str = ""
    delai: str = ""


@dataclass
class ResultatVerification:
    """Resultat complet de la verification documentaire."""
    operation: TypeOperation
    documents_requis: list[DocumentRequis] = field(default_factory=list)
    alertes: list[AlerteDocument] = field(default_factory=list)
    est_complet: bool = False
    taux_completude: float = 0.0
    resume: str = ""


# ===================================================================
# REFERENTIEL DES DOCUMENTS PAR OPERATION
# ===================================================================

DOCUMENTS_PAR_OPERATION = {
    TypeOperation.COMPTABILISATION_FACTURE: [
        DocumentRequis(
            nom="Facture originale",
            description="Facture d'achat ou de vente avec mentions obligatoires (CGI art. 242 nonies A)",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="CGI art. 289, 242 nonies A",
            delai_conservation="10 ans (Code de commerce art. L123-22)",
        ),
        DocumentRequis(
            nom="Bon de livraison / Bon de reception",
            description="Preuve de la livraison des biens ou de la realisation du service",
            niveau=NiveauObligation.RECOMMANDE,
            reference_legale="Code de commerce art. L441-9",
        ),
        DocumentRequis(
            nom="Bon de commande",
            description="Document attestant de la commande initiale",
            niveau=NiveauObligation.RECOMMANDE,
        ),
        DocumentRequis(
            nom="Justificatif de paiement",
            description="Releve bancaire, cheque, bordereau de virement",
            niveau=NiveauObligation.RECOMMANDE,
            alternatives=["Releve bancaire", "Copie cheque", "Bordereau virement"],
        ),
        DocumentRequis(
            nom="Contrat ou devis accepte",
            description="Pour les prestations de services > 1500 EUR",
            niveau=NiveauObligation.RECOMMANDE,
            reference_legale="Code civil art. 1353",
        ),
    ],

    TypeOperation.DECLARATION_TVA: [
        DocumentRequis(
            nom="Factures de vente du mois/trimestre",
            description="Ensemble des factures emises sur la periode",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="CGI art. 287",
        ),
        DocumentRequis(
            nom="Factures d'achat avec TVA deductible",
            description="Factures fournisseurs avec TVA recuperable",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="CGI art. 271",
        ),
        DocumentRequis(
            nom="Releves de comptes bancaires",
            description="Pour controle de coherence avec le CA declare",
            niveau=NiveauObligation.RECOMMANDE,
        ),
        DocumentRequis(
            nom="Journal de ventes",
            description="Recapitulatif des ventes de la periode",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Journal des achats",
            description="Recapitulatif des achats avec TVA",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
    ],

    TypeOperation.BULLETIN_PAIE: [
        DocumentRequis(
            nom="Contrat de travail",
            description="CDI, CDD ou avenant en cours",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="Code du travail art. L1221-1",
            delai_conservation="5 ans apres depart du salarie",
        ),
        DocumentRequis(
            nom="DPAE (Declaration prealable a l'embauche)",
            description="Copie de la DPAE transmise a l'URSSAF",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="Code du travail art. L1221-10",
        ),
        DocumentRequis(
            nom="Fiche de pointage / planning",
            description="Releve des heures effectuees",
            niveau=NiveauObligation.RECOMMANDE,
            reference_legale="Code du travail art. L3171-2",
        ),
        DocumentRequis(
            nom="Justificatifs absences",
            description="Arret maladie, conges, formation...",
            niveau=NiveauObligation.RECOMMANDE,
        ),
        DocumentRequis(
            nom="Convention collective applicable",
            description="Texte de la convention collective en vigueur",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="Code du travail art. L2261-1",
        ),
        DocumentRequis(
            nom="Grille de classification",
            description="Grille de salaire de la convention collective",
            niveau=NiveauObligation.RECOMMANDE,
        ),
    ],

    TypeOperation.DECLARATION_SOCIALE: [
        DocumentRequis(
            nom="DSN (Declaration Sociale Nominative)",
            description="DSN mensuelle du mois M-1",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="CSS art. L133-5-3",
        ),
        DocumentRequis(
            nom="Bulletins de paie du mois",
            description="Ensemble des bulletins de paie generes",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Bordereau URSSAF",
            description="Recapitulatif des cotisations dues",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Attestation de versement",
            description="Preuve du paiement des cotisations",
            niveau=NiveauObligation.RECOMMANDE,
        ),
    ],

    TypeOperation.CONTROLE_URSSAF: [
        DocumentRequis(
            nom="Avis de verification",
            description="Lettre d'avis de controle URSSAF (15 jours avant)",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="CSS art. R243-59",
        ),
        DocumentRequis(
            nom="DADS/DSN des 3 derniers exercices",
            description="Declarations annuelles de donnees sociales",
            niveau=NiveauObligation.OBLIGATOIRE,
            delai_conservation="6 ans (CSS art. L244-3)",
        ),
        DocumentRequis(
            nom="Bulletins de paie (3 ans)",
            description="Ensemble des bulletins de paie des exercices controles",
            niveau=NiveauObligation.OBLIGATOIRE,
            delai_conservation="5 ans (Code du travail art. L3243-4)",
        ),
        DocumentRequis(
            nom="Contrats de travail",
            description="CDI, CDD, avenants des salaries concernes",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Livre de paie ou journal de paie",
            description="Registre des remunerations",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Grand livre comptable",
            description="Comptes de charges sociales (comptes 64x)",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Contrats prevoyance/mutuelle",
            description="Contrats collectifs obligatoires",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="CSS art. L911-7",
        ),
        DocumentRequis(
            nom="Registre unique du personnel",
            description="Registre a jour des entrees/sorties",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="Code du travail art. L1221-13",
        ),
    ],

    TypeOperation.CREATION_ENTREPRISE: [
        DocumentRequis(
            nom="Statuts constitutifs",
            description="Statuts signes de la societe",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="KBIS ou extrait K",
            description="Extrait d'immatriculation RCS",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Piece d'identite du gerant",
            description="CNI ou passeport du representant legal",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Attestation de domiciliation",
            description="Bail, contrat de domiciliation ou attestation",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Attestation de depot de capital",
            description="Attestation de la banque",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Declaration de non-condamnation",
            description="Attestation sur l'honneur du gerant",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Avis de publication JAL",
            description="Annonce legale de constitution",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
    ],

    TypeOperation.EMBAUCHE_SALARIE: [
        DocumentRequis(
            nom="Contrat de travail signe",
            description="CDI ou CDD signe par les deux parties",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="Code du travail art. L1221-1",
        ),
        DocumentRequis(
            nom="DPAE",
            description="Declaration prealable a l'embauche (avant prise de poste)",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="Code du travail art. L1221-10",
        ),
        DocumentRequis(
            nom="Piece d'identite du salarie",
            description="CNI, passeport ou titre de sejour",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Carte vitale / attestation SS",
            description="Numero de securite sociale",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="RIB du salarie",
            description="Pour le versement du salaire",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Visite medicale d'embauche",
            description="Convocation a la visite d'information et de prevention",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="Code du travail art. L4624-1",
        ),
        DocumentRequis(
            nom="Adhesion mutuelle obligatoire",
            description="Bulletin d'adhesion ou dispense",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="CSS art. L911-7",
        ),
    ],

    TypeOperation.NOTE_FRAIS: [
        DocumentRequis(
            nom="Note de frais remplie",
            description="Formulaire avec date, motif, montant",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Justificatifs originaux",
            description="Tickets, facturettes, factures des depenses",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="CGI art. 39-1",
        ),
        DocumentRequis(
            nom="Ordre de mission",
            description="Pour les deplacements professionnels",
            niveau=NiveauObligation.RECOMMANDE,
        ),
        DocumentRequis(
            nom="Attestation de deplacement",
            description="Justificatif du motif professionnel",
            niveau=NiveauObligation.RECOMMANDE,
        ),
    ],

    TypeOperation.CLOTURE_EXERCICE: [
        DocumentRequis(
            nom="Grand livre comptable",
            description="Grand livre de l'exercice complet",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="Code de commerce art. L123-12",
        ),
        DocumentRequis(
            nom="Balance generale",
            description="Balance des comptes en fin d'exercice",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Journal des operations diverses",
            description="Ecritures d'inventaire (provisions, amortissements)",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Inventaire physique des stocks",
            description="Si l'entreprise detient des stocks",
            niveau=NiveauObligation.RECOMMANDE,
            reference_legale="Code de commerce art. L123-12",
        ),
        DocumentRequis(
            nom="Etat des immobilisations et amortissements",
            description="Tableau des immobilisations de l'exercice",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Lettrages des comptes tiers",
            description="Verification des soldes clients/fournisseurs",
            niveau=NiveauObligation.RECOMMANDE,
        ),
        DocumentRequis(
            nom="Rapprochement bancaire",
            description="Rapprochement de tous les comptes bancaires",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="PV d'assemblee generale",
            description="Approbation des comptes par les associes",
            niveau=NiveauObligation.OBLIGATOIRE,
            reference_legale="Code de commerce art. L232-22",
        ),
    ],

    TypeOperation.INSCRIPTION_INDEPENDANT: [
        DocumentRequis(
            nom="Piece d'identite",
            description="CNI ou passeport du travailleur independant",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Justificatif de domicile",
            description="Facture ou attestation de moins de 3 mois",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Formulaire P0 ou M0",
            description="Declaration de debut d'activite",
            niveau=NiveauObligation.OBLIGATOIRE,
        ),
        DocumentRequis(
            nom="Diplome ou qualification",
            description="Si activite reglementee (artisan, profession liberale)",
            niveau=NiveauObligation.RECOMMANDE,
        ),
        DocumentRequis(
            nom="Attestation assurance RC Pro",
            description="Responsabilite civile professionnelle",
            niveau=NiveauObligation.RECOMMANDE,
        ),
    ],
}


class DocumentChecker:
    """Verifie la completude des documents pour une operation donnee."""

    def verifier_operation(
        self,
        operation: TypeOperation,
        documents_fournis: list[str] = None,
    ) -> ResultatVerification:
        """Verifie les documents pour une operation.

        Args:
            operation: Type d'operation
            documents_fournis: Noms des documents deja fournis
        """
        if documents_fournis is None:
            documents_fournis = []

        docs_fournis_lower = [d.lower() for d in documents_fournis]
        documents_requis = self._get_documents_requis(operation)
        alertes = []

        # Verifier chaque document requis
        nb_obligatoires = 0
        nb_presents = 0

        for doc in documents_requis:
            # Verifier si le document est present
            est_present = self._document_present(doc, docs_fournis_lower)
            doc.statut = StatutDocument.PRESENT if est_present else StatutDocument.MANQUANT

            if doc.niveau == NiveauObligation.OBLIGATOIRE:
                nb_obligatoires += 1
                if est_present:
                    nb_presents += 1
                else:
                    alertes.append(AlerteDocument(
                        titre=f"Document obligatoire manquant : {doc.nom}",
                        description=doc.description,
                        niveau=NiveauObligation.OBLIGATOIRE,
                        operation=operation,
                        reference_legale=doc.reference_legale,
                        action_requise=f"Fournir : {doc.nom}",
                        delai=doc.delai_conservation,
                    ))
            elif doc.niveau == NiveauObligation.RECOMMANDE and not est_present:
                alertes.append(AlerteDocument(
                    titre=f"Document recommande manquant : {doc.nom}",
                    description=doc.description,
                    niveau=NiveauObligation.RECOMMANDE,
                    operation=operation,
                    reference_legale=doc.reference_legale,
                    action_requise=f"Recommande : {doc.nom}",
                ))

        # Calcul de completude
        total_docs = len(documents_requis)
        docs_presents = sum(1 for d in documents_requis if d.statut == StatutDocument.PRESENT)
        taux = (docs_presents / total_docs * 100) if total_docs > 0 else 0

        est_complet = nb_presents >= nb_obligatoires

        resume = (
            f"Verification {operation.value} : "
            f"{docs_presents}/{total_docs} documents fournis "
            f"({taux:.0f}% de completude). "
        )
        if est_complet:
            resume += "Tous les documents obligatoires sont presents."
        else:
            nb_manquants = nb_obligatoires - nb_presents
            resume += f"{nb_manquants} document(s) obligatoire(s) manquant(s)."

        return ResultatVerification(
            operation=operation,
            documents_requis=documents_requis,
            alertes=alertes,
            est_complet=est_complet,
            taux_completude=taux,
            resume=resume,
        )

    def verifier_facture(self, piece_comptable: dict) -> list[AlerteDocument]:
        """Verifie la conformite d'une facture."""
        alertes = []

        # Mentions obligatoires d'une facture (CGI art. 242 nonies A)
        mentions = {
            "numero_piece": "Numero de facture",
            "date_piece": "Date d'emission",
            "montant_ht": "Montant HT",
            "montant_ttc": "Montant TTC",
        }

        for champ, libelle in mentions.items():
            val = piece_comptable.get(champ)
            if not val or val == 0 or val == "0":
                alertes.append(AlerteDocument(
                    titre=f"Mention obligatoire manquante : {libelle}",
                    description=f"La facture ne contient pas le champ '{libelle}' requis par le CGI.",
                    niveau=NiveauObligation.OBLIGATOIRE,
                    operation=TypeOperation.COMPTABILISATION_FACTURE,
                    reference_legale="CGI art. 242 nonies A",
                    action_requise=f"Completer le champ '{libelle}' sur la facture.",
                ))

        # Verifier emetteur
        emetteur = piece_comptable.get("emetteur", {})
        if not emetteur.get("nom") and not emetteur.get("siret"):
            alertes.append(AlerteDocument(
                titre="Identification emetteur manquante",
                description="L'emetteur de la facture n'est pas identifie (nom, SIRET).",
                niveau=NiveauObligation.OBLIGATOIRE,
                operation=TypeOperation.COMPTABILISATION_FACTURE,
                reference_legale="CGI art. 242 nonies A, 2°",
                action_requise="Identifier l'emetteur de la facture.",
            ))

        # Coherence montants
        ht = float(piece_comptable.get("montant_ht", 0) or 0)
        tva = float(piece_comptable.get("montant_tva", 0) or 0)
        ttc = float(piece_comptable.get("montant_ttc", 0) or 0)

        if ht > 0 and tva >= 0 and ttc > 0:
            ecart = abs(ht + tva - ttc)
            if ecart > 0.10:
                alertes.append(AlerteDocument(
                    titre="Incoherence montants facture",
                    description=f"HT ({ht:.2f}) + TVA ({tva:.2f}) != TTC ({ttc:.2f}). Ecart: {ecart:.2f} EUR.",
                    niveau=NiveauObligation.OBLIGATOIRE,
                    operation=TypeOperation.COMPTABILISATION_FACTURE,
                    action_requise="Verifier et corriger les montants de la facture.",
                ))

        return alertes

    def verifier_bulletin_paie(
        self, bulletin: dict, documents_fournis: list[str] = None,
    ) -> list[AlerteDocument]:
        """Verifie les elements d'un bulletin de paie."""
        alertes = []
        if documents_fournis is None:
            documents_fournis = []

        docs_lower = [d.lower() for d in documents_fournis]

        # Verifier contrat de travail
        if not any("contrat" in d for d in docs_lower):
            alertes.append(AlerteDocument(
                titre="Contrat de travail non fourni",
                description="Le contrat de travail du salarie doit etre disponible pour generer un bulletin conforme.",
                niveau=NiveauObligation.OBLIGATOIRE,
                operation=TypeOperation.BULLETIN_PAIE,
                reference_legale="Code du travail art. L1221-1",
            ))

        # Verifier DPAE
        if not any("dpae" in d for d in docs_lower):
            alertes.append(AlerteDocument(
                titre="DPAE non referencee",
                description="La Declaration Prealable a l'Embauche doit avoir ete effectuee.",
                niveau=NiveauObligation.OBLIGATOIRE,
                operation=TypeOperation.BULLETIN_PAIE,
                reference_legale="Code du travail art. L1221-10",
            ))

        # Verifier convention collective
        if not any("convention" in d for d in docs_lower):
            alertes.append(AlerteDocument(
                titre="Convention collective non referencee",
                description="La convention collective applicable doit figurer sur le bulletin de paie.",
                niveau=NiveauObligation.OBLIGATOIRE,
                operation=TypeOperation.BULLETIN_PAIE,
                reference_legale="Code du travail art. R3243-1",
            ))

        return alertes

    def detecter_documents_complementaires(
        self,
        type_document: str,
        contenu: dict,
    ) -> list[AlerteDocument]:
        """Detecte les documents complementaires necessaires en fonction du type de document analyse."""
        alertes = []

        if type_document in ("facture_achat", "facture_vente"):
            # Facture > 1500 EUR : devis/contrat recommande
            ttc = float(contenu.get("montant_ttc", 0) or 0)
            if ttc > 1500:
                alertes.append(AlerteDocument(
                    titre="Devis ou contrat recommande",
                    description=f"Pour une facture de {ttc:.2f} EUR, un contrat ou devis signe est recommande.",
                    niveau=NiveauObligation.RECOMMANDE,
                    operation=TypeOperation.COMPTABILISATION_FACTURE,
                    reference_legale="Code civil art. 1353",
                ))

            # Facture d'achat : bon de reception
            if type_document == "facture_achat":
                alertes.append(AlerteDocument(
                    titre="Bon de reception recommande",
                    description="Un bon de reception/livraison est recommande pour justifier la facture d'achat.",
                    niveau=NiveauObligation.RECOMMANDE,
                    operation=TypeOperation.COMPTABILISATION_FACTURE,
                ))

            # TVA intracommunautaire
            tva_intra = contenu.get("emetteur", {}).get("numero_tva", "")
            if tva_intra and not tva_intra.startswith("FR"):
                alertes.append(AlerteDocument(
                    titre="Facture intracommunautaire - DEB requise",
                    description="Pour une facture avec TVA intracommunautaire, une Declaration d'Echanges de Biens (DEB) peut etre requise.",
                    niveau=NiveauObligation.OBLIGATOIRE,
                    operation=TypeOperation.DECLARATION_TVA,
                    reference_legale="CGI art. 289 B",
                ))

        elif type_document == "bulletin_paie":
            alertes.append(AlerteDocument(
                titre="DSN mensuelle a transmettre",
                description="Le bulletin de paie genere doit etre integre dans la DSN mensuelle.",
                niveau=NiveauObligation.OBLIGATOIRE,
                operation=TypeOperation.DECLARATION_SOCIALE,
                reference_legale="CSS art. L133-5-3",
                delai="Le 5 ou le 15 du mois suivant",
            ))

        elif type_document == "note_frais":
            alertes.append(AlerteDocument(
                titre="Justificatifs originaux requis",
                description="Les justificatifs originaux (tickets, facturettes) doivent etre conserves.",
                niveau=NiveauObligation.OBLIGATOIRE,
                operation=TypeOperation.NOTE_FRAIS,
                reference_legale="CGI art. 39-1",
            ))

        return alertes

    # --- Methodes internes ---

    def _get_documents_requis(self, operation: TypeOperation) -> list[DocumentRequis]:
        """Retourne la liste des documents requis pour une operation."""
        templates = DOCUMENTS_PAR_OPERATION.get(operation, [])
        # Creer des copies pour ne pas modifier le referentiel
        return [
            DocumentRequis(
                nom=t.nom, description=t.description,
                niveau=t.niveau, reference_legale=t.reference_legale,
                alternatives=list(t.alternatives),
                delai_conservation=t.delai_conservation,
            )
            for t in templates
        ]

    def _document_present(self, doc_requis: DocumentRequis, docs_fournis_lower: list[str]) -> bool:
        """Verifie si un document requis est present parmi les fournis."""
        nom_lower = doc_requis.nom.lower()
        # Mots-cles du document requis
        mots_cles = nom_lower.split()

        for doc in docs_fournis_lower:
            # Correspondance exacte
            if nom_lower in doc:
                return True
            # Correspondance par mots-cles (au moins 50% des mots)
            matches = sum(1 for mc in mots_cles if mc in doc)
            if matches >= len(mots_cles) * 0.5:
                return True
            # Verifier les alternatives
            for alt in doc_requis.alternatives:
                if alt.lower() in doc:
                    return True

        return False
