# Changelog

Toutes les modifications notables de ce projet sont documentées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

## [1.0.0] - 2026-03-04

### Ajouté
- Analyse multi-documents (DSN, bulletins de paie, bordereaux URSSAF)
- 3 scores de conformité distincts (URSSAF, DGFIP, Cour des comptes)
- Chaîne de preuve numérique avec horodatage RFC 3161
- Alertes sécurité PSSI §6.3 et déduplication inter-analyzers
- Conformité RGPD art. 22 (aide à la décision avec garde-fous)
- Certification readiness ISO 27001 / 42001
- Authentification JWT avec bootstrap admin automatique
- API REST FastAPI complète
- Déploiement Docker + CI/CD OVHcloud
- OCR via Tesseract pour documents scannés
- Audit QA pré-production (14 failles critiques corrigées)
- Audit juridique adversarial (12 failles corrigées)
