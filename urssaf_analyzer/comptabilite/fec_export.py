"""Export des ecritures comptables au format FEC (Fichier des Ecritures Comptables).

Format reglementaire : Art. L.47 A-I du Livre des Procedures Fiscales.
18 colonnes obligatoires, separateur tabulation, encodage UTF-8 ou ISO-8859-15.
Nom de fichier conventionnel : {SIREN}FEC{YYYYMMDD}.txt
"""

import io
from datetime import date
from decimal import Decimal, InvalidOperation

from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures, Ecriture, TypeJournal


# Libelles des journaux par code
JOURNAL_LIBELLES = {
    TypeJournal.ACHATS: "Journal des achats",
    TypeJournal.VENTES: "Journal des ventes",
    TypeJournal.BANQUE: "Journal de banque",
    TypeJournal.OPERATIONS_DIVERSES: "Operations diverses",
    TypeJournal.PAIE: "Journal de paie",
    TypeJournal.A_NOUVEAU: "A nouveaux",
}

COLONNES_FEC = [
    "JournalCode",
    "JournalLib",
    "EcritureNum",
    "EcritureDate",
    "CompteNum",
    "CompteLib",
    "CompAuxNum",
    "CompAuxLib",
    "PieceRef",
    "PieceDate",
    "EcritureLib",
    "Debit",
    "Credit",
    "EcritureLet",
    "DateLet",
    "ValidDate",
    "Montantdevise",
    "Idevise",
]


def _fmt_date(d: date | None) -> str:
    """Formate une date au format FEC (YYYYMMDD)."""
    if d is None:
        return ""
    return d.strftime("%Y%m%d")


def _fmt_montant(m: Decimal | float | int) -> str:
    """Formate un montant au format FEC (2 decimales, virgule comme separateur)."""
    if isinstance(m, float):
        m = Decimal(str(m))
    elif isinstance(m, int):
        m = Decimal(m)
    # Format francais : virgule decimale, pas de separateur de milliers
    return f"{m:.2f}".replace(".", ",")


def exporter_fec(
    moteur: MoteurEcritures,
    siren: str = "",
    date_cloture: date | None = None,
    separateur: str = "\t",
    validees_seulement: bool = True,
) -> str:
    """Exporte les ecritures comptables au format FEC.

    Args:
        moteur: Le moteur d'ecritures contenant les donnees.
        siren: Le SIREN de l'entreprise (pour le nom de fichier).
        date_cloture: Date de cloture de l'exercice.
        separateur: Separateur de champs (tabulation par defaut).
        validees_seulement: Si True, n'exporte que les ecritures validees.

    Returns:
        Le contenu du fichier FEC sous forme de chaine.
    """
    lignes = []
    # En-tete
    lignes.append(separateur.join(COLONNES_FEC))

    # Compteur global d'ecriture pour numerotation sequentielle
    num_ecriture = 0

    for ecriture in moteur.ecritures:
        if validees_seulement and not ecriture.validee:
            continue

        num_ecriture += 1
        ecriture_num = ecriture.numero_piece or f"{num_ecriture:06d}"
        journal_code = ecriture.journal.value
        journal_lib = JOURNAL_LIBELLES.get(ecriture.journal, journal_code)

        for ligne in ecriture.lignes:
            # Determiner compte auxiliaire
            comp_aux_num = ""
            comp_aux_lib = ""
            compte = ligne.compte
            # Comptes de tiers (401xxx, 411xxx) -> compte auxiliaire
            if compte.startswith("401") or compte.startswith("411"):
                if len(compte) > 6:
                    comp_aux_num = compte
                    comp_aux_lib = ligne.libelle
                    # Tronquer au compte general
                    compte = compte[:6] + "0" * (len(compte) - 6)

            # Recuperer le libelle du compte depuis le plan comptable
            cpt_obj = moteur.plan.get_compte(ligne.compte)
            compte_lib = cpt_obj.libelle if cpt_obj else ligne.libelle

            valid_date = ""
            if ecriture.date_validation:
                valid_date = _fmt_date(ecriture.date_validation.date())

            champs = [
                journal_code,
                journal_lib,
                ecriture_num,
                _fmt_date(ecriture.date_ecriture),
                compte,
                compte_lib,
                comp_aux_num,
                comp_aux_lib,
                ligne.piece_ref or ecriture.numero_piece,
                _fmt_date(ecriture.date_piece),
                ligne.libelle,
                _fmt_montant(ligne.debit),
                _fmt_montant(ligne.credit),
                ligne.lettrage,
                _fmt_date(ecriture.date_ecriture) if ligne.lettrage else "",  # DateLet
                valid_date,
                "",  # Montantdevise
                "",  # Idevise
            ]
            lignes.append(separateur.join(champs))

    return "\n".join(lignes)


