# Politique de Securite du Systeme d'Information (PSSI)
# NormaCheck v4.0

**Version :** 1.0
**Date :** 2026-03-04
**Statut :** En vigueur
**Classification :** Interne - Confidentiel
**Responsable :** Responsable Securite du Systeme d'Information (RSSI)
**Reference :** ISO/IEC 27001:2022 clause A.5.1

---

## 1. Objet et perimetre

### 1.1 Objet

La presente Politique de Securite du Systeme d'Information (PSSI) definit les principes, regles et mesures de securite applicables au systeme NormaCheck. Elle est conforme aux exigences de :

- **ISO/IEC 27001:2022** — Management de la securite de l'information
- **ISO/IEC 27701:2019** — Management de la vie privee (RGPD)
- **RGPD (UE 2016/679)** — Protection des donnees personnelles
- **NF Z42-013 (AFNOR)** — Archivage electronique a valeur probante
- **Art. L102 B LPF** — Conservation fiscale (6 ans)
- **Art. L243-16 CSS** — Conservation sociale (5 ans)

### 1.2 Perimetre

Le perimetre couvre l'ensemble du systeme NormaCheck :

| Composant | Description | Criticite |
|-----------|-------------|-----------|
| Moteur d'analyse | Parsers, analyseurs, scoring | CRITIQUE |
| API REST (FastAPI) | 128 endpoints, authentification | CRITIQUE |
| Chaine de preuve | SHA-256, chaine append-only | CRITIQUE |
| Chiffrement | AES-256-GCM des documents | CRITIQUE |
| Base de donnees | SQLite (OVH) / In-memory (Vercel) | HAUTE |
| Interface web | SPA, export PDF | MOYENNE |
| Infrastructure | Docker, Nginx, SSL/TLS | HAUTE |

### 1.3 Parties prenantes

| Role | Responsabilites |
|------|----------------|
| RSSI | Pilotage de la PSSI, gestion des incidents |
| Developpeurs | Application des regles de developpement securise |
| Operateurs | Validation humaine des scores (art. 22 RGPD) |
| Auditeurs | Verification de conformite |
| DPO | Conformite RGPD, registre des traitements |

---

## 2. Classification des donnees

### 2.1 Niveaux de classification

| Niveau | Definition | Exemples NormaCheck |
|--------|-----------|-------------------|
| **C4 - SECRET** | Donnees dont la divulgation causerait un prejudice grave | Cles de chiffrement, mots de passe (hashes PBKDF2) |
| **C3 - CONFIDENTIEL** | Donnees personnelles sensibles | NIR (numero de securite sociale), bulletins de paie, DSN |
| **C2 - INTERNE** | Donnees a usage interne | Rapports d'analyse, scores, constats |
| **C1 - PUBLIC** | Donnees publiables | Documentation technique, mentions legales, CGU |

### 2.2 Mesures par niveau

| Mesure | C4 - SECRET | C3 - CONFIDENTIEL | C2 - INTERNE | C1 - PUBLIC |
|--------|------------|-------------------|-------------|------------|
| Chiffrement au repos | AES-256-GCM obligatoire | AES-256-GCM obligatoire | Recommande | Non requis |
| Chiffrement en transit | TLS 1.3 obligatoire | TLS 1.2+ obligatoire | TLS 1.2+ | HTTPS |
| Controle d'acces | Nominatif + MFA | Nominatif | Par role | Aucun |
| Journalisation | Chaque acces | Chaque acces | Operations | Non requis |
| Duree conservation | Minimale | Legale (5-6 ans) | 2 ans | Illimitee |
| Sauvegarde | Chiffree + hors-site | Chiffree | Standard | Non requis |
| Suppression | Ecrasement securise (3 passes) | Ecrasement securise | Suppression standard | N/A |

### 2.3 Donnees traitees par NormaCheck

