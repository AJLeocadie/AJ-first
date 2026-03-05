"""Validation des données métier pour les parseurs de documents.

Fournit des fonctions de validation pour les identifiants (NIR, SIRET, SIREN),
les montants, les taux, et d'autres données critiques utilisées par les parseurs.
"""

import logging
import re
from decimal import Decimal
from typing import NamedTuple

logger = logging.getLogger(__name__)


class ValidationResult(NamedTuple):
    """Résultat d'une validation."""
    valide: bool
    valeur_corrigee: str
    message: str


# ============================================================
# NIR (Numéro d'Inscription au Répertoire - Sécurité Sociale)
# ============================================================

def valider_nir(nir: str) -> ValidationResult:
    """Valide et normalise un NIR (numéro de sécurité sociale).

    Format: 1 chiffre sexe + 2 annee + 2 mois + 5 commune/pays + 3 ordre + 2 cle
    Total: 15 caractères (13 chiffres + 2 clé de contrôle).
    La Corse utilise 2A/2B au lieu de 20/19.
    """
    nir_clean = nir.strip().replace(" ", "").replace(".", "").replace("-", "")

    if not nir_clean:
        return ValidationResult(False, "", "NIR vide")

    # Gestion des NIR corses (2A, 2B)
    nir_calc = nir_clean.upper()
    corse_offset = 0
    if "2A" in nir_calc[:3]:
        nir_calc = nir_calc.replace("2A", "19", 1)
        corse_offset = 0
    elif "2B" in nir_calc[:3]:
        nir_calc = nir_calc.replace("2B", "18", 1)
        corse_offset = 0

    if len(nir_clean) == 13:
        # NIR sans clé de contrôle - on peut calculer
        if not nir_calc[:13].isdigit():
            return ValidationResult(False, nir_clean, "NIR contient des caractères invalides")
        cle = 97 - (int(nir_calc[:13]) % 97)
        nir_complet = nir_clean + f"{cle:02d}"
        return ValidationResult(True, nir_complet, "NIR valide (clé calculée)")

    if len(nir_clean) != 15:
        return ValidationResult(False, nir_clean, f"NIR doit avoir 15 caractères, trouvé {len(nir_clean)}")

    if not nir_calc.isdigit():
        return ValidationResult(False, nir_clean, "NIR contient des caractères invalides")

    # Vérification de la clé de contrôle
    nombre = int(nir_calc[:13])
    cle_attendue = 97 - (nombre % 97)
    cle_fournie = int(nir_calc[13:15])

    if cle_attendue != cle_fournie:
        return ValidationResult(
            False, nir_clean,
            f"Clé NIR invalide: attendue {cle_attendue:02d}, trouvée {cle_fournie:02d}"
        )

    # Vérification du sexe (1=M, 2=F, 3/4=étranger provisoire)
    sexe = int(nir_clean[0])
    if sexe not in (1, 2, 3, 4):
        return ValidationResult(False, nir_clean, f"Code sexe invalide: {sexe}")

    # Vérification du mois (01-12, ou 20-42 pour certains cas spéciaux)
    mois = int(nir_clean[3:5])
    if not (1 <= mois <= 12 or 20 <= mois <= 42 or mois == 99):
        return ValidationResult(False, nir_clean, f"Mois invalide dans le NIR: {mois}")

    return ValidationResult(True, nir_clean, "NIR valide")


# ============================================================
# Validation des montants et taux
# ============================================================

def valider_montant(montant: Decimal, champ: str = "montant",
                    min_val: Decimal | None = None,
                    max_val: Decimal | None = None,
                    accepter_negatif: bool = True) -> ValidationResult:
    """Valide un montant financier.

    Args:
        montant: Le montant à valider.
        champ: Nom du champ pour le message d'erreur.
        min_val: Valeur minimale acceptable.
        max_val: Valeur maximale acceptable.
        accepter_negatif: Si False, rejette les montants négatifs.
    """
    if not accepter_negatif and montant < 0:
        return ValidationResult(
            False, str(montant),
            f"{champ}: montant négatif non autorisé ({montant})"
        )

    if min_val is not None and montant < min_val:
        return ValidationResult(
            False, str(montant),
            f"{champ}: montant {montant} inférieur au minimum {min_val}"
        )

    if max_val is not None and montant > max_val:
        return ValidationResult(
            False, str(montant),
            f"{champ}: montant {montant} supérieur au maximum {max_val}"
        )

    return ValidationResult(True, str(montant), "Montant valide")


def valider_taux(taux: Decimal, champ: str = "taux") -> ValidationResult:
    """Valide un taux de cotisation (doit être entre 0 et 1, soit 0% à 100%).

    Si le taux est > 1, il est considéré comme exprimé en pourcentage et converti.
    Si le taux est > 100 (après conversion), il est considéré invalide.
    """
    if taux < 0:
        return ValidationResult(False, str(taux), f"{champ}: taux négatif ({taux})")

    if taux > 1:
        # Probablement exprimé en pourcentage
        taux_converti = taux / 100
        if taux_converti > 1:
            return ValidationResult(
                False, str(taux),
                f"{champ}: taux aberrant ({taux}%, soit {taux_converti*100:.1f}%)"
            )
        return ValidationResult(True, str(taux_converti), f"Taux converti de {taux}% à {taux_converti}")

    return ValidationResult(True, str(taux), "Taux valide")


