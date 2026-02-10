"""Exceptions personnalisees pour URSSAF Analyzer."""


class URSSAFAnalyzerError(Exception):
    """Exception de base."""


class ParseError(URSSAFAnalyzerError):
    """Erreur lors du parsing d'un document."""


class UnsupportedFormatError(ParseError):
    """Format de fichier non supporte."""


class SecurityError(URSSAFAnalyzerError):
    """Erreur de securite."""


class EncryptionError(SecurityError):
    """Erreur de chiffrement/dechiffrement."""


class IntegrityError(SecurityError):
    """Erreur d'integrite des donnees."""


class AnalysisError(URSSAFAnalyzerError):
    """Erreur lors de l'analyse."""


class ReportError(URSSAFAnalyzerError):
    """Erreur lors de la generation du rapport."""


class ConfigError(URSSAFAnalyzerError):
    """Erreur de configuration."""
