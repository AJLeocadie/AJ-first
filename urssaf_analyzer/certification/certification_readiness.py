"""Evaluation de la maturite du moteur pour certification par un organisme tiers.

Ce module fournit :
- L'analyse des normes ISO applicables
- Le diagnostic des ecarts (gap analysis)
- Le plan de remediation par priorite
- Les tests de determinisme et reproductibilite du scoring

Standards evalues :
- ISO/IEC 25010:2023 - Modele de qualite logicielle (SQuaRE)
- ISO/IEC 27001:2022 - Management de la securite de l'information
- ISO/IEC 27701:2019 - Management de la vie privee (RGPD)
- ISO/IEC 42001:2023 - Management des systemes d'IA
- ISO 19011:2018 - Lignes directrices pour l'audit
- NF Z42-013 (AFNOR) - Archivage electronique a valeur probante
- Reglement eIDAS (UE 910/2014) - Identification electronique
- EU AI Act (Reglement 2024/1689) - Classification des systemes d'IA
"""

from dataclasses import dataclass, field
from enum import Enum


class MaturiteNiveau(str, Enum):
    """Niveaux de maturite pour chaque exigence."""
    ABSENT = "absent"
    INITIAL = "initial"
    PARTIEL = "partiel"
    CONFORME = "conforme"
    OPTIMISE = "optimise"


class PrioriteRemediation(str, Enum):
    """Priorite de remediation."""
    BLOQUANT = "bloquant"        # Prerequis absolu pour la certification
    HAUTE = "haute"              # Requis pour la plupart des standards
    MOYENNE = "moyenne"          # Ameliore la posture mais non bloquant
    FAIBLE = "faible"            # Optimisation


@dataclass
class ExigenceCertification:
    """Une exigence de certification avec son evaluation."""
    norme: str
    clause: str
    exigence: str
    maturite: MaturiteNiveau
    ecart: str
    remediation: str
    priorite: PrioriteRemediation
    effort_jours: int = 0


def evaluer_maturite_certification() -> dict:
    """Produit le diagnostic complet de maturite pour certification.

    Retourne un dictionnaire structurant :
    - Les normes ISO pertinentes et leur applicabilite
    - Le gap analysis par domaine
    - Le plan de remediation ordonne
    - Les metriques de maturite globale
    """
    normes = _normes_iso_pertinentes()
    exigences = _evaluer_exigences()
    plan = _plan_remediation(exigences)
    metriques = _metriques_globales(exigences)

    return {
        "titre": "Evaluation de maturite pour certification du moteur NormaCheck v4.0",
        "normes_iso_pertinentes": normes,
        "gap_analysis": [_exigence_to_dict(e) for e in exigences],
        "plan_remediation": plan,
        "metriques_globales": metriques,
        "conclusion": _conclusion(metriques),
    }


