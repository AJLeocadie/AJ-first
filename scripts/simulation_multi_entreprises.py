#!/usr/bin/env python3
"""
Simulation multi-entreprises NormaCheck
========================================
Simule 5 entreprises variées (secteurs, effectifs, anomalies) et teste
le parcours complet d'un gérant : inscription, upload, analyse, export.

Entreprises simulées :
1. BTP Construction Pro SARL  — BTP, 45 salariés, taux AT/MP élevé
2. TechStart SAS              — Tech, 8 salariés cadres, erreurs de taux
3. Restaurant Le Gourmet      — HCR, 12 salariés, salaires sous le SMIC
4. Cabinet Santé Plus         — Médical, 5 salariés, régime spécial
5. Transport Express SARL     — Transport, 30 salariés, heures sup
"""

import csv
import io
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import requests

BASE_URL = os.environ.get("NORMACHECK_URL", "http://localhost:8000")
RESULTS = []

# ============================================================
# Constantes réglementaires 2026 (alignées sur urssaf_analyzer)
# ============================================================

PASS_MENSUEL = 4005.00       # Plafond mensuel sécurité sociale 2026
PASS_ANNUEL = 48060.00       # Plafond annuel
SMIC_MENSUEL = 1823.03       # SMIC mensuel brut 2026

# Taux de cotisations de référence 2026 — FORMAT DÉCIMAL
# Aligné sur urssaf_analyzer/config/constants.py
# IMPORTANT : tous les taux sont en décimal (0.13 = 13%)
# Les noms DOIVENT correspondre aux patterns du CSV parser (substring matching)
# Le parser CSV fait: if taux > 1 → divise par 100, sinon garde tel quel

# Cotisations reconnues par le CSV parser (noms compatibles avec le mapping)
TAUX_CSV = {
    # Sécurité sociale
    "maladie":                  {"patronal": 0.13,    "salarial": 0.00,    "assiette": "totalite"},
    "vieillesse plafonnee":     {"patronal": 0.0855,  "salarial": 0.069,   "assiette": "plafonnee_pass"},
    "vieillesse deplafonnee":   {"patronal": 0.0211,  "salarial": 0.004,   "assiette": "totalite"},
    "allocations familiales":   {"patronal": 0.0525,  "salarial": 0.00,    "assiette": "totalite"},
    "accident travail":         {"patronal": 0.0208,  "salarial": 0.00,    "assiette": "totalite"},
    # CSG / CRDS (parser: "csg" → CSG_DEDUCTIBLE, "crds" → CRDS)
    # Note: "csg non deductible" exclue du CSV car le parser la mappe à CSG_DEDUCTIBLE
    #        (substring "csg" matché avant "csg non deductible" dans le dict)
    "csg":                      {"patronal": 0.00,    "salarial": 0.068,   "assiette": "98.25%"},
    "crds":                     {"patronal": 0.00,    "salarial": 0.005,   "assiette": "98.25%"},
    # Chômage (parser: "chomage" → ASSURANCE_CHOMAGE, "ags" → AGS)
    "chomage":                  {"patronal": 0.0405,  "salarial": 0.00,    "assiette": "totalite"},
    "ags":                      {"patronal": 0.0015,  "salarial": 0.00,    "assiette": "totalite"},
    # Retraite AGIRC-ARRCO (parser: "retraite complementaire"→T1, "ceg"→CEG_T1)
    "retraite complementaire":  {"patronal": 0.0472,  "salarial": 0.0315,  "assiette": "plafonnee_pass"},
    "ceg":                      {"patronal": 0.0129,  "salarial": 0.0086,  "assiette": "plafonnee_pass"},
    # Autres (parser: "fnal"→FNAL, "formation"→FORMATION_PRO, "taxe apprentissage"→TAXE_APP)
    "fnal":                     {"patronal": 0.001,   "salarial": 0.00,    "assiette": "plafonnee_pass"},
    "formation":                {"patronal": 0.0055,  "salarial": 0.00,    "assiette": "totalite"},
    "taxe apprentissage":       {"patronal": 0.0068,  "salarial": 0.00,    "assiette": "totalite"},
}

# Cotisations T2 pour cadres au-dessus du PASS (noms reconnus par le parser)
# "agirc" → RETRAITE_COMPLEMENTAIRE_T2
# Note: CEG_T2 n'a pas de mapping CSV distinct, on ne l'inclut pas en CSV
TAUX_T2_CSV = {
    "agirc":                    {"patronal": 0.1295,  "salarial": 0.0864,  "assiette": "tranche_2"},
}

