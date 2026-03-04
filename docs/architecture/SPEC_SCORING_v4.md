# Specification Algorithmique du Scoring NormaCheck v4.0

**Version :** 4.1
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
- Contester ou valider chaque parametre par reference legale

**Avertissement :** Le score NormaCheck est un indicateur methodologique interne. Il ne constitue pas une certification officielle et n'est pas opposable aux administrations. Il ne produit aucun effet juridique par lui-meme.

---

## 2. Principes fondateurs

| Principe | Definition | Verification |
|----------|-----------|-------------|
| **Ordinalite proportionnelle** | Les poids Wk refletent un classement ordinal de gravite, calibre sur les echelons de sanctions legales (cf. 4.2.1) | Pas de pretention de proportionnalite arithmetique |
| **Objectivabilite** | Tout parametre traçable a une reference legale ou normative | Aucune constante sans reference |
| **Reproductibilite** | Memes constats = meme score | Pas de composante aleatoire, arrondi specifie |
| **Non-discretionnaire** | Aucun coefficient arbitraire | Poids derives de Nk/Somme_Nk |
| **Favorabilite** | En cas d'ambiguite aux frontieres, le calcul ne defavorise pas l'entite auditee | Arrondi half-up (Math.round), pas de troncature |

---

## 3. Entrees

### 3.1 Constats (Findings)

Chaque constat possede :

| Champ | Type | Description | Obligatoire |
|-------|------|-------------|-------------|
| `categorie` | Enum | ANOMALIE, INCOHERENCE, DONNEE_MANQUANTE, DEPASSEMENT_SEUIL, PATTERN_SUSPECT | Oui |
| `severite` | Enum | CRITIQUE, HAUTE, MOYENNE, FAIBLE | Oui |
| `titre` | String | Intitule du constat | Oui |
| `reference_legale` | String | Article de loi applicable | Oui |
| `score_risque` | Integer 0-100 | Indicateur informatif de risque (NON utilise dans le calcul du score, cf. 4.8) | Non |

### 3.2 Documents

- `nbDocuments` : nombre de documents analyses (entier >= 1)

### 3.3 Deduplication des constats

**Regle :** Si deux analyseurs detectent le meme probleme (meme titre, meme categorie, meme severite), le constat n'est compte qu'une seule fois dans le calcul du score. L'identifiant de deduplication est le triplet `(titre_normalise, categorie, severite)`.

**Justification :** Eviter le double comptage qui penaliserait artificiellement l'entite auditee. Un meme ecart ne peut etre sanctionne qu'une fois (principe non bis in idem).

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

**Biais du routage par defaut :** Le routage par defaut vers URSSAF est documente comme biais connu (cf. section 7). Le nombre de constats routes par defaut est trace dans le proof record pour audit. Si ce nombre depasse 20% des constats totaux, un avertissement est genere.

### 4.2 Etape 2 — Calcul du score par domaine

Pour chaque domaine D in {URSSAF, DGFIP, CDC} :

#### 4.2.1 Poids de severite (Wk) — Echelle ordinale

| Severite | Poids Wk | Echelon legal de reference | Nature de l'echelle |
|----------|---------|---------------------------|---------------------|
| CRITIQUE | 4 | Manquement delibere : majoration 40% (CSS L243-7-7, CGI art. 1729) | Ordinal rang 4 |
| HAUTE | 3 | Retard/omission significatif : majoration 10% (CSS L243-7-2, CGI art. 1728) | Ordinal rang 3 |
| MOYENNE | 2 | Ecart formel : droit a regularisation (CSS L243-6-7, tolerance BOSS) | Ordinal rang 2 |
| FAIBLE | 1 | Anomalie mineure : pas de sanction directe | Ordinal rang 1 |

**Precision sur la nature de l'echelle :** Les poids Wk constituent une echelle **ordinale** (classement par rang de gravite), et non une echelle proportionnelle aux montants de majorations. Le choix d'une echelle lineaire (1, 2, 3, 4) plutot que proportionnelle aux taux de majoration (1%, 10%, 40%) est delibere :
- Une echelle proportionnelle aux taux (ex: 1, 10, 40) ecraserait les constats faibles et moyens, rendant le score insensible a leur accumulation.
- L'echelle ordinale lineaire reflete le **rang de gravite** dans la hierarchie des sanctions, pas leur montant.
- Ce choix est conforme a la pratique des systemes de notation de conformite (ISO 19011:2018, clause 6.4.9).

