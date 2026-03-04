# Dossier d'Architecture Technique (DAT) - NormaCheck v4.0

**Version :** 4.0
**Date :** 2026-03-04
**Statut :** En cours de validation
**Classification :** Interne - Confidentiel

---

## 1. Vue d'ensemble

### 1.1 Objectif du systeme

NormaCheck est une plateforme d'aide a la decision pour l'audit de conformite sociale et fiscale. Elle analyse des documents declaratifs (DSN, bulletins de paie, bordereaux URSSAF) et produit un triple score de conformite couvrant trois domaines reglementaires.

### 1.2 Qualification reglementaire

- **Art. 22 RGPD :** Outil d'aide a la decision (non decision automatisee)
- **Art. L121-1 CRPA :** Procedure contradictoire integree
- **NF Z42-013 :** Archivage a valeur probante (chaine de preuve SHA-256)
- **eIDAS (UE 910/2014) :** Horodatage et integrite

### 1.3 Perimetre fonctionnel

| Domaine | Organisme | Points de controle | Cadre legal |
|---------|-----------|-------------------|-------------|
| URSSAF | Caisse Nationale | 10 | Code de la securite sociale (CSS) |
| DGFIP | Direction Generale des Finances Publiques | 10 | Code general des impots (CGI) |
| Cour des comptes | CRC | 8 | Code de commerce / NEP-ISA |

---

## 2. Architecture logique

### 2.1 Couches applicatives

```
+------------------------------------------------------------------+
|                     COUCHE PRESENTATION                          |
|  Landing page / Application SPA / PDF Export                     |
|  (HTML/CSS/JS inline dans api/index.py)                          |
+------------------------------------------------------------------+
|                     COUCHE API (FastAPI)                          |
|  128 endpoints REST (89 GET, 35 POST, 2 PUT, 2 DELETE)           |
|  Middleware : CORS + Auth JWT + Auto-persistence                  |
+------------------------------------------------------------------+
|                   COUCHE METIER (Python)                          |
|  +------------------+  +-------------------+  +----------------+ |
|  | Moteur d'analyse |  | Scoring Engine    |  | Modules metier | |
|  | (3 analyseurs)   |  | (JS client-side)  |  | (RH, Compta,   | |
|  |                  |  |                   |  |  Simulations)  | |
|  +------------------+  +-------------------+  +----------------+ |
+------------------------------------------------------------------+
|                   COUCHE SECURITE                                 |
|  Chaine de preuve | Chiffrement AES-256 | Audit logger           |
|  SHA-256 chaine   | PBKDF2 + GCM        | JSON Lines append-only |
+------------------------------------------------------------------+
|                   COUCHE DONNEES                                  |
|  SQLite (OVH) | In-memory (Vercel) | Fichiers persistants       |
+------------------------------------------------------------------+
```

### 2.2 Pipeline d'analyse

```
Documents (DSN, PDF, CSV, XML)
        |
        v
  +-- Parsers --+
  |  pdf_parser  |
  |  csv_parser  |
  |  xml_parser  |
  |  dsn_parser  |
  +------+------+
         |
         v
  Declaration[]  (modele unifie)
         |
         v
  +-- AnalyzerEngine --+
  |                     |
  |  1. AnomalyDetector |  -> Anomalies intra-document
  |  2. ConsistencyChecker -> Incoherences inter-documents
  |  3. PatternAnalyzer |  -> Patterns statistiques
  |                     |
  +----------+----------+
             |
             v
       Finding[] (constats)
             |
             v
  +-- Scoring Engine (JS) --+
  |                          |
  |  categToDomain()         |  -> Routage domaine + trace
  |  _scoreOne()             |  -> Score par domaine
  |  calculateTripleScore()  |  -> Score global pondere
  |                          |
  +------------+-------------+
               |
               v
     Triple Score + Proof Record
               |
               v
     +-- ProofChain --+
     |  SHA-256 chain  |  -> Scellement cryptographique
     +----------------+
```

### 2.3 Modele de donnees principal

```
Declaration
  +-- type_declaration: str (DSN, DUCS, AE...)
  +-- periode: DateRange (debut, fin)
  +-- employeur: Employeur (siret, effectif, raison_sociale)
  +-- employes: list[Employe] (nir, nom, statut, temps_travail)
  +-- cotisations: list[Cotisation] (type, base, taux, montants)
  +-- masse_salariale_brute: Decimal
  +-- effectif_declare: int

Finding
  +-- categorie: FindingCategory (ANOMALIE, INCOHERENCE, DONNEE_MANQUANTE,
  |                                DEPASSEMENT_SEUIL, PATTERN_SUSPECT)
  +-- severite: Severity (CRITIQUE, HAUTE, MOYENNE, FAIBLE)
  +-- titre: str
  +-- description: str
  +-- score_risque: int (0-100)
  +-- reference_legale: str
  +-- montant_impact: Decimal
  +-- recommandation: str
  +-- detecte_par: str
```