def _normes_iso_pertinentes() -> list[dict]:
    """Identifie les normes ISO applicables avec justification."""
    return [
        {
            "norme": "ISO/IEC 25010:2023",
            "titre": "Modele de qualite des systemes et logiciels (SQuaRE)",
            "applicabilite": "DIRECTE",
            "justification": (
                "Definit les 8 caracteristiques de qualite logicielle (adequation fonctionnelle, "
                "fiabilite, performance, securite, maintenabilite, compatibilite, utilisabilite, "
                "portabilite). Cadre de reference pour l'evaluation du moteur de scoring."
            ),
            "clauses_clefs": [
                "5.1 Adequation fonctionnelle (completude, exactitude, pertinence)",
                "5.2 Fiabilite (maturite, disponibilite, tolerance aux pannes, recuperabilite)",
                "5.3 Efficacite (temps de reponse, utilisation des ressources)",
                "5.4 Securite (confidentialite, integrite, non-repudiation, authenticite)",
                "5.6 Maintenabilite (modularite, reutilisabilite, analysabilite, testabilite)",
            ],
        },
        {
            "norme": "ISO/IEC 25040:2024",
            "titre": "Processus d'evaluation de la qualite logicielle",
            "applicabilite": "DIRECTE",
            "justification": (
                "Definit le processus en 5 etapes pour evaluer la qualite logicielle : "
                "etablir les exigences, specifier l'evaluation, concevoir l'evaluation, "
                "executer l'evaluation, conclure. Cadre operationnel pour l'audit."
            ),
            "clauses_clefs": [
                "6.1 Exigences d'evaluation",
                "6.2 Specification de l'evaluation",
                "6.3 Conception de l'evaluation",
                "6.4 Execution de l'evaluation",
                "6.5 Conclusion de l'evaluation",
            ],
        },
        {
            "norme": "ISO/IEC 27001:2022",
            "titre": "Management de la securite de l'information (SMSI)",
            "applicabilite": "DIRECTE",
            "justification": (
                "Obligatoire pour tout systeme traitant des donnees personnelles et "
                "financieres. NormaCheck traite des DSN, bulletins de paie, NIR, SIRET. "
                "Certification la plus reconnue pour la confiance des organismes tiers."
            ),
            "clauses_clefs": [
                "A.5 Politiques de securite de l'information",
                "A.8 Gestion des actifs",
                "A.12 Securite des operations (journalisation, protection contre les malware)",
                "A.14 Developpement securise",
                "A.18 Conformite (exigences legales et reglementaires)",
            ],
        },
        {
            "norme": "ISO/IEC 27701:2019",
            "titre": "Management de la vie privee (extension 27001)",
            "applicabilite": "DIRECTE",
            "justification": (
                "Extension de 27001 specifique au RGPD. Couvre le traitement des donnees "
                "personnelles (NIR, identite employes), les droits des personnes "
                "concernees, et la transparence algorithmique (art. 22 RGPD)."
            ),
            "clauses_clefs": [
                "7.2.5 AIPD (Analyse d'Impact sur la Protection des Donnees)",
                "7.3.5 Droits des personnes concernees",
                "7.4.5 Privacy by design et by default",
                "8.5 Partage, transfert et divulgation des donnees",
            ],
        },
        {
            "norme": "ISO/IEC 42001:2023",
            "titre": "Management des systemes d'intelligence artificielle",
            "applicabilite": "FORTE",
            "justification": (
                "Nouvelle norme pour les systemes d'IA. NormaCheck utilise des algorithmes "
                "de detection de patterns (Benford, outliers), de scoring automatise et "
                "de routage par regles. Meme qualifie d'aide a la decision, le systeme "
                "releve du champ d'application de l'ISO 42001."
            ),
            "clauses_clefs": [
                "6.1 Actions pour traiter les risques lies a l'IA",
                "A.2 Impact et contexte du systeme d'IA",
                "A.4 Evaluation de l'IA (equite, transparence, explicabilite)",
                "A.6 Cycle de vie du systeme d'IA (donnees, developpement, deploiement)",
                "A.10 Relations avec les tiers et sous-traitants",
            ],
        },
        {
            "norme": "ISO 19011:2018",
            "titre": "Lignes directrices pour l'audit de systemes de management",
            "applicabilite": "FORTE",
            "justification": (
                "NormaCheck est lui-meme un outil d'audit. La norme ISO 19011 s'applique "
                "doublement : pour auditer NormaCheck, et pour valider que NormaCheck "
                "respecte les principes d'audit (independance, approche factuelle, "
                "confidentialite)."
            ),
            "clauses_clefs": [
                "4 Principes de l'audit (integrite, presentation impartiale, conscience professionnelle)",
                "5.4 Mise en oeuvre du programme d'audit",
                "6.3 Preparation des activites d'audit",
                "6.4 Conduite de l'audit",
            ],
        },
        {
            "norme": "NF Z42-013 (AFNOR)",
            "titre": "Archivage electronique a valeur probante",
            "applicabilite": "DIRECTE (deja reference)",
            "justification": (
                "Deja implementee via proof_chain.py. Definit les exigences pour "
                "l'archivage electronique avec valeur probante devant les tribunaux. "
                "Duree de conservation : 10 ans (recommandation AFNOR)."
            ),
            "clauses_clefs": [
                "5.2 Integrite des documents",
                "5.3 Perennite et lisibilite",
                "5.4 Tracabilite des operations",
                "5.5 Securite du systeme d'archivage",
            ],
        },
        {
            "norme": "EU AI Act (Reglement 2024/1689)",
            "titre": "Reglement europeen sur l'intelligence artificielle",
            "applicabilite": "EVALUATION REQUISE",
            "justification": (
                "Classification du systeme par niveau de risque. Si NormaCheck est utilise "
                "pour des decisions affectant l'emploi ou l'acces au credit (art. 6(2) + "
                "Annexe III), il pourrait etre classe 'haut risque'. En tant qu'aide a la "
                "decision sans effet juridique direct, il serait 'risque limite' (art. 50 : "
                "obligation de transparence)."
            ),
            "clauses_clefs": [
                "Art. 6 + Annexe III : Classification par niveau de risque",
                "Art. 9 : Systeme de gestion des risques (si haut risque)",
                "Art. 10 : Gouvernance des donnees (si haut risque)",
                "Art. 13 : Transparence et information (toutes categories)",
                "Art. 50 : Obligations de transparence (risque limite)",
            ],
        },
        {
            "norme": "ISO/IEC 12207:2017",
            "titre": "Processus du cycle de vie du logiciel",
            "applicabilite": "RECOMMANDEE",
            "justification": (
                "Definit les processus de developpement, maintenance et exploitation "
                "du logiciel. Requis pour demontrer un processus de developpement "
                "maitrise et reproductible a un auditeur."
            ),
            "clauses_clefs": [
                "6.3.1 Processus de definition des exigences",
                "6.3.2 Processus d'analyse des exigences",
                "6.4.1 Processus d'implementation",
                "6.4.8 Processus de qualification",
                "6.4.10 Processus de validation",
            ],
        },
    ]


