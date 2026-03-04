# Specification Algorithmique du Scoring NormaCheck v4.0

**Version :** 4.0
**Date :** 2026-03-04
**Statut :** En cours de validation
**Classification :** Document auditable - Ne depend pas du code source

---

## 1. Objet

Ce document specifie de maniere independante du code source l'algorithme de scoring de NormaCheck v4.0. Il permet a un auditeur tiers de :
- Comprendre le calcul sans lire le code
- Reproduire manuellement tout score a partir des constats
- Verifier l'absence de parametres discretionnaires
- Evaluer la conformite a l'art. 22 RGPD (transparence algorithmique)

---

## 2. Principes fondateurs

| Principe | Definition | Verification |
|----------|-----------|-------------|
| **Proportionnalite** | Chaque deduction est proportionnelle a la gravite reglementaire | Wk derives des majorations legales |
| **Objectivabilite** | Tout parametre traçable a une reference legale | Aucune constante sans reference |
| **Reproductibilite** | Memes constats = meme score | Pas de composante aleatoire |
| **Non-discretionnaire** | Aucun coefficient arbitraire | Poids derives de Nk/Somme_Nk |

---

## 3. Entrees

### 3.1 Constats (Findings)

Chaque constat possede :

| Champ | Type | Description |
|-------|------|-------------|
| `categorie` | Enum | ANOMALIE, INCOHERENCE, DONNEE_MANQUANTE, DEPASSEMENT_SEUIL, PATTERN_SUSPECT |
| `severite` | Enum | CRITIQUE, HAUTE, MOYENNE, FAIBLE |
| `titre` | String | Intitule du constat |
| `reference_legale` | String | Article de loi applicable |

### 3.2 Documents

- `nbDocuments` : nombre de documents analyses (entier >= 1)

---

## 4. Algorithme de scoring

### 4.1 Etape 1 — Routage des constats par domaine

Chaque constat est affecte a un domaine reglementaire selon des regles deterministes :

**Regles de routage (par ordre de priorite) :**

1. Si `categorie` contient "apprentissage" ou "formation_pro" → **URSSAF**
2. Si `reference_legale` contient "code du travail" (et pas "cgi") → **URSSAF**
3. Si `categorie` contient "fiscal", "tva", "impot" OU `reference_legale` contient "cgi", "lpf" OU `categorie` = "taxe_sur_salaires" → **DGFIP**
4. Si `reference_legale` contient "nep", "isa", "code de commerce", "pcg" OU `categorie` contient "comptab" → **CDC**
5. Si `titre` contient "total" ET "detail" → **CDC**
6. Si `titre` contient "ecart calcul cotisation" ou "base x taux" → **CDC**
7. Si `titre` contient "s89" → **CDC**
8. Si `titre` contient "masse salariale" ET "bases individuelles" → **CDC**
9. Si `categorie` = "incoherence" :
   - Si `titre` contient "total patronal" ou "taux at" → **CDC**
   - Si `titre` contient "convention collective" ou "statut divergent" → **DGFIP**
   - Sinon → **URSSAF**
10. Si `categorie` = "donnee_manquante" ET `titre` contient "mois de declaration manquants" → **DGFIP**
11. Si `categorie` = "pattern_suspect" ET `titre` contient "benford" ou "valeur atypique" → **CDC**
12. **Defaut** → **URSSAF**

Chaque routage produit une trace : `{constat, domaine_affecte, regle_appliquee}`.

### 4.2 Etape 2 — Calcul du score par domaine

Pour chaque domaine D in {URSSAF, DGFIP, CDC} :

**Parametres fixes :**

| Severite | Poids Wk | Justification legale |
|----------|---------|---------------------|
| CRITIQUE | 4 | Manquement delibere, majoration 40% (CSS L243-7-7, CGI art. 1729) |
| HAUTE | 3 | Retard/omission significatif, majoration 10% (CSS L243-7-2, CGI art. 1728) |
| MOYENNE | 2 | Ecart formel, droit a regularisation (CSS L243-6-7, tolerance BOSS) |
| FAIBLE | 1 | Anomalie mineure, pas de sanction directe |

| Domaine | Npoints | Justification |
|---------|---------|---------------|
| URSSAF | 10 | 10 points de controle identifies dans le CSS/CT |
| DGFIP | 10 | 10 points de controle identifies dans le CGI/LPF |
| CDC | 8 | 8 points de controle identifies dans le C.com/NEP |

**Algorithme :**

```
1. Soit constats_D = les constats routes vers le domaine D
2. Pour chaque constat c dans constats_D :
     Wk(c) = poids_severite[c.severite]
3. totalW = Somme(Wk(c)) pour tout c dans constats_D
4. Wmax = max(totalW, 4 * Npoints_D)
5. Sbrut = max(0, arrondi(100 * (1 - totalW / Wmax)))
6. Fc = min(1, nbDocuments / 3)
7. score_D = max(0, min(100, arrondi(Sbrut * (0.5 + 0.5 * Fc))))
```

**Proprietes mathematiques :**
- `score_D` est toujours dans [0, 100]
- Si aucun constat : `totalW = 0`, `Sbrut = 100`, `score_D = arrondi(100 * (0.5 + 0.5 * Fc))`
- Si `nbDocuments >= 3` : `Fc = 1`, `score_D = Sbrut` (pas de penalite)
- Si `nbDocuments = 1` : `Fc = 0.33`, `score_D = arrondi(Sbrut * 0.67)` (penalite 33%)

### 4.3 Etape 3 — Grade par domaine

