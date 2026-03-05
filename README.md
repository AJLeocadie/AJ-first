# NormaCheck

Logiciel sécurisé d'analyse de documents sociaux et fiscaux, conçu pour automatiser l'audit de conformité URSSAF, DGFIP et Cour des comptes.

[![CI](https://github.com/AJLeocadie/AJ-first/actions/workflows/ci.yml/badge.svg)](https://github.com/AJLeocadie/AJ-first/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Fonctionnalités

- **Analyse multi-documents** : DSN, bulletins de paie, bordereaux URSSAF, fichiers CSV/XML/PDF
- **Scoring de conformité** : 3 scores distincts (URSSAF, DGFIP, Cour des comptes) avec formules détaillées
- **Détection d'anomalies** : identification automatique des écarts, incohérences et risques
- **Chaîne de preuve numérique** : traçabilité inviolable des scores (horodatage RFC 3161)
- **Sécurité** : chiffrement, authentification JWT, conformité RGPD art. 22
- **Reporting** : génération de rapports d'audit détaillés
- **OCR** : extraction de données depuis des documents scannés (Tesseract)

## Prérequis

- Python 3.11+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (optionnel, pour l'OCR)

## Installation

```bash
# Cloner le dépôt
git clone https://github.com/AJLeocadie/AJ-first.git
cd AJ-first

# Créer un environnement virtuel
python -m venv .venv
source .venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt

# Configurer l'environnement
cp .env.example .env
# Éditer .env avec vos paramètres
```

## Utilisation

### Serveur API (développement)

```bash
uvicorn api.index:app --reload --port 8000
```

### Ligne de commande

```bash
python -m urssaf_analyzer --help
```

### Docker (production)

```bash
docker compose up -d
```

L'application est accessible sur `http://localhost:8000`.

## Tests

```bash
# Lancer tous les tests
python -m pytest tests/ -v

# Avec couverture
python -m pytest tests/ --cov=urssaf_analyzer --cov-report=term-missing

# Tests par catégorie
python -m pytest tests/ -m determinisme    # ISO 42001
python -m pytest tests/ -m securite        # ISO 27001
python -m pytest tests/ -m rgpd            # RGPD
```

## Qualité du code

```bash
# Linting
ruff check .

# Formatage
ruff format .

# Type checking
mypy urssaf_analyzer/
```

## Architecture

```
urssaf_analyzer/
├── analyzers/       # Analyseurs de documents (DSN, paie, URSSAF...)
├── certification/   # Outils de certification ISO
├── compliance/      # Règles de conformité
├── config/          # Configuration
├── core/            # Moteur de scoring et logique métier
├── database/        # Couche de persistance
├── models/          # Modèles de données
├── ocr/             # Extraction OCR
├── parsers/         # Parseurs de fichiers (CSV, XML, PDF...)
├── reporting/       # Génération de rapports
├── rules/           # Règles métier
├── security/        # Chiffrement et sécurité
└── utils/           # Utilitaires
api/
├── index.py         # Application FastAPI (endpoints REST)
tests/
├── unit/            # Tests unitaires
├── integration/     # Tests d'intégration
└── fixtures/        # Données de test
```

## Déploiement

Le déploiement en production sur OVH VPS est automatisé via GitHub Actions. Un push sur `main` déclenche :

1. Exécution des tests
2. Build Docker multi-stage
3. Déploiement via SSH avec health check

Voir [deploy-ovh.yml](.github/workflows/deploy-ovh.yml) pour les détails.

## Conformité et certifications

Ce projet vise la conformité avec :

- **ISO/IEC 25010** : qualité logicielle
- **ISO 27001** : sécurité de l'information
- **ISO 42001** : systèmes d'IA
- **RGPD** : protection des données personnelles
- **NF Z42-013** : archivage électronique

## Licence

Ce projet est sous licence MIT. Voir le fichier [LICENSE](LICENSE) pour plus de détails.