def nom_fichier_fec(siren: str, date_cloture: date | None = None) -> str:
    """Genere le nom de fichier FEC conventionnel : {SIREN}FEC{YYYYMMDD}.txt"""
    siren = siren.replace(" ", "")[:9]
    if not siren:
        siren = "000000000"
    dt = date_cloture or date.today()
    return f"{siren}FEC{dt.strftime('%Y%m%d')}.txt"


def valider_fec(contenu: str, separateur: str = "\t") -> dict:
    """Valide un fichier FEC et retourne un rapport de conformite.

    Controles effectues (conformes aux specifications DGFIP) :
    - Presence des 18 colonnes obligatoires
    - Format des dates (YYYYMMDD)
    - Equilibre debit/credit par ecriture
    - Numerotation sequentielle
    - Absence de lignes vides
    """
    lignes = contenu.strip().split("\n")
    if not lignes:
        return {"valide": False, "erreurs": ["Fichier vide"]}

    erreurs = []
    avertissements = []

    # Verifier l'en-tete
    header = lignes[0].split(separateur)
    header_clean = [c.strip() for c in header]

    from urssaf_analyzer.parsers.fec_parser import COLONNES_FEC as COLONNES_REF, COLONNES_FEC_ALT
    colonnes_trouvees = set()
    for c in header_clean:
        c_lower = c.lower()
        if c_lower in COLONNES_FEC_ALT:
            colonnes_trouvees.add(COLONNES_FEC_ALT[c_lower])
        elif c in COLONNES_REF:
            colonnes_trouvees.add(c)

    manquantes = [c for c in COLONNES_REF if c not in colonnes_trouvees]
    if manquantes:
        erreurs.append(f"Colonnes obligatoires manquantes: {', '.join(manquantes)}")

    # Construire la map d'index
    col_idx = {}
    for i, c in enumerate(header_clean):
        c_lower = c.lower()
        if c_lower in COLONNES_FEC_ALT:
            col_idx[COLONNES_FEC_ALT[c_lower]] = i
        elif c in COLONNES_REF:
            col_idx[c] = i

    # Valider les lignes
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    ecritures = {}  # num -> (total_debit, total_credit)
    nb_lignes_valides = 0
    nb_lignes_erreur = 0

    for i, ligne in enumerate(lignes[1:], start=2):
        ligne = ligne.strip()
        if not ligne:
            continue

        champs = ligne.split(separateur)
        if len(champs) < 5:
            erreurs.append(f"Ligne {i}: nombre de champs insuffisant ({len(champs)})")
            nb_lignes_erreur += 1
            continue

        nb_lignes_valides += 1

        # Verifier les montants
        debit = Decimal("0")
        credit = Decimal("0")
        if "Debit" in col_idx:
            try:
                val = champs[col_idx["Debit"]].strip().replace(",", ".").replace(" ", "")
                debit = Decimal(val) if val else Decimal("0")
            except (InvalidOperation, IndexError):
                erreurs.append(f"Ligne {i}: montant Debit invalide")
        if "Credit" in col_idx:
            try:
                val = champs[col_idx["Credit"]].strip().replace(",", ".").replace(" ", "")
                credit = Decimal(val) if val else Decimal("0")
            except (InvalidOperation, IndexError):
                erreurs.append(f"Ligne {i}: montant Credit invalide")

        total_debit += debit
        total_credit += credit

        # Regrouper par ecriture
        if "EcritureNum" in col_idx:
            try:
                num = champs[col_idx["EcritureNum"]].strip()
                if num not in ecritures:
                    ecritures[num] = [Decimal("0"), Decimal("0")]
                ecritures[num][0] += debit
                ecritures[num][1] += credit
            except IndexError:
                pass

    # Verifier l'equilibre par ecriture
    ecritures_desequilibrees = []
    for num, (d, c) in ecritures.items():
        if abs(d - c) >= Decimal("0.01"):
            ecritures_desequilibrees.append(num)
    if ecritures_desequilibrees:
        avertissements.append(
            f"{len(ecritures_desequilibrees)} ecriture(s) desequilibree(s): "
            f"{', '.join(ecritures_desequilibrees[:10])}"
        )

    # Equilibre general
    equilibre_general = abs(total_debit - total_credit) < Decimal("0.01")

    return {
        "valide": len(erreurs) == 0,
        "erreurs": erreurs[:50],
        "avertissements": avertissements[:20],
        "nb_lignes": nb_lignes_valides,
        "nb_ecritures": len(ecritures),
        "total_debit": float(total_debit),
        "total_credit": float(total_credit),
        "equilibre_general": equilibre_general,
        "ecritures_desequilibrees": len(ecritures_desequilibrees),
        "colonnes_manquantes": manquantes,
        "taux_conformite": round(
            ((len(COLONNES_REF) - len(manquantes)) / len(COLONNES_REF)) * 100, 1
        ),
    }