| Score | Grade |
|-------|-------|
| >= 90 | A |
| >= 75 | B |
| >= 60 | C |
| >= 45 | D |
| >= 30 | E |
| < 30 | F |

### 4.4 Etape 4 — Intervalle de confiance

```
marge = min(20, arrondi((1 - Fc) * 15 + nb_constats * 0.5))
score_bas = max(0, score_D - marge)
score_haut = min(100, score_D + marge)
```

### 4.5 Etape 5 — Score global

```
Nu = 10, Nf = 10, Nc = 8
Nt = Nu + Nf + Nc = 28
wu = Nu / Nt = 10/28 ≈ 0.3571
wf = Nf / Nt = 10/28 ≈ 0.3571
wc = Nc / Nt = 8/28 ≈ 0.2857

global = arrondi(score_URSSAF * wu + score_DGFIP * wf + score_CDC * wc)
```

### 4.6 Etape 6 — Penalite d'accumulation d'incoherences

```
nbIncoherences = nombre de constats avec categorie = "INCOHERENCE"

Si nbIncoherences > 5 :
    penalite = min(15, (nbIncoherences - 5) * 2)
    global = max(0, global - penalite)
```

### 4.7 Etape 7 — Grade global

Meme echelle que le grade par domaine (4.3).

---

## 5. Exemple de calcul complet

### Donnees d'entree

- 2 documents analyses (Fc = min(1, 2/3) = 0.667)
- 5 constats :

| # | Titre | Categorie | Severite | Domaine (route) |
|---|-------|-----------|----------|----------------|
| 1 | SMIC infra-legal | ANOMALIE | CRITIQUE | URSSAF |
| 2 | Taux AT incorrect | ANOMALIE | HAUTE | URSSAF |
| 3 | SIRET divergent | INCOHERENCE | HAUTE | URSSAF |
| 4 | Benford suspect | PATTERN_SUSPECT | FAIBLE | CDC |
| 5 | Mois manquant | DONNEE_MANQUANTE | MOYENNE | DGFIP |

### Calcul URSSAF
- Constats : #1 (Wk=4), #2 (Wk=3), #3 (Wk=3) → totalW = 10
- Wmax = max(10, 4*10) = 40
- Sbrut = max(0, arrondi(100 * (1 - 10/40))) = arrondi(75) = 75
- score = arrondi(75 * (0.5 + 0.5 * 0.667)) = arrondi(75 * 0.833) = arrondi(62.5) = 63
- Grade : C

### Calcul DGFIP
- Constats : #5 (Wk=2) → totalW = 2
- Wmax = max(2, 4*10) = 40
- Sbrut = arrondi(100 * (1 - 2/40)) = arrondi(95) = 95
- score = arrondi(95 * 0.833) = arrondi(79.2) = 79
- Grade : B

### Calcul CDC
- Constats : #4 (Wk=1) → totalW = 1
- Wmax = max(1, 4*8) = 32
- Sbrut = arrondi(100 * (1 - 1/32)) = arrondi(96.9) = 97
- score = arrondi(97 * 0.833) = arrondi(80.8) = 81
- Grade : B

### Score global
- global = arrondi(63 * 0.3571 + 79 * 0.3571 + 81 * 0.2857)
- global = arrondi(22.50 + 28.21 + 23.14) = arrondi(73.85) = 74
- Penalite incoherences : nbIncoherences = 1 (< 5, pas de penalite)
- **Score final : 74/100 (C)**

---

## 6. Constats structurels

Lorsque les donnees sont insuffisantes, des constats automatiques sont generes :

| Condition | Constat | Severite | Score risque |
|-----------|---------|----------|-------------|
| 1 seul document | Document unique - verification inter-documents impossible | MOYENNE | 40 |
| Pas d'employeur (siret/effectif) | Employeur non identifie - controles de seuil impossibles | MOYENNE | 50 |
| Pas d'employes mais des cotisations | Aucun employe identifie - controles individuels impossibles | MOYENNE | 45 |
| Aucune cotisation dans aucun document | Aucune cotisation dans les documents analyses | HAUTE | 60 |

---

## 7. Biais identifies et mitigations

| Biais | Description | Mitigation |
|-------|-------------|-----------|
| Fc penalise les petites structures | 1 document → score * 0.67 | Facteur continu (pas binaire), justifie par NEP 500, minimum 50% |
| Effectif=0 saute des controles | FNAL, mobilite, PEEC ignores | Constat DONNEE_MANQUANTE genere explicitement |
| Routage defaut = URSSAF | Constats non classes → URSSAF | Trace du routage, regles par titre reduisent les cas |
| Detection apprenti par mots-cles | Faux positifs possibles | Marque PATTERN_SUSPECT (non probant), Wk=1 max |

---

## 8. Statut de validation (art. 22 RGPD)

| Statut | Signification |
|--------|--------------|
| **PROVISOIRE** | Score calcule automatiquement, en attente de validation humaine |
| **VALIDE** | Valide par un operateur qualifie |
| **AJUSTE** | Modifie par un operateur avec justification |
| **REJETE** | Rejete, recalcul demande |
| **CONTESTE** | Conteste par l'entite auditee, reexamen humain en cours |

Tout changement de statut est scelle dans la chaine de preuve (SHA-256).

---

## 9. Versionnement des constantes

Les constantes reglementaires (PASS, SMIC, taux) sont versionnees :
- **Hash de reference :** SHA-256 du fichier constants.py
- **Snapshot :** Capture de toutes les valeurs a la date du calcul
- **Scellement :** Stocke dans la chaine de preuve (`snapshot_constantes`)

Toute modification des constantes produit un nouveau hash, permettant de retrouver les parametres applicables a une date donnee.
