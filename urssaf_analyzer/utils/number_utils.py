"""Utilitaires pour le traitement des montants et nombres."""

import re
from decimal import Decimal, InvalidOperation


def parser_montant(valeur: str) -> Decimal:
    """Parse un montant depuis differents formats (1 234,56 ou 1234.56 etc.)."""
    if not valeur or not valeur.strip():
        return Decimal("0")

    v = valeur.strip()

    # Retirer les symboles monetaires
    v = v.replace("€", "").replace("EUR", "").replace("$", "").strip()

    # Gerer le format francais : 1 234,56
    if "," in v and "." in v:
        # 1.234,56 -> format europeen
        if v.rindex(",") > v.rindex("."):
            v = v.replace(".", "").replace(",", ".")
        else:
            # 1,234.56 -> format anglo-saxon
            v = v.replace(",", "")
    elif "," in v:
        # Virgule comme separateur decimal
        v = v.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    else:
        v = v.replace(" ", "").replace("\u00a0", "")

    try:
        return Decimal(v)
    except InvalidOperation:
        return Decimal("0")


def est_nombre_rond(montant: Decimal, precision: int = 0) -> bool:
    """Verifie si un montant est un nombre rond."""
    if precision == 0:
        return montant == montant.to_integral_value()
    diviseur = Decimal(10) ** precision
    return (montant / diviseur) == (montant / diviseur).to_integral_value()


def ecart_relatif(valeur: Decimal, reference: Decimal) -> Decimal:
    """Calcule l'ecart relatif entre deux valeurs."""
    if reference == 0:
        return Decimal("0") if valeur == 0 else Decimal("1")
    return abs(valeur - reference) / abs(reference)


def formater_montant(montant: Decimal) -> str:
    """Formate un montant en format francais."""
    signe = "-" if montant < 0 else ""
    abs_montant = abs(montant)
    partie_entiere = int(abs_montant)
    partie_decimale = abs_montant - partie_entiere
    decimales = f"{partie_decimale:.2f}"[1:]  # .XX

    # Separateur de milliers
    s = str(partie_entiere)
    groupes = []
    while s:
        groupes.insert(0, s[-3:])
        s = s[:-3]
    entier_formate = " ".join(groupes)

    return f"{signe}{entier_formate}{decimales} EUR"