# Cotisations supplémentaires pour DSN/XML uniquement (pas de mapping CSV fiable)
# Le parser CSV les mapperait à MALADIE par défaut → faux doublons
TAUX_DSN_ONLY = {
    "versement mobilite":       {"patronal": 0.0175,  "salarial": 0.00,   "assiette": "totalite", "seuil": 11},
    "peec":                     {"patronal": 0.0045,  "salarial": 0.00,   "assiette": "totalite", "seuil": 20},
    "contribution solidarite autonomie": {"patronal": 0.003, "salarial": 0.00, "assiette": "totalite"},
    "ceg t2":                   {"patronal": 0.0162,  "salarial": 0.0108, "assiette": "tranche_2"},
}

# Mapping CTP pour DSN
CTP_MAPPING = {
    "maladie": "100",
    "vieillesse plafonnee": "260",
    "vieillesse deplafonnee": "262",
    "allocations familiales": "332",
    "accident travail": "452",
    "csg": "012",
    "csg non deductible": "013",
    "crds": "018",
    "chomage": "772",
    "ags": "937",
    "fnal": "236",
    "formation": "971",
    "retraite complementaire": "400",
    "ceg": "403",
    "agirc": "401",
    "ceg t2": "404",
    "versement mobilite": "900",
    "peec": "960",
    "taxe apprentissage": "979",
}


# ============================================================
# Génération des données d'entreprise
# ============================================================

ENTREPRISES = [
    {
        "nom": "BTP Construction Pro SARL",
        "siret": "44455566600011",
        "siren": "444555666",
        "secteur": "BTP",
        "effectif": 45,
        "email": "gerant.btp@test.com",
        "password": "BtpTest2026!",
        "prenom": "Marc",
        "nom_gerant": "LEFEBVRE",
        "salaries": [
            {"nir": "1780175000001", "nom": "BERNARD", "prenom": "Luc", "statut": "non-cadre",
             "base_brute": 2400.00},
            {"nir": "1850175000002", "nom": "PETIT", "prenom": "Alain", "statut": "non-cadre",
             "base_brute": 2600.00},
            {"nir": "2900175000003", "nom": "MOREAU", "prenom": "Claire", "statut": "cadre",
             "base_brute": 4200.00},
            {"nir": "1950175000004", "nom": "GARCIA", "prenom": "Antoine", "statut": "non-cadre",
             "base_brute": 2300.00},
            {"nir": "1880175000005", "nom": "ROUX", "prenom": "David", "statut": "non-cadre",
             "base_brute": 2500.00},
        ],
        "anomalies": {
            "taux_atmp_eleve": 0.055,  # Taux AT/MP BTP élevé (5.5% en décimal)
            "montant_maladie_errone": True,  # Montant calculé incorrect
        },
    },
    {
        "nom": "TechStart SAS",
        "siret": "55566677700022",
        "siren": "555666777",
        "secteur": "Tech / Informatique",
        "effectif": 8,
        "email": "gerant.tech@test.com",
        "password": "TechTest2026!",
        "prenom": "Sophie",
        "nom_gerant": "DUBOIS",
        "salaries": [
            {"nir": "2850175000010", "nom": "LEROY", "prenom": "Emma", "statut": "cadre",
             "base_brute": 5500.00},
            {"nir": "1900175000011", "nom": "FOURNIER", "prenom": "Thomas", "statut": "cadre",
             "base_brute": 6200.00},
            {"nir": "2880175000012", "nom": "GIRARD", "prenom": "Julie", "statut": "cadre",
             "base_brute": 5800.00},
            {"nir": "1920175000013", "nom": "BONNET", "prenom": "Nicolas", "statut": "cadre",
             "base_brute": 7500.00},
        ],
        "anomalies": {
            "taux_vieillesse_errone": 0.10,  # Taux patronal vieillesse incorrect (devrait être 0.0855)
            "doublon_cotisation": True,  # Ligne de cotisation en double
        },
    },
    {
        "nom": "Restaurant Le Gourmet",
        "siret": "66677788800033",
        "siren": "666777888",
        "secteur": "HCR (Hôtellerie-Restauration)",
        "effectif": 12,
        "email": "gerant.resto@test.com",
        "password": "RestoTest2026!",
        "prenom": "Pierre",
        "nom_gerant": "LAMBERT",
        "salaries": [
            {"nir": "1870175000020", "nom": "FAURE", "prenom": "Julien", "statut": "non-cadre",
             "base_brute": 1700.00},  # Sous le SMIC !
            {"nir": "2910175000021", "nom": "MERCIER", "prenom": "Camille", "statut": "non-cadre",
             "base_brute": 1850.00},
            {"nir": "1940175000022", "nom": "BLANC", "prenom": "Hugo", "statut": "non-cadre",
             "base_brute": 1900.00},
            {"nir": "2860175000023", "nom": "ROBIN", "prenom": "Léa", "statut": "non-cadre",
             "base_brute": 1750.00},  # Sous le SMIC !
        ],
        "anomalies": {
            "salaire_sous_smic": True,  # 2 salariés sous le SMIC
            "base_negative": -500.00,  # Base brute négative (erreur)
        },
    },
    {
        "nom": "Cabinet Santé Plus",
        "siret": "77788899900044",
        "siren": "777888999",
        "secteur": "Santé / Médical",
        "effectif": 5,
        "email": "gerant.sante@test.com",
        "password": "SanteTest2026!",
        "prenom": "Anne",
        "nom_gerant": "VINCENT",
        "salaries": [
            {"nir": "2830175000030", "nom": "CLEMENT", "prenom": "Marie", "statut": "cadre",
             "base_brute": 3800.00},
            {"nir": "1960175000031", "nom": "MOREL", "prenom": "François", "statut": "non-cadre",
             "base_brute": 2200.00},
            {"nir": "2970175000032", "nom": "SIMON", "prenom": "Isabelle", "statut": "non-cadre",
             "base_brute": 2100.00},
        ],
        "anomalies": {
            "taux_af_errone": 0.075,  # Allocations familiales taux bien trop élevé (7.5% en décimal)
        },
    },
    {
        "nom": "Transport Express SARL",
        "siret": "88899900000055",
        "siren": "888999000",
        "secteur": "Transport routier",
        "effectif": 30,
        "email": "gerant.transport@test.com",
        "password": "TransTest2026!",
        "prenom": "Jean-Pierre",
        "nom_gerant": "DUVAL",
        "salaries": [
            {"nir": "1810175000040", "nom": "RENARD", "prenom": "Patrick", "statut": "non-cadre",
             "base_brute": 2800.00},
            {"nir": "1850175000041", "nom": "PICARD", "prenom": "Sébastien", "statut": "non-cadre",
             "base_brute": 2900.00},
            {"nir": "2890175000042", "nom": "ROGER", "prenom": "Nathalie", "statut": "cadre",
             "base_brute": 4100.00},
            {"nir": "1930175000043", "nom": "BRUNET", "prenom": "Christophe", "statut": "non-cadre",
             "base_brute": 2750.00},
            {"nir": "1870175000044", "nom": "SCHMITT", "prenom": "Michel", "statut": "non-cadre",
             "base_brute": 3100.00},
        ],
        "anomalies": {
            "montant_calcul_errone": True,  # Montant patronal incorrect
            "taux_atmp_transport": 0.038,  # Taux AT/MP transport (3.8% en décimal)
        },
    },
]


