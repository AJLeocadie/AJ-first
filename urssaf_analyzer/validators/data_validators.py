"""Validateurs de donnees metier pour l'integrite des fichiers sociaux et comptables.

Fournit des classes de validation structurees pour les identifiants (SIREN, NIR),
les schemas DSN et FEC, les taux de cotisation, et la reconciliation inter-fichiers.

Les validateurs de base (valider_nir, valider_bloc_dsn) sont definis dans
urssaf_analyzer.utils.validators et reutilises ici via delegation.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from urssaf_analyzer.utils.number_utils import valider_siren as _luhn_siren
from urssaf_analyzer.utils.validators import valider_nir as _valider_nir_base
from urssaf_analyzer.parsers.fec_parser import COLONNES_FEC

logger = logging.getLogger(__name__)


# ============================================================
# Resultat de validation
# ============================================================

@dataclass
class ValidationResult:
    """Resultat structure d'une validation unitaire.

    Attributes:
        valide: True si la donnee est conforme.
        message: Description du resultat ou de l'erreur.
        valeur_corrigee: Valeur corrigee ou completee (vide si non applicable).
    """
    valide: bool
    message: str
    valeur_corrigee: str = ""


# ============================================================
# SIREN
# ============================================================

class SIRENValidator:
    """Validation du numero SIREN (9 chiffres, algorithme de Luhn).

    Le SIREN (Systeme d'Identification du Repertoire des ENtreprises)
    est attribue par l'INSEE a chaque unite legale.
    """

    @staticmethod
    def valider(siren: str) -> ValidationResult:
        """Valide un numero SIREN par somme de controle Luhn.

        Args:
            siren: Numero SIREN a valider (9 chiffres).

        Returns:
            ValidationResult avec le statut de validation.
        """
        siren_clean = siren.strip().replace(" ", "").replace(".", "")

        if not siren_clean:
            return ValidationResult(
                valide=False,
                message="SIREN vide",
            )

        if len(siren_clean) != 9:
            return ValidationResult(
                valide=False,
                message=f"SIREN doit contenir 9 chiffres, trouve {len(siren_clean)}",
                valeur_corrigee=siren_clean,
            )

        if not siren_clean.isdigit():
            return ValidationResult(
                valide=False,
                message="SIREN ne doit contenir que des chiffres",
                valeur_corrigee=siren_clean,
            )

        if _luhn_siren(siren_clean):
            logger.debug("SIREN %s valide (Luhn OK)", siren_clean)
            return ValidationResult(
                valide=True,
                message="SIREN valide",
                valeur_corrigee=siren_clean,
            )

        # Tentative de correction : recalcul du dernier chiffre
        base = siren_clean[:8]
        for digit in range(10):
            candidat = base + str(digit)
            if _luhn_siren(candidat):
                logger.info(
                    "SIREN %s invalide, suggestion de correction : %s",
                    siren_clean, candidat,
                )
                return ValidationResult(
                    valide=False,
                    message=f"Somme de controle Luhn invalide (suggestion : {candidat})",
                    valeur_corrigee=candidat,
                )

        return ValidationResult(
            valide=False,
            message="Somme de controle Luhn invalide",
            valeur_corrigee=siren_clean,
        )


# ============================================================
# NIR (Numero d'Inscription au Repertoire)
# ============================================================

class NIRValidator:
    """Validation du NIR (numero de securite sociale francais).

    Delegue la logique de base a urssaf_analyzer.utils.validators.valider_nir
    et enrichit avec des verifications supplementaires (departement, code sexe).
    """

    # Departements valides (metropole + DOM-TOM + Corse 2A/2B)
    _DEPARTEMENTS_VALIDES = (
        {f"{i:02d}" for i in range(1, 96) if i != 20}
        | {"2A", "2B"}
        | {"97", "98", "99"}
    )

    @staticmethod
    def valider(nir: str) -> ValidationResult:
        """Valide un NIR complet (13 chiffres + 2 cle de controle).

        Verifications effectuees :
        - Longueur (13 sans cle, 15 avec cle)
        - Code sexe (1, 2, 3, 4)
        - Code departement valide
        - Cle de controle modulo 97

        Args:
            nir: Numero NIR a valider.

        Returns:
            ValidationResult avec le statut de validation.
        """
        # Delegation au validateur de base existant
        result_base = _valider_nir_base(nir)

        if not result_base.valide:
            return ValidationResult(
                valide=False,
                message=result_base.message,
                valeur_corrigee=result_base.valeur_corrigee,
            )

        nir_clean = result_base.valeur_corrigee

        # Verification supplementaire du departement
        dept_code = nir_clean[1:3]
        # Gestion Corse : caractere alphabetique possible
        if dept_code.upper() in ("2A", "2B"):
            dept_ok = True
        elif dept_code.isdigit():
            dept_num = int(dept_code)
            # 01-95 (sauf 20), 97, 98, 99
            dept_ok = (
                (1 <= dept_num <= 95 and dept_num != 20)
                or dept_num in (97, 98, 99)
            )
        else:
            dept_ok = False

        if not dept_ok:
            return ValidationResult(
                valide=False,
                message=f"Code departement invalide dans le NIR : {dept_code}",
                valeur_corrigee=nir_clean,
            )

        logger.debug("NIR valide (15 caracteres, cle OK, dept %s)", dept_code)
        return ValidationResult(
            valide=True,
            message="NIR valide",
            valeur_corrigee=nir_clean,
        )


# ============================================================
# DSN Schema Validator
# ============================================================

class DSNSchemaValidator:
    """Validation de la structure et de la coherence d'une declaration DSN.

    Verifie la presence des blocs obligatoires, les plages de numeros de blocs,
    et la coherence des dates dans les periodes declarees.
    """

    # Blocs obligatoires dans toute DSN (NEODeS Phase 3)
    BLOCS_OBLIGATOIRES = {"S10", "S20", "S21", "S30"}

    # Plages de numeros de groupes valides par bloc principal
    BLOC_RANGES = {
        "S10": (0, 2),     # S10.G00.00 a S10.G00.02
        "S20": (0, 15),    # S20.G00.00 a S20.G00.15
        "S21": (0, 99),    # S21.G00.00 a S21.G00.99
        "S30": (0, 40),    # S30.G00.00 a S30.G00.40
        "S40": (0, 99),
        "S41": (0, 10),
        "S43": (0, 5),
        "S44": (0, 5),
        "S48": (0, 10),
        "S51": (0, 20),
        "S60": (0, 15),
        "S65": (0, 10),
        "S70": (0, 5),
        "S78": (0, 10),
        "S79": (0, 5),
        "S81": (0, 30),
        "S89": (0, 20),
    }

    @staticmethod
    def valider_structure(donnees: dict) -> list[str]:
        """Verifie la presence des blocs DSN obligatoires.

        Args:
            donnees: Dictionnaire dont les cles sont des identifiants de blocs
                     DSN (ex. 'S10.G00.00.001') ou des noms de blocs principaux
                     (ex. 'S10', 'S20').

        Returns:
            Liste de messages d'erreur (vide si tout est conforme).
        """
        erreurs: list[str] = []

        # Extraire les prefixes de blocs presents dans les donnees
        blocs_presents: set[str] = set()
        for cle in donnees:
            cle_str = str(cle)
            # Extraire le prefixe Sxx depuis 'S10.G00.00.001' ou 'S10'
            if cle_str.startswith("S") and len(cle_str) >= 3:
                prefixe = cle_str[:3]
                blocs_presents.add(prefixe)

        for bloc in DSNSchemaValidator.BLOCS_OBLIGATOIRES:
            if bloc not in blocs_presents:
                erreurs.append(f"Bloc obligatoire manquant : {bloc}")
                logger.warning("DSN : bloc obligatoire %s absent", bloc)

        return erreurs

    @staticmethod
    def valider_bloc_ranges(donnees: dict) -> list[str]:
        """Verifie que les numeros de groupes des blocs sont dans les plages valides.

        Args:
            donnees: Dictionnaire dont les cles sont des identifiants de blocs
                     DSN au format 'Sxx.Gyy.zz.nnn'.

        Returns:
            Liste de messages d'erreur pour les blocs hors plage.
        """
        erreurs: list[str] = []
        import re

        pattern = re.compile(r"^(S\d{2})\.G(\d{2})\.(\d{2})\.\d{3}$")

        for cle in donnees:
            cle_str = str(cle)
            match = pattern.match(cle_str)
            if not match:
                continue

            bloc_principal = match.group(1)
            groupe_num = int(match.group(2))

            if bloc_principal in DSNSchemaValidator.BLOC_RANGES:
                range_min, range_max = DSNSchemaValidator.BLOC_RANGES[bloc_principal]
                if not (range_min <= groupe_num <= range_max):
                    erreurs.append(
                        f"Bloc {cle_str} : numero de groupe {groupe_num:02d} "
                        f"hors plage valide ({range_min:02d}-{range_max:02d}) "
                        f"pour {bloc_principal}"
                    )

        return erreurs

    @staticmethod
    def valider_dates(donnees: dict) -> list[str]:
        """Verifie la coherence des dates dans les blocs DSN.

        Controle que les dates de debut sont anterieures aux dates de fin
        pour les periodes identifiees dans les donnees.

        Args:
            donnees: Dictionnaire de donnees DSN. Les cles de type date
                     doivent contenir 'debut' ou 'fin' et les valeurs
                     etre des objets date, datetime ou des chaines ISO.

        Returns:
            Liste de messages d'erreur pour les incoherences de dates.
        """
        erreurs: list[str] = []

        # Regrouper les dates debut/fin par prefixe de bloc
        dates_debut: dict[str, date] = {}
        dates_fin: dict[str, date] = {}

        for cle, valeur in donnees.items():
            cle_str = str(cle).lower()
            parsed_date = DSNSchemaValidator._parse_date(valeur)
            if parsed_date is None:
                continue

            # Identifier les paires debut/fin par prefixe commun
            if "debut" in cle_str or "start" in cle_str:
                prefixe = cle_str.replace("debut", "").replace("start", "").strip("_. ")
                dates_debut[prefixe] = parsed_date
            elif "fin" in cle_str or "end" in cle_str:
                prefixe = cle_str.replace("fin", "").replace("end", "").strip("_. ")
                dates_fin[prefixe] = parsed_date

        # Comparer les paires trouvees
        for prefixe, dt_debut in dates_debut.items():
            if prefixe in dates_fin:
                dt_fin = dates_fin[prefixe]
                if dt_debut > dt_fin:
                    erreurs.append(
                        f"Incoherence de dates ({prefixe}) : "
                        f"debut {dt_debut.isoformat()} > fin {dt_fin.isoformat()}"
                    )

        return erreurs

    @staticmethod
    def _parse_date(valeur: Any) -> date | None:
        """Tente de convertir une valeur en objet date."""
        if isinstance(valeur, datetime):
            return valeur.date()
        if isinstance(valeur, date):
            return valeur
        if isinstance(valeur, str):
            valeur = valeur.strip()
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d%m%Y"):
                try:
                    return datetime.strptime(valeur, fmt).date()
                except ValueError:
                    continue
        return None


# ============================================================
# FEC Schema Validator
# ============================================================

class FECSchemaValidator:
    """Validation du schema et de la coherence d'un fichier FEC.

    Verifie les 18 colonnes obligatoires (art. A.47 A-1 LPF),
    la sequentialite des numeros d'ecriture, et l'equilibre debit/credit.
    """

    # Les 18 colonnes obligatoires importees du parseur FEC
    COLONNES_OBLIGATOIRES: list[str] = list(COLONNES_FEC)

    @staticmethod
    def valider_colonnes(header: list[str]) -> list[str]:
        """Verifie la presence des 18 colonnes obligatoires du FEC.

        Args:
            header: Liste des noms de colonnes trouvees dans le fichier.

        Returns:
            Liste de messages d'erreur pour les colonnes manquantes.
        """
        erreurs: list[str] = []

        # Normaliser les noms pour comparaison insensible a la casse
        header_lower = {col.strip().lower() for col in header}

        for col_attendue in FECSchemaValidator.COLONNES_OBLIGATOIRES:
            if col_attendue.lower() not in header_lower:
                erreurs.append(
                    f"Colonne FEC obligatoire manquante : {col_attendue} "
                    f"(art. A.47 A-1 LPF)"
                )

        if erreurs:
            logger.warning(
                "FEC : %d colonne(s) obligatoire(s) manquante(s) sur 18",
                len(erreurs),
            )

        return erreurs

    @staticmethod
    def valider_sequentialite(ecritures_nums: list[str]) -> list[str]:
        """Verifie la sequentialite des numeros d'ecriture.

        Le FEC impose un classement chronologique avec une numerotation
        continue (art. L123-12 du Code de Commerce).

        Args:
            ecritures_nums: Liste ordonnee des numeros d'ecriture (EcritureNum).

        Returns:
            Liste de messages d'erreur pour les ruptures de sequence.
        """
        erreurs: list[str] = []

        if not ecritures_nums:
            erreurs.append("Aucun numero d'ecriture fourni")
            return erreurs

        precedent: str | None = None
        for i, num in enumerate(ecritures_nums):
            num_stripped = num.strip()

            if precedent is not None:
                # Comparaison numerique si possible, sinon lexicographique
                try:
                    val_prec = int(precedent)
                    val_curr = int(num_stripped)
                    if val_curr < val_prec:
                        erreurs.append(
                            f"Rupture de sequence a la ligne {i + 1} : "
                            f"ecriture {num_stripped} < precedente {precedent}"
                        )
                    elif val_curr > val_prec + 1:
                        # Trou dans la numerotation
                        ecart = val_curr - val_prec - 1
                        erreurs.append(
                            f"Trou de numerotation a la ligne {i + 1} : "
                            f"{ecart} ecriture(s) manquante(s) "
                            f"entre {precedent} et {num_stripped}"
                        )
                except ValueError:
                    # Numerotation non numerique : verification lexicographique
                    if num_stripped < precedent:
                        erreurs.append(
                            f"Rupture de sequence a la ligne {i + 1} : "
                            f"ecriture '{num_stripped}' < precedente '{precedent}'"
                        )

            precedent = num_stripped

        return erreurs

    @staticmethod
    def valider_equilibre_ecritures(ecritures: dict) -> list[str]:
        """Verifie l'equilibre debit/credit par ecriture comptable.

        Chaque ecriture (identifiee par EcritureNum) doit etre equilibree :
        la somme des debits doit egaliser la somme des credits.

        Args:
            ecritures: Dictionnaire {ecriture_num: [{"Debit": ..., "Credit": ...}, ...]}.
                       Les valeurs Debit/Credit peuvent etre Decimal ou str.

        Returns:
            Liste de messages d'erreur pour les ecritures desequilibrees.
        """
        erreurs: list[str] = []

        for ecriture_num, lignes in ecritures.items():
            total_debit = Decimal("0")
            total_credit = Decimal("0")

            for ligne in lignes:
                debit = FECSchemaValidator._to_decimal(ligne.get("Debit", "0"))
                credit = FECSchemaValidator._to_decimal(ligne.get("Credit", "0"))
                total_debit += debit
                total_credit += credit

            # Tolerance d'un centime pour les arrondis
            ecart = abs(total_debit - total_credit)
            if ecart > Decimal("0.01"):
                erreurs.append(
                    f"Ecriture {ecriture_num} desequilibree : "
                    f"debit={total_debit}, credit={total_credit}, "
                    f"ecart={ecart}"
                )

        if erreurs:
            logger.warning(
                "FEC : %d ecriture(s) desequilibree(s) detectee(s)",
                len(erreurs),
            )

        return erreurs

    @staticmethod
    def _to_decimal(valeur: Any) -> Decimal:
        """Convertit une valeur en Decimal de maniere tolerante."""
        if isinstance(valeur, Decimal):
            return valeur
        if isinstance(valeur, (int, float)):
            return Decimal(str(valeur))
        if isinstance(valeur, str):
            v = valeur.strip().replace(",", ".").replace(" ", "")
            if not v or v == "-":
                return Decimal("0")
            try:
                return Decimal(v)
            except InvalidOperation:
                return Decimal("0")
        return Decimal("0")


# ============================================================
# Taux Validator
# ============================================================

class TauxValidator:
    """Validation de la coherence des taux de cotisation.

    Compare un taux declare avec les plages connues pour chaque type de
    cotisation (reference : urssaf.fr, baremes 2026).
    """

    # Plages acceptables (min, max) en taux decimal pour chaque type de cotisation.
    # Les bornes incluent une marge de tolerance pour les cas particuliers
    # (bonus-malus, taux reduits, majorations).
    TAUX_RANGES: dict[str, tuple[Decimal, Decimal]] = {
        # Securite sociale
        "maladie": (Decimal("0.0"), Decimal("0.14")),
        "maladie_alsace_moselle": (Decimal("0.013"), Decimal("0.015")),
        "vieillesse_plafonnee": (Decimal("0.069"), Decimal("0.155")),
        "vieillesse_deplafonnee": (Decimal("0.004"), Decimal("0.025")),
        "allocations_familiales": (Decimal("0.0345"), Decimal("0.0525")),
        "accident_travail": (Decimal("0.009"), Decimal("0.06")),
        # CSG / CRDS
        "csg_deductible": (Decimal("0.065"), Decimal("0.070")),
        "csg_non_deductible": (Decimal("0.023"), Decimal("0.025")),
        "crds": (Decimal("0.004"), Decimal("0.006")),
        # Contributions URSSAF
        "fnal": (Decimal("0.001"), Decimal("0.005")),
        "versement_mobilite": (Decimal("0.0"), Decimal("0.035")),
        "csa": (Decimal("0.002"), Decimal("0.004")),
        "dialogue_social": (Decimal("0.00010"), Decimal("0.00020")),
        # Chomage
        "assurance_chomage": (Decimal("0.030"), Decimal("0.0505")),
        "ags": (Decimal("0.0010"), Decimal("0.0020")),
        # Formation
        "formation_professionnelle": (Decimal("0.0055"), Decimal("0.015")),
        "taxe_apprentissage": (Decimal("0.0068"), Decimal("0.0077")),
        # Retraite complementaire
        "retraite_complementaire_t1": (Decimal("0.070"), Decimal("0.085")),
        "retraite_complementaire_t2": (Decimal("0.200"), Decimal("0.225")),
        "ceg_t1": (Decimal("0.020"), Decimal("0.025")),
        "ceg_t2": (Decimal("0.025"), Decimal("0.030")),
        "cet": (Decimal("0.003"), Decimal("0.004")),
        "apec": (Decimal("0.0005"), Decimal("0.0007")),
        # Prevoyance
        "prevoyance_cadre": (Decimal("0.015"), Decimal("0.06")),
        "forfait_social": (Decimal("0.08"), Decimal("0.20")),
        # Construction
        "peec": (Decimal("0.0040"), Decimal("0.0050")),
    }

    @classmethod
    def valider_taux_coherent(cls, taux: float, type_cotisation: str) -> bool:
        """Verifie qu'un taux est dans la plage connue pour le type de cotisation.

        Args:
            taux: Taux a verifier (en decimal, ex. 0.13 pour 13%).
            type_cotisation: Identifiant du type de cotisation (cle de TAUX_RANGES).

        Returns:
            True si le taux est dans la plage acceptable, False sinon.
        """
        type_lower = type_cotisation.strip().lower()
        taux_dec = Decimal(str(taux))

        if type_lower not in cls.TAUX_RANGES:
            logger.warning(
                "Type de cotisation inconnu pour la validation de taux : '%s'",
                type_cotisation,
            )
            # Par defaut, un taux entre 0 et 100% est considere acceptable
            return Decimal("0") <= taux_dec <= Decimal("1")

        taux_min, taux_max = cls.TAUX_RANGES[type_lower]
        coherent = taux_min <= taux_dec <= taux_max

        if not coherent:
            logger.info(
                "Taux incoherent pour %s : %s (plage attendue : %s - %s)",
                type_cotisation, taux_dec, taux_min, taux_max,
            )

        return coherent


# ============================================================
# Cross-File Validator
# ============================================================

class CrossFileValidator:
    """Reconciliation entre fichiers DSN et FEC.

    Compare les totaux declares dans la DSN (cotisations sociales) avec
    les soldes comptables FEC (comptes de classe 43x) pour detecter
    les ecarts entre declarations sociales et comptabilite.
    """

    # Tolerance par defaut pour les ecarts de reconciliation
    TOLERANCE_DEFAUT = Decimal("0.01")

    @classmethod
    def reconcilier_dsn_fec(
        cls,
        dsn_totals: dict,
        fec_balances: dict,
        tolerance: Decimal | None = None,
    ) -> dict:
        """Reconciliation croisee entre totaux DSN et soldes FEC.

        Compare les montants declares dans la DSN avec les ecritures comptables
        du FEC pour les memes types de cotisations ou comptes.

        Args:
            dsn_totals: Dictionnaire {type_cotisation: Decimal} des montants
                        declares dans la DSN.
            fec_balances: Dictionnaire {type_cotisation: Decimal} des soldes
                          comptables extraits du FEC.
            tolerance: Ecart maximal tolere (par defaut 0.01 EUR).

        Returns:
            Dictionnaire de resultats :
                - 'ecarts': liste des ecarts detectes avec details
                - 'total_dsn': somme des montants DSN
                - 'total_fec': somme des montants FEC
                - 'ecart_global': ecart total
                - 'reconcilie': True si tous les ecarts sont dans la tolerance
                - 'cles_dsn_seules': cles presentes uniquement dans la DSN
                - 'cles_fec_seules': cles presentes uniquement dans le FEC
        """
        tol = tolerance if tolerance is not None else cls.TOLERANCE_DEFAUT

        # Normaliser les cles
        dsn = {k.strip().lower(): cls._to_decimal(v) for k, v in dsn_totals.items()}
        fec = {k.strip().lower(): cls._to_decimal(v) for k, v in fec_balances.items()}

        cles_dsn = set(dsn.keys())
        cles_fec = set(fec.keys())
        cles_communes = cles_dsn & cles_fec
        cles_dsn_seules = cles_dsn - cles_fec
        cles_fec_seules = cles_fec - cles_dsn

        ecarts: list[dict[str, Any]] = []

        for cle in sorted(cles_communes):
            montant_dsn = dsn[cle]
            montant_fec = fec[cle]
            ecart = montant_dsn - montant_fec

            if abs(ecart) > tol:
                ecarts.append({
                    "type": cle,
                    "montant_dsn": montant_dsn,
                    "montant_fec": montant_fec,
                    "ecart": ecart,
                    "ecart_pct": (
                        (ecart / montant_dsn * 100) if montant_dsn != 0
                        else Decimal("0")
                    ),
                })

        # Ajouter les cles orphelines comme ecarts
        for cle in sorted(cles_dsn_seules):
            ecarts.append({
                "type": cle,
                "montant_dsn": dsn[cle],
                "montant_fec": Decimal("0"),
                "ecart": dsn[cle],
                "note": "Present uniquement dans la DSN",
            })

        for cle in sorted(cles_fec_seules):
            ecarts.append({
                "type": cle,
                "montant_dsn": Decimal("0"),
                "montant_fec": fec[cle],
                "ecart": -fec[cle],
                "note": "Present uniquement dans le FEC",
            })

        total_dsn = sum(dsn.values(), Decimal("0"))
        total_fec = sum(fec.values(), Decimal("0"))
        ecart_global = total_dsn - total_fec

        reconcilie = len(ecarts) == 0

        if ecarts:
            logger.info(
                "Reconciliation DSN/FEC : %d ecart(s) detecte(s), ecart global %s EUR",
                len(ecarts), ecart_global,
            )

        return {
            "ecarts": ecarts,
            "total_dsn": total_dsn,
            "total_fec": total_fec,
            "ecart_global": ecart_global,
            "reconcilie": reconcilie,
            "cles_dsn_seules": sorted(cles_dsn_seules),
            "cles_fec_seules": sorted(cles_fec_seules),
        }

    @staticmethod
    def _to_decimal(valeur: Any) -> Decimal:
        """Convertit une valeur en Decimal de maniere tolerante."""
        if isinstance(valeur, Decimal):
            return valeur
        if isinstance(valeur, (int, float)):
            return Decimal(str(valeur))
        if isinstance(valeur, str):
            v = valeur.strip().replace(",", ".").replace(" ", "")
            if not v:
                return Decimal("0")
            try:
                return Decimal(v)
            except InvalidOperation:
                return Decimal("0")
        return Decimal("0")