#### 4.2.2 Points de controle par domaine (Npoints)

| Domaine | Npoints | Justification | Inventaire |
|---------|---------|---------------|-----------|
| URSSAF | 10 | 10 points de controle identifies dans le CSS/CT | Cf. endpoint /api/scores/methodologie |
| DGFIP | 10 | 10 points de controle identifies dans le CGI/LPF | Cf. endpoint /api/scores/methodologie |
| CDC | 8 | 8 points de controle identifies dans le C.com/NEP | Cf. endpoint /api/scores/methodologie |

L'inventaire exhaustif de chaque point de controle avec sa reference legale est disponible dans l'endpoint `/api/scores/methodologie` (sections `perimetres_controle`). En cas d'ajout ou de retrait d'un point de controle, Npoints est modifie et les poids inter-domaines s'ajustent automatiquement.

#### 4.2.3 Algorithme de calcul

```
1. Soit constats_D = les constats routes vers le domaine D (apres deduplication)
2. Pour chaque constat c dans constats_D :
     Wk(c) = poids_severite[c.severite]
3. totalW = Somme(Wk(c)) pour tout c dans constats_D
4. Wmax = max(totalW, 4 * Npoints_D)
5. Sbrut = max(0, arrondi(100 * (1 - totalW / Wmax)))
6. Fc = min(1, nbDocuments / 3)
7. score_D = max(0, min(100, arrondi(Sbrut * (0.5 + 0.5 * Fc))))
```

**Methode d'arrondi :** `arrondi()` designe l'arrondi arithmetique standard (half-up) : `Math.round(x)` en JavaScript, soit `floor(x + 0.5)` pour x >= 0. Cette methode est favorable a l'entite auditee aux frontieres de grade (ex: 89.5 → 90 = grade A).

**Proprietes mathematiques :**
- `score_D` est toujours dans [0, 100] (entier)
- Si aucun constat : `totalW = 0`, `Sbrut = 100`, `score_D = arrondi(100 * (0.5 + 0.5 * Fc))`
- Si `nbDocuments >= 3` : `Fc = 1`, `score_D = Sbrut` (pas de penalite)
- Si `nbDocuments = 1` : `Fc = 0.33`, `score_D = arrondi(Sbrut * 0.67)` (penalite 33%)

#### 4.2.4 Justification du facteur de couverture Fc

Le seuil de 3 documents pour Fc = 1 est derive de la norme **NEP 500 — Elements probants**, qui pose le principe de corroboration multi-sources :

1. **Document declaratif** (DSN, bordereau URSSAF) — source primaire
2. **Document justificatif** (bulletin de paie, journal de paie) — source de recoupement
3. **Document de synthese ou externe** (bilan social, attestation, bordereau recapitulatif) — source de verification

Avec moins de 3 sources, la fiabilite de l'analyse est reduite car les controles inter-documents sont limites. Le facteur Fc est **continu** (non binaire) pour eviter un effet de seuil brutal. Le score minimum avec 0 documents serait `Sbrut * 0.5` (50% du score brut), jamais zero.

### 4.3 Etape 3 — Grade par domaine

| Score | Grade | Signification |
|-------|-------|--------------|
| >= 90 | A | Conformite elevee |
| >= 75 | B | Conformite satisfaisante, ecarts mineurs |
| >= 60 | C | Conformite partielle, ecarts a corriger |
| >= 45 | D | Non-conformite significative |
| >= 30 | E | Non-conformite majeure |
| < 30 | F | Non-conformite critique |

**Justification des seuils :** L'echelle A-F est une echelle conventionnelle d'evaluation, utilisee dans les referentiels de notation de conformite (ISO 19011:2018, systemes de notation des organismes de controle). Les seuils ne sont pas derives de textes legaux specifiques. **Le grade est informatif et ne produit aucun effet juridique.**

### 4.4 Etape 4 — Intervalle de confiance