| Donnee | Classification | Base legale | Conservation |
|--------|---------------|------------|-------------|
| NIR (numero SS) | C3 - CONFIDENTIEL | Art. L243-16 CSS | 5 ans |
| Identite employes | C3 - CONFIDENTIEL | RGPD art. 6(1)(c) | 5 ans |
| Bulletins de paie | C3 - CONFIDENTIEL | Art. L3243-4 CT | 5 ans |
| DSN (declarations sociales) | C3 - CONFIDENTIEL | Art. L133-5-3 CSS | 5 ans |
| Bordereaux URSSAF | C3 - CONFIDENTIEL | Art. L243-16 CSS | 5 ans |
| SIRET, effectifs | C2 - INTERNE | Art. L123-1 C.com | 6 ans |
| Scores, constats | C2 - INTERNE | Interet legitime | 10 ans (NF Z42-013) |
| Chaine de preuve | C2 - INTERNE | NF Z42-013 | 10 ans |
| Cles de chiffrement | C4 - SECRET | ISO 27001 A.10 | Rotation annuelle |

---

## 3. Gestion des acces

### 3.1 Principes

- **Moindre privilege** : chaque utilisateur n'accede qu'aux fonctions necessaires a son role
- **Separation des taches** : le meme operateur ne peut pas generer et valider un score
- **Traçabilite** : tout acces est journalise (audit_logger.py)

### 3.2 Authentification

| Parametre | Valeur | Reference |
|-----------|--------|-----------|
| Methode | JWT (HMAC-SHA256) | RFC 7519 |
| Stockage mots de passe | PBKDF2-HMAC-SHA256 | NIST SP 800-132 |
| Iterations PBKDF2 | 150 000 | OWASP 2024 |
| Longueur sel | 16 octets (128 bits) | NIST SP 800-132 |
| Duree token JWT | 24 heures | Configurable |
| Complexite mot de passe | Min. 12 caracteres, mixte | NIST SP 800-63B |
| Verrouillage compte | 5 tentatives echouees → 15 min | OWASP |

### 3.3 Roles et permissions

| Role | Analyse | Scores | Validation | Administration | Preuve |
|------|---------|--------|-----------|---------------|--------|
| Lecteur | Lecture | Lecture | — | — | Lecture |
| Operateur | Lecture/Ecriture | Lecture | Validation | — | Lecture |
| Auditeur | Lecture | Lecture | Lecture | — | Verification |
| Administrateur | Toutes | Toutes | Toutes | Toutes | Toutes |

---

## 4. Chiffrement

### 4.1 Chiffrement au repos

| Parametre | Valeur | Reference |
|-----------|--------|-----------|
| Algorithme | AES-256-GCM (AEAD) | NIST SP 800-38D |
| Derivation cle | PBKDF2-HMAC-SHA256 | NIST SP 800-132 |
| Iterations | 100 000 | OWASP 2024 |
| Taille sel | 32 octets (256 bits) | NIST SP 800-132 |
| Taille IV | 12 octets (96 bits) | NIST SP 800-38D |
| Format fichier | MAGIC(8) + SEL(32) + IV(12) + CIPHERTEXT | encryption.py |
| Implementation | Module `cryptography` (OpenSSL) | FIPS 140-2 |

### 4.2 Chiffrement en transit

| Parametre | Valeur | Reference |
|-----------|--------|-----------|
| Protocole | TLS 1.2 minimum, TLS 1.3 recommande | ANSSI RGS |
| Certificat | Let's Encrypt (DV) | ACME RFC 8555 |
| Renouvellement | Automatique (Certbot) | Tous les 90 jours |
| HSTS | Strict-Transport-Security active | RFC 6797 |
| Cipher suites | AES-256-GCM, CHACHA20-POLY1305 | Mozilla Modern |

### 4.3 Gestion des cles

