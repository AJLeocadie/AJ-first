"""Validation stricte des donnees entrantes.

Niveau de fiabilite : bancaire.
Toute donnee entrant dans le systeme est validee avant traitement.
"""

import re
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

logger = logging.getLogger("urssaf_analyzer.validation")

# Patterns de validation
_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)
_SIRET_PATTERN = re.compile(r"^\d{14}$")
_SIREN_PATTERN = re.compile(r"^\d{9}$")
_NIR_PATTERN = re.compile(r"^[12][0-9]{12,14}$")
_PHONE_PATTERN = re.compile(r"^(\+33|0)[1-9]\d{8}$")

# Limites
MAX_FILE_SIZE_MB = 100
MAX_FILENAME_LENGTH = 255
MAX_STRING_LENGTH = 10000
ALLOWED_FILE_EXTENSIONS = {
    ".csv", ".xml", ".pdf", ".xlsx", ".xls",
    ".dsn", ".txt", ".docx", ".jpg", ".jpeg",
    ".png", ".heic", ".heif", ".pnm",
}


class ValidationError(Exception):
    """Erreur de validation des donnees entrantes."""

    def __init__(self, field: str, message: str, value: Any = None):
        self.field = field
        self.message = message
        self.value = value
        super().__init__(f"Validation [{field}]: {message}")


def validate_email(email: str) -> str:
    """Valide et normalise un email."""
    if not email or not isinstance(email, str):
        raise ValidationError("email", "Email requis")
    email = email.strip().lower()
    if len(email) > 254:
        raise ValidationError("email", "Email trop long (max 254 caracteres)")
    if not _EMAIL_PATTERN.match(email):
        raise ValidationError("email", "Format d'email invalide", email)
    return email


def validate_password(password: str) -> str:
    """Valide la robustesse d'un mot de passe."""
    if not password or not isinstance(password, str):
        raise ValidationError("password", "Mot de passe requis")
    if len(password) < 12:
        raise ValidationError("password", "Mot de passe trop court (min 12 caracteres)")
    if len(password) > 128:
        raise ValidationError("password", "Mot de passe trop long (max 128 caracteres)")
    if password.lower() == password:
        raise ValidationError("password", "Doit contenir au moins une majuscule")
    if password.upper() == password:
        raise ValidationError("password", "Doit contenir au moins une minuscule")
    if not re.search(r"\d", password):
        raise ValidationError("password", "Doit contenir au moins un chiffre")
    return password


def validate_siret(siret: str) -> str:
    """Valide un numero SIRET (14 chiffres, algo Luhn)."""
    if not siret or not isinstance(siret, str):
        raise ValidationError("siret", "SIRET requis")
    siret = siret.replace(" ", "")
    if not _SIRET_PATTERN.match(siret):
        raise ValidationError("siret", "SIRET invalide (14 chiffres requis)", siret)
    # Verification Luhn
    if not _check_luhn(siret):
        raise ValidationError("siret", "SIRET invalide (cle de controle incorrecte)", siret)
    return siret


def validate_siren(siren: str) -> str:
    """Valide un numero SIREN (9 chiffres, algo Luhn)."""
    if not siren or not isinstance(siren, str):
        raise ValidationError("siren", "SIREN requis")
    siren = siren.replace(" ", "")
    if not _SIREN_PATTERN.match(siren):
        raise ValidationError("siren", "SIREN invalide (9 chiffres requis)", siren)
    if not _check_luhn(siren):
        raise ValidationError("siren", "SIREN invalide (cle de controle incorrecte)", siren)
    return siren


def validate_nir(nir: str) -> str:
    """Valide un NIR (numero de securite sociale)."""
    if not nir or not isinstance(nir, str):
        raise ValidationError("nir", "NIR requis")
    nir = nir.replace(" ", "")
    if not _NIR_PATTERN.match(nir):
        raise ValidationError("nir", "NIR invalide", nir)
    return nir


def validate_amount(value: Any, field_name: str = "montant") -> Decimal:
    """Valide et convertit un montant financier."""
    if value is None:
        raise ValidationError(field_name, "Montant requis")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(field_name, f"Montant invalide: {value}", value)
    if abs(amount) > Decimal("999999999.99"):
        raise ValidationError(field_name, "Montant hors limites", value)
    return amount


def validate_rate(value: Any, field_name: str = "taux") -> Decimal:
    """Valide un taux (pourcentage entre 0 et 100 ou decimal entre 0 et 1)."""
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(field_name, f"Taux invalide: {value}", value)
    if rate < 0:
        raise ValidationError(field_name, "Taux negatif", value)
    if rate > 100:
        raise ValidationError(field_name, "Taux superieur a 100%", value)
    return rate


def validate_file_upload(filename: str, file_size: int) -> str:
    """Valide un fichier uploade."""
    if not filename:
        raise ValidationError("filename", "Nom de fichier requis")
    if len(filename) > MAX_FILENAME_LENGTH:
        raise ValidationError("filename", f"Nom trop long (max {MAX_FILENAME_LENGTH})")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_FILE_EXTENSIONS:
        raise ValidationError(
            "filename",
            f"Extension '{ext}' non autorisee. Extensions valides: {', '.join(sorted(ALLOWED_FILE_EXTENSIONS))}",
        )

    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        raise ValidationError(
            "file_size",
            f"Fichier trop volumineux ({file_size / 1024 / 1024:.1f} MB, max {MAX_FILE_SIZE_MB} MB)",
        )
    if file_size == 0:
        raise ValidationError("file_size", "Fichier vide")

    return filename


def validate_string(
    value: str,
    field_name: str,
    min_length: int = 0,
    max_length: int = MAX_STRING_LENGTH,
    allow_empty: bool = False,
) -> str:
    """Valide une chaine de caracteres."""
    if not isinstance(value, str):
        raise ValidationError(field_name, "Chaine de caracteres requise")
    if not allow_empty and not value.strip():
        raise ValidationError(field_name, "Champ requis (ne peut pas etre vide)")
    if len(value) < min_length:
        raise ValidationError(field_name, f"Trop court (min {min_length} caracteres)")
    if len(value) > max_length:
        raise ValidationError(field_name, f"Trop long (max {max_length} caracteres)")
    # Detecter les injections
    _check_injection(value, field_name)
    return value


def _check_luhn(number: str) -> bool:
    """Verification Luhn (ISO/IEC 7812-1)."""
    digits = [int(d) for d in number]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _check_injection(value: str, field_name: str):
    """Detecte les tentatives d'injection basiques."""
    dangerous_patterns = [
        "<script",
        "javascript:",
        "onload=",
        "onerror=",
        "'; DROP",
        "1=1",
        "UNION SELECT",
    ]
    value_lower = value.lower()
    for pattern in dangerous_patterns:
        if pattern.lower() in value_lower:
            logger.warning(
                "Tentative d'injection detectee dans %s: %s",
                field_name, pattern,
            )
            raise ValidationError(
                field_name,
                "Contenu potentiellement dangereux detecte",
            )