def _evaluer_exigences() -> list[ExigenceCertification]:
    """Evalue chaque exigence de certification avec le niveau de maturite actuel."""
    return [
        # === DOCUMENTATION ===
        ExigenceCertification(
            norme="ISO/IEC 25010 + 12207",
            clause="Documentation technique",
            exigence="Documentation d'architecture complete (composants, flux, interfaces)",
            maturite=MaturiteNiveau.ABSENT,
            ecart="Aucun document d'architecture. README vide ('tesr'). Pas de diagrammes.",
            remediation=(
                "Creer un dossier d'architecture technique (DAT) couvrant : architecture "
                "logique, flux de donnees du scoring, interfaces API (OpenAPI/Swagger), "
                "modele de donnees, diagramme de deploiement."
            ),
            priorite=PrioriteRemediation.BLOQUANT,
            effort_jours=5,
        ),
        ExigenceCertification(
            norme="ISO/IEC 25010 + 42001",
            clause="Specification algorithmique",
            exigence="Document de specification du scoring independant du code",
            maturite=MaturiteNiveau.PARTIEL,
            ecart=(
                "La methodologie est documentee dans le code (endpoint /api/scores/methodologie) "
                "mais pas dans un document independant auditable. La specification est melee au "
                "code d'implementation."
            ),
            remediation=(
                "Extraire la specification algorithmique dans un document independant : "
                "formules, parametres, justifications legales, cas limites, exemples. "
                "Ce document doit etre versionne et signe."
            ),
            priorite=PrioriteRemediation.BLOQUANT,
            effort_jours=3,
        ),
        ExigenceCertification(
            norme="ISO/IEC 27001",
            clause="A.5.1",
            exigence="Politique de securite de l'information documentee",
            maturite=MaturiteNiveau.ABSENT,
            ecart="Pas de politique de securite formelle. Les mesures existent dans le code mais ne sont pas documentees.",
            remediation=(
                "Rediger une Politique de Securite du Systeme d'Information (PSSI) couvrant : "
                "classification des donnees, gestion des acces, chiffrement, journalisation, "
                "gestion des incidents, continuite d'activite."
            ),
            priorite=PrioriteRemediation.BLOQUANT,
            effort_jours=3,
        ),

        # === QUALITE LOGICIELLE ===
        ExigenceCertification(
            norme="ISO/IEC 25010",
            clause="5.6 Maintenabilite - Testabilite",
            exigence="Couverture de tests >= 80% sur les composants critiques",
            maturite=MaturiteNiveau.PARTIEL,
            ecart=(
                "Couverture globale 40%. Modules critiques non couverts : "
                "proof_chain.py (0%), encryption.py (0%), portfolio_manager (0%), "
                "veille modules (0%). 233 tests existants mais insuffisants."
            ),
            remediation=(
                "Porter la couverture a 80%+ sur les modules critiques : "
                "proof_chain, encryption, analyzer_engine, scoring (JS -> tests E2E). "
                "Ajouter des tests de proprietes (hypothesis) et des tests de mutation."
            ),
            priorite=PrioriteRemediation.BLOQUANT,
            effort_jours=8,
        ),
        ExigenceCertification(
            norme="ISO/IEC 25010 + 42001",
            clause="5.1 Exactitude fonctionnelle",
            exigence="Tests de determinisme du scoring (memes entrees -> meme score)",
            maturite=MaturiteNiveau.INITIAL,
            ecart=(
                "Aucun test verifiant explicitement le determinisme du scoring. "
                "Le scoring JS n'est pas teste (code embarque dans l'HTML Python). "
                "Pas de test de reproductibilite a partir d'un proof record."
            ),
            remediation=(
                "Creer une suite de tests de determinisme : "
                "(1) memes constats -> meme score (invariance), "
                "(2) reproduction a partir d'un proof record, "
                "(3) equivalence JS/Python si dual-implementation."
            ),
            priorite=PrioriteRemediation.BLOQUANT,
            effort_jours=3,
        ),
        ExigenceCertification(
            norme="ISO/IEC 25010",
            clause="5.6 Maintenabilite - Analysabilite",
            exigence="Analyse statique du code (linter, type checker)",
            maturite=MaturiteNiveau.ABSENT,
            ecart="Aucun outil d'analyse statique configure (pas de mypy, ruff, pylint, black, isort).",
            remediation=(
                "Configurer ruff (linter+formatter), mypy (type checking strict) dans "
                "pyproject.toml. Integrer au CI/CD avec seuils bloquants."
            ),
            priorite=PrioriteRemediation.HAUTE,
            effort_jours=2,
        ),

        # === SECURITE ===
        ExigenceCertification(
            norme="ISO/IEC 27001",
            clause="A.14.2 Developpement securise",
            exigence="Audit de securite applicative (pentesting, SAST/DAST)",
            maturite=MaturiteNiveau.ABSENT,
            ecart="Aucun audit de securite formel. Pas de SAST/DAST dans le pipeline CI/CD.",
            remediation=(
                "Integrer bandit (SAST Python) au CI/CD. Realiser un pentest "
                "applicatif (OWASP Top 10) par un prestataire qualifie. "
                "Documenter les resultats dans un rapport d'audit securite."
            ),
            priorite=PrioriteRemediation.HAUTE,
            effort_jours=5,
        ),
        ExigenceCertification(
            norme="ISO/IEC 27001",
            clause="A.12.4 Journalisation",
            exigence="Journalisation centralisee avec alertes",
            maturite=MaturiteNiveau.PARTIEL,
            ecart=(
                "audit_logger.py existe (append-only JSON Lines) + proof_chain.py. "
                "Mais pas de centralisation, pas d'alertes, pas de monitoring."
            ),
            remediation=(
                "Ajouter un collecteur de logs centralise (ex: ELK stack ou Loki). "
                "Configurer des alertes sur : erreurs d'integrite chain, tentatives "
                "d'acces non autorisees, anomalies de volume."
            ),
            priorite=PrioriteRemediation.MOYENNE,
            effort_jours=3,
        ),

        # === REPRODUCTIBILITE ===
        ExigenceCertification(
            norme="ISO/IEC 42001 + 25010",
            clause="Reproductibilite des resultats",
            exigence="Build reproductible avec dependances epinglees",
            maturite=MaturiteNiveau.INITIAL,
            ecart=(
                "requirements.txt utilise >= (versions flottantes). Pas de lock file "
                "(pip-tools/poetry.lock). Le build Docker n'est pas reproductible."
            ),
            remediation=(
                "Epingler toutes les dependances avec hash (pip-compile --generate-hashes). "
                "Stocker le lock file en VCS. Verifier la reproductibilite du build."
            ),
            priorite=PrioriteRemediation.HAUTE,
            effort_jours=1,
        ),
        ExigenceCertification(
            norme="ISO/IEC 42001",
            clause="A.6 Cycle de vie IA",
            exigence="Versionnement semantique coherent",
            maturite=MaturiteNiveau.INITIAL,
            ecart=(
                "Versions incoherentes : setup.py='1.0.0', Dockerfile='3.8.1', "
                "methodologie='4.0', start.sh='3.8.1'. Pas de CHANGELOG."
            ),
            remediation=(
                "Unifier le versionnement (SemVer). Source unique dans __init__.py "
                "propagee a tous les artefacts. Creer un CHANGELOG.md."
            ),
            priorite=PrioriteRemediation.HAUTE,
            effort_jours=1,
        ),

        # === RGPD / VIE PRIVEE ===
        ExigenceCertification(
            norme="ISO/IEC 27701",
            clause="7.2.5",
            exigence="AIPD documentee et signee",
            maturite=MaturiteNiveau.INITIAL,
            ecart=(
                "L'AIPD est referencee dans la methodologie mais n'existe pas "
                "en tant que document formel signe. Les risques sont identifies "
                "dans le code mais pas dans un registre."
            ),
            remediation=(
                "Rediger l'AIPD formelle conformement au guide CNIL. Inclure : "
                "description du traitement, necessite/proportionnalite, risques "
                "pour les droits et libertes, mesures d'attenuation. Signer et dater."
            ),
            priorite=PrioriteRemediation.HAUTE,
            effort_jours=3,
        ),

        # === GESTION DES CHANGEMENTS ===
        ExigenceCertification(
            norme="ISO/IEC 12207 + 27001",
            clause="Gestion des changements",
            exigence="Processus formel de gestion des changements (change management)",
            maturite=MaturiteNiveau.INITIAL,
            ecart=(
                "Pas de processus formel de changement. Le CI/CD deploie directement "
                "sur push to main. Pas de code review obligatoire, pas de staging."
            ),
            remediation=(
                "Implementer : branches protegees (main), PR obligatoires avec "
                "review, environnement de staging, process de release avec "
                "approbation. Documenter dans un guide de contribution."
            ),
            priorite=PrioriteRemediation.HAUTE,
            effort_jours=2,
        ),

        # === CONTINUITE ===
        ExigenceCertification(
            norme="ISO 22301 + 27001",
            clause="Continuite d'activite",
            exigence="Plan de continuite (PCA) et de reprise (PRA)",
            maturite=MaturiteNiveau.PARTIEL,
            ecart=(
                "Backup automatique quotidien (30 jours). Healthcheck Docker. "
                "Mais pas de PCA/PRA documente, pas de RTO/RPO definis, "
                "pas de test de restauration."
            ),
            remediation=(
                "Documenter le PCA/PRA : RTO (temps de reprise), RPO (perte "
                "maximale), procedure de restauration, test annuel."
            ),
            priorite=PrioriteRemediation.MOYENNE,
            effort_jours=2,
        ),

        # === TRACABILITE ===
        ExigenceCertification(
            norme="ISO/IEC 42001 + 25010",
            clause="Tracabilite exigences-tests",
            exigence="Matrice de tracabilite exigences <-> tests <-> code",
            maturite=MaturiteNiveau.ABSENT,
            ecart="Aucune matrice de tracabilite. Les tests ne referencent pas les exigences.",
            remediation=(
                "Creer une matrice de tracabilite liant chaque exigence reglementaire "
                "a ses tests et a son implementation. Utiliser des marqueurs pytest "
                "pour categoriser les tests par exigence."
            ),
            priorite=PrioriteRemediation.MOYENNE,
            effort_jours=3,
        ),
    ]


