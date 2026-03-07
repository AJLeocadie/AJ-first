"""Module de validation des donnees metier.

Fournit des validateurs structures pour les identifiants sociaux (SIREN, NIR),
les schemas de fichiers reglementaires (DSN, FEC), les taux de cotisation,
et la reconciliation inter-fichiers.

Utilisation :

    from urssaf_analyzer.validators import SIRENValidator, ValidationResult

    result = SIRENValidator.valider("443061841")
    if result.valide:
        print(f"SIREN OK : {result.valeur_corrigee}")

Les validateurs de bas niveau (fonctions) restent disponibles dans
urssaf_analyzer.utils.validators (valider_nir, valider_bloc_dsn, etc.).
"""

from urssaf_analyzer.validators.data_validators import (
    CrossFileValidator,
    DSNSchemaValidator,
    FECSchemaValidator,
    NIRValidator,
    SIRENValidator,
    TauxValidator,
    ValidationResult,
)

__all__ = [
    "CrossFileValidator",
    "DSNSchemaValidator",
    "FECSchemaValidator",
    "NIRValidator",
    "SIRENValidator",
    "TauxValidator",
    "ValidationResult",
]