def _calcul_assiette(base_brute, assiette_type):
    """Calcule l'assiette selon le type de cotisation."""
    if assiette_type == "plafonnee_pass":
        return min(base_brute, PASS_MENSUEL)
    elif assiette_type == "98.25%":
        return round(abs(base_brute) * 0.9825, 2)
    elif assiette_type == "tranche_2":
        if base_brute > PASS_MENSUEL:
            return min(base_brute - PASS_MENSUEL, 7 * PASS_MENSUEL)
        return 0
    return abs(base_brute)


def _get_cotisations_csv(entreprise, salarie):
    """Retourne les cotisations pour le CSV (noms reconnus par le parser)."""
    cots = dict(TAUX_CSV)
    effectif = entreprise["effectif"]

    # FNAL : adapter le taux selon effectif (0.50% déplafonné si >= 50)
    if effectif >= 50:
        cots["fnal"] = {"patronal": 0.005, "salarial": 0.00, "assiette": "totalite"}

    # Formation professionnelle : adapter selon effectif (1.00% si >= 11)
    if effectif >= 11:
        cots["formation"] = {"patronal": 0.01, "salarial": 0.00, "assiette": "totalite"}

    # Retraite T2 (agirc) si salaire > PASS
    if salarie["base_brute"] > PASS_MENSUEL:
        for nom_cot, params in TAUX_T2_CSV.items():
            cots[nom_cot] = params

    return cots


def _get_cotisations_dsn(entreprise, salarie):
    """Retourne TOUTES les cotisations pour DSN/XML (y compris non-CSV)."""
    cots = _get_cotisations_csv(entreprise, salarie)
    effectif = entreprise["effectif"]

    # Cotisations DSN-only (pas de mapping CSV fiable)
    for nom_cot, params in TAUX_DSN_ONLY.items():
        seuil = params.get("seuil", 0)
        if seuil and effectif < seuil:
            continue
        if params.get("assiette") == "tranche_2" and salarie["base_brute"] <= PASS_MENSUEL:
            continue
        cots[nom_cot] = params

    return cots