def _exigence_to_dict(e: ExigenceCertification) -> dict:
    return {
        "norme": e.norme,
        "clause": e.clause,
        "exigence": e.exigence,
        "maturite": e.maturite.value,
        "ecart": e.ecart,
        "remediation": e.remediation,
        "priorite": e.priorite.value,
        "effort_jours": e.effort_jours,
    }


def _plan_remediation(exigences: list[ExigenceCertification]) -> dict:
    """Organise la remediation en phases."""
    priorite_ordre = {
        PrioriteRemediation.BLOQUANT: 0,
        PrioriteRemediation.HAUTE: 1,
        PrioriteRemediation.MOYENNE: 2,
        PrioriteRemediation.FAIBLE: 3,
    }
    tri = sorted(exigences, key=lambda e: priorite_ordre[e.priorite])

    phases = {
        "phase_1_prerequis_bloquants": {
            "description": "Prerequis absolus sans lesquels aucune certification n'est envisageable",
            "delai": "4-6 semaines",
            "actions": [],
            "effort_total_jours": 0,
        },
        "phase_2_conformite_haute": {
            "description": "Exigences requises pour la plupart des referentiels ISO",
            "delai": "6-10 semaines apres phase 1",
            "actions": [],
            "effort_total_jours": 0,
        },
        "phase_3_optimisation": {
            "description": "Ameliorations de maturite et optimisations",
            "delai": "10-16 semaines apres phase 2",
            "actions": [],
            "effort_total_jours": 0,
        },
    }

    for e in tri:
        action = {
            "exigence": e.exigence,
            "norme": e.norme,
            "remediation": e.remediation,
            "effort_jours": e.effort_jours,
        }
        if e.priorite == PrioriteRemediation.BLOQUANT:
            phases["phase_1_prerequis_bloquants"]["actions"].append(action)
            phases["phase_1_prerequis_bloquants"]["effort_total_jours"] += e.effort_jours
        elif e.priorite == PrioriteRemediation.HAUTE:
            phases["phase_2_conformite_haute"]["actions"].append(action)
            phases["phase_2_conformite_haute"]["effort_total_jours"] += e.effort_jours
        else:
            phases["phase_3_optimisation"]["actions"].append(action)
            phases["phase_3_optimisation"]["effort_total_jours"] += e.effort_jours

    return phases