def valider_base_brute(base: Decimal, net: Decimal | None = None,
                       cotisations: Decimal | None = None) -> ValidationResult:
    """Vérifie la cohérence entre base brute, net et cotisations."""
    if base <= 0:
        return ValidationResult(False, str(base), "Base brute nulle ou négative")

    # Plafond raisonnable: 100x le PMSS 2026 (mensuel ~3 864 EUR)
    if base > Decimal("500000"):
        return ValidationResult(
            False, str(base),
            f"Base brute anormalement élevée: {base} EUR"
        )

    if net is not None and net > 0:
        # Le net ne peut pas être supérieur au brut (sauf avantages en nature)
        if net > base * Decimal("1.05"):  # Marge 5% pour avantages
            return ValidationResult(
                False, str(base),
                f"Net ({net}) supérieur au brut ({base})"
            )

    return ValidationResult(True, str(base), "Base brute valide")


# ============================================================
# Validation spécifique DSN
# ============================================================

def valider_bloc_dsn(bloc: str, valeur: str) -> ValidationResult:
    """Valide une valeur de bloc DSN selon la norme NEODeS."""
    # S20.G00.05.001 = SIREN (9 chiffres)
    if bloc == "S20.G00.05.001":
        from urssaf_analyzer.utils.number_utils import valider_siren
        v = valeur.strip().replace(" ", "")
        if valider_siren(v):
            return ValidationResult(True, v, "SIREN valide")
        return ValidationResult(False, v, "SIREN invalide (Luhn)")

    # S21.G00.06.001 = SIRET (14 chiffres)
    if bloc == "S21.G00.06.001":
        from urssaf_analyzer.utils.number_utils import valider_siret
        v = valeur.strip().replace(" ", "")
        if valider_siret(v):
            return ValidationResult(True, v, "SIRET valide")
        return ValidationResult(False, v, "SIRET invalide (Luhn)")

    # S21.G00.30.001 = NIR
    if bloc == "S21.G00.30.001" or bloc == "S30.G00.30.001":
        return valider_nir(valeur)

    return ValidationResult(True, valeur, "Non validé (pas de règle spécifique)")


# ============================================================
# Validation FEC spécifique
# ============================================================

# Classes de comptes du PCG (Plan Comptable Général)
CLASSES_PCG = {
    "1": "Comptes de capitaux",
    "2": "Comptes d'immobilisations",
    "3": "Comptes de stocks",
    "4": "Comptes de tiers",
    "5": "Comptes financiers",
    "6": "Comptes de charges",
    "7": "Comptes de produits",
}

# Comptes sociaux courants (classe 43x = Personnel et organismes sociaux)
COMPTES_SOCIAUX = {
    "421": "Personnel - Rémunérations dues",
    "425": "Personnel - Avances et acomptes",
    "427": "Personnel - Oppositions",
    "428": "Personnel - Charges à payer",
    "431": "Sécurité sociale",
    "437": "Autres organismes sociaux",
    "438": "Organismes sociaux - Charges à payer",
    "4311": "URSSAF - Cotisations",
    "4312": "URSSAF - Allocations familiales",
    "4313": "URSSAF - CSG/CRDS",
    "43711": "AGIRC-ARRCO",
    "43712": "Prévoyance",
    "43713": "Mutuelle obligatoire",
    "43714": "France Travail - Assurance chômage",
    "43715": "AGS",
}


def valider_compte_fec(compte_num: str) -> ValidationResult:
    """Valide un numéro de compte selon le Plan Comptable Général."""
    compte = compte_num.strip()
    if not compte:
        return ValidationResult(False, "", "Numéro de compte vide")

    if not compte[0].isdigit():
        return ValidationResult(False, compte, f"Compte ne commence pas par un chiffre: {compte}")

    classe = compte[0]
    if classe not in CLASSES_PCG and classe not in ("0", "8", "9"):
        return ValidationResult(False, compte, f"Classe de compte inconnue: {classe}")

    if len(compte) < 3:
        return ValidationResult(False, compte, f"Numéro de compte trop court: {compte}")

    return ValidationResult(True, compte, f"Compte valide - {CLASSES_PCG.get(classe, 'Hors PCG standard')}")


# ============================================================
# ParseLog - Journal de parsing structuré
# ============================================================

class ParseLog:
    """Journal structuré pour tracer les opérations de parsing et les erreurs."""

    def __init__(self, parser_name: str, fichier: str = ""):
        self.parser_name = parser_name
        self.fichier = fichier
        self._errors: list[dict] = []
        self._warnings: list[dict] = []
        self._info: list[str] = []

    def error(self, ligne: int, champ: str, message: str, valeur: str = "") -> None:
        self._errors.append({
            "ligne": ligne, "champ": champ,
            "message": message, "valeur": valeur,
        })

    def warning(self, ligne: int, champ: str, message: str, valeur: str = "") -> None:
        self._warnings.append({
            "ligne": ligne, "champ": champ,
            "message": message, "valeur": valeur,
        })

    def info(self, message: str) -> None:
        self._info.append(message)

    @property
    def has_errors(self) -> bool:
        return len(self._errors) > 0

    @property
    def errors(self) -> list[dict]:
        return self._errors

    @property
    def warnings(self) -> list[dict]:
        return self._warnings

    def to_dict(self) -> dict:
        return {
            "parser": self.parser_name,
            "fichier": self.fichier,
            "nb_erreurs": len(self._errors),
            "nb_avertissements": len(self._warnings),
            "erreurs": self._errors[:50],
            "avertissements": self._warnings[:50],
            "info": self._info[:20],
        }