def generer_csv_paie(entreprise):
    """Génère un fichier CSV de paie avec toutes les cotisations et anomalies spécifiques."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "nir", "nom", "prenom", "statut", "base_brute", "type_cotisation",
        "taux_patronal", "montant_patronal", "taux_salarial", "montant_salarial",
        "periode_debut", "periode_fin"
    ])

    anomalies = entreprise.get("anomalies", {})

    for sal in entreprise["salaries"]:
        base = sal["base_brute"]

        # Anomalie : base négative pour le premier salarié
        if anomalies.get("base_negative") and sal == entreprise["salaries"][0]:
            base = anomalies["base_negative"]

        cotisations = _get_cotisations_csv(entreprise, sal)

        for cot_type, taux in cotisations.items():
            tp = taux["patronal"]
            ts = taux["salarial"]
            assiette_type = taux.get("assiette", "totalite")

            # Calcul de l'assiette correcte
            assiette = _calcul_assiette(base, assiette_type)

            # Anomalie : taux AT/MP élevé (en décimal)
            if cot_type == "accident travail" and anomalies.get("taux_atmp_eleve"):
                tp = anomalies["taux_atmp_eleve"]
            if cot_type == "accident travail" and anomalies.get("taux_atmp_transport"):
                tp = anomalies["taux_atmp_transport"]

            # Anomalie : taux vieillesse erroné
            if cot_type == "vieillesse plafonnee" and anomalies.get("taux_vieillesse_errone"):
                tp = anomalies["taux_vieillesse_errone"]

            # Anomalie : taux AF erroné
            if cot_type == "allocations familiales" and anomalies.get("taux_af_errone"):
                tp = anomalies["taux_af_errone"]

            # Taux en décimal → multiplication directe
            mp = round(abs(assiette) * tp, 2)
            ms = round(abs(assiette) * ts, 2)

            # Anomalie : montant maladie erroné
            if cot_type == "maladie" and anomalies.get("montant_maladie_errone"):
                mp = round(mp * 1.15, 2)  # +15% d'erreur

            # Anomalie : montant calcul erroné
            if anomalies.get("montant_calcul_errone") and cot_type == "vieillesse deplafonnee":
                mp = round(mp * 0.5, 2)  # 50% trop bas

            # Pour le CSV, écrire l'assiette réelle (pas la base brute)
            # afin que l'analyseur voie la bonne base dans la colonne base_brute
            base_csv = assiette if assiette_type != "totalite" else base
            writer.writerow([
                sal["nir"], sal["nom"], sal["prenom"], sal["statut"],
                f"{base_csv:.2f}", cot_type, f"{tp:.4f}", f"{mp:.2f}",
                f"{ts:.4f}", f"{ms:.2f}", "01/01/2026", "31/01/2026"
            ])

        # Anomalie : doublon cotisation
        if anomalies.get("doublon_cotisation") and sal == entreprise["salaries"][0]:
            tp = TAUX_CSV["maladie"]["patronal"]
            mp = round(abs(base) * tp, 2)
            writer.writerow([
                sal["nir"], sal["nom"], sal["prenom"], sal["statut"],
                f"{base:.2f}", "maladie", f"{tp:.4f}", f"{mp:.2f}",
                "0.0000", "0.00", "01/01/2026", "31/01/2026"
            ])

    return output.getvalue()


def generer_dsn(entreprise):
    """Génère un fichier DSN complet avec tous les blocs obligatoires."""
    lines = []

    # S10 — Emetteur
    lines.append(f"S10.G00.00.001 '{entreprise['nom']}'")
    lines.append("S10.G00.00.002 '01'")
    lines.append("S10.G00.00.003 '11'")
    lines.append("S10.G00.00.004 '01012026'")
    lines.append("S10.G00.00.005 '31012026'")

    # S20 — Entreprise
    lines.append(f"S20.G00.05.001 '{entreprise['siren']}'")
    lines.append(f"S20.G00.05.002 '{entreprise['nom']}'")

    # S21.G00.06 — Etablissement
    lines.append(f"S21.G00.06.001 '{entreprise['siret'][-5:]}'")
    lines.append("S21.G00.06.003 '012026'")

    # S21.G00.11 — Effectif
    lines.append(f"S21.G00.11.001 '{entreprise['effectif']}'")

    # Pour chaque salarié : S30 + S21.G00.40 (contrat) + S21.G00.51 (rémunération)
    # + S21.G00.78 (base assujettie) + S21.G00.81 (cotisation individuelle)
    for i, sal in enumerate(entreprise["salaries"]):
        # S30 — Identification salarié
        lines.append(f"S30.G00.30.001 '{sal['nir']}'")
        lines.append(f"S30.G00.30.002 '{sal['nom']}'")
        lines.append(f"S30.G00.30.004 '{sal['prenom']}'")

        # S21.G00.40 — Contrat
        lines.append(f"S21.G00.40.001 '{i+1:03d}'")  # Numéro contrat
        lines.append("S21.G00.40.002 '01'")           # CDI
        lines.append("S21.G00.40.007 '01012026'")     # Date début
        lines.append(f"S21.G00.40.009 '{sal['statut']}'")

        # S21.G00.51 — Rémunération
        lines.append(f"S21.G00.51.001 '{sal['base_brute']:.2f}'")
        lines.append("S21.G00.51.002 '001'")          # Type : brut
        lines.append("S21.G00.51.010 '01012026'")
        lines.append("S21.G00.51.011 '31012026'")

        # S21.G00.78 — Bases assujetties
        base = sal["base_brute"]
        base_plaf = min(base, PASS_MENSUEL)
        base_csg = round(base * 0.9825, 2)
        lines.append(f"S21.G00.78.001 '02'")  # Brut SS
        lines.append(f"S21.G00.78.004 '{base:.2f}'")
        lines.append(f"S21.G00.78.001 '03'")  # Plafonné
        lines.append(f"S21.G00.78.004 '{base_plaf:.2f}'")
        lines.append(f"S21.G00.78.001 '04'")  # Base CSG
        lines.append(f"S21.G00.78.004 '{base_csg:.2f}'")

        # S21.G00.81 — Cotisations individuelles
        cotisations = _get_cotisations_dsn(entreprise, sal)
        for cot_type, taux in cotisations.items():
            ctp = CTP_MAPPING.get(cot_type)
            if not ctp:
                continue
            assiette = _calcul_assiette(base, taux.get("assiette", "totalite"))
            if assiette <= 0:
                continue
            tp = taux["patronal"]
            mp = round(assiette * tp, 2)  # taux en décimal
            lines.append(f"S21.G00.81.001 '{ctp}'")
            lines.append(f"S21.G00.81.003 '{assiette:.2f}'")
            lines.append(f"S21.G00.81.004 '{tp:.4f}'")
            lines.append(f"S21.G00.81.005 '{mp:.2f}'")

    # S21.G00.22 — Cotisations agrégées
    total_base = sum(s["base_brute"] for s in entreprise["salaries"])
    total_base_plaf = sum(min(s["base_brute"], PASS_MENSUEL) for s in entreprise["salaries"])

    for cot_type in ["maladie", "vieillesse plafonnee", "vieillesse deplafonnee",
                      "allocations familiales", "accident travail", "chomage",
                      "retraite complementaire"]:
        ctp = CTP_MAPPING.get(cot_type, "000")
        taux_info = TAUX_CSV[cot_type]
        if taux_info.get("assiette") == "plafonnee_pass":
            base_agg = total_base_plaf
        else:
            base_agg = total_base
        tp = taux_info["patronal"]
        mp = round(base_agg * tp, 2)  # taux en décimal
        lines.append(f"S21.G00.22.001 '{ctp}'")
        lines.append(f"S21.G00.22.003 '{base_agg:.2f}'")
        lines.append(f"S21.G00.22.004 '{tp:.4f}'")
        lines.append(f"S21.G00.22.005 '{mp:.2f}'")

    # S21.G00.23 — Bordereau de cotisation due
    total_patronal = round(total_base * 0.13, 2)  # Maladie seule (simplifié)
    lines.append("S21.G00.23.001 '01'")
    lines.append(f"S21.G00.23.002 '{entreprise['siret']}'")
    lines.append("S21.G00.23.003 '012026'")
    lines.append(f"S21.G00.23.005 '{total_patronal:.2f}'")

    return "\n".join(lines)


def generer_bordereau_xml(entreprise):
    """Génère un bordereau de cotisations XML complet."""
    cotisations = ""
    total_base = sum(s["base_brute"] for s in entreprise["salaries"])
    total_base_plaf = sum(min(s["base_brute"], PASS_MENSUEL) for s in entreprise["salaries"])

    for cot_type, taux in TAUX_CSV.items():
        if taux.get("assiette") == "plafonnee_pass":
            base_cot = total_base_plaf
        elif taux.get("assiette") == "98.25%":
            base_cot = round(total_base * 0.9825, 2)
        else:
            base_cot = total_base

        mp = round(base_cot * taux["patronal"], 2)   # taux en décimal
        ms = round(base_cot * taux["salarial"], 2)   # taux en décimal
        cotisations += f"""    <ligne_cotisation>
        <type_cotisation>{cot_type.replace(' ', '_')}</type_cotisation>
        <base>{base_cot:.2f}</base>
        <taux_patronal>{taux['patronal']:.4f}</taux_patronal>
        <montant_patronal>{mp:.2f}</montant_patronal>
        <taux_salarial>{taux['salarial']:.4f}</taux_salarial>
        <montant_salarial>{ms:.2f}</montant_salarial>
    </ligne_cotisation>