```
marge = min(20, arrondi((1 - Fc) * 15 + nb_constats * 0.5))
score_bas = max(0, score_D - marge)
score_haut = min(100, score_D + marge)
```

**Statut de l'intervalle :** L'intervalle de confiance est **informatif**. Il n'est pas utilise pour determiner le grade. Il indique l'incertitude liee a la couverture documentaire et au nombre de constats. Un intervalle large (ex: 75 +/- 20) signale que le grade pourrait varier avec des documents supplementaires.

**Avertissement obligatoire :** Si la marge depasse 10 points, le rapport doit mentionner : "Le score est calcule avec une incertitude significative due a la couverture documentaire limitee. Le grade pourrait varier d'un cran avec des documents supplementaires."

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

**Justification du seuil de 5 :** Ce seuil reflete qu'un faible nombre d'incoherences inter-documents (≤ 5) peut resulter d'ecarts formels isoles. Au-dela, l'accumulation suggere un probleme systemique de fiabilite des declarations.

**Precision :** La penalite s'applique uniquement au score global, pas aux scores par domaine. Les grades par domaine refletent la conformite individuelle ; la penalite globale reflete le risque systemique transversal. Cette distinction est deliberee.

### 4.7 Etape 7 — Grade global

Meme echelle que le grade par domaine (4.3). Le grade global est determine **apres** application de la penalite d'incoherence.

### 4.8 Champ score_risque des constats

Le champ `score_risque` (0-100) attache a chaque constat est un indicateur informatif de criticite **qui n'entre pas dans le calcul du score**. Seule la `severite` (CRITIQUE/HAUTE/MOYENNE/FAIBLE) determine le poids Wk du constat dans le score.

**Justification :** Le `score_risque` est utilise pour le tri visuel des constats dans les rapports (du plus critique au moins critique). Il n'a pas de base legale specifique et ne doit pas influencer le calcul du score pour respecter le principe d'objectivabilite.

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

| Condition | Constat | Severite | Score risque | Reference legale |
|-----------|---------|----------|-------------|-----------------|
| 1 seul document | Document unique - verification inter-documents impossible | MOYENNE | 40 | NEP 500 - Elements probants |
| Pas d'employeur (siret/effectif) | Employeur non identifie - controles de seuil impossibles | MOYENNE | 50 | Art. R243-14 CSS |
| Pas d'employes mais des cotisations | Aucun employe identifie - controles individuels impossibles | MOYENNE | 45 | Art. L133-5-3 CSS |
| Aucune cotisation dans aucun document | Aucune cotisation dans les documents analyses | HAUTE | 60 | Art. L241-1 CSS |

**Principe :** Les constats structurels identifient les cas ou le score pourrait etre artificiellement eleve faute de controles possibles. Ils informent l'entite auditee et l'operateur que le score est calcule sur une base incomplete.

---

## 7. Biais identifies et mitigations

| # | Biais | Description | Mitigation | Gravite residuelle |
|---|-------|-------------|-----------|-------------------|
| 1 | Fc penalise les petites structures | 1 document → score * 0.67 | Facteur continu (pas binaire), justifie par NEP 500, minimum 50% | FAIBLE — attenuation par Fc continu |
| 2 | Effectif=0 saute des controles | FNAL, mobilite, PEEC ignores | Constat DONNEE_MANQUANTE genere explicitement | FAIBLE — transparence |
| 3 | Routage defaut = URSSAF | Constats non classes → URSSAF | Trace du routage, comptage des defauts dans le proof record | MOYENNE — biais systematique documente |
| 4 | Detection apprenti par mots-cles | Faux positifs possibles | Marque PATTERN_SUSPECT (non probant), Wk=1 max | FAIBLE — poids minimal |
| 5 | Echelle Wk ordinale non proportionnelle | Wk=4/3 ne reflete pas le ratio 40%/10% | Echelle ordinale explicitement documentee (cf. 4.2.1) | FAIBLE — transparence |
| 6 | Seuils de grades conventionnels | A≥90, B≥75, etc. sans base legale | Grades informatifs, non opposables, documentes (cf. 4.3) | FAIBLE — pas d'effet juridique |
| 7 | Intervalle de confiance non utilise pour le grade | Le grade est un point estimate | Avertissement obligatoire si marge > 10 (cf. 4.4) | MOYENNE — information du lecteur |
| 8 | Penalite incoherence au global uniquement | Grades par domaine non impactes | Distinction deliberee : conformite locale vs risque systemique (cf. 4.6) | FAIBLE — choix methodologique documente |