---

## 3. Architecture des composants

### 3.1 Moteur d'analyse (`urssaf_analyzer/`)

| Package | Responsabilite |
|---------|---------------|
| `analyzers/` | 3 analyseurs (anomalies, coherence, patterns) + moteur orchestrateur |
| `config/` | Constantes reglementaires 2026 (PASS, SMIC, taux), settings |
| `models/` | Modeles de donnees (Declaration, Finding, Employe, Cotisation) |
| `parsers/` | Extraction de donnees (PDF, CSV, XML, DSN) |
| `security/` | Chaine de preuve, chiffrement AES-256, audit logger, stockage securise, alertes securite (PSSI §6.3), horodatage RFC 3161 |
| `rules/` | Regles de contribution, regimes speciaux, travailleurs detaches |
| `regimes/` | Regimes specifiques (independants, GUSO/AGESSA) |
| `compliance/` | Verification de completude documentaire |
| `comptabilite/` | Plan comptable, ecritures, bilan, compte de resultat |
| `reporting/` | Generation de rapports (templates Jinja2) |
| `veille/` | Clients Legifrance et URSSAF pour mise a jour reglementaire |
| `certification/` | Evaluation de maturite pour certification ISO |
| `core/` | Orchestrateur principal du workflow d'analyse |
| `utils/` | Utilitaires (dates, nombres) |
| `ocr/` | Extraction OCR (Tesseract) |
| `portfolio/` | Gestion multi-entreprises |
| `database/` | Couche d'acces aux donnees |

### 3.2 Couche API (`api/index.py`)

**Framework :** FastAPI (ASGI)
**Serveur :** Gunicorn + Uvicorn workers
**Endpoints :** 128 routes RESTful

| Categorie | Nb endpoints | Fonction |
|-----------|-------------|----------|
| Analyse & Scoring | 5 | Analyse de documents, methodologie, scoring |
| Chaine de preuve | 5 | Scellement, verification, consultation |
| Validation RGPD | 4 | Validation humaine, contestation, statut |
| Certification | 1 | Evaluation de maturite ISO |
| Authentification | 4 | Login, register, logout, profil |
| RH | 29 | Gestion complete des ressources humaines |
| Comptabilite | 16 | Journal, balance, bilan, ecritures |
| Simulations | 18 | Bulletins, optimisation, couts |
| References | 8 | IDCC, AT/MP, regimes speciaux |
| Entreprises | 4 | CRUD multi-entreprises |
| Veille reglementaire | 5 | Baremes, legislation, alertes |
| Autres | 29 | Collaboration, documents, DSN, export, config |

### 3.3 Scoring Engine (JavaScript client-side)

Le moteur de scoring s'execute cote client (navigateur). Choix delibere :
- **Transparence :** L'utilisateur peut inspecter le calcul dans le navigateur
- **Reproductibilite :** Le proof record scelle cote serveur contient tous les parametres

**Formule universelle :**
```
S_domaine = max(0, 100 * (1 - Sigma(Wk) / Wmax)) * (0.5 + 0.5 * Fc)
```

**Parametres :**
- `Wk` : Poids de severite (critique=4, haute=3, moyenne=2, faible=1)
- `Wmax` : max(Sigma(Wk), 4 * Npoints) — normalisation
- `Fc` : min(1, nbDocuments / 3) — couverture documentaire
- `S_global` : moyenne ponderee par Nk/Somme_Nk (10/28, 10/28, 8/28)

---

## 4. Architecture de securite

### 4.1 Authentification

- **Methode :** JWT (HMAC-SHA256)
- **Stockage mot de passe :** PBKDF2-HMAC-SHA256, 150 000 iterations, sel 16 octets
- **Duree token :** 24h (configurable)
- **Transport :** Cookie `nc_token` + header `Authorization: Bearer`

### 4.2 Chiffrement

- **Algorithme :** AES-256-GCM (AEAD)
- **Derivation cle :** PBKDF2-HMAC-SHA256, sel 32 octets
- **IV :** 12 octets (96 bits, recommandation NIST)
- **Format fichier :** MAGIC (8o) | SEL (32o) | IV (12o) | CIPHERTEXT

### 4.3 Chaine de preuve (NF Z42-013)

- **Structure :** JSON Lines, append-only, verrouillage fcntl
- **Chainage :** hash_N = SHA-256(seq + timestamp + type + payload + hash_N-1)
- **Verification :** Methode `verify()` parcourt toute la chaine
- **Types d'evenements :** score_triple_scelle, validation_humaine_score, contestation_score, snapshot_constantes

