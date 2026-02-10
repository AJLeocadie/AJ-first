"""Utilitaires de parsing et manipulation de dates."""

from datetime import date, datetime
from typing import Optional

FORMATS_DATE = [
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y%m%d",
    "%m/%Y",
    "%Y/%m",
    "%d/%m/%y",
]


def parser_date(valeur: str) -> Optional[date]:
    """Tente de parser une date a partir de differents formats courants."""
    valeur = valeur.strip()
    if not valeur:
        return None

    for fmt in FORMATS_DATE:
        try:
            return datetime.strptime(valeur, fmt).date()
        except ValueError:
            continue
    return None


def mois_entre(debut: date, fin: date) -> int:
    """Calcule le nombre de mois entre deux dates."""
    return (fin.year - debut.year) * 12 + (fin.month - debut.month) + 1


def meme_periode(d1_debut: date, d1_fin: date, d2_debut: date, d2_fin: date) -> bool:
    """Verifie si deux periodes se chevauchent."""
    return d1_debut <= d2_fin and d2_debut <= d1_fin