"""

    # Cotisations DSN-only (versement mobilité, PEEC, etc.)
    effectif = entreprise["effectif"]
    for cot_type, params in TAUX_DSN_ONLY.items():
        seuil = params.get("seuil", 0)
        if seuil and effectif < seuil:
            continue
        if params.get("assiette") == "tranche_2":
            continue  # T2 traité séparément ci-dessous
        mp = round(total_base * params["patronal"], 2)
        cotisations += f"""    <ligne_cotisation>
        <type_cotisation>{cot_type.replace(' ', '_')}</type_cotisation>
        <base>{total_base:.2f}</base>
        <taux_patronal>{params['patronal']:.4f}</taux_patronal>
        <montant_patronal>{mp:.2f}</montant_patronal>
        <taux_salarial>{params.get('salarial', 0):.4f}</taux_salarial>
        <montant_salarial>0.00</montant_salarial>
    </ligne_cotisation>
"""

    # T2 pour cadres au-dessus du PASS (agirc CSV + ceg t2 DSN-only)
    all_t2 = dict(TAUX_T2_CSV)
    all_t2["ceg t2"] = TAUX_DSN_ONLY["ceg t2"]
    for sal in entreprise["salaries"]:
        if sal["base_brute"] > PASS_MENSUEL:
            tranche2 = sal["base_brute"] - PASS_MENSUEL
            for cot_type, params in all_t2.items():
                mp = round(tranche2 * params["patronal"], 2)
                ms = round(tranche2 * params["salarial"], 2)
                cotisations += f"""    <ligne_cotisation>
        <type_cotisation>{cot_type.replace(' ', '_')}_{sal['nom']}</type_cotisation>
        <base>{tranche2:.2f}</base>
        <taux_patronal>{params['patronal']:.4f}</taux_patronal>
        <montant_patronal>{mp:.2f}</montant_patronal>
        <taux_salarial>{params['salarial']:.4f}</taux_salarial>
        <montant_salarial>{ms:.2f}</montant_salarial>
    </ligne_cotisation>