def _metriques_globales(exigences: list[ExigenceCertification]) -> dict:
    """Calcule les metriques de maturite globale."""
    par_maturite = {}
    par_priorite = {}
    effort_total = 0

    for e in exigences:
        par_maturite[e.maturite.value] = par_maturite.get(e.maturite.value, 0) + 1
        par_priorite[e.priorite.value] = par_priorite.get(e.priorite.value, 0) + 1
        effort_total += e.effort_jours

    nb_total = len(exigences)
    nb_conforme = par_maturite.get("conforme", 0) + par_maturite.get("optimise", 0)
    nb_partiel = par_maturite.get("partiel", 0)
    nb_absent = par_maturite.get("absent", 0) + par_maturite.get("initial", 0)

    score_maturite = round(
        ((nb_conforme * 100) + (nb_partiel * 50) + (nb_absent * 0)) / nb_total
    ) if nb_total > 0 else 0

    return {
        "nb_exigences_evaluees": nb_total,
        "repartition_maturite": par_maturite,
        "repartition_priorite": par_priorite,
        "score_maturite_pct": score_maturite,
        "effort_remediation_total_jours": effort_total,
        "nb_bloquants": par_priorite.get("bloquant", 0),
        "pret_certification": nb_absent == 0 and par_priorite.get("bloquant", 0) == 0,
    }