- Les cles de chiffrement ne sont jamais stockees en clair
- Derivation a partir d'un mot de passe (jamais de cle statique en code)
- Pas de cle en dur dans le code source (`NORMACHECK_SECRET_KEY` en variable d'environnement)
- Rotation des cles : annuelle ou apres incident

---

## 5. Chaine de preuve et integrite

### 5.1 Architecture de la chaine de preuve

Conforme NF Z42-013 — implementation dans `proof_chain.py` :

| Propriete | Implementation | Verification |
|-----------|---------------|-------------|
| Immutabilite | Fichier append-only avec verrouillage fcntl | `verify()` parcourt la chaine |
| Chainage | hash_N = SHA-256(seq + timestamp + type + payload + hash_N-1) | Rupture de chaine detectable |
| Horodatage | UTC ISO 8601 avec fuseau horaire | Chaque entree horodatee |
| Integrite | Hash SHA-256 de chaque entree | Recalcul et comparaison |
| Non-repudiation | session_id + operateur identifies | Tracabilite complete |

### 5.2 Evenements scelles

| Type d'evenement | Declencheur | Donnees scelleees |
|-----------------|------------|-------------------|
| `score_triple_scelle` | Calcul de score | Tous les parametres de calcul (ScoreProofRecord) |
| `validation_humaine_score` | Validation operateur | Operateur, decision, justification |
| `contestation_score` | Contestation art. 22 | Demandeur, motif, scores contestes |
| `snapshot_constantes` | Modification des taux | Toutes les constantes reglementaires |

### 5.3 Verification d'integrite

- **Automatique** : a chaque demarrage de l'application (healthcheck)
- **Manuelle** : endpoint `GET /api/preuve/verifier/{session_id}`
- **Audit** : methode `ProofChain.verify()` — parcours integral de la chaine

---

## 6. Journalisation et surveillance

### 6.1 Journal d'audit

Implementation : `audit_logger.py` (JSON Lines append-only)

| Operation tracee | Donnees enregistrees |
|-----------------|---------------------|
| `import_document` | session_id, fichier, hash SHA-256 |
| `analyse` | session_id, analyseur, nb_findings |
| `generation_rapport` | session_id, format, chemin |
| `chiffrement_*` | session_id, fichier, operation |
| `erreur` | session_id, operation, message d'erreur |

### 6.2 Conservation des journaux

| Type de journal | Conservation | Base legale |
|----------------|-------------|------------|
| Journal d'audit | 10 ans | NF Z42-013 |
| Chaine de preuve | 10 ans | NF Z42-013 |
| Logs applicatifs | 1 an | ISO 27001 A.12.4 |
| Logs d'acces | 1 an | LCEN art. 6-II |

### 6.3 Alertes (a mettre en oeuvre)

| Alerte | Condition | Severite |
|--------|----------|---------|
| Rupture chaine de preuve | `verify()` retourne `valid: false` | CRITIQUE |
| Tentatives d'acces echouees | > 5 en 15 minutes par IP | HAUTE |
| Erreur de dechiffrement | Echec AES-GCM (tag invalide) | HAUTE |
| Volume anormal | > 100 analyses / heure | MOYENNE |

---

## 7. Developpement securise

### 7.1 Principes

- **Security by design** : les mesures de securite sont integrees des la conception
- **Privacy by design** : protection des donnees personnelles des la conception (RGPD art. 25)
- **Defense en profondeur** : plusieurs couches de protection

### 7.2 Regles de developpement

| Regle | Implementation | Verification |
|-------|---------------|-------------|
| Pas de secret en dur | Variables d'environnement | Revue de code + ruff (S105/S106) |
| Validation des entrees | Pydantic v2 (schemas stricts) | Tests unitaires |
| Encodage des sorties | Jinja2 autoescaping | Tests d'injection |
| Requetes parametrees | ORM / parametres lies | Analyse statique |
| Gestion des erreurs | Exceptions typees, pas de stacktrace en production | Configuration gunicorn |
| Dependances | Versions epinglees, audit regulier | `pip audit` |

### 7.3 Outillage qualite

| Outil | Usage | Configuration |
|-------|-------|--------------|
| ruff | Linter + formatter Python | pyproject.toml (select E/W/F/I/N/S/B/UP) |
| mypy | Type checking | pyproject.toml (strict, py311) |
| pytest | Tests unitaires et integration | pyproject.toml (markers, coverage) |
| bandit (via ruff S) | Analyse de securite statique | Regles flake8-bandit |
| coverage | Couverture de code | Seuil minimum 40% → objectif 80% |

### 7.4 Processus de deploiement

```
Developpeur → Branche feature → PR avec review
    → CI/CD (tests + lint + security scan)
    → Merge main → Deploiement staging
    → Validation → Deploiement production (OVH via SSH)
```

---

## 8. Infrastructure et deploiement

### 8.1 Architecture de deploiement

| Composant | Technologie | Securite |
|-----------|------------|---------|
| Application | Docker (Python 3.11-slim multi-stage) | Image minimale, utilisateur non-root |
| Reverse proxy | Nginx Alpine | TLS termination, headers securite |
| SSL/TLS | Let's Encrypt via Certbot | Renouvellement auto 90 jours |
| Base de donnees | SQLite (OVH) | Fichier local, pas d'exposition reseau |
| Hebergement | OVHcloud VPS (production) | Datacenter France (souverainete) |
| Staging | Vercel (in-memory) | Donnees non persistantes |

### 8.2 Durcissement

| Mesure | Implementation |
|--------|---------------|
| Pare-feu | iptables / UFW : ports 80, 443 uniquement |
| SSH | Cles uniquement, port non-standard, fail2ban |
| Docker | Read-only filesystem, no-new-privileges, seccomp |
| Nginx | Headers securite (X-Frame-Options, CSP, X-Content-Type-Options) |
| CORS | Origines autorisees explicites |
| Rate limiting | Configurable par endpoint |

### 8.3 Sauvegardes

| Parametre | Valeur |
|-----------|--------|
| Frequence | Quotidienne |
| Retention | 30 jours |
| Chiffrement | AES-256 (backup chiffre) |
| Localisation | Hors-site (serveur de backup separe) |
| Test de restauration | Trimestriel (a documenter) |

---

## 9. Gestion des incidents

### 9.1 Classification

| Niveau | Definition | Delai de reaction | Exemples |
|--------|-----------|------------------|----------|
| P1 - CRITIQUE | Compromission active, fuite de donnees | < 1 heure | Intrusion, rupture chaine preuve |
| P2 - MAJEUR | Vulnerabilite exploitable, indisponibilite | < 4 heures | Faille auth, base corrompue |
| P3 - MINEUR | Anomalie sans impact immediat | < 24 heures | Tentatives echouees, erreur config |
| P4 - INFO | Evenement a suivre | < 72 heures | Alerte volume, mise a jour disponible |

### 9.2 Procedure de reponse

1. **Detection** — Journaux, alertes, signalement utilisateur
2. **Qualification** — Classification du niveau de severite
3. **Confinement** — Isolation du composant affecte
4. **Investigation** — Analyse de la cause racine
5. **Remediation** — Correction de la vulnerabilite
6. **Communication** — Notification aux parties concernees (CNIL sous 72h si donnees personnelles - RGPD art. 33)
7. **Retour d'experience** — Documentation et amelioration des mesures

### 9.3 Contacts

| Role | Responsabilite |
|------|---------------|
| RSSI | Pilotage de l'incident |
| DPO | Notification CNIL si necessaire |
| Equipe technique | Confinement et remediation |
| Direction | Decisions strategiques (P1/P2) |

---

## 10. Continuite d'activite

### 10.1 Objectifs

| Metrique | Valeur | Justification |
|----------|--------|--------------|
| RTO (Recovery Time Objective) | < 4 heures | Restauration depuis backup + redeploiement Docker |
| RPO (Recovery Point Objective) | < 24 heures | Backup quotidien |
| Disponibilite | 99.5% | SLA interne (hors maintenance planifiee) |

### 10.2 Procedures de reprise

| Scenario | Procedure | RTO estime |
|----------|----------|-----------|
| Panne serveur | Redeploiement Docker sur VPS de secours | 2 heures |
| Corruption base | Restauration depuis dernier backup | 1 heure |
| Compromission | Isolation, restauration image propre, rotation cles | 4 heures |
| Perte datacenter | Deploiement sur infrastructure de secours | 8 heures |

---

## 11. Conformite RGPD

### 11.1 Principes appliques

| Principe RGPD | Implementation NormaCheck |
|--------------|--------------------------|
| Licéité (art. 6) | Base legale : obligation legale (CSS, CGI) + interet legitime |
| Minimisation (art. 5(1)(c)) | Seules les donnees necessaires a l'analyse sont traitees |
| Exactitude (art. 5(1)(d)) | Verification inter-documents (consistency_checker) |
| Limitation conservation (art. 5(1)(e)) | Durees legales appliquees (5-6 ans selon domaine) |
| Integrite/Confidentialite (art. 5(1)(f)) | Chiffrement AES-256, chaine de preuve SHA-256 |
| Transparence (art. 13-14) | Methodologie documentee, mentions legales, CGU |

### 11.2 Droits des personnes (art. 15-22)

| Droit | Implementation | Endpoint |
|-------|---------------|---------|
| Acces (art. 15) | Export des donnees traitees | `GET /api/rgpd/export` |
| Rectification (art. 16) | Correction des constats | `POST /api/scores/contestation` |
| Effacement (art. 17) | Suppression securisee | `DELETE /api/rgpd/suppression` |
| Opposition (art. 21) | Arret du traitement | Via contestation |
| Decision automatisee (art. 22) | Score provisoire + validation humaine obligatoire | `POST /api/scores/validation-humaine` |

### 11.3 AIPD (Analyse d'Impact)

Une AIPD est recommandee si NormaCheck est utilise pour des decisions affectant significativement les personnes (RGPD art. 35). L'AIPD doit couvrir :

- Description du traitement et finalites
- Evaluation de la necessite et de la proportionnalite
- Risques pour les droits et libertes
- Mesures d'attenuation (chiffrement, pseudonymisation, validation humaine)

---

## 12. Versionnement et revisions

### 12.1 Historique

| Version | Date | Modification | Auteur |
|---------|------|-------------|--------|
| 1.0 | 2026-03-04 | Creation initiale | RSSI |

### 12.2 Revisions planifiees

- **Annuelle** : revue complete de la PSSI
- **Evenementielle** : apres tout incident P1/P2, changement reglementaire, ou audit
- **Trimestrielle** : verification de l'application des mesures

### 12.3 Approbation

La PSSI est approuvee par :
- Le Responsable de la Securite du Systeme d'Information (RSSI)
- La Direction Generale
- Le Delegue a la Protection des Donnees (DPO)

---

## Annexe A — Matrice des mesures ISO 27001 Annexe A

| Clause | Mesure | Statut |
|--------|--------|--------|
| A.5.1 | Politique de securite | CONFORME (ce document) |
| A.5.2 | Revue de la politique | PLANIFIE (revue annuelle) |
| A.8.1 | Inventaire des actifs | CONFORME (section 1.2) |
| A.8.2 | Classification des informations | CONFORME (section 2) |
| A.9.1 | Controle d'acces | CONFORME (section 3) |
| A.10.1 | Chiffrement | CONFORME (section 4) |
| A.12.4 | Journalisation | PARTIEL (section 6, alertes a implementer) |
| A.14.2 | Developpement securise | CONFORME (section 7) |
| A.16.1 | Gestion des incidents | CONFORME (section 9) |
| A.17.1 | Continuite d'activite | PARTIEL (section 10, tests a documenter) |
| A.18.1 | Conformite legale | CONFORME (sections 2.3, 11) |