"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<bordereau_cotisations>
    <employeur>
        <siret>{entreprise['siret']}</siret>
        <siren>{entreprise['siren']}</siren>
        <raison_sociale>{entreprise['nom']}</raison_sociale>
        <effectif>{entreprise['effectif']}</effectif>
    </employeur>
    <periode>
        <date_debut>01/01/2026</date_debut>
        <date_fin>31/01/2026</date_fin>
    </periode>
    <masse_salariale>{total_base:.2f}</masse_salariale>
    <nb_salaries>{len(entreprise['salaries'])}</nb_salaries>
{cotisations}</bordereau_cotisations>
"""


# ============================================================
# Simulation du parcours gérant
# ============================================================

def simuler_gerant(entreprise, session):
    """Simule le parcours complet d'un gérant sur NormaCheck."""
    result = {
        "entreprise": entreprise["nom"],
        "secteur": entreprise["secteur"],
        "effectif": entreprise["effectif"],
        "etapes": [],
        "erreurs": [],
        "analyse": None,
    }

    print(f"\n{'='*70}")
    print(f"  SIMULATION : {entreprise['nom']}")
    print(f"  Secteur : {entreprise['secteur']} | Effectif : {entreprise['effectif']}")
    print(f"{'='*70}")

    # --- Étape 1 : Inscription ---
    print("\n  [1/5] Inscription du gérant...")
    try:
        resp = session.post(f"{BASE_URL}/api/auth/register", data={
            "nom": entreprise["nom_gerant"],
            "prenom": entreprise["prenom"],
            "email": entreprise["email"],
            "mot_de_passe": entreprise["password"],
        })
        if resp.status_code == 200:
            result["etapes"].append({"inscription": "OK"})
            print(f"        → Inscrit : {entreprise['email']}")
        else:
            # Peut-être déjà inscrit, essayons le login
            resp = session.post(f"{BASE_URL}/api/auth/login", data={
                "email": entreprise["email"],
                "mot_de_passe": entreprise["password"],
            })
            if resp.status_code == 200:
                result["etapes"].append({"inscription": "déjà inscrit, login OK"})
                print(f"        → Login : {entreprise['email']}")
            else:
                result["erreurs"].append(f"Auth failed: {resp.status_code} - {resp.text[:200]}")
                print(f"        → ERREUR auth: {resp.status_code}")
                return result

        # Extraire le token JWT
        token = session.cookies.get("nc_token")
        if not token:
            set_cookie = resp.headers.get("set-cookie", "")
            if "nc_token=" in set_cookie:
                token = set_cookie.split("nc_token=")[1].split(";")[0]
        if token:
            session.headers["Authorization"] = f"Bearer {token}"
            print(f"        → Token JWT récupéré")
        else:
            print(f"        → WARN: Token JWT non trouvé")

    except Exception as e:
        result["erreurs"].append(f"Auth exception: {e}")
        print(f"        → EXCEPTION: {e}")
        return result

    # --- Étape 2 : Génération des documents ---
    print("\n  [2/5] Génération des documents...")
    with tempfile.TemporaryDirectory() as tmpdir:
        # CSV paie
        csv_path = os.path.join(tmpdir, f"paie_{entreprise['siren']}.csv")
        csv_content = generer_csv_paie(entreprise)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(csv_content)
        nb_lignes_csv = csv_content.count("\n")
        print(f"        → CSV paie généré ({nb_lignes_csv} lignes)")

        # DSN
        dsn_path = os.path.join(tmpdir, f"dsn_{entreprise['siren']}.dsn")
        dsn_content = generer_dsn(entreprise)
        with open(dsn_path, "w", encoding="utf-8") as f:
            f.write(dsn_content)
        nb_lignes_dsn = dsn_content.count("\n")
        print(f"        → DSN générée ({nb_lignes_dsn} lignes, blocs S10-S81)")

        # Bordereau XML
        xml_path = os.path.join(tmpdir, f"bordereau_{entreprise['siren']}.xml")
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(generer_bordereau_xml(entreprise))
        print(f"        → Bordereau XML généré (toutes cotisations)")

        result["etapes"].append({"documents": ["CSV paie complet", "DSN complète", "Bordereau XML complet"]})

        # --- Étape 3 : Upload et analyse ---
        print("\n  [3/5] Upload et analyse des documents...")
        try:
            files = [
                ("fichiers", (os.path.basename(csv_path), open(csv_path, "rb"), "text/csv")),
                ("fichiers", (os.path.basename(dsn_path), open(dsn_path, "rb"), "application/octet-stream")),
                ("fichiers", (os.path.basename(xml_path), open(xml_path, "rb"), "application/xml")),
            ]
            resp = session.post(
                f"{BASE_URL}/api/analyze",
                files=files,
                params={"mode_analyse": "complet", "format_rapport": "json"},
            )

            if resp.status_code == 200:
                data = resp.json()
                result["analyse"] = data
                result["etapes"].append({"analyse": "OK", "status_code": 200})

                synthese = data.get("synthese", {})
                constats = data.get("constats", [])

                print(f"        → Analyse réussie !")
                print(f"        → Fichiers analysés : {synthese.get('nb_fichiers', '?')}")
                print(f"        → Salariés détectés : {synthese.get('nb_salaries', '?')}")
                print(f"        → Masse salariale : {synthese.get('masse_salariale_totale', '?')} €")
                print(f"        → Score risque global : {synthese.get('score_risque_global', '?')}")
                print(f"        → Impact financier : {synthese.get('impact_financier_total', '?')} €")
                print(f"        → Constats : {len(constats)}")

                # Classement par sévérité
                par_sev = {}
                for c in constats:
                    sev = c.get("severite", "inconnue")
                    par_sev[sev] = par_sev.get(sev, 0) + 1
                print(f"        → Par sévérité : {par_sev}")

                if constats:
                    print(f"\n        Détail des constats :")
                    for i, c in enumerate(constats[:20], 1):
                        sev = c.get("severite", "?")
                        titre = c.get("titre", "?")
                        impact = c.get("montant_impact", 0)
                        print(f"          {i}. [{sev.upper()}] {titre} (impact: {impact} €)")
            else:
                result["erreurs"].append(f"Analyse failed: {resp.status_code} - {resp.text[:500]}")
                print(f"        → ERREUR analyse: {resp.status_code}")
                try:
                    err = resp.json()
                    print(f"        → Détail: {json.dumps(err, indent=2, ensure_ascii=False)[:500]}")
                except Exception:
                    print(f"        → Réponse: {resp.text[:500]}")

        except Exception as e:
            result["erreurs"].append(f"Analyse exception: {traceback.format_exc()}")
            print(f"        → EXCEPTION: {e}")

    # --- Étape 4 : Export du rapport ---
    print("\n  [4/5] Export du rapport PDF...")
    if result["analyse"]:
        try:
            export_data = {
                "data": {
                    "synthese": result["analyse"].get("synthese", {}),
                    "constats": result["analyse"].get("constats", []),
                    "recommandations": result["analyse"].get("recommandations", []),
                    "mode_analyse": "complet",
                },
                "synthese": result["analyse"].get("synthese", {}),
            }
            resp = session.post(f"{BASE_URL}/api/export/pdf", json=export_data)
            if resp.status_code == 200:
                result["etapes"].append({"export_pdf": "OK", "taille": len(resp.content)})
                print(f"        → Rapport généré ({len(resp.content)} octets)")
            else:
                result["erreurs"].append(f"Export failed: {resp.status_code}")
                print(f"        → ERREUR export: {resp.status_code}")
        except Exception as e:
            result["erreurs"].append(f"Export exception: {e}")
            print(f"        → EXCEPTION: {e}")
    else:
        print(f"        → Ignoré (analyse échouée)")

    # --- Étape 5 : Vérification de la chaîne de preuve ---
    print("\n  [5/5] Vérification chaîne de preuve...")
    try:
        resp = session.get(f"{BASE_URL}/api/proof/verify")
        if resp.status_code == 200:
            proof = resp.json()
            result["etapes"].append({"proof_verify": proof})
            print(f"        → Chaîne valide : {proof.get('valid', '?')}")
            print(f"        → Entrées : {proof.get('entries', '?')}")
        else:
            result["erreurs"].append(f"Proof verify failed: {resp.status_code}")
            print(f"        → ERREUR: {resp.status_code}")
    except Exception as e:
        result["erreurs"].append(f"Proof exception: {e}")

    # --- Étape bonus : Consultation comptabilité ---
    try:
        resp = session.get(f"{BASE_URL}/api/comptabilite/journal")
        if resp.status_code == 200:
            journal = resp.json()
            nb = len(journal) if isinstance(journal, list) else 0
            print(f"\n  [bonus] Journal comptable : {nb} écritures")
    except Exception:
        pass

    return result