def _conclusion(metriques: dict) -> dict:
    """Produit la conclusion de l'evaluation."""
    score = metriques["score_maturite_pct"]
    bloquants = metriques["nb_bloquants"]

    if score >= 80 and bloquants == 0:
        verdict = "PRET POUR CERTIFICATION"
        detail = "Le systeme atteint un niveau de maturite suffisant pour engager un audit de certification."
    elif score >= 50:
        verdict = "CERTIFICATION POSSIBLE APRES REMEDIATION"
        detail = (
            f"Le systeme presente {bloquants} prerequis bloquant(s) et un score de maturite "
            f"de {score}%. La remediation est necessaire avant tout engagement d'audit."
        )
    else:
        verdict = "REMISE A NIVEAU PREALABLE NECESSAIRE"
        detail = (
            f"Le score de maturite ({score}%) est insuffisant. "
            f"La phase 1 (prerequis bloquants) doit etre completee en priorite."
        )

    return {
        "verdict": verdict,
        "score_maturite": score,
        "nb_bloquants": bloquants,
        "detail": detail,
        "recommandation_organisme": (
            "Pour un systeme de scoring social/fiscal francais, les organismes "
            "de certification pertinents sont : "
            "AFNOR Certification (NF, ISO 27001), "
            "Bureau Veritas (ISO 27001, ISO 42001), "
            "BSI Group (ISO 27001), "
            "LSTI (Prestataire de Services de Confiance). "
            "Privilegier un organisme accrédite par le COFRAC."
        ),
        "duree_estimee_audit": (
            "Audit initial ISO 27001 : 3-5 jours. "
            "Evaluation ISO 42001 : 2-3 jours supplementaires. "
            "Pre-audit recommande : 1-2 jours."
        ),
    }