### 4.4 Journalisation

- **Audit logger :** JSON Lines append-only (`audit_logger.py`)
- **Operations tracees :** import_document, analyse, generation_rapport, chiffrement, erreurs
- **Integrite :** Hash SHA-256 des fichiers importes

### 4.5 Systeme d'alertes de securite (PSSI §6.3)

Implementation : `alert_manager.py`

| Composant | Responsabilite |
|-----------|---------------|
| `AlertManager` | Detection centralisee, persistance, notification |
| `LoginTracker` | Detection brute force (fenetre glissante par IP/email) |
| `VolumeTracker` | Detection exfiltration/injection (compteurs horaires) |
| Callback `on_alert` | Hook pour notification externe (webhook, email, SIEM) |

**4 types d'alertes implementes :**
- Rupture chaine de preuve (CRITIQUE)
- Tentatives de connexion excessives (HAUTE)
- Erreurs de dechiffrement repetees (HAUTE)
- Volumes anormaux d'operations (MOYENNE)

### 4.6 Horodatage certifie RFC 3161

Implementation : `timestamp_authority.py`

- **Client RFC 3161 :** Construction de requetes TSA (ASN.1/DER), interrogation de TSA publics
- **Fallback :** Horloge systeme UTC si TSA injoignable (annote "non certifie")
- **Integration :** Chaque entree de la chaine de preuve peut recevoir un jeton TSA
- **Verification :** Hash SHA-256 + verification locale (signature TSA via `openssl ts`)
- **Conformite :** eIDAS art. 41-42, RFC 3161, RFC 5816

---

## 5. Architecture de deploiement

```
+--Internet--+     +--Nginx (443/80)--+     +--Docker--+
|  Client    | --> |  SSL/TLS         | --> | NormaCheck|
|  (Browser) |     |  Let's Encrypt   |     | :8000     |
+------------+     +------------------+     +-----+-----+
                                                  |
                   +--Certbot--+           +------+------+
                   | Renouvellement SSL    | /data/normacheck |
                   +----------+            | db/ uploads/    |
                                           | reports/ logs/  |
                   +--Backup--+            +---------+------+
                   | Quotidien 30j|                   |
                   +-----------+             +--------+------+
                                             | SQLite (OVH)  |
                                             | In-memory (Vercel)|
                                             +---------------+
```

**Infrastructure :**
- **Plateforme :** OVHcloud VPS (production) / Vercel (staging)
- **Container :** Docker multi-stage (Python 3.11-slim)
- **Reverse proxy :** Nginx Alpine
- **SSL :** Let's Encrypt via Certbot (renouvellement automatique)
- **Backup :** Quotidien, retention 30 jours
- **Health check :** Docker HEALTHCHECK + endpoint `/api/health`
- **CI/CD :** GitHub Actions -> SSH deploy OVH

---

## 6. Exigences non-fonctionnelles

| Exigence | Valeur | Reference |
|----------|--------|-----------|
| Disponibilite | 99.5% (hors maintenance planifiee) | SLA interne |
| Temps de reponse analyse | < 10s pour 5 documents | Performance interne |
| Conservation donnees fiscales | 6 ans | Art. L102 B LPF |
| Conservation donnees sociales | 5 ans | Art. L243-16 CSS |
| Conservation probante | 10 ans | NF Z42-013 |
| Taille max upload | 2 Go (configurable) | NORMACHECK_MAX_UPLOAD_MB |
| Fichiers max simultanes | 50 | NORMACHECK_MAX_FILES |
| Workers | Auto (CPU-based, max 8) | gunicorn.conf.py |

---

## 7. Matrice des dependances externes

| Dependance | Version | Usage | Criticite |
|-----------|---------|-------|-----------|
| FastAPI | >= 0.104 | Framework API | CRITIQUE |
| Pydantic | >= 2.0 | Validation donnees | CRITIQUE |
| pdfplumber | >= 0.10 | Extraction PDF | HAUTE |
| cryptography | >= 41.0 | AES-256-GCM, PBKDF2 | CRITIQUE |
| openpyxl | >= 3.1 | Lecture Excel | MOYENNE |
| lxml | >= 4.9 | Parsing XML/DSN | HAUTE |
| Jinja2 | >= 3.1 | Templates rapports | MOYENNE |
| Pillow | >= 10.0 | Traitement images OCR | MOYENNE |
| supabase | >= 2.0 | Base de donnees (optionnel) | FAIBLE |
| uvicorn | >= 0.24 | Serveur ASGI | CRITIQUE |