# ============================================================
# Rapport final
# ============================================================

def rapport_final(results):
    """Affiche le rapport consolidé de toutes les simulations."""
    print(f"\n\n{'#'*70}")
    print(f"#  RAPPORT CONSOLIDÉ — SIMULATION MULTI-ENTREPRISES")
    print(f"{'#'*70}\n")

    total_constats = 0
    total_erreurs = 0
    total_impact = 0

    for r in results:
        analyse = r.get("analyse", {}) or {}
        synthese = analyse.get("synthese", {})
        constats = analyse.get("constats", [])
        nb_constats = len(constats)
        impact = synthese.get("impact_financier_total", 0) or 0
        nb_erreurs = len(r.get("erreurs", []))

        total_constats += nb_constats
        total_erreurs += nb_erreurs
        total_impact += impact

        status = "OK" if nb_erreurs == 0 else f"ERREURS ({nb_erreurs})"

        print(f"  {r['entreprise']:<35} | {r['secteur']:<25} | "
              f"Eff: {r['effectif']:>3} | Constats: {nb_constats:>3} | "
              f"Impact: {impact:>10.2f} € | {status}")

    print(f"\n  {'─'*100}")
    print(f"  TOTAL : {total_constats} constats | {total_impact:,.2f} € d'impact | "
          f"{total_erreurs} erreurs techniques")

    # Détail des erreurs
    if total_erreurs > 0:
        print(f"\n  ERREURS DÉTECTÉES :")
        for r in results:
            for err in r.get("erreurs", []):
                print(f"    [{r['entreprise']}] {err[:200]}")

    return total_erreurs