---

## 8. Statut de validation (art. 22 RGPD)

| Statut | Signification | Delai maximal |
|--------|--------------|--------------|
| **PROVISOIRE** | Score calcule automatiquement, en attente de validation humaine | 30 jours calendaires |
| **VALIDE** | Valide par un operateur qualifie | — |
| **AJUSTE** | Modifie par un operateur avec justification tracee | — |
| **REJETE** | Rejete, recalcul demande | — |
| **CONTESTE** | Conteste par l'entite auditee, reexamen humain en cours | 30 jours pour reexamen |

**Delai de validation :** Un score PROVISOIRE qui n'est pas valide dans les 30 jours calendaires doit etre requalifie en EXPIRE. Il ne peut plus etre utilise a des fins decisionnelles sans revalidation.

**Procedure contradictoire :** Conformement a l'art. L121-1 CRPA et R*243-59 CSS, l'entite auditee dispose de 30 jours pour formuler ses observations sur les constats provisoires. Les constats contestes sont reexamines par un operateur humain. La contestation et sa resolution sont scellees dans la chaine de preuve.

Tout changement de statut est scelle dans la chaine de preuve (SHA-256).

---

## 9. Horodatage et tracabilite

### 9.1 Source d'horodatage

L'horodatage des evenements de la chaine de preuve utilise l'horloge systeme UTC (`datetime.now(timezone.utc)` au format ISO 8601).

**Limitation connue :** L'horodatage est auto-genere et n'est pas certifie par une autorite de confiance (TSA) au sens du RFC 3161. En consequence :
- L'horodatage fait foi entre les parties utilisatrices du systeme
- Il n'a pas de valeur probante erga omnes (opposable aux tiers)
- Pour une valeur probante maximale, l'integration d'un service TSA qualifie eIDAS est recommandee

### 9.2 Chaine de preuve

Chaque evenement est scelle par un hash SHA-256 chaine :
`hash_N = SHA-256(json(seq + timestamp + type + payload + hash_N-1))`

La chaine garantit :
- **Immutabilite** : toute modification retroactive est detectable
- **Ordonnancement** : les evenements sont sequences
- **Completude** : toute suppression d'entree rompt la chaine

---

## 10. Versionnement des constantes

Les constantes reglementaires (PASS, SMIC, taux) sont versionnees :
- **Hash de reference :** SHA-256 du fichier constants.py
- **Snapshot :** Capture de toutes les valeurs a la date du calcul
- **Scellement :** Stocke dans la chaine de preuve (`snapshot_constantes`)

**Annee de reference :** Les constantes sont millésimées (ex: TAUX_COTISATIONS_2026). L'analyse d'une declaration de l'annee N doit utiliser les constantes de l'annee N. En cas de discordance (declaration 2025 analysee avec constantes 2026), un avertissement est genere dans le rapport.

Toute modification des constantes produit un nouveau hash, permettant de retrouver les parametres applicables a une date donnee.

---

## 11. Limites et avertissements juridiques

1. **Non-opposabilite :** Le score NormaCheck n'est pas opposable aux administrations (URSSAF, DGFIP, Cour des comptes). Il constitue un outil d'aide a la decision interne.

2. **Pattern suspect :** Les constats de type PATTERN_SUSPECT (Benford, nombres ronds, valeurs atypiques) sont des indicateurs statistiques non probants au sens de l'art. L243-7 CSS. Ils ne peuvent a eux seuls fonder un constat d'irregularite.

3. **Scoring client-side :** Le calcul du score s'execute dans le navigateur client (JavaScript). Le proof record scelle cote serveur contient tous les parametres necessaires a la reconstitution independante du score. En cas de contestation, le score est recalculable a partir du proof record.

4. **Deduplication :** Le systeme ne garantit pas actuellement la deduplication parfaite des constats identiques detectes par plusieurs analyseurs. Ce point est identifie comme amelioration a implémenter (cf. section 3.3).