# ============================================================
# Main
# ============================================================

def main():
    print(f"\n{'='*70}")
    print(f"  NormaCheck — Simulation Multi-Entreprises")
    print(f"  {len(ENTREPRISES)} entreprises | Parcours gérant complet")
    print(f"  Serveur : {BASE_URL}")
    print(f"  PASS mensuel : {PASS_MENSUEL} € | SMIC : {SMIC_MENSUEL} €")
    print(f"  Cotisations CSV : {len(TAUX_CSV)} + {len(TAUX_T2_CSV)} T2 | DSN-only : {len(TAUX_DSN_ONLY)}")
    print(f"{'='*70}")

    # Vérifier que le serveur est accessible
    print("\n  Vérification du serveur...")
    try:
        resp = requests.get(f"{BASE_URL}/api/health", timeout=5)
        if resp.status_code == 200:
            health = resp.json()
            print(f"  → Serveur OK : v{health.get('version', '?')} | env: {health.get('env', '?')}")
        else:
            print(f"  → Serveur répond mais status {resp.status_code}")
    except requests.ConnectionError:
        print(f"  → ERREUR : Serveur non accessible sur {BASE_URL}")
        print(f"  → Lancez : uvicorn api.index:app --port 8000")
        sys.exit(1)

    results = []

    for entreprise in ENTREPRISES:
        session = requests.Session()
        result = simuler_gerant(entreprise, session)
        results.append(result)
        RESULTS.append(result)

    nb_errors = rapport_final(results)

    # Sauvegarder les résultats JSON
    output_path = Path(__file__).parent.parent / "data" / "simulation_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        summary = []
        for r in results:
            s = {
                "entreprise": r["entreprise"],
                "secteur": r["secteur"],
                "effectif": r["effectif"],
                "etapes": r["etapes"],
                "erreurs": r["erreurs"],
            }
            if r.get("analyse"):
                s["synthese"] = r["analyse"].get("synthese", {})
                s["nb_constats"] = len(r["analyse"].get("constats", []))
                s["constats_resume"] = [
                    {"titre": c.get("titre"), "severite": c.get("severite"),
                     "montant_impact": c.get("montant_impact")}
                    for c in r["analyse"].get("constats", [])[:20]
                ]
            summary.append(s)
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n  Résultats sauvegardés dans {output_path}")

    return nb_errors


if __name__ == "__main__":
    errors = main()
    sys.exit(1 if errors > 0 else 0)
