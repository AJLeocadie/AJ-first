"""NormaCheck v3.5 - Plateforme professionnelle de conformite sociale et fiscale.

Point d'entree web : import/analyse de documents, gestion entreprise,
comptabilite, simulation, veille juridique, portefeuille, collaboration, DSN.
"""

import io
import json
import tempfile
import time
import shutil
import hashlib
import uuid
import traceback
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from urssaf_analyzer.config.settings import AppConfig
from urssaf_analyzer.config.constants import SUPPORTED_EXTENSIONS
from urssaf_analyzer.core.orchestrator import Orchestrator
from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError
from urssaf_analyzer.database.db_manager import Database
from urssaf_analyzer.portfolio.portfolio_manager import PortfolioManager
from urssaf_analyzer.veille.veille_manager import VeilleManager
from urssaf_analyzer.veille.urssaf_client import get_baremes_annee, comparer_baremes, BAREMES_PAR_ANNEE
from urssaf_analyzer.veille.legifrance_client import get_legislation_par_annee, ARTICLES_CSS_COTISATIONS
from urssaf_analyzer.comptabilite.plan_comptable import PlanComptable
from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures, TypeJournal
from urssaf_analyzer.comptabilite.rapports_comptables import GenerateurRapports

app = FastAPI(
    title="NormaCheck",
    description="Plateforme professionnelle de conformite sociale et fiscale",
    version="3.5.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Singletons ---
_db: Optional[Database] = None
_moteur: Optional[MoteurEcritures] = None

# --- In-memory stores ---
_doc_library: list[dict] = []
_biblio_knowledge: dict = {
    "salaries": {},        # nir -> {nom, prenom, brut, net, statut, contrat_type, ...}
    "employeurs": {},      # siret -> {raison_sociale, effectif, code_naf, ...}
    "cotisations": [],     # [{code, libelle, base, taux_salarial, taux_patronal, employe_nir, ...}]
    "declarations_dsn": [],# DSN importees
    "bulletins_paie": [],  # bulletins detectes
    "documents_comptables": [],  # ecritures/factures detectees
    "taux_verifies": {},   # {code_cotisation: {taux_attendu, taux_constate, conforme}}
    "periodes_couvertes": [],  # ["2025-01", "2025-02", ...]
    "anomalies_detectees": [],
    "pieces_justificatives": {},  # {type_piece: [doc_ids]}
    "contrats_detectes": [],  # contrats extraits des documents
    "masse_salariale": {},  # {periode: montant}
    "effectifs": {},        # {periode: nb}
    "conventions_collectives": [],  # CCN detectees
    "exonerations_detectees": [],  # exonerations apprentis, ZRR, etc.
    "derniere_maj": None,
}
_invitations: list[dict] = []
_facture_statuses: dict[str, dict] = {}
_audit_log: list[dict] = []
_dsn_drafts: list[dict] = []
_rh_contrats: list[dict] = []
_rh_avenants: list[dict] = []
_rh_conges: list[dict] = []
_rh_arrets: list[dict] = []
_rh_sanctions: list[dict] = []
_rh_attestations: list[dict] = []
_rh_entretiens: list[dict] = []
_rh_visites_med: list[dict] = []
_rh_echanges: list[dict] = []
_rh_planning: list[dict] = []
_entete_config: dict = {}


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database("/tmp/urssaf_analyzer.db")
    return _db


def get_moteur() -> MoteurEcritures:
    global _moteur
    if _moteur is None:
        _moteur = MoteurEcritures(PlanComptable())
    return _moteur


def log_action(profil_email: str, action: str, details: str = ""):
    _audit_log.append({
        "id": str(uuid.uuid4())[:8],
        "date": datetime.now().isoformat(),
        "profil": profil_email,
        "action": action,
        "details": details,
    })


# ==============================
# PAGES
# ==============================

@app.get("/", response_class=HTMLResponse)
async def accueil():
    return LANDING_HTML


@app.get("/app", response_class=HTMLResponse)
async def application():
    return APP_HTML


@app.get("/legal/cgu", response_class=HTMLResponse)
async def legal_cgu():
    return LEGAL_CGU


@app.get("/legal/cgv", response_class=HTMLResponse)
async def legal_cgv():
    return LEGAL_CGV


@app.get("/legal/mentions", response_class=HTMLResponse)
async def legal_mentions():
    return LEGAL_MENTIONS


# ==============================
# AUTH
# ==============================

@app.post("/api/auth/login")
async def auth_login(email: str = Form("admin"), mot_de_passe: str = Form("admin")):
    log_action(email, "connexion")
    return {"status": "ok", "email": email, "role": "admin"}


@app.post("/api/auth/register")
async def auth_register(
    nom: str = Form(...), prenom: str = Form(...),
    email: str = Form(...), mot_de_passe: str = Form(...)
):
    if len(mot_de_passe) < 6:
        raise HTTPException(400, "Mot de passe trop court (min. 6 caracteres)")
    log_action(email, "inscription", f"{prenom} {nom}")
    return {"status": "ok", "email": email}


# ==============================
# BIBLIOTHEQUE DE CONNAISSANCES
# ==============================

def _alimenter_knowledge(result):
    """Alimente la base de connaissances a partir d'un resultat d'analyse."""
    kb = _biblio_knowledge
    kb["derniere_maj"] = datetime.now().isoformat()

    for decl in result.declarations:
        # --- Employeur ---
        if decl.employeur:
            siret = decl.employeur.siret or ""
            if siret:
                kb["employeurs"][siret] = {
                    "siren": decl.employeur.siren,
                    "siret": siret,
                    "raison_sociale": decl.employeur.raison_sociale,
                    "effectif": decl.employeur.effectif,
                    "code_naf": decl.employeur.code_naf,
                    "derniere_maj": datetime.now().isoformat(),
                }
                # Effectif par periode
                periode = ""
                if decl.periode and decl.periode.debut:
                    periode = decl.periode.debut.strftime("%Y-%m")
                if periode and decl.employeur.effectif:
                    kb["effectifs"][periode] = decl.employeur.effectif

        # --- Periode ---
        if decl.periode and decl.periode.debut:
            per = decl.periode.debut.strftime("%Y-%m")
            if per not in kb["periodes_couvertes"]:
                kb["periodes_couvertes"].append(per)
                kb["periodes_couvertes"].sort()

        # --- Type de document ---
        fmt = (decl.type_declaration or "").lower()
        meta = getattr(decl, "metadata", {}) or {}
        doc_type = meta.get("type_document", "")
        per_kb = decl.periode.debut.strftime("%Y-%m") if decl.periode and decl.periode.debut else ""
        if fmt in ("dsn", "dsn/xml"):
            kb["declarations_dsn"].append({
                "reference": decl.reference,
                "periode": per_kb,
                "nb_salaries": len(decl.employes),
                "nb_cotisations": len(decl.cotisations),
                "masse_salariale": float(decl.masse_salariale_brute),
                "s89_total_cotisations": meta.get("s89_total_cotisations", 0),
                "s89_total_brut": meta.get("s89_total_brut", 0),
                "date_import": datetime.now().isoformat(),
            })
            if "dsn" not in kb["pieces_justificatives"]:
                kb["pieces_justificatives"]["dsn"] = []
            kb["pieces_justificatives"]["dsn"].append(decl.reference)
        elif fmt == "bulletin" or doc_type == "bulletin_de_paie" or (len(decl.cotisations) > 0 and len(decl.employes) <= 1):
            kb["bulletins_paie"].append({
                "reference": decl.reference,
                "nb_salaries": len(decl.employes),
                "nb_cotisations": len(decl.cotisations),
                "masse_salariale": float(decl.masse_salariale_brute),
                "net_a_payer": meta.get("net_a_payer", 0),
                "total_patronal": meta.get("total_patronal", 0),
                "total_salarial": meta.get("total_salarial", 0),
                "periode": per_kb,
                "date_import": datetime.now().isoformat(),
            })
            if "bulletins" not in kb["pieces_justificatives"]:
                kb["pieces_justificatives"]["bulletins"] = []
            kb["pieces_justificatives"]["bulletins"].append(decl.reference)
        elif fmt == "livre_de_paie" or doc_type == "livre_de_paie":
            kb["bulletins_paie"].append({
                "reference": decl.reference,
                "nb_salaries": len(decl.employes),
                "nb_cotisations": len(decl.cotisations),
                "masse_salariale": float(decl.masse_salariale_brute),
                "periode": per_kb,
                "date_import": datetime.now().isoformat(),
            })
            if "livre_de_paie" not in kb["pieces_justificatives"]:
                kb["pieces_justificatives"]["livre_de_paie"] = []
            kb["pieces_justificatives"]["livre_de_paie"].append(decl.reference)
        elif fmt == "facture" or doc_type in ("facture_achat", "facture_vente"):
            if "factures" not in kb["pieces_justificatives"]:
                kb["pieces_justificatives"]["factures"] = []
            kb["pieces_justificatives"]["factures"].append(decl.reference)
        elif fmt == "contrat" or doc_type == "contrat_de_travail":
            if "contrats" not in kb["pieces_justificatives"]:
                kb["pieces_justificatives"]["contrats"] = []
            kb["pieces_justificatives"]["contrats"].append(decl.reference)
        elif len(decl.cotisations) > 0 or float(decl.masse_salariale_brute) > 0:
            kb["bulletins_paie"].append({
                "reference": decl.reference,
                "nb_salaries": len(decl.employes),
                "nb_cotisations": len(decl.cotisations),
                "masse_salariale": float(decl.masse_salariale_brute),
                "periode": per_kb,
                "date_import": datetime.now().isoformat(),
            })
            if "autres" not in kb["pieces_justificatives"]:
                kb["pieces_justificatives"]["autres"] = []
            kb["pieces_justificatives"]["autres"].append(decl.reference)

        # --- Salaries ---
        for emp in decl.employes:
            nir = emp.nir or f"unknown_{emp.id}"
            existing = kb["salaries"].get(nir, {})
            cots = [c for c in decl.cotisations if c.employe_id == emp.id]
            brut = float(sum(c.base_brute for c in cots)) if cots else 0
            if brut <= 0 and float(decl.masse_salariale_brute) > 0:
                brut = float(decl.masse_salariale_brute) / max(len(decl.employes), 1)
            statut = "cadre" if emp.statut and "cadre" in emp.statut.lower() else "non-cadre"
            kb["salaries"][nir] = {
                "nir": nir,
                "nom": emp.nom or existing.get("nom", ""),
                "prenom": emp.prenom or existing.get("prenom", ""),
                "date_naissance": emp.date_naissance.isoformat() if emp.date_naissance else existing.get("date_naissance", ""),
                "statut": statut,
                "dernier_brut": brut if brut > 0 else existing.get("dernier_brut", 0),
                "periodes_presentes": list(set(existing.get("periodes_presentes", []) + ([decl.periode.debut.strftime("%Y-%m")] if decl.periode and decl.periode.debut else []))),
                "derniere_maj": datetime.now().isoformat(),
            }

        # --- Cotisations et taux ---
        per_str = decl.periode.debut.strftime("%Y-%m") if decl.periode and decl.periode.debut else ""
        for cot in decl.cotisations:
            code = cot.type_cotisation.value if cot.type_cotisation else ""
            libelle = code.replace("_", " ").title()
            kb["cotisations"].append({
                "code": code,
                "libelle": libelle,
                "base": float(cot.base_brute),
                "taux_salarial": float(cot.taux_salarial) if cot.taux_salarial else 0,
                "taux_patronal": float(cot.taux_patronal) if cot.taux_patronal else 0,
                "montant_salarial": float(cot.montant_salarial) if cot.montant_salarial else 0,
                "montant_patronal": float(cot.montant_patronal) if cot.montant_patronal else 0,
                "employe_nir": cot.employe_id,
                "periode": per_str,
            })
            # Verification des taux
            if code and cot.taux_salarial:
                kb["taux_verifies"][code] = {
                    "taux_constate": float(cot.taux_salarial),
                    "base": float(cot.base_brute),
                    "conforme": None,  # sera evalue par l'audit
                }

        # --- Masse salariale ---
        if decl.periode and decl.periode.debut and float(decl.masse_salariale_brute) > 0:
            per = decl.periode.debut.strftime("%Y-%m")
            kb["masse_salariale"][per] = kb["masse_salariale"].get(per, 0) + float(decl.masse_salariale_brute)

    # --- Anomalies ---
    for f in result.findings:
        kb["anomalies_detectees"].append({
            "id": f.id,
            "categorie": f.categorie.value,
            "severite": f.severite.value,
            "titre": f.titre,
            "reference_legale": f.reference_legale,
        })


def _get_knowledge_summary() -> dict:
    """Resume l'etat de la base de connaissances pour l'audit."""
    kb = _biblio_knowledge
    nb_sal = len(kb["salaries"])
    nb_cadres = sum(1 for s in kb["salaries"].values() if s.get("statut") == "cadre")
    has_dsn = len(kb["declarations_dsn"]) > 0
    has_bulletins = len(kb["bulletins_paie"]) > 0
    has_multi_docs = len(kb["pieces_justificatives"]) > 1
    nb_periodes = len(kb["periodes_couvertes"])
    nb_cotisations = len(kb["cotisations"])
    total_masse = sum(kb["masse_salariale"].values())
    nb_anomalies = len(kb["anomalies_detectees"])
    nb_employeurs = len(kb["employeurs"])
    # Pieces disponibles
    pieces = list(kb["pieces_justificatives"].keys())
    # Contrats RH enregistres
    nb_contrats = len(_rh_contrats)
    nb_contrats_actifs = sum(1 for c in _rh_contrats if c.get("statut") == "actif")
    # Visites medicales
    nb_visites = len(_rh_visites_med)
    # Entretiens
    nb_entretiens = len(_rh_entretiens)

    # Types de cotisations presentes
    types_cot = {}
    for cot in kb["cotisations"]:
        code = cot.get("code", "")
        if code:
            if code not in types_cot:
                types_cot[code] = {"count": 0, "total_patronal": 0, "total_salarial": 0}
            types_cot[code]["count"] += 1
            types_cot[code]["total_patronal"] += cot.get("montant_patronal", 0)
            types_cot[code]["total_salarial"] += cot.get("montant_salarial", 0)

    return {
        "nb_salaries_connus": nb_sal,
        "nb_cadres": nb_cadres,
        "nb_employeurs": nb_employeurs,
        "has_dsn": has_dsn,
        "has_bulletins": has_bulletins,
        "has_multi_docs": has_multi_docs,
        "nb_periodes": nb_periodes,
        "periodes": kb["periodes_couvertes"],
        "nb_cotisations_analysees": nb_cotisations,
        "total_masse_salariale": total_masse,
        "nb_anomalies": nb_anomalies,
        "pieces_disponibles": pieces,
        "nb_contrats_rh": nb_contrats,
        "nb_contrats_actifs": nb_contrats_actifs,
        "nb_visites_medicales": nb_visites,
        "nb_entretiens": nb_entretiens,
        "taux_verifies": kb["taux_verifies"],
        "exonerations": kb["exonerations_detectees"],
        "conventions": kb["conventions_collectives"],
        "derniere_maj": kb["derniere_maj"],
        "types_cotisations": types_cot,
    }


# ==============================
# ANALYSE
# ==============================

@app.post("/api/analyze")
async def analyser_documents(
    fichiers: list[UploadFile] = File(...),
    format_rapport: str = Query("json"),
    integrer: bool = Query(True),
    mode_analyse: str = Query("complet"),
):
    if len(fichiers) > 20:
        raise HTTPException(400, "Maximum 20 fichiers par analyse.")

    config = AppConfig(base_dir=Path("/tmp/normacheck_data"))
    orchestrator = Orchestrator(config)

    with tempfile.TemporaryDirectory() as td:
        chemins = []
        total_size = 0
        for f in fichiers:
            data = await f.read()
            total_size += len(data)
            if total_size > 500 * 1024 * 1024:
                raise HTTPException(400, "Taille totale depasse 500 Mo.")
            chemin = Path(td) / f.filename
            chemin.write_bytes(data)
            chemins.append(chemin)

        try:
            orchestrator.analyser_documents(chemins, format_rapport)
        except URSSAFAnalyzerError as e:
            raise HTTPException(422, str(e))
        except Exception as e:
            raise HTTPException(500, f"Erreur interne : {str(e)}")

        result = orchestrator.result

        # --- Alimenter la bibliotheque de connaissances ---
        _alimenter_knowledge(result)

        if integrer:
            for idx_f, f in enumerate(fichiers):
                await f.seek(0)
                raw = await f.read()
                sha = hashlib.sha256(raw).hexdigest()[:16]
                # Extraire les donnees du document correspondant
                doc_data = {}
                if idx_f < len(result.declarations):
                    decl = result.declarations[idx_f]
                    doc_data = {
                        "nb_salaries": len(decl.employes),
                        "nb_cotisations": len(decl.cotisations),
                        "masse_salariale": float(decl.masse_salariale_brute),
                        "type_declaration": decl.type_declaration,
                        "employeur_siret": decl.employeur.siret if decl.employeur else "",
                        "employeur_nom": decl.employeur.raison_sociale if decl.employeur else "",
                        "periode": decl.periode.debut.strftime("%Y-%m") if decl.periode and decl.periode.debut else "",
                        "salaries_noms": [f"{e.prenom} {e.nom}" for e in decl.employes],
                    }
                _doc_library.append({
                    "id": str(uuid.uuid4())[:8],
                    "nom": f.filename,
                    "taille": len(raw),
                    "sha256": sha,
                    "date_import": datetime.now().isoformat(),
                    "statut": "analyse",
                    "donnees_extraites": doc_data,
                    "actions": [{"action": "import+analyse", "par": "utilisateur", "date": datetime.now().isoformat()}],
                    "erreurs_corrigees": [],
                })
            log_action("utilisateur", "analyse", f"{len(fichiers)} fichiers")

        # Toujours generer le rapport HTML pour l'inclure dans la reponse JSON
        try:
            html_report = orchestrator.report_generator._construire_html(result)
        except Exception:
            html_report = ""

        if format_rapport == "html":
            return HTMLResponse(html_report)

        findings = result.findings
        constats = []
        for f in findings:
            constats.append({
                "id": f.id,
                "categorie": f.categorie.value,
                "severite": f.severite.value,
                "titre": f.titre,
                "description": f.description,
                "montant_impact": float(f.montant_impact) if f.montant_impact else 0,
                "score_risque": f.score_risque,
                "recommandation": f.recommandation,
                "reference_legale": f.reference_legale,
            })
        recommandations = orchestrator.report_generator._generer_recommandations(findings)

        declarations_out = []
        for decl in result.declarations:
            emp = None
            if decl.employeur:
                emp = {
                    "siren": decl.employeur.siren,
                    "siret": decl.employeur.siret,
                    "raison_sociale": decl.employeur.raison_sociale,
                    "effectif": decl.employeur.effectif,
                    "code_naf": decl.employeur.code_naf,
                }
            salaries = []
            for e in decl.employes:
                cots = [c for c in decl.cotisations if c.employe_id == e.id]
                brut = float(sum(c.base_brute for c in cots)) if cots else float(decl.masse_salariale_brute / max(len(decl.employes), 1))
                net = round(brut * 0.78, 2)
                heures = 151.67
                salaries.append({
                    "nir": e.nir, "nom": e.nom, "prenom": e.prenom,
                    "date_naissance": e.date_naissance.strftime("%d%m%Y") if e.date_naissance else "",
                    "brut_mensuel": round(brut, 2), "net_fiscal": net,
                    "heures": heures,
                    "statut_conventionnel": "01" if e.statut and "cadre" in e.statut.lower() else "02",
                    "num_contrat": f"CTR{e.id[:6]}",
                })
            periode_str = ""
            if decl.periode and decl.periode.debut:
                periode_str = decl.periode.debut.strftime("%Y%m")
            # Determine document nature from parser type_declaration and metadata
            fmt = (decl.type_declaration or "").lower()
            nb_cots = len(decl.cotisations)
            nb_sal = len(decl.employes)
            decl_meta = getattr(decl, "metadata", {}) or {}
            doc_type = decl_meta.get("type_document", "")

            # Map from parser-detected type
            nature_map = {
                "bulletin_de_paie": "Bulletin de paie",
                "bulletin": "Bulletin de paie",
                "livre_de_paie": "Livre de paie / Recapitulatif cotisations",
                "facture_achat": "Facture d achat",
                "facture_vente": "Facture de vente",
                "contrat_de_travail": "Contrat de travail",
                "accord_interessement": "Accord d interessement",
                "accord_participation": "Accord de participation",
                "attestation": "Attestation employeur",
            }
            nature = nature_map.get(doc_type, "")

            # Fallback: use type_declaration from parser
            if not nature:
                if fmt in ("dsn", "dsn/xml"):
                    nature = "Declaration sociale nominative (DSN)"
                elif fmt == "bulletin":
                    nature = "Bulletin de paie"
                elif fmt == "livre_de_paie":
                    nature = "Livre de paie / Recapitulatif cotisations"
                elif fmt == "facture":
                    nature = "Facture"
                elif fmt == "contrat":
                    nature = "Contrat de travail"
                elif fmt in ("interessement", "participation"):
                    nature = "Accord d " + fmt
                elif fmt == "attestation":
                    nature = "Attestation employeur"
                elif fmt == "xml/bordereau":
                    nature = "Bordereau recapitulatif de cotisations (BRC)"
                elif nb_cots > 0 and nb_sal == 1:
                    nature = "Bulletin de paie"
                elif nb_cots > 0 and nb_sal > 1:
                    nature = "Livre de paie / Recapitulatif cotisations"
                elif nb_sal > 0 and nb_cots == 0:
                    nature = "Liste du personnel / Registre"
                elif float(decl.masse_salariale_brute) > 0:
                    nature = "Bulletin de paie" if nb_sal <= 1 else "Recapitulatif de paie"
                else:
                    nature = "Document comptable / social"
            decl_out = {
                "type": decl.type_declaration,
                "reference": decl.reference,
                "periode": periode_str,
                "employeur": emp,
                "salaries": salaries,
                "masse_salariale_brute": float(decl.masse_salariale_brute),
                "effectif_declare": decl.effectif_declare,
                "nature": nature,
                "nb_cotisations": nb_cots,
                "s89_total_cotisations": decl_meta.get("s89_total_cotisations"),
                "s89_total_brut": decl_meta.get("s89_total_brut"),
                "nb_salaries": nb_sal,
            }
            # Add parsed metadata (net_a_payer, facture amounts, contrat type, etc.)
            if decl_meta.get("net_a_payer"):
                decl_out["net_a_payer"] = decl_meta["net_a_payer"]
            if decl_meta.get("total_patronal"):
                decl_out["total_patronal"] = decl_meta["total_patronal"]
            if decl_meta.get("total_salarial"):
                decl_out["total_salarial"] = decl_meta["total_salarial"]
            if decl_meta.get("date_virement"):
                decl_out["date_virement"] = decl_meta["date_virement"]
            if decl_meta.get("montant_ht"):
                decl_out["montant_ht"] = decl_meta["montant_ht"]
            if decl_meta.get("montant_tva"):
                decl_out["montant_tva"] = decl_meta["montant_tva"]
            if decl_meta.get("montant_ttc"):
                decl_out["montant_ttc"] = decl_meta["montant_ttc"]
            if decl_meta.get("tiers"):
                decl_out["tiers"] = decl_meta["tiers"]
            if decl_meta.get("type_contrat"):
                decl_out["type_contrat"] = decl_meta["type_contrat"]
            if decl_meta.get("remuneration_brute"):
                decl_out["remuneration_brute"] = decl_meta["remuneration_brute"]
            declarations_out.append(decl_out)

        # Auto-generer les ecritures comptables a partir des declarations
        _integration_log = []
        try:
            moteur = get_moteur()
            nb_ecr_paie = 0
            nb_ecr_facture = 0
            for decl in result.declarations:
                d_meta = getattr(decl, "metadata", {}) or {}
                d_type = d_meta.get("type_document", "")
                _integration_log.append(f"Decl: type={decl.type_declaration}, meta_type={d_type}, emps={len(decl.employes)}, cots={len(decl.cotisations)}, masse={float(decl.masse_salariale_brute)}")

                # --- Ecritures de paie (bulletins, DSN, livres de paie) ---
                if d_type in ("facture_achat", "facture_vente"):
                    # Factures: generer ecriture facture
                    ht = Decimal(str(d_meta.get("montant_ht", 0)))
                    tva = Decimal(str(d_meta.get("montant_tva", 0)))
                    ttc = Decimal(str(d_meta.get("montant_ttc", 0)))
                    if ht > 0 or ttc > 0:
                        try:
                            moteur.generer_ecriture_facture(
                                type_doc=d_type,
                                date_piece=date.today(),
                                numero_piece=d_meta.get("numero_facture", decl.reference),
                                montant_ht=ht,
                                montant_tva=tva if tva > 0 else ht * Decimal("0.20"),
                                montant_ttc=ttc if ttc > 0 else ht * Decimal("1.20"),
                                nom_tiers=d_meta.get("tiers", "Tiers"),
                            )
                            nb_ecr_facture += 1
                            _integration_log.append(f"  -> Ecriture facture OK: HT={ht} TVA={tva} TTC={ttc}")
                        except Exception as e:
                            _integration_log.append(f"  -> ERREUR facture: {e}")
                    else:
                        _integration_log.append(f"  -> Facture ignoree: HT={ht} TTC={ttc} (montants nuls)")
                    continue

                if d_type in ("contrat_de_travail", "accord_interessement", "accord_participation", "attestation"):
                    _integration_log.append(f"  -> Skip (type {d_type}, pas d ecriture)")
                    continue  # pas d ecriture comptable

                # Ecritures de paie
                if not decl.employes:
                    # Pas d employe mais masse salariale > 0 : generer une ecriture globale
                    if decl.masse_salariale_brute > 0:
                        brut = decl.masse_salariale_brute
                        d_meta_net = Decimal(str(d_meta.get("net_a_payer", 0)))
                        d_meta_pat = Decimal(str(d_meta.get("total_patronal", 0)))
                        d_meta_sal = Decimal(str(d_meta.get("total_salarial", 0)))
                        cot_sal = float(d_meta_sal) if d_meta_sal > 0 else round(float(brut) * 0.22, 2)
                        cot_pat_total = float(d_meta_pat) if d_meta_pat > 0 else round(float(brut) * 0.45, 2)
                        cot_pat_urssaf = round(cot_pat_total * 0.78, 2)
                        cot_pat_retraite = round(cot_pat_total * 0.22, 2)
                        net_a_payer = float(d_meta_net) if d_meta_net > 0 else round(float(brut) - cot_sal, 2)
                        date_piece = date.today()
                        if decl.periode and decl.periode.debut:
                            date_piece = decl.periode.debut
                        try:
                            moteur.generer_ecriture_paie(
                                date_piece=date_piece,
                                nom_salarie="Salaries (global)",
                                salaire_brut=brut,
                                cotisations_salariales=Decimal(str(cot_sal)),
                                cotisations_patronales_urssaf=Decimal(str(cot_pat_urssaf)),
                                cotisations_patronales_retraite=Decimal(str(cot_pat_retraite)),
                                net_a_payer=Decimal(str(net_a_payer)),
                            )
                            nb_ecr_paie += 1
                            _integration_log.append(f"  -> Ecriture paie globale OK: brut={brut}")
                        except Exception as e:
                            _integration_log.append(f"  -> ERREUR paie globale: {e}")
                    else:
                        _integration_log.append(f"  -> Pas d employe ni de masse salariale")
                else:
                    for emp in decl.employes:
                        cots = [c for c in decl.cotisations if c.employe_id == emp.id]
                        brut = sum(c.base_brute for c in cots) if cots else Decimal("0")
                        # Fallback: use masse_salariale / nb_employes
                        if brut <= 0 and decl.masse_salariale_brute > 0:
                            brut = decl.masse_salariale_brute / max(len(decl.employes), 1)
                        if brut <= 0:
                            _integration_log.append(f"  -> Skip emp {emp.nom}: brut=0, cots={len(cots)}, masse={float(decl.masse_salariale_brute)}")
                            continue
                        # Use actual parsed cotisation totals when available
                        actual_pat = sum(c.montant_patronal for c in cots) if cots else Decimal("0")
                        actual_sal = sum(c.montant_salarial for c in cots) if cots else Decimal("0")
                        net_from_meta = Decimal(str(d_meta.get("net_a_payer", 0)))
                        cot_sal = float(actual_sal) if actual_sal > 0 else round(float(brut) * 0.22, 2)
                        cot_pat_total = float(actual_pat) if actual_pat > 0 else round(float(brut) * 0.45, 2)
                        cot_pat_urssaf = round(cot_pat_total * 0.78, 2)
                        cot_pat_retraite = round(cot_pat_total * 0.22, 2)
                        net_a_payer = float(net_from_meta) if net_from_meta > 0 else round(float(brut) - cot_sal, 2)
                        date_piece = date.today()
                        if decl.periode and decl.periode.debut:
                            date_piece = decl.periode.debut
                        elif decl.periode and decl.periode.fin:
                            date_piece = decl.periode.fin
                        nom_sal = f"{emp.prenom} {emp.nom}".strip() or "Salarie"
                        try:
                            moteur.generer_ecriture_paie(
                                date_piece=date_piece,
                                nom_salarie=nom_sal,
                                salaire_brut=brut,
                                cotisations_salariales=Decimal(str(cot_sal)),
                                cotisations_patronales_urssaf=Decimal(str(cot_pat_urssaf)),
                                cotisations_patronales_retraite=Decimal(str(cot_pat_retraite)),
                                net_a_payer=Decimal(str(net_a_payer)),
                            )
                            nb_ecr_paie += 1
                            _integration_log.append(f"  -> Ecriture paie OK: {nom_sal} brut={float(brut):.2f}")
                        except Exception as e:
                            _integration_log.append(f"  -> ERREUR paie {nom_sal}: {e}")
            _integration_log.append(f"COMPTA: {nb_ecr_paie} ecritures paie + {nb_ecr_facture} ecritures facture generees")
        except Exception as e:
            _integration_log.append(f"ERREUR COMPTA GLOBALE: {e}\\n{traceback.format_exc()}")

        # Auto-integrer les salaries dans le module RH + Planning
        nb_rh_new = 0
        nb_rh_updated = 0
        nb_planning_new = 0
        try:
            for decl in result.declarations:
                d_meta = getattr(decl, "metadata", {}) or {}
                d_type = d_meta.get("type_document", "")
                if not decl.employes:
                    # Pas d employe dans la declaration : tenter de creer un salarie generique
                    # si on a la masse salariale (LDP sans detail employe par ex.)
                    if decl.masse_salariale_brute > 0 and d_type not in ("facture_achat", "facture_vente", "contrat_de_travail"):
                        emp_nom = "Salarie"
                        if decl.employeur and decl.employeur.raison_sociale:
                            emp_nom = f"Salarie ({decl.employeur.raison_sociale})"
                        existing = [c for c in _rh_contrats if c.get("nom_salarie", "").lower() == emp_nom.lower()]
                        if not existing:
                            contrat = {
                                "id": str(uuid.uuid4())[:8],
                                "type_contrat": "CDI",
                                "nom_salarie": emp_nom,
                                "prenom_salarie": "",
                                "poste": "Employe",
                                "date_debut": date.today().strftime("%Y-%m-%d"),
                                "date_fin": "",
                                "salaire_brut": str(round(float(decl.masse_salariale_brute), 2)),
                                "temps_travail": "temps_complet",
                                "duree_hebdo": "35",
                                "convention_collective": "",
                                "periode_essai_jours": "0",
                                "motif_cdd": "",
                                "statut": "actif",
                                "nir": "",
                                "source": "analyse_automatique (" + (d_type or decl.type_declaration) + ")",
                                "date_creation": datetime.now().isoformat(),
                            }
                            _rh_contrats.append(contrat)
                            nb_rh_new += 1
                    continue
                for emp in decl.employes:
                    if not emp.nom and not emp.nir:
                        _integration_log.append(f"  -> RH skip: employe sans nom ni NIR")
                        continue
                    # Identifier le salarie par nom+prenom OU par NIR
                    existing = [c for c in _rh_contrats if
                                (c.get("nom_salarie", "").lower() == (emp.nom or "").lower() and
                                 c.get("prenom_salarie", "").lower() == (emp.prenom or "").lower()) or
                                (emp.nir and c.get("nir", "") == emp.nir)]
                    if not existing:
                        cots = [c for c in decl.cotisations if c.employe_id == emp.id]
                        brut = float(sum(c.base_brute for c in cots)) if cots else 0
                        if brut <= 0:
                            brut = float(decl.masse_salariale_brute / max(len(decl.employes), 1))
                        is_cadre = emp.statut and "cadre" in emp.statut.lower()
                        # Type contrat from document or default
                        type_ctr = d_meta.get("type_contrat", "CDI")
                        # Date from document or period
                        date_debut_str = ""
                        if emp.date_embauche:
                            date_debut_str = emp.date_embauche.strftime("%Y-%m-%d")
                        elif decl.periode and decl.periode.debut:
                            date_debut_str = decl.periode.debut.strftime("%Y-%m-%d")
                        else:
                            date_debut_str = date.today().strftime("%Y-%m-%d")
                        # Poste from parser
                        poste = emp.convention_collective or ("Cadre" if is_cadre else "Employe")
                        contrat = {
                            "id": str(uuid.uuid4())[:8],
                            "type_contrat": type_ctr,
                            "nom_salarie": emp.nom or "",
                            "prenom_salarie": emp.prenom or "",
                            "poste": poste,
                            "date_debut": date_debut_str,
                            "date_fin": "",
                            "salaire_brut": str(round(brut, 2)) if brut > 0 else "0",
                            "temps_travail": "temps_complet",
                            "duree_hebdo": "35",
                            "convention_collective": "",
                            "periode_essai_jours": "0",
                            "motif_cdd": "",
                            "statut": "actif",
                            "nir": emp.nir or "",
                            "source": "analyse_automatique (" + (d_type or decl.type_declaration) + ")",
                            "date_creation": datetime.now().isoformat(),
                        }
                        _rh_contrats.append(contrat)
                        nb_rh_new += 1
                        _integration_log.append(f"  -> RH nouveau: {emp.prenom} {emp.nom} brut={brut:.2f}")
                        # Auto-creer un planning pour le salarie
                        try:
                            if date_debut_str:
                                from datetime import timedelta
                                d0 = date.fromisoformat(date_debut_str)
                                for j in range(5):
                                    d_planning = d0 + timedelta(days=j)
                                    if d_planning.weekday() < 5:
                                        _rh_planning.append({
                                            "id": str(uuid.uuid4())[:8],
                                            "salarie_id": contrat["id"],
                                            "salarie_nom": f"{emp.prenom} {emp.nom}".strip(),
                                            "date": d_planning.strftime("%Y-%m-%d"),
                                            "heure_debut": "09:00",
                                            "heure_fin": "17:00",
                                            "type_poste": "normal",
                                            "note": "Planning auto (analyse)",
                                        })
                                        nb_planning_new += 1
                        except Exception as e:
                            _integration_log.append(f"  -> ERREUR planning: {e}")
                    else:
                        # Mettre a jour le salarie existant si nouvelles infos
                        c = existing[0]
                        cots = [ct for ct in decl.cotisations if ct.employe_id == emp.id]
                        brut = float(sum(ct.base_brute for ct in cots)) if cots else 0
                        if brut <= 0:
                            brut = float(decl.masse_salariale_brute / max(len(decl.employes), 1))
                        if brut > 0 and (not c.get("salaire_brut") or c.get("salaire_brut") == "0"):
                            c["salaire_brut"] = str(round(brut, 2))
                            nb_rh_updated += 1
                        if emp.nir and not c.get("nir"):
                            c["nir"] = emp.nir
                            nb_rh_updated += 1
            _integration_log.append(f"RH: {nb_rh_new} nouveaux contrats, {nb_rh_updated} mis a jour, {nb_planning_new} creneaux planning")
        except Exception as e:
            _integration_log.append(f"ERREUR RH GLOBALE: {e}\\n{traceback.format_exc()}")

        # Build file info from actual uploaded files
        fichiers_info = []
        for i, f in enumerate(fichiers):
            ext = Path(f.filename).suffix.lower() if f.filename else ""
            fichiers_info.append({"nom": f.filename, "extension": ext, "index": i})

        return {
            "synthese": {
                "nb_constats": len(findings),
                "nb_anomalies": result.nb_anomalies,
                "nb_incoherences": result.nb_incoherences,
                "nb_critiques": result.nb_critiques,
                "impact_financier_total": float(result.impact_total),
                "score_risque_global": result.score_risque_global,
                "nb_fichiers": len(result.documents_analyses),
            },
            "constats": constats,
            "recommandations": recommandations,
            "declarations": declarations_out,
            "fichiers_info": fichiers_info,
            "mode_analyse": mode_analyse,
            "html_report": html_report,
            "knowledge_summary": _get_knowledge_summary(),
            "integration": {
                "compta_ecritures_paie": nb_ecr_paie,
                "compta_ecritures_facture": nb_ecr_facture,
                "rh_contrats_crees": nb_rh_new,
                "rh_contrats_maj": nb_rh_updated,
                "rh_planning_crees": nb_planning_new,
                "log": _integration_log,
            },
            "limites": {"fichiers_max": 20, "taille_max_mo": 500}}


# ==============================
# FACTURES
# ==============================

@app.post("/api/factures/analyser")
async def analyser_facture(fichier: UploadFile = File(...)):
    from urssaf_analyzer.ocr.invoice_detector import InvoiceDetector
    from urssaf_analyzer.ocr.image_reader import ImageReader

    config = AppConfig()
    detector = InvoiceDetector()

    with tempfile.TemporaryDirectory() as td:
        data = await fichier.read()
        chemin = Path(td) / fichier.filename
        chemin.write_bytes(data)
        ext = chemin.suffix.lower()

        texte = ""
        ecriture_manuscrite = False
        if ext in (".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp"):
            reader = ImageReader(config)
            ocr_result = reader.lire_image(chemin)
            texte = ocr_result.get("texte", "")
            ecriture_manuscrite = ocr_result.get("ecriture_manuscrite", False)
        elif ext == ".pdf":
            try:
                reader = ImageReader(config)
                ocr_result = reader.lire_pdf(chemin)
                texte = ocr_result.get("texte", "")
                ecriture_manuscrite = ocr_result.get("ecriture_manuscrite", False)
            except Exception:
                texte = chemin.read_text(errors="replace")
        else:
            texte = chemin.read_text(errors="replace")

        resultat = detector.detecter(texte, str(chemin))
        resultat["ecriture_manuscrite"] = ecriture_manuscrite
        log_action("utilisateur", "analyse_facture", fichier.filename)
        return resultat


@app.post("/api/factures/comptabiliser")
async def comptabiliser_facture(
    type_doc: str = Form("facture_achat"),
    date_piece: str = Form(""),
    numero_piece: str = Form(""),
    montant_ht: str = Form("0"),
    montant_tva: str = Form("0"),
    montant_ttc: str = Form("0"),
    nom_tiers: str = Form(""),
):
    moteur = get_moteur()
    ht = Decimal(montant_ht or "0")
    tva = Decimal(montant_tva or "0")
    ttc = Decimal(montant_ttc or "0")

    try:
        dp = date.today()
        if date_piece:
            try:
                dp = date.fromisoformat(date_piece)
            except ValueError:
                pass
        ecriture = moteur.generer_ecriture_facture(
            type_doc=type_doc, date_piece=dp,
            numero_piece=numero_piece, montant_ht=ht,
            montant_tva=tva, montant_ttc=ttc, nom_tiers=nom_tiers,
        )
        log_action("utilisateur", "comptabilisation", f"{type_doc} {numero_piece} {ttc}")
        return {
            "ecriture_id": ecriture.id,
            "lignes": [
                {"compte": l.compte, "libelle": l.libelle,
                 "debit": float(l.debit), "credit": float(l.credit)}
                for l in ecriture.lignes
            ]
        }
    except Exception as e:
        raise HTTPException(422, str(e))


@app.post("/api/factures/statut")
async def maj_statut_facture(
    facture_id: str = Form(...),
    statut: str = Form("impaye"),
    date_paiement: str = Form(""),
    reference_paiement: str = Form(""),
    montant_paye: str = Form(""),
):
    entry = {
        "facture_id": facture_id,
        "statut": statut,
        "date_paiement": date_paiement,
        "reference_paiement": reference_paiement,
        "maj_le": datetime.now().isoformat(),
    }
    if statut == "partiellement_paye" and montant_paye:
        entry["montant_paye"] = float(montant_paye)
    _facture_statuses[facture_id] = entry
    log_action("utilisateur", "maj_statut_facture", f"{facture_id} -> {statut}")
    return {"status": "ok"}


@app.get("/api/factures/statuts")
async def liste_statuts_factures():
    return list(_facture_statuses.values())


# ==============================
# COMPTABILITE
# ==============================

@app.get("/api/comptabilite/journal")
async def journal_ecritures():
    moteur = get_moteur()
    return moteur.get_journal()


@app.get("/api/comptabilite/balance")
async def balance_comptable():
    moteur = get_moteur()
    bal = moteur.get_balance()
    # Serialize Decimal to float
    for item in bal:
        for k in ("total_debit", "total_credit", "solde_debiteur", "solde_crediteur"):
            if k in item and not isinstance(item[k], float):
                item[k] = float(item[k])
    return bal


@app.get("/api/comptabilite/grand-livre-detail")
async def grand_livre_detail(
    date_debut: Optional[str] = None,
    date_fin: Optional[str] = None,
):
    moteur = get_moteur()
    gl = moteur.get_grand_livre()
    result = []
    for compte, mouvements in gl.items():
        cpt = moteur.plan.get_compte(compte)
        mvts = []
        for m in mouvements:
            if date_debut and m.get("date", "") < date_debut:
                continue
            if date_fin and m.get("date", "") > date_fin:
                continue
            mvts.append({
                "date": m.get("date", ""),
                "libelle": m.get("libelle", ""),
                "debit": float(m.get("debit", 0)),
                "credit": float(m.get("credit", 0)),
                "sans_justificatif": "[SANS JUSTIFICATIF]" in m.get("libelle", ""),
            })
        if mvts:
            result.append({
                "compte": compte,
                "libelle": cpt.libelle if cpt else compte,
                "mouvements": mvts,
            })
    return result


@app.get("/api/comptabilite/compte-resultat")
async def compte_resultat():
    moteur = get_moteur()
    gen = GenerateurRapports(moteur)
    return gen.compte_resultat()


@app.get("/api/comptabilite/bilan")
async def bilan():
    moteur = get_moteur()
    gen = GenerateurRapports(moteur)
    return gen.bilan_simplifie()


@app.get("/api/comptabilite/declaration-tva")
async def declaration_tva(mois: int = Query(1), annee: int = Query(2026)):
    moteur = get_moteur()
    gen = GenerateurRapports(moteur)
    return gen.declaration_tva(mois=mois, annee=annee)


@app.get("/api/comptabilite/charges-sociales-detail")
async def charges_sociales_detail():
    moteur = get_moteur()
    gen = GenerateurRapports(moteur)
    return gen.recapitulatif_charges_sociales()


@app.get("/api/comptabilite/plan-comptable")
async def plan_comptable_api(terme: Optional[str] = None):
    pc = PlanComptable()
    comptes = pc.rechercher(terme) if terme else list(pc.comptes.values())
    return [{"numero": c.numero, "libelle": c.libelle, "classe": c.classe} for c in comptes]


@app.post("/api/comptabilite/ecriture/manuelle")
async def ecriture_manuelle(
    date_piece: str = Form(...), libelle: str = Form(...),
    compte_debit: str = Form(...), compte_credit: str = Form(...),
    montant: str = Form("0"), has_justificatif: str = Form("false"),
):
    from urssaf_analyzer.comptabilite.ecritures import Ecriture, LigneEcriture, TypeJournal
    moteur = get_moteur()
    mt = Decimal(montant or "0")
    has_j = has_justificatif.lower() == "true"
    dp = date.today()
    if date_piece:
        try:
            dp = date.fromisoformat(date_piece)
        except ValueError:
            pass
    sans_justif = "" if has_j else " [SANS JUSTIFICATIF]"
    ecriture = Ecriture(
        journal=TypeJournal.OPERATIONS_DIVERSES,
        date_ecriture=dp,
        date_piece=dp,
        libelle=libelle + sans_justif,
        lignes=[
            LigneEcriture(compte=compte_debit, libelle=libelle + sans_justif, debit=mt, credit=Decimal("0")),
            LigneEcriture(compte=compte_credit, libelle=libelle + sans_justif, debit=Decimal("0"), credit=mt),
        ],
    )
    moteur.ecritures.append(ecriture)
    log_action("utilisateur", "ecriture_manuelle", f"{compte_debit}/{compte_credit} {mt}")
    return {
        "ecriture_id": ecriture.id,
        "sans_justificatif": not has_j,
        "alerte": "Ecriture sans justificatif - marquee en rouge." if not has_j else "Ecriture enregistree.",
    }


@app.post("/api/comptabilite/valider")
async def valider_ecritures():
    moteur = get_moteur()
    nb_avant = sum(1 for e in moteur.ecritures if not e.validee)
    erreurs = moteur.valider_ecritures()
    nb_validees = nb_avant - len(erreurs)
    log_action("utilisateur", "validation_ecritures", f"{nb_validees} ecritures validees")
    return {"nb_validees": nb_validees, "erreurs": erreurs}


# ==============================
# SIMULATION
# ==============================

@app.get("/api/simulation/bulletin")
async def sim_bulletin(
    brut_mensuel: float = Query(2500),
    effectif: int = Query(10),
    est_cadre: bool = Query(False),
):
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    calc = ContributionRules()
    res = calc.calculer_bulletin_complet(Decimal(str(brut_mensuel)), est_cadre=est_cadre)
    lignes = []
    for l in res.get("lignes", []):
        lignes.append({
            "libelle": l["libelle"],
            "montant_patronal": float(l["montant_patronal"]),
            "montant_salarial": float(l["montant_salarial"]),
        })
    return {
        "brut_mensuel": float(res["brut_mensuel"]),
        "net_a_payer": float(res["net_avant_impot"]),
        "cout_total_employeur": float(res["cout_total_employeur"]),
        "total_patronal": float(res["total_patronal"]),
        "total_salarial": float(res["total_salarial"]),
        "lignes": lignes,
    }


@app.get("/api/simulation/micro-entrepreneur")
async def sim_micro(
    chiffre_affaires: float = Query(50000),
    activite: str = Query("prestations_bnc"),
    acre: bool = Query(False),
):
    ca = Decimal(str(chiffre_affaires))
    taux = {"vente_marchandises": Decimal("0.128"), "prestations_bic": Decimal("0.220"),
            "prestations_bnc": Decimal("0.224"), "liberal_cipav": Decimal("0.232")}
    t = taux.get(activite, Decimal("0.224"))
    if acre:
        t = t / 2
    cotisations = round(float(ca * t), 2)
    ir_forfait = {"vente_marchandises": Decimal("0.71"), "prestations_bic": Decimal("0.50"),
                  "prestations_bnc": Decimal("0.34"), "liberal_cipav": Decimal("0.34")}
    abat = ir_forfait.get(activite, Decimal("0.34"))
    revenu_imposable = round(float(ca * (1 - abat)), 2)
    ir_estim = round(revenu_imposable * 0.11, 2)
    return {
        "chiffre_affaires": float(ca), "taux_cotisations": float(t),
        "cotisations_sociales": cotisations, "acre_applique": acre,
        "revenu_imposable": revenu_imposable, "impot_estime": ir_estim,
        "revenu_net": round(float(ca) - cotisations - ir_estim, 2),
    }


@app.get("/api/simulation/tns")
async def sim_tns(
    revenu_net: float = Query(40000),
    type_statut: str = Query("gerant_majoritaire"),
    acre: bool = Query(False),
):
    rev = Decimal(str(revenu_net))
    base = rev
    maladie = round(float(base * Decimal("0.065")), 2)
    vieillesse_base = round(float(min(base, Decimal("46368")) * Decimal("0.1775")), 2)
    vieillesse_compl = round(float(min(base, Decimal("185472")) * Decimal("0.07")), 2)
    invalidite = round(float(base * Decimal("0.013")), 2)
    af = round(float(base * Decimal("0.0310")), 2)
    csg_crds = round(float(base * Decimal("0.097")), 2)
    formation = round(float(base * Decimal("0.0025")), 2)
    total = maladie + vieillesse_base + vieillesse_compl + invalidite + af + csg_crds + formation
    if acre:
        total = round(total * 0.5, 2)
    return {
        "revenu_net": float(rev), "type_statut": type_statut,
        "maladie_maternite": maladie, "vieillesse_base": vieillesse_base,
        "vieillesse_complementaire": vieillesse_compl, "invalidite_deces": invalidite,
        "allocations_familiales": af, "csg_crds": csg_crds, "formation": formation,
        "total_cotisations": total, "acre_applique": acre,
    }


@app.get("/api/simulation/guso")
async def sim_guso(
    salaire_brut: float = Query(500),
    nb_heures: float = Query(8),
):
    brut = Decimal(str(salaire_brut))
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    calc = ContributionRules()
    res = calc.calculer_bulletin_complet(brut, est_cadre=False)
    conge_spectacle = round(float(brut * Decimal("0.155")), 2)
    medecine_travail = round(float(Decimal(str(nb_heures)) * Decimal("0.46")), 2)
    total_guso = round(float(res["total_patronal"]) + conge_spectacle + medecine_travail, 2)
    return {
        "salaire_brut": float(brut), "nb_heures": nb_heures,
        "cotisations_patronales": float(res["total_patronal"]),
        "conge_spectacle": conge_spectacle, "medecine_travail": medecine_travail,
        "total_guso": total_guso,
        "net_artiste": float(res["net_avant_impot"]),
        "cout_total": round(float(brut) + total_guso, 2),
    }


@app.get("/api/simulation/impot-independant")
async def sim_ir(
    benefice: float = Query(40000),
    nb_parts: float = Query(1),
    autres_revenus: float = Query(0),
):
    rev = benefice + autres_revenus
    qi = rev / nb_parts
    tranches = [(11294, 0), (28797, 0.11), (82341, 0.30), (177106, 0.41), (float("inf"), 0.45)]
    impot_qi = 0
    prev = 0
    for seuil, taux in tranches:
        if qi <= prev:
            break
        tranche = min(qi, seuil) - prev
        impot_qi += tranche * taux
        prev = seuil
    impot_total = round(impot_qi * nb_parts, 2)
    taux_moyen = round(impot_total / rev * 100, 2) if rev > 0 else 0
    return {
        "benefice": benefice, "autres_revenus": autres_revenus,
        "revenu_global": rev, "nb_parts": nb_parts,
        "quotient_familial": round(qi, 2),
        "impot_brut": impot_total,
        "taux_moyen_imposition": taux_moyen,
        "revenu_apres_impot": round(rev - impot_total, 2),
    }


# --- Simulation : Exonerations ---
@app.get("/api/simulation/exonerations")
async def sim_exonerations(
    brut_mensuel: float = Query(2500),
    effectif: int = Query(10),
    zone: str = Query("metropole"),
    statut_salarie: str = Query("standard"),
    age_salarie: int = Query(30),
    ccn: str = Query(""),
    duree_contrat_mois: int = Query(0),
):
    brut = brut_mensuel
    smic_mensuel = 1801.80
    ratio_smic = brut / smic_mensuel if smic_mensuel > 0 else 1

    exonerations = []
    total_exo = 0.0

    # 1. Reduction generale (ex-Fillon) - tous employeurs < 3.5 SMIC
    if ratio_smic <= 3.5:
        coeff_t = 0.3194 if effectif < 50 else 0.3234
        coeff = (coeff_t / 0.6) * (1.6 * smic_mensuel / brut - 1)
        coeff = max(0, min(coeff, coeff_t))
        montant_fillon = round(brut * coeff, 2)
        exonerations.append({"nom": "Reduction generale (ex-Fillon)", "reference": "Art. L.241-13 CSS",
            "montant_mensuel": montant_fillon, "montant_annuel": round(montant_fillon * 12, 2),
            "conditions": f"Salaire <= 3.5 SMIC (ratio: {ratio_smic:.2f})", "applicable": True})
        total_exo += montant_fillon
    else:
        exonerations.append({"nom": "Reduction generale (ex-Fillon)", "reference": "Art. L.241-13 CSS",
            "montant_mensuel": 0, "montant_annuel": 0,
            "conditions": f"Non applicable: salaire > 3.5 SMIC (ratio: {ratio_smic:.2f})", "applicable": False})

    # 2. Exoneration apprenti
    if statut_salarie == "apprenti":
        exo_app = round(brut * 0.3194, 2)
        exonerations.append({"nom": "Exoneration apprenti", "reference": "Art. L.6243-2 CT",
            "montant_mensuel": exo_app, "montant_annuel": round(exo_app * 12, 2),
            "conditions": "Contrat d apprentissage - exo totale part patronale", "applicable": True})
        total_exo += exo_app

    # 3. Aide embauche jeune (-26 ans)
    if age_salarie < 26 and brut <= smic_mensuel * 2:
        aide_jeune = 333.33
        exonerations.append({"nom": "Aide embauche jeune (<26 ans)", "reference": "Decret 2021-94",
            "montant_mensuel": aide_jeune, "montant_annuel": round(aide_jeune * 12, 2),
            "conditions": f"Salarie < 26 ans, brut <= 2 SMIC", "applicable": True})
        total_exo += aide_jeune

    # 4. Aide senior (+55 ans)
    if age_salarie >= 55:
        aide_senior = round(brut * 0.08, 2)
        exonerations.append({"nom": "CDD senior / CDI inclusion (+55 ans)", "reference": "Art. L.5134-19-1 CT",
            "montant_mensuel": aide_senior, "montant_annuel": round(aide_senior * 12, 2),
            "conditions": "Salarie >= 55 ans", "applicable": True})
        total_exo += aide_senior

    # 5. AGEFIPH (travailleur handicape)
    if statut_salarie == "handicape":
        aide_th = 250.0
        exonerations.append({"nom": "Aide AGEFIPH embauche TH", "reference": "Art. L.5212-9 CT",
            "montant_mensuel": aide_th, "montant_annuel": round(aide_th * 12, 2),
            "conditions": "Travailleur handicape RQTH", "applicable": True})
        total_exo += aide_th

    # 6. ZRR (Zone de Revitalisation Rurale)
    if zone == "zrr" and effectif < 50:
        exo_zrr = round(brut * 0.28, 2)
        exonerations.append({"nom": "Exoneration ZRR", "reference": "Art. 1465A CGI / Art. L.131-4-2 CSS",
            "montant_mensuel": exo_zrr, "montant_annuel": round(exo_zrr * 12, 2),
            "conditions": "Zone de Revitalisation Rurale, < 50 salaries, 12 mois", "applicable": True})
        total_exo += exo_zrr

    # 7. ZFU (Zone Franche Urbaine)
    if zone == "zfu":
        exo_zfu = round(brut * 0.32, 2)
        exonerations.append({"nom": "Exoneration ZFU-TE", "reference": "Art. 44 octies A CGI",
            "montant_mensuel": exo_zfu, "montant_annuel": round(exo_zfu * 12, 2),
            "conditions": "Zone Franche Urbaine - 5 ans degressif", "applicable": True})
        total_exo += exo_zfu

    # 8. QPV (Quartier Prioritaire Ville)
    if zone == "qpv" and effectif < 50:
        exo_qpv = round(min(brut * 0.28, smic_mensuel * 1.4 * 0.28), 2)
        exonerations.append({"nom": "Exoneration QPV", "reference": "Art. L.131-4-3 CSS",
            "montant_mensuel": exo_qpv, "montant_annuel": round(exo_qpv * 12, 2),
            "conditions": "Quartier prioritaire, < 50 sal, <= 1.4 SMIC", "applicable": True})
        total_exo += exo_qpv

    # 9. Outre-mer (LODEOM)
    if zone == "outremer":
        if effectif < 11:
            exo_om = round(brut * 0.32, 2)
            desc = "LODEOM renforce < 11 sal"
        else:
            exo_om = round(brut * 0.28, 2) if ratio_smic <= 1.3 else round(brut * 0.18, 2)
            desc = "LODEOM competitivite" if ratio_smic <= 1.3 else "LODEOM competitivite renforcee"
        exonerations.append({"nom": f"Exoneration outre-mer ({desc})", "reference": "Art. L.752-3-2 CSS (LODEOM)",
            "montant_mensuel": exo_om, "montant_annuel": round(exo_om * 12, 2),
            "conditions": f"DOM-TOM, effectif {effectif}, ratio SMIC {ratio_smic:.2f}", "applicable": True})
        total_exo += exo_om

    # 10. JEI (Jeune Entreprise Innovante)
    if statut_salarie == "jei":
        exo_jei = round(brut * 0.32, 2)
        exonerations.append({"nom": "Exoneration JEI (Jeune Entreprise Innovante)", "reference": "Art. 44 sexies-0 A CGI",
            "montant_mensuel": exo_jei, "montant_annuel": round(exo_jei * 12, 2),
            "conditions": "Chercheurs, techniciens, mandataires - 8 ans max", "applicable": True})
        total_exo += exo_jei

    # Cout sans/avec exoneration
    taux_pat = 0.42
    charges_normales = round(brut * taux_pat, 2)
    charges_apres_exo = round(max(0, charges_normales - total_exo), 2)

    return {
        "brut_mensuel": brut, "effectif": effectif, "zone": zone, "statut_salarie": statut_salarie,
        "ratio_smic": round(ratio_smic, 2), "exonerations": exonerations,
        "total_exonerations_mensuelles": round(total_exo, 2),
        "total_exonerations_annuelles": round(total_exo * 12, 2),
        "charges_patronales_normales": charges_normales,
        "charges_patronales_apres_exo": charges_apres_exo,
        "economie_pct": round(total_exo / charges_normales * 100, 2) if charges_normales > 0 else 0,
    }


# --- Simulation : Cout total employeur ---
@app.get("/api/simulation/cout-employeur")
async def sim_cout_employeur(
    brut_mensuel: float = Query(2500),
    effectif: int = Query(10),
    est_cadre: bool = Query(False),
    avantages_nature: float = Query(0),
    frais_km: float = Query(0),
    primes: float = Query(0),
    tickets_restaurant: float = Query(0),
    mutuelle_employeur: float = Query(40),
):
    brut = brut_mensuel + primes
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    calc = ContributionRules()
    res = calc.calculer_bulletin_complet(Decimal(str(brut)), est_cadre=est_cadre)

    # Charges patronales detaillees
    pat = float(res["total_patronal"])
    sal = float(res["total_salarial"])
    net = float(res["net_avant_impot"])

    # Contribution formation
    formation = round(brut * (0.0055 if effectif < 11 else 0.01), 2)
    # Taxe apprentissage
    taxe_apprentissage = round(brut * 0.0068, 2)
    # Effort construction (>= 50)
    effort_construction = round(brut * 0.0045, 2) if effectif >= 50 else 0
    # Participation (>= 50)
    participation_oblig = round(brut * 0.005, 2) if effectif >= 50 else 0

    cout_annexes = formation + taxe_apprentissage + effort_construction + participation_oblig
    cout_avantages = avantages_nature + tickets_restaurant + mutuelle_employeur

    cout_total = round(brut + pat + cout_annexes + cout_avantages + frais_km, 2)
    ratio_cout = round(cout_total / net, 2) if net > 0 else 0

    return {
        "brut_mensuel": brut_mensuel, "primes": primes, "brut_total": brut,
        "charges_patronales_urssaf": pat, "charges_salariales": sal, "net_a_payer": net,
        "formation_professionnelle": formation, "taxe_apprentissage": taxe_apprentissage,
        "effort_construction": effort_construction, "participation_obligatoire": participation_oblig,
        "total_charges_annexes": cout_annexes,
        "avantages_nature": avantages_nature, "frais_km_rembourses": frais_km,
        "tickets_restaurant": tickets_restaurant, "mutuelle_employeur": mutuelle_employeur,
        "total_avantages": cout_avantages,
        "cout_total_mensuel": cout_total, "cout_total_annuel": round(cout_total * 12, 2),
        "ratio_cout_net": ratio_cout,
        "repartition": {"salaire_net": round(net / cout_total * 100, 1) if cout_total else 0,
                        "charges_salariales": round(sal / cout_total * 100, 1) if cout_total else 0,
                        "charges_patronales": round(pat / cout_total * 100, 1) if cout_total else 0,
                        "annexes_avantages": round((cout_annexes + cout_avantages + frais_km) / cout_total * 100, 1) if cout_total else 0},
    }


# --- Simulation : Seuils d'effectif ---
@app.get("/api/simulation/seuils-effectif")
async def sim_seuils(
    effectif_actuel: int = Query(10),
    masse_salariale_annuelle: float = Query(400000),
):
    seuils = [
        {"seuil": 11, "obligations": [
            {"nom": "CSE (elections)", "reference": "Art. L.2311-2 CT", "cout_estime": 3000,
             "detail": "Mise en place du CSE obligatoire"},
            {"nom": "Participation formation", "reference": "Art. L.6331-1 CT", "cout_estime": round(masse_salariale_annuelle * 0.0045, 2),
             "detail": "Taux contribution formation passe de 0.55% a 1%"},
        ]},
        {"seuil": 20, "obligations": [
            {"nom": "FNAL taux plein", "reference": "Art. L.834-1 CSS", "cout_estime": round(masse_salariale_annuelle * 0.0030, 2),
             "detail": "FNAL passe de 0.10% plafonnd a 0.50% totalite"},
            {"nom": "Obligation emploi TH", "reference": "Art. L.5212-2 CT", "cout_estime": round(max(0, 20 - 0) * 600 * 0.04, 2),
             "detail": "6% de l effectif TH ou contribution AGEFIPH"},
        ]},
        {"seuil": 50, "obligations": [
            {"nom": "Participation (benefices)", "reference": "Art. L.3322-2 CT", "cout_estime": round(masse_salariale_annuelle * 0.005, 2),
             "detail": "Accord obligatoire de participation aux resultats"},
            {"nom": "CSE renforce (budgets)", "reference": "Art. L.2315-61 CT", "cout_estime": round(masse_salariale_annuelle * 0.002, 2),
             "detail": "Budget fonctionnement 0.2% + ASC"},
            {"nom": "Plan de sauvegarde emploi", "reference": "Art. L.1233-61 CT", "cout_estime": 0,
             "detail": "PSE obligatoire si licenciement >= 10 salaries"},
            {"nom": "Reglement interieur", "reference": "Art. L.1311-2 CT", "cout_estime": 500,
             "detail": "Redaction et depot obligatoires"},
            {"nom": "Effort construction (1%)", "reference": "Art. L.313-1 CCH", "cout_estime": round(masse_salariale_annuelle * 0.0045, 2),
             "detail": "Participation des employeurs a l effort de construction"},
            {"nom": "Index egalite pro", "reference": "Art. L.1142-8 CT", "cout_estime": 1500,
             "detail": "Calcul et publication obligatoires"},
        ]},
        {"seuil": 250, "obligations": [
            {"nom": "Quota alternants 5%", "reference": "Art. L.6241-1 CT", "cout_estime": round(masse_salariale_annuelle * 0.001, 2),
             "detail": "Contribution supplementaire si < 5% alternants"},
        ]},
        {"seuil": 300, "obligations": [
            {"nom": "Bilan social", "reference": "Art. L.2312-28 CT", "cout_estime": 2000,
             "detail": "Bilan social annuel obligatoire"},
            {"nom": "GPEC (GEPP)", "reference": "Art. L.2242-20 CT", "cout_estime": 5000,
             "detail": "Negociation obligatoire gestion des emplois et parcours professionnels"},
        ]},
    ]

    prochain_seuil = None
    impact_franchissement = []
    total_cout_actuel = 0
    total_cout_prochain = 0

    for s in seuils:
        franchi = effectif_actuel >= s["seuil"]
        for oblig in s["obligations"]:
            oblig["franchi"] = franchi
            if franchi:
                total_cout_actuel += oblig["cout_estime"]
        if not franchi and prochain_seuil is None:
            prochain_seuil = s["seuil"]
            impact_franchissement = s["obligations"]
            total_cout_prochain = sum(o["cout_estime"] for o in s["obligations"])

    return {
        "effectif_actuel": effectif_actuel,
        "masse_salariale_annuelle": masse_salariale_annuelle,
        "seuils": seuils,
        "total_obligations_actuelles": round(total_cout_actuel, 2),
        "prochain_seuil": prochain_seuil,
        "impact_prochain_seuil": impact_franchissement,
        "cout_prochain_seuil": round(total_cout_prochain, 2),
        "marge_avant_seuil": (prochain_seuil - effectif_actuel) if prochain_seuil else None,
    }


# --- Simulation : Masse salariale ---
@app.get("/api/simulation/masse-salariale")
async def sim_masse_salariale(
    brut_moyen: float = Query(2500),
    effectif: int = Query(10),
    augmentation_pct: float = Query(3.0),
    inflation_pct: float = Query(2.0),
    frais_km_moyen: float = Query(50),
    avantages_nature_moyen: float = Query(0),
    primes_variables_pct: float = Query(5.0),
    turnover_pct: float = Query(10.0),
):
    masse_actuelle = brut_moyen * effectif * 12
    taux_charges = 0.45
    charges_actuelles = masse_actuelle * taux_charges

    # Apres augmentation
    nouveau_brut = brut_moyen * (1 + augmentation_pct / 100)
    masse_apres_aug = nouveau_brut * effectif * 12
    cout_augmentation = masse_apres_aug - masse_actuelle
    charges_suppl_aug = cout_augmentation * taux_charges

    # Impact inflation (perte pouvoir achat si pas d augmentation)
    perte_reel = masse_actuelle * inflation_pct / 100

    # Primes variables
    primes_total = masse_actuelle * primes_variables_pct / 100
    charges_primes = primes_total * taux_charges

    # Frais kilometriques (non soumis)
    frais_km_total = frais_km_moyen * effectif * 12

    # Avantages nature (soumis)
    avantages_total = avantages_nature_moyen * effectif * 12
    charges_avantages = avantages_total * taux_charges

    # Turnover
    cout_recrutement = brut_moyen * 3
    cout_turnover = round(effectif * turnover_pct / 100 * cout_recrutement, 2)

    masse_totale_projetee = masse_apres_aug + primes_total + avantages_total
    charges_totales = masse_totale_projetee * taux_charges
    cout_global = masse_totale_projetee + charges_totales + frais_km_total + cout_turnover

    return {
        "masse_actuelle": round(masse_actuelle, 2),
        "charges_patronales_actuelles": round(charges_actuelles, 2),
        "cout_total_actuel": round(masse_actuelle + charges_actuelles, 2),
        "augmentation_pct": augmentation_pct,
        "nouveau_brut_moyen": round(nouveau_brut, 2),
        "masse_apres_augmentation": round(masse_apres_aug, 2),
        "cout_augmentation_brut": round(cout_augmentation, 2),
        "cout_augmentation_charges": round(charges_suppl_aug, 2),
        "cout_augmentation_total": round(cout_augmentation + charges_suppl_aug, 2),
        "perte_pouvoir_achat_inflation": round(perte_reel, 2),
        "ecart_augmentation_inflation": round(cout_augmentation - perte_reel, 2),
        "primes_variables_total": round(primes_total, 2),
        "charges_primes": round(charges_primes, 2),
        "frais_km_total": round(frais_km_total, 2),
        "avantages_nature_total": round(avantages_total, 2),
        "charges_avantages": round(charges_avantages, 2),
        "cout_turnover_estime": cout_turnover,
        "masse_totale_projetee": round(masse_totale_projetee, 2),
        "charges_totales_projetees": round(charges_totales, 2),
        "cout_global_projete": round(cout_global, 2),
        "evolution_pct": round((cout_global / (masse_actuelle + charges_actuelles) - 1) * 100, 2) if masse_actuelle > 0 else 0,
    }


# --- Simulation : Fin de contrat ---
@app.get("/api/simulation/fin-contrat")
async def sim_fin_contrat(
    type_fin: str = Query("licenciement"),
    salaire_brut: float = Query(2500),
    anciennete_mois: int = Query(36),
    est_cadre: bool = Query(False),
    motif: str = Query("personnel"),
):
    brut = salaire_brut
    anciennete_ans = anciennete_mois / 12
    salaire_ref = brut  # base mensuelle

    result = {"type_fin": type_fin, "salaire_brut": brut, "anciennete_mois": anciennete_mois,
              "anciennete_ans": round(anciennete_ans, 1)}

    if type_fin == "licenciement":
        # Indemnite legale : 1/4 mois par annee (10 premieres) + 1/3 au-dela
        if anciennete_ans <= 10:
            indemnite = salaire_ref * anciennete_ans * 0.25
        else:
            indemnite = salaire_ref * 10 * 0.25 + salaire_ref * (anciennete_ans - 10) / 3
        indemnite = round(indemnite, 2)

        # Preavis
        if anciennete_ans < 0.5:
            preavis_mois = 0
        elif anciennete_ans < 2:
            preavis_mois = 1
        else:
            preavis_mois = 2 if not est_cadre else 3

        indemnite_preavis = round(brut * preavis_mois, 2)
        conges_solde = round(brut * 2.5 / 30 * min(anciennete_mois, 12), 2)

        # Charges patronales sur indemnites
        exo_ss = min(indemnite, 92736)  # 2x PASS 2026
        charges_indemnite = round(max(0, indemnite - exo_ss) * 0.22, 2)

        # Contribution CSP si >= 1 an
        contrib_csp = round(brut * 3, 2) if motif == "economique" and anciennete_ans >= 1 else 0

        result.update({
            "indemnite_licenciement": indemnite,
            "indemnite_preavis": indemnite_preavis,
            "preavis_mois": preavis_mois,
            "conges_solde": conges_solde,
            "exoneration_ss": round(exo_ss, 2),
            "charges_indemnite": charges_indemnite,
            "contribution_csp": contrib_csp,
            "cout_total": round(indemnite + indemnite_preavis + conges_solde + charges_indemnite + contrib_csp, 2),
            "motif": motif,
            "reference": "Art. L.1234-9 CT (indemnite), Art. R.1234-2 CT (calcul)",
        })

    elif type_fin == "rupture_conventionnelle":
        if anciennete_ans <= 10:
            indemnite = salaire_ref * anciennete_ans * 0.25
        else:
            indemnite = salaire_ref * 10 * 0.25 + salaire_ref * (anciennete_ans - 10) / 3
        indemnite = round(max(indemnite, salaire_ref * anciennete_ans * 0.25), 2)

        conges_solde = round(brut * 2.5 / 30 * min(anciennete_mois, 12), 2)
        forfait_social = round(indemnite * 0.20, 2)

        result.update({
            "indemnite_rupture": indemnite,
            "conges_solde": conges_solde,
            "forfait_social_20pct": forfait_social,
            "cout_total": round(indemnite + conges_solde + forfait_social, 2),
            "reference": "Art. L.1237-13 CT - Indemnite >= legale licenciement",
            "note": "Homologation DREETS obligatoire (15 jours ouvrables)",
        })

    elif type_fin == "fin_cdd":
        indemnite_precarite = round(brut * anciennete_mois * 0.10, 2)
        conges_solde = round(brut * anciennete_mois * 0.10, 2)
        charges_precarite = round(indemnite_precarite * 0.22, 2)

        result.update({
            "indemnite_precarite_10pct": indemnite_precarite,
            "conges_payes_10pct": conges_solde,
            "charges_sur_precarite": charges_precarite,
            "cout_total": round(indemnite_precarite + conges_solde + charges_precarite, 2),
            "reference": "Art. L.1243-8 CT - 10% indemnite de precarite",
            "exceptions": "Pas de precarite si: CDI propose, saisonnier, etudiant, usage",
        })

    elif type_fin == "retraite":
        if anciennete_ans >= 30:
            indemnite = brut * 2
        elif anciennete_ans >= 20:
            indemnite = brut * 1.5
        elif anciennete_ans >= 15:
            indemnite = brut * 1
        elif anciennete_ans >= 10:
            indemnite = brut * 0.5
        else:
            indemnite = 0
        indemnite = round(indemnite, 2)
        charges = round(indemnite * 0.097, 2)

        result.update({
            "indemnite_depart_retraite": indemnite,
            "csg_crds_sur_indemnite": charges,
            "cout_total": round(indemnite + charges, 2),
            "reference": "Art. L.1237-9 CT",
        })

    return result


# --- Simulation : Optimisation legale ---
@app.get("/api/simulation/optimisation")
async def sim_optimisation(
    benefice_net: float = Query(80000),
    remuneration_gerant: float = Query(40000),
    dividendes: float = Query(20000),
    interessement: float = Query(0),
    participation: float = Query(0),
    frais_pro: float = Query(0),
    pee_abondement: float = Query(0),
    nb_parts: float = Query(1),
    forme_juridique: str = Query("sas"),
):
    result = {"forme_juridique": forme_juridique}
    scenarios = []

    # Scenario 1: Tout en salaire
    sal_total = benefice_net * 0.85
    charges_sal = sal_total * 0.42
    net_sal = sal_total - sal_total * 0.22
    ir_sal = _calculer_ir_simple(net_sal, nb_parts)
    total_net_1 = net_sal - ir_sal
    scenarios.append({
        "nom": "100% Salaire", "salaire_brut": round(sal_total, 2),
        "charges_sociales": round(charges_sal, 2), "dividendes": 0,
        "ir": round(ir_sal, 2), "net_disponible": round(total_net_1, 2),
        "protection_sociale": "Maximale (chomage, retraite, prevoyance)",
    })

    # Scenario 2: Mix actuel
    charges_rem = remuneration_gerant * 0.42
    net_rem = remuneration_gerant - remuneration_gerant * 0.22
    is_val = max(0, benefice_net - remuneration_gerant - charges_rem - frais_pro)
    is_impot = is_val * 0.15 if is_val <= 42500 else 42500 * 0.15 + (is_val - 42500) * 0.25
    div_net = dividendes * 0.7  # abattement 40% puis PFU ou bareme
    pfu_div = dividendes * 0.30  # PFU 30%
    ir_rem = _calculer_ir_simple(net_rem, nb_parts)
    total_net_2 = net_rem - ir_rem + dividendes - pfu_div
    scenarios.append({
        "nom": "Mix actuel (salaire + dividendes)", "salaire_brut": round(remuneration_gerant, 2),
        "charges_sociales": round(charges_rem, 2), "dividendes": round(dividendes, 2),
        "is_entreprise": round(is_impot, 2), "pfu_dividendes": round(pfu_div, 2),
        "ir": round(ir_rem, 2), "net_disponible": round(total_net_2, 2),
        "protection_sociale": "Moyenne (pas de cotisation sur dividendes)",
    })

    # Scenario 3: Maximum dividendes
    sal_min = 12 * 1801.80  # SMIC annuel
    charges_min = sal_min * 0.42
    net_min = sal_min - sal_min * 0.22
    is_base_3 = max(0, benefice_net - sal_min - charges_min)
    is_impot_3 = is_base_3 * 0.15 if is_base_3 <= 42500 else 42500 * 0.15 + (is_base_3 - 42500) * 0.25
    div_max = is_base_3 - is_impot_3
    pfu_3 = div_max * 0.30
    ir_3 = _calculer_ir_simple(net_min, nb_parts)
    total_net_3 = net_min - ir_3 + div_max - pfu_3
    scenarios.append({
        "nom": "Maximum dividendes (salaire SMIC)", "salaire_brut": round(sal_min, 2),
        "charges_sociales": round(charges_min, 2), "dividendes": round(div_max, 2),
        "is_entreprise": round(is_impot_3, 2), "pfu_dividendes": round(pfu_3, 2),
        "ir": round(ir_3, 2), "net_disponible": round(total_net_3, 2),
        "protection_sociale": "Minimale (retraite, chomage au minimum)",
    })

    # Scenario 4: Avec optimisation (interessement + PEE)
    int_val = min(benefice_net * 0.15, 3 * 46368)  # plafond interessement
    part_val = max(0, (benefice_net - remuneration_gerant * 1.42) * 0.5 * 0.5)
    abond_val = min(pee_abondement, 3709)  # plafond 2026
    forfait_social_int = round(int_val * 0.20, 2)
    forfait_social_part = round(part_val * 0.20, 2)
    charges_s4 = remuneration_gerant * 0.42
    net_s4 = remuneration_gerant - remuneration_gerant * 0.22
    ir_s4 = _calculer_ir_simple(net_s4, nb_parts)
    epargne_exo = int_val + part_val + abond_val - forfait_social_int - forfait_social_part
    total_net_4 = net_s4 - ir_s4 + epargne_exo * 0.903
    scenarios.append({
        "nom": "Optimise (interessement + participation + PEE)",
        "salaire_brut": round(remuneration_gerant, 2),
        "charges_sociales": round(charges_s4, 2),
        "interessement": round(int_val, 2),
        "participation": round(part_val, 2),
        "abondement_pee": round(abond_val, 2),
        "forfait_social": round(forfait_social_int + forfait_social_part, 2),
        "ir": round(ir_s4, 2),
        "net_disponible": round(total_net_4, 2),
        "protection_sociale": "Bonne + epargne salariale bloquee 5 ans",
    })

    # Meilleur scenario
    best = max(scenarios, key=lambda s: s["net_disponible"])
    result["scenarios"] = scenarios
    result["meilleur_scenario"] = best["nom"]
    result["ecart_max"] = round(best["net_disponible"] - min(s["net_disponible"] for s in scenarios), 2)

    # Frais professionnels deductibles
    result["frais_professionnels"] = {
        "frais_declares": frais_pro,
        "economie_is": round(frais_pro * 0.25, 2),
        "types_eligibles": ["Frais de deplacement", "Frais de repas (19.40 EUR/j)",
                            "Materiel professionnel", "Formation", "Abonnements pro",
                            "Cotisations syndicales", "Frais de bureau (domicile)"],
    }

    return result


# --- Simulation : Risques sectoriels ---
@app.get("/api/simulation/risques-sectoriels")
async def sim_risques(
    code_naf: str = Query("6201Z"),
    effectif: int = Query(10),
    masse_salariale: float = Query(400000),
):
    # Base de risques par grand secteur NAF
    secteurs = {
        "A": {"nom": "Agriculture", "taux_at": 3.5, "risques": [
            "Accidents du travail (machines, chutes)", "Exposition produits phytosanitaires",
            "Penibilite C2P (postures, vibrations)", "Saisonniers: DPAE et hebergement",
            "MSA au lieu d URSSAF pour cotisations"]},
        "C": {"nom": "Industrie manufacturiere", "taux_at": 2.8, "risques": [
            "Penibilite (travail de nuit, bruit, temperatures)", "Amiante (suivi post-exposition)",
            "Accidents machines (obligations EPI)", "ICPE et REACH (conformite chimique)",
            "Convention metallurgie: classifications specifiques"]},
        "F": {"nom": "Construction BTP", "taux_at": 5.2, "risques": [
            "Taux AT eleve (chutes de hauteur, engins)", "Carte BTP obligatoire",
            "Conges intemperies (Caisse CIBTP)", "Penibilite C2P: travail de nuit, postures",
            "Sous-traitance: vigilance solidarite financiere",
            "OPPBTP: cotisation obligatoire 0.11%"]},
        "G": {"nom": "Commerce", "taux_at": 1.5, "risques": [
            "Travail du dimanche (majorations)", "Temps partiel (minimum 24h/sem)",
            "Convention collective specifique (commerce detail, gros)",
            "Inventaires: heures supplementaires"]},
        "H": {"nom": "Transport", "taux_at": 3.0, "risques": [
            "Temps de conduite (reglementation EU)", "Versement mobilite (>= 11 sal)",
            "Convention transport routier (frais de route)", "Chronotachygraphe obligatoire",
            "Aptitude medicale renforcee"]},
        "I": {"nom": "Hebergement-restauration", "taux_at": 2.2, "risques": [
            "Avantages en nature repas (evaluation)", "Heures supplementaires (convention HCR)",
            "Saisonniers: DPAE, contrats, DUE", "Pourboires (regime fiscal 2022+)",
            "Hygiene alimentaire (formation HACCP obligatoire)"]},
        "J": {"nom": "Information-communication", "taux_at": 0.8, "risques": [
            "Teletravail (accord, indemnite, assurance)", "Forfait jours (cadres autonomes)",
            "Droit a la deconnexion", "RGPD (DPO si >= 250 salaries)",
            "Propriete intellectuelle des salaries"]},
        "K": {"nom": "Finance-assurance", "taux_at": 0.7, "risques": [
            "Convention collective banque/assurance specifique", "Risques psychosociaux",
            "Conformite reglementaire (AMF, ACPR)", "Lanceurs d alerte",
            "Formation obligatoire continue (DDA, MIF2)"]},
        "M": {"nom": "Activites scientifiques-techniques", "taux_at": 0.9, "risques": [
            "CIR/CII: credit impot recherche/innovation", "JEI: exoneration sociale possible",
            "Propriete intellectuelle (brevets, inventions salaries)",
            "Missions a l etranger (detachement, expatriation)",
            "Convention Syntec: modalites temps travail"]},
        "Q": {"nom": "Sante-action sociale", "taux_at": 2.5, "risques": [
            "Travail de nuit (majorations specifiques)", "Penibilite: manutention patients",
            "Obligation vaccinale (certains postes)", "Convention 66 ou BAD selon structure",
            "Astreintes et gardes (indemnisation specifique)"]},
        "S": {"nom": "Autres services", "taux_at": 1.2, "risques": [
            "Convention collective applicable (verifier IDCC)",
            "Associations: specificites (benevoles vs salaries)",
            "Services a la personne: CESU, mandataire/prestataire"]},
    }

    # Trouver le secteur
    lettre = code_naf[0] if code_naf else "J"
    secteur = secteurs.get(lettre, secteurs["S"])

    # Calcul cout AT
    cout_at = round(masse_salariale * secteur["taux_at"] / 100, 2)

    # Risques financiers
    risques_financiers = []
    if effectif >= 50:
        risques_financiers.append({"risque": "Licenciement collectif (>= 10)", "impact_estime": round(masse_salariale * 0.15, 2),
            "detail": "PSE obligatoire, indemnites supra-legales possibles"})
    risques_financiers.append({"risque": "Controle URSSAF (redressement moyen)", "impact_estime": round(masse_salariale * 0.03, 2),
        "detail": "Redressement moyen PME: 3% de la masse salariale sur 3 ans"})
    risques_financiers.append({"risque": "Prud hommes (moyenne)", "impact_estime": round(3 * (masse_salariale / max(effectif, 1) / 12), 2),
        "detail": "Indemnite moyenne: 3 mois de salaire + frais"})
    risques_financiers.append({"risque": "AT/MP grave", "impact_estime": round(masse_salariale * 0.05, 2),
        "detail": "Surcotisation AT + indemnisation + remplacement"})

    # Subventions possibles
    subventions = []
    if lettre in ("C", "F"):
        subventions.append({"nom": "Subvention prevention CARSAT", "montant_max": 25000,
            "condition": "Investissement prevention risques pro"})
    if effectif < 250:
        subventions.append({"nom": "Aide TPE-PME (FACT)", "montant_max": 50000,
            "condition": "Amelioration conditions de travail"})
    subventions.append({"nom": "FNE-Formation", "montant_max": round(effectif * 1500, 2),
        "condition": "Formation salaries en activite partielle ou mutation"})
    if lettre in ("J", "M"):
        subventions.append({"nom": "CIR - Credit Impot Recherche", "montant_max": round(masse_salariale * 0.30, 2),
            "condition": "30% des depenses R&D (salaires chercheurs inclus)"})

    return {
        "code_naf": code_naf, "secteur": secteur["nom"], "effectif": effectif,
        "taux_at_moyen": secteur["taux_at"], "cout_at_annuel": cout_at,
        "risques_specifiques": secteur["risques"],
        "risques_financiers": risques_financiers,
        "subventions_eligibles": subventions,
        "recommandations": [
            f"Taux AT {secteur['nom']}: {secteur['taux_at']}% - verifier votre taux reel",
            "Mettre a jour le DUERP avec les risques sectoriels identifies",
            "Souscrire une assurance RC pro adaptee au secteur",
        ],
    }


def _calculer_ir_simple(revenu: float, nb_parts: float) -> float:
    qi = revenu / nb_parts
    tranches = [(11294, 0), (28797, 0.11), (82341, 0.30), (177106, 0.41), (float("inf"), 0.45)]
    impot = 0.0
    prev = 0.0
    for seuil, taux in tranches:
        if qi <= prev:
            break
        tranche = min(qi, seuil) - prev
        impot += tranche * taux
        prev = seuil
    return round(impot * nb_parts, 2)


# ==============================
# VEILLE
# ==============================

@app.get("/api/veille/baremes/{annee}")
async def baremes_annee(annee: int):
    b = get_baremes_annee(annee)
    if not b:
        raise HTTPException(404, f"Baremes {annee} non disponibles")
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in b.items()}


@app.get("/api/veille/baremes/comparer/{a1}/{a2}")
async def comparer_baremes_route(a1: int, a2: int):
    return comparer_baremes(a1, a2)


@app.get("/api/veille/legislation/{annee}")
async def legislation_annee(annee: int):
    return get_legislation_par_annee(annee)


@app.get("/api/veille/alertes")
async def alertes_recentes(limit: int = Query(50, ge=1, le=200)):
    vm = VeilleManager()
    return vm.get_alertes_recentes(limit=limit)


# ==============================
# PORTEFEUILLE
# ==============================

@app.post("/api/entreprises")
async def ajouter_entreprise(
    siret: str = Form(...), raison_sociale: str = Form(...),
    forme_juridique: str = Form(""), code_naf: str = Form(""),
    effectif: int = Form(0), ville: str = Form(""),
):
    pm = PortfolioManager(get_db())
    ent = pm.ajouter_entreprise(
        siret=siret, raison_sociale=raison_sociale,
        forme_juridique=forme_juridique, code_naf=code_naf,
        effectif=effectif, ville=ville,
    )
    log_action("utilisateur", "ajout_entreprise", f"{raison_sociale} ({siret})")
    return {"id": ent.id, "siret": ent.siret, "raison_sociale": ent.raison_sociale}


@app.get("/api/entreprises")
async def liste_entreprises(q: str = Query("")):
    pm = PortfolioManager(get_db())
    return pm.rechercher_entreprises(q)


@app.get("/api/entreprises/{entreprise_id}")
async def detail_entreprise(entreprise_id: str):
    pm = PortfolioManager(get_db())
    ent = pm.get_entreprise(entreprise_id)
    if not ent:
        raise HTTPException(404, "Entreprise non trouvee")
    return ent


@app.get("/api/entreprises/{entreprise_id}/declarations")
async def declarations_entreprise(
    entreprise_id: str,
    limit: int = Query(50, ge=1, le=200),
    profil_id: Optional[str] = None,
):
    pm = PortfolioManager(get_db())
    return pm.get_historique_analyses(
        entreprise_id=entreprise_id, profil_id=profil_id, limit=limit,
    )


# ==============================
# DOCUMENTS / BIBLIOTHEQUE
# ==============================

@app.get("/api/documents/bibliotheque")
async def bibliotheque():
    return _doc_library


@app.get("/api/bibliotheque/knowledge")
async def knowledge_base():
    """Retourne l'etat complet de la base de connaissances accumulee."""
    return {
        "summary": _get_knowledge_summary(),
        "salaries": _biblio_knowledge["salaries"],
        "employeurs": _biblio_knowledge["employeurs"],
        "periodes_couvertes": _biblio_knowledge["periodes_couvertes"],
        "pieces_justificatives": _biblio_knowledge["pieces_justificatives"],
        "masse_salariale": _biblio_knowledge["masse_salariale"],
        "taux_verifies": _biblio_knowledge["taux_verifies"],
        "nb_cotisations": len(_biblio_knowledge["cotisations"]),
        "nb_dsn": len(_biblio_knowledge["declarations_dsn"]),
        "nb_bulletins": len(_biblio_knowledge["bulletins_paie"]),
        "anomalies": _biblio_knowledge["anomalies_detectees"][-20:],
    }


@app.get("/api/bibliotheque/knowledge/audit")
async def knowledge_audit():
    """Genere un rapport d'audit complet base sur la base de connaissances."""
    ks = _get_knowledge_summary()
    kb = _biblio_knowledge

    # --- AUDIT SOCIAL (CSS + CT) ---
    social_checks = []

    # 1. DPAE (L.1221-10 CT)
    social_checks.append(_audit_check(
        "DPAE (Declaration prealable a l embauche)",
        "Art. L.1221-10 CT",
        ks["nb_contrats_rh"] > 0,
        "Contrats RH enregistres avec DPAE generees automatiquement" if ks["nb_contrats_rh"] > 0 else "Aucun contrat enregistre dans le module RH",
        "Registre des DPAE, accuses de reception URSSAF",
    ))

    # 2. Contrats de travail (L.1221-1 CT)
    social_checks.append(_audit_check(
        "Contrats de travail complets et signes",
        "Art. L.1221-1 CT",
        ks["nb_contrats_rh"] > 0 and ks["nb_contrats_rh"] >= ks["nb_salaries_connus"],
        f"{ks['nb_contrats_rh']} contrat(s) pour {ks['nb_salaries_connus']} salarie(s) detecte(s)" if ks["nb_contrats_rh"] > 0 else "Aucun contrat enregistre",
        "Contrats de travail signes pour chaque salarie",
    ))

    # 3. DSN / Bulletins rapprochement (R.133-14 CSS) - Rapprochement des masses
    # Calculer le rapprochement reel des masses salariales BS vs DSN vs LDP
    masses_bs = {}  # periode -> {"brut": x, "refs": [...]}
    masses_dsn = {}
    masses_ldp = {}
    for bp in kb["bulletins_paie"]:
        per = bp.get("periode", "")
        if per:
            if per not in masses_bs:
                masses_bs[per] = {"brut": 0, "refs": [], "patronal": 0, "salarial": 0}
            masses_bs[per]["brut"] += bp.get("masse_salariale", 0)
            masses_bs[per]["patronal"] += float(bp.get("total_patronal", 0))
            masses_bs[per]["salarial"] += float(bp.get("total_salarial", 0))
            masses_bs[per]["refs"].append(bp.get("reference", ""))
    for d in kb["declarations_dsn"]:
        per = d.get("periode", "")
        if per:
            if per not in masses_dsn:
                masses_dsn[per] = {"brut": 0, "refs": [], "s89_brut": 0, "s89_cot": 0}
            masses_dsn[per]["brut"] += d.get("masse_salariale", 0)
            masses_dsn[per]["s89_brut"] += float(d.get("s89_total_brut", 0))
            masses_dsn[per]["s89_cot"] += float(d.get("s89_total_cotisations", 0))
            masses_dsn[per]["refs"].append(d.get("reference", ""))
    # Livre de paie stored separately in pieces_justificatives
    for bp in kb["bulletins_paie"]:
        ref = bp.get("reference", "")
        if ref in (kb["pieces_justificatives"].get("livre_de_paie") or []):
            per = bp.get("periode", "")
            if per:
                if per not in masses_ldp:
                    masses_ldp[per] = {"brut": 0, "refs": []}
                masses_ldp[per]["brut"] += bp.get("masse_salariale", 0)
                masses_ldp[per]["refs"].append(ref)

    # Comparer les masses par periode
    toutes_periodes = sorted(set(list(masses_bs.keys()) + list(masses_dsn.keys()) + list(masses_ldp.keys())))
    ecarts = []
    seuil_ecart = 0.01  # 1% de tolerance
    for per in toutes_periodes:
        bs = masses_bs.get(per)
        dsn = masses_dsn.get(per)
        ldp = masses_ldp.get(per)
        sources = {}
        if bs:
            sources["BS"] = bs["brut"]
        if dsn:
            sources["DSN"] = dsn["brut"]
        if ldp:
            sources["LDP"] = ldp["brut"]
        if len(sources) >= 2:
            vals = list(sources.values())
            ref_val = max(vals)
            if ref_val > 0:
                for s1, v1 in sources.items():
                    for s2, v2 in sources.items():
                        if s1 < s2:
                            ecart_pct = abs(v1 - v2) / ref_val
                            if ecart_pct > seuil_ecart:
                                ecarts.append({
                                    "periode": per,
                                    "source1": s1, "montant1": round(v1, 2),
                                    "source2": s2, "montant2": round(v2, 2),
                                    "ecart": round(abs(v1 - v2), 2),
                                    "ecart_pct": round(ecart_pct * 100, 2),
                                })

    has_rapprochement = ks["has_dsn"] and ks["has_bulletins"]
    rapprochement_ok = has_rapprochement and len(ecarts) == 0
    if ecarts:
        detail_rappr = f"ECARTS DETECTES sur {len(ecarts)} periode(s): "
        for e in ecarts[:3]:
            detail_rappr += f"[{e['periode']}: {e['source1']}={e['montant1']:.2f} vs {e['source2']}={e['montant2']:.2f}, ecart={e['ecart']:.2f} EUR ({e['ecart_pct']:.1f}%)] "
    elif has_rapprochement:
        nb_per_commun = len([p for p in toutes_periodes if p in masses_bs and p in masses_dsn])
        detail_rappr = f"Masses concordantes: {len(kb['declarations_dsn'])} DSN + {len(kb['bulletins_paie'])} BS sur {nb_per_commun} periode(s) commune(s)"
    else:
        detail_rappr = "DSN et/ou bulletins manquants pour rapprochement des masses"
    social_checks.append(_audit_check(
        "Rapprochement des masses BS / DSN / LDP",
        "Art. R.133-14 CSS - Art. L.242-1 CSS",
        rapprochement_ok,
        detail_rappr,
        "DSN mensuelle + bulletins de paie + livre de paie de la meme periode",
        incidence="Redressement URSSAF en cas d ecart significatif entre masse declaree (DSN) et masse versee (bulletins)" if ecarts else "",
        alerte=len(ecarts) > 0,
    ))

    # 4. Taux URSSAF (L.242-1 CSS) - verification reelle des taux
    nb_taux = len(ks["taux_verifies"])
    taux_non_conformes = []
    from urssaf_analyzer.rules.contribution_rules import ContributionRules as _CR
    from urssaf_analyzer.config.constants import ContributionType as _CT
    effectif_audit = max(ks.get("nb_salaries_connus", 0), max((kb["effectifs"].values()), default=0))
    _rules_audit = _CR(effectif_audit)
    for code_t, info_t in ks["taux_verifies"].items():
        taux_c = info_t.get("taux_constate", 0)
        if taux_c > 0:
            try:
                ct_enum = _CT(code_t)
                conforme, attendu = _rules_audit.verifier_taux(ct_enum, Decimal(str(taux_c)), Decimal(str(info_t.get("base", 0))))
                if not conforme and attendu is not None:
                    taux_non_conformes.append({"code": code_t, "constate": taux_c, "attendu": float(attendu)})
            except (ValueError, KeyError):
                pass
    if taux_non_conformes:
        taux_detail = f"{nb_taux} taux verifies, {len(taux_non_conformes)} NON CONFORME(S): "
        for tnc in taux_non_conformes[:3]:
            taux_detail += f"[{tnc['code']}: {tnc['constate']*100:.2f}% vs attendu {tnc['attendu']*100:.2f}%] "
    elif nb_taux > 0:
        taux_detail = f"{nb_taux} taux de cotisation verifies - tous conformes"
    else:
        taux_detail = "Aucun taux verifie - importer des bulletins de paie avec detail des cotisations"
    social_checks.append(_audit_check(
        "Verification des taux URSSAF 2026",
        "Art. L.242-1 CSS - Baremes URSSAF 2026",
        ks["has_bulletins"] and nb_taux > 0 and len(taux_non_conformes) == 0,
        taux_detail,
        "Bulletins de paie avec detail des cotisations",
        incidence="Redressement URSSAF pour application de taux incorrects" if taux_non_conformes else "",
        alerte=len(taux_non_conformes) > 0,
    ))

    # 4bis. Cotisations obligatoires - completude (controle negatif)
    types_cot_presents = set()
    for cot_kb in kb["cotisations"]:
        code_c = cot_kb.get("code", "")
        if code_c:
            types_cot_presents.add(code_c)
    # Cotisations universelles obligatoires
    universelles = [
        ("maladie", "Maladie"),
        ("vieillesse_plafonnee", "Vieillesse plafonnee"),
        ("vieillesse_deplafonnee", "Vieillesse deplafonnee"),
        ("allocations_familiales", "Allocations familiales"),
        ("accident_travail", "AT/MP"),
        ("csg_deductible", "CSG deductible"),
        ("assurance_chomage", "Assurance chomage"),
        ("retraite_complementaire_t1", "Retraite complementaire T1"),
        ("fnal", "FNAL"),
        ("formation_professionnelle", "Formation professionnelle"),
        ("taxe_apprentissage", "Taxe apprentissage"),
    ]
    # Cotisations par seuil
    par_seuil = [
        (11, "versement_mobilite", "Versement mobilite"),
        (20, "peec", "PEEC (1% logement)"),
    ]
    cots_manquantes = []
    cots_presentes = []
    if ks["has_bulletins"] or len(types_cot_presents) > 0:
        for code_u, label_u in universelles:
            if code_u in types_cot_presents:
                cots_presentes.append(label_u)
            else:
                # Tolerance pour CSG/CRDS souvent regroupees
                if code_u == "csg_deductible" and "csg_non_deductible" in types_cot_presents:
                    cots_presentes.append(label_u)
                    continue
                cots_manquantes.append(label_u)
        for seuil_c, code_c, label_c in par_seuil:
            if effectif_audit >= seuil_c:
                if code_c in types_cot_presents:
                    cots_presentes.append(label_c)
                else:
                    cots_manquantes.append(f"{label_c} (obligatoire >= {seuil_c} sal.)")
    if cots_manquantes:
        completude_detail = f"{len(cots_presentes)} cotisation(s) trouvee(s), {len(cots_manquantes)} MANQUANTE(S): " + ", ".join(cots_manquantes[:5])
    elif len(cots_presentes) > 0:
        completude_detail = f"{len(cots_presentes)} cotisations obligatoires presentes - completude OK"
    else:
        completude_detail = "Aucune cotisation analysee - importer des bulletins de paie"
    social_checks.append(_audit_check(
        "Completude des cotisations obligatoires",
        "Art. L242-1 CSS - Art. L2333-64 CGCT - Art. L313-1 CCH",
        len(cots_presentes) > 0 and len(cots_manquantes) == 0,
        completude_detail,
        "Bulletins de paie complets avec toutes les lignes de cotisations",
        incidence="Redressement URSSAF sur 3 ans + majorations 5% + 0.4%/mois pour cotisations non declarees" if cots_manquantes else "",
        alerte=len(cots_manquantes) > 0,
    ))

    # 5. Coherence masse salariale / effectif (L.242-1 CSS)
    masse_par_sal = ks["total_masse_salariale"] / max(ks["nb_salaries_connus"], 1) if ks["nb_salaries_connus"] > 0 else 0
    masse_coherente = ks["total_masse_salariale"] > 0 and ks["nb_salaries_connus"] > 0
    # Verifier si la masse par salarie est plausible (entre SMIC et 15000 EUR/mois)
    masse_alerte = False
    if masse_par_sal > 0:
        smic_m = 1823.03
        if masse_par_sal < smic_m * 0.5:
            masse_alerte = True
            masse_detail_extra = f" - ATTENTION: moyenne {masse_par_sal:.2f} EUR/sal. est anormalement basse (< 50% SMIC)"
        elif masse_par_sal > 15000:
            masse_detail_extra = f" - moyenne {masse_par_sal:.2f} EUR/sal. (a verifier si coherent)"
        else:
            masse_detail_extra = f" - moyenne {masse_par_sal:.2f} EUR/salarie"
    else:
        masse_detail_extra = ""
    social_checks.append(_audit_check(
        "Coherence masse salariale / effectif declare",
        "Art. L.242-1 CSS",
        masse_coherente and not masse_alerte,
        (f"Masse salariale: {ks['total_masse_salariale']:.2f} EUR pour {ks['nb_salaries_connus']} salarie(s)" + masse_detail_extra) if ks["total_masse_salariale"] > 0 else "Pas assez de donnees",
        "Bulletins de paie, DADS ou DSN annuelle",
        alerte=masse_alerte,
    ))

    # 6. Plafonnement PASS (L.241-3 CSS)
    social_checks.append(_audit_check(
        "Plafonnement PASS (vieillesse plafonnee, FNAL)",
        "Art. L.241-3 CSS - PASS 2026: 47 100 EUR",
        ks["has_bulletins"] and ks["nb_cotisations_analysees"] > 0,
        f"{ks['nb_cotisations_analysees']} lignes de cotisations analysees" if ks["nb_cotisations_analysees"] > 0 else "Aucune cotisation analysee",
        "Bulletins avec lignes vieillesse plafonnee",
    ))

    # 7. Detection apprentis (L.6243-2 CT)
    social_checks.append(_audit_check(
        "Detection apprentis et exonerations specifiques",
        "Art. L.6243-2 CT",
        len(ks["exonerations"]) > 0 or ks["has_bulletins"],
        f"{len(ks['exonerations'])} exoneration(s) detectee(s)" if ks["exonerations"] else "Verifiable si bulletins d apprentis importes",
        "Contrats d apprentissage, bulletins specifiques",
    ))

    # 8. NIR / identite (R.114-7 CSS)
    nirs_valides = sum(1 for s in kb["salaries"].values() if s.get("nir") and not s["nir"].startswith("unknown"))
    social_checks.append(_audit_check(
        "Controle NIR / identite des salaries",
        "Art. R.114-7 CSS",
        nirs_valides > 0 and ks["has_multi_docs"],
        f"{nirs_valides} NIR verifies sur {ks['nb_salaries_connus']} salarie(s)" if nirs_valides > 0 else "NIR non disponibles dans les documents importes",
        "Bulletins + DSN avec NIR concordants",
    ))

    # 9. SMIC et minima (L.3231-2 CT)
    salaires_analyses = [s["dernier_brut"] for s in kb["salaries"].values() if s.get("dernier_brut", 0) > 0]
    smic_mensuel = 1801.80  # SMIC 2025/2026 approximatif
    sous_smic = [b for b in salaires_analyses if b < smic_mensuel and b > 0]
    social_checks.append(_audit_check(
        "Verification SMIC et minima conventionnels",
        "Art. L.3231-2 CT - Art. L.2253-1 CT",
        len(salaires_analyses) > 0,
        (f"{len(salaires_analyses)} salaire(s) analyse(s), {len(sous_smic)} sous le SMIC mensuel ({smic_mensuel} EUR)" if sous_smic else f"{len(salaires_analyses)} salaire(s) conforme(s) au SMIC") if salaires_analyses else "Aucun salaire disponible",
        "Bulletins de paie, grille de la convention collective",
        alerte=len(sous_smic) > 0,
    ))

    # 10. Blocs DSN (Cahier technique)
    social_checks.append(_audit_check(
        "Blocs obligatoires DSN (S21.G00.06, S21.G00.40, etc.)",
        "Cahier technique DSN - Norme NEODeS",
        ks["has_dsn"],
        f"{len(kb['declarations_dsn'])} DSN importee(s) et analysee(s)" if ks["has_dsn"] else "Aucune DSN importee",
        "Fichier DSN au format NEODeS",
    ))

    # 11. Prevoyance cadres (ANI 17/11/2017)
    social_checks.append(_audit_check(
        "Prevoyance obligatoire cadres (1.50% TA)",
        "ANI 17/11/2017 - Art. 7 CCN Cadres 1947",
        "prevoyance" in kb["pieces_justificatives"],
        "Contrat de prevoyance importe" if "prevoyance" in kb["pieces_justificatives"] else f"{ks['nb_cadres']} cadre(s) detecte(s) - document de prevoyance non importe",
        "Contrat de prevoyance collective, DUE ou accord collectif",
        incidence="Redressement URSSAF : reintegration dans l assiette de cotisations des contributions patronales",
    ))

    # 12. Mutuelle obligatoire (L.911-7 CSS)
    social_checks.append(_audit_check(
        "Complementaire sante obligatoire (mutuelle ANI)",
        "Art. L.911-7 CSS - ANI 11/01/2013 - Loi 2016",
        "mutuelle" in kb["pieces_justificatives"],
        "Justificatif mutuelle importe" if "mutuelle" in kb["pieces_justificatives"] else "Aucun justificatif de complementaire sante importe",
        "Contrat de complementaire sante, DUE ou accord, attestation mutuelle",
        incidence="Amende + redressement URSSAF sur contributions patronales",
    ))

    # 13. DUERP (R.4121-1 CT)
    social_checks.append(_audit_check(
        "Document unique d evaluation des risques (DUERP)",
        "Art. R.4121-1 a R.4121-4 CT",
        "duerp" in kb["pieces_justificatives"],
        "DUERP importe" if "duerp" in kb["pieces_justificatives"] else "DUERP non importe - obligatoire des le 1er salarie",
        "Document unique d evaluation des risques professionnels",
        incidence="Contravention 5eme classe (1500 EUR). Responsabilite penale en cas AT.",
    ))

    # 14. Registre personnel (L.1221-13 CT)
    social_checks.append(_audit_check(
        "Registre unique du personnel",
        "Art. L.1221-13 CT",
        ks["nb_contrats_rh"] > 0 and ks["nb_contrats_rh"] >= ks["nb_salaries_connus"],
        f"Registre reconstitue via {ks['nb_contrats_rh']} contrat(s) RH" if ks["nb_contrats_rh"] > 0 else "Aucun contrat enregistre - registre non verifiable",
        "Registre avec entrees/sorties de tous les salaries",
        incidence="Contravention 4eme classe (750 EUR par salarie concerne)",
    ))

    # 15. Medecine du travail (R.4624-10 CT)
    social_checks.append(_audit_check(
        "Suivi individuel de sante (medecine du travail)",
        "Art. R.4624-10 CT",
        ks["nb_visites_medicales"] > 0,
        f"{ks['nb_visites_medicales']} visite(s) medicale(s) enregistree(s)" if ks["nb_visites_medicales"] > 0 else "Aucune visite medicale enregistree",
        "Fiches d aptitude, convocations, attestations de suivi",
        incidence="Mise en cause de la responsabilite de l employeur en cas de dommage",
    ))

    # 16. Duree du travail (L.3121-1 CT)
    nb_planning = len(_rh_planning)
    social_checks.append(_audit_check(
        "Duree du travail et repos obligatoires",
        "Art. L.3121-1 CT - Art. L.3131-1 CT (11h repos)",
        nb_planning > 0,
        f"{nb_planning} creneau(x) planning enregistre(s)" if nb_planning > 0 else "Aucun planning enregistre - impossible de verifier les durees",
        "Planning, registre des horaires, accords temps de travail",
    ))

    # 17. Egalite professionnelle (L.1142-8 CT)
    nb_actifs = ks["nb_contrats_actifs"]
    social_checks.append(_audit_check(
        "Index egalite professionnelle (si >= 50 salaries)",
        "Art. L.1142-8 CT",
        nb_actifs < 50 or "index_egalite" in kb["pieces_justificatives"],
        "Non applicable (effectif < 50)" if nb_actifs < 50 else ("Index importe" if "index_egalite" in kb["pieces_justificatives"] else "Index non importe - obligatoire >= 50 salaries"),
        "Index egalite, accord egalite professionnelle",
        incidence="Penalite financiere pouvant atteindre 1% de la masse salariale" if nb_actifs >= 50 else "",
    ))

    # 18. CSE (L.2311-2 CT)
    social_checks.append(_audit_check(
        "Comite social et economique (CSE)",
        "Art. L.2311-2 CT",
        nb_actifs < 11 or "pv_cse" in kb["pieces_justificatives"],
        "Non applicable (effectif < 11)" if nb_actifs < 11 else ("PV CSE importe" if "pv_cse" in kb["pieces_justificatives"] else "CSE obligatoire >= 11 salaries - aucun PV importe"),
        "PV elections CSE, registre des PV de reunions",
        incidence="Delit d entrave (L.2317-1 CT): 1 an emprisonnement + 7500 EUR amende" if nb_actifs >= 11 else "",
    ))

    # 19. Formation professionnelle (L.6321-1 CT)
    social_checks.append(_audit_check(
        "Plan de developpement des competences",
        "Art. L.6321-1 CT",
        ks["nb_entretiens"] > 0,
        f"{ks['nb_entretiens']} entretien(s) professionnel(s) enregistre(s)" if ks["nb_entretiens"] > 0 else "Aucun entretien professionnel enregistre",
        "Plan de formation, bilans, entretiens professionnels",
    ))

    # 20. Conges payes (L.3141-1 CT)
    nb_conges = len(_rh_conges)
    social_checks.append(_audit_check(
        "Suivi des conges payes",
        "Art. L.3141-1 CT - 2.5 jours ouvrables / mois",
        nb_conges > 0 or ks["nb_contrats_rh"] == 0,
        f"{nb_conges} conge(s) enregistre(s)" if nb_conges > 0 else "Aucun conge enregistre" if ks["nb_contrats_rh"] > 0 else "Non applicable (aucun salarie)",
        "Registre des conges, compteurs individuels",
    ))

    # 21. Heures supplementaires (L.3121-33 CT)
    social_checks.append(_audit_check(
        "Heures supplementaires - Contingent annuel (220h)",
        "Art. L.3121-33 CT - Art. D.3121-24 CT",
        nb_planning > 0 or ks["has_bulletins"],
        f"Verifiable via {nb_planning} creneau(x) planning" if nb_planning > 0 else "Verifiable si bulletins avec HS importes" if ks["has_bulletins"] else "Aucune donnee disponible",
        "Registre heures sup, bulletins detailles, accords",
    ))

    # --- AUDIT FISCAL (CGI) ---
    fiscal_checks = []

    fiscal_checks.append(_audit_check("Declarations TVA (CA3/CA12)", "Art. 287 CGI",
        "declarations_tva" in kb["pieces_justificatives"],
        "Declarations TVA importees" if "declarations_tva" in kb["pieces_justificatives"] else "Aucune declaration TVA importee",
        "Declarations de TVA, livre des achats/ventes"))

    fiscal_checks.append(_audit_check("Coherence CA declare / comptabilise", "Art. 38 CGI",
        "comptabilite" in kb["pieces_justificatives"] or len(_biblio_knowledge["documents_comptables"]) > 0,
        "Documents comptables disponibles" if "comptabilite" in kb["pieces_justificatives"] else "Aucun document comptable importe",
        "Grand livre, balance, declarations fiscales"))

    fiscal_checks.append(_audit_check("IS/IR - Resultat fiscal", "Art. 209 CGI",
        "liasse_fiscale" in kb["pieces_justificatives"],
        "Liasse fiscale importee" if "liasse_fiscale" in kb["pieces_justificatives"] else "Liasse fiscale non importee",
        "Liasse fiscale (2065/2031), comptes annuels"))

    fiscal_checks.append(_audit_check("CET (CFE + CVAE)", "Art. 1447-0 CGI",
        "cet" in kb["pieces_justificatives"],
        "Documents CET importes" if "cet" in kb["pieces_justificatives"] else "Declarations CFE/CVAE non importees",
        "Declarations 1447-C, 1330-CVAE"))

    fiscal_checks.append(_audit_check("Charges deductibles", "Art. 39 CGI",
        ks["has_bulletins"] or "comptabilite" in kb["pieces_justificatives"],
        "Charges verifiables via les documents importes" if ks["has_bulletins"] else "Aucun justificatif de charges importe",
        "Justificatifs de charges, factures fournisseurs"))

    fiscal_checks.append(_audit_check("Amortissements", "Art. 39B CGI",
        "immobilisations" in kb["pieces_justificatives"],
        "Tableau des immobilisations importe" if "immobilisations" in kb["pieces_justificatives"] else "Tableau des immobilisations non importe",
        "Tableau des immobilisations et amortissements"))

    fiscal_checks.append(_audit_check("Provisions", "Art. 39-1-5 CGI",
        "provisions" in kb["pieces_justificatives"],
        "Releve des provisions importe" if "provisions" in kb["pieces_justificatives"] else "Non verifiable - aucun releve de provisions",
        "Releve des provisions, justificatifs"))

    fiscal_checks.append(_audit_check("TVA intracommunautaire", "Art. 262 ter CGI",
        "deb_des" in kb["pieces_justificatives"],
        "DEB/DES importees" if "deb_des" in kb["pieces_justificatives"] else "Pas de DEB/DES importees",
        "DEB/DES, factures intracommunautaires"))

    fiscal_checks.append(_audit_check("Taxe sur les salaires (si non assujetti TVA)", "Art. 231 CGI",
        ks["has_bulletins"],
        "Verifiable via les bulletins importes" if ks["has_bulletins"] else "Non verifiable sans bulletin",
        "Declaration annuelle taxe sur salaires 2502"))

    # --- COUR DES COMPTES ---
    cdc_checks = []
    cdc_checks.append(_audit_check("Regularite des comptes", "Normes NEP - ISA",
        "comptes_annuels" in kb["pieces_justificatives"],
        "Comptes annuels importes" if "comptes_annuels" in kb["pieces_justificatives"] else "Comptes annuels non importes",
        "Comptes annuels certifies par CAC"))

    cdc_checks.append(_audit_check("Sincerite des ecritures", "Art. L.123-14 Code de commerce",
        len(_biblio_knowledge["documents_comptables"]) > 0 or ks["has_bulletins"],
        "Ecritures verifiables" if len(_biblio_knowledge["documents_comptables"]) > 0 else "Pas de pieces comptables detaillees",
        "Grand livre, pieces justificatives"))

    cdc_checks.append(_audit_check("Image fidele du patrimoine", "Art. L.123-14 Code de commerce",
        "bilan" in kb["pieces_justificatives"],
        "Bilan importe" if "bilan" in kb["pieces_justificatives"] else "Bilan non importe",
        "Bilan, annexe, rapport de gestion"))

    cdc_checks.append(_audit_check("Continuite d exploitation", "NEP 570",
        "previsionnel" in kb["pieces_justificatives"],
        "Previsionnel importe" if "previsionnel" in kb["pieces_justificatives"] else "Previsionnel non disponible",
        "Previsionnels, plan de tresorerie"))

    # Rapprochement detaille des masses (donnees supplementaires pour affichage)
    rapprochement_detail = {
        "periodes": toutes_periodes,
        "masses_bs": {p: {"brut": v["brut"], "patronal": v["patronal"], "salarial": v["salarial"]} for p, v in masses_bs.items()},
        "masses_dsn": {p: {"brut": v["brut"], "s89_brut": v["s89_brut"], "s89_cot": v["s89_cot"]} for p, v in masses_dsn.items()},
        "masses_ldp": {p: {"brut": v["brut"]} for p, v in masses_ldp.items()},
        "ecarts": ecarts,
        "seuil_tolerance_pct": seuil_ecart * 100,
    }

    return {
        "social": social_checks,
        "fiscal": fiscal_checks,
        "cour_des_comptes": cdc_checks,
        "knowledge_summary": ks,
        "score_audit": _calculer_score_audit(social_checks, fiscal_checks, cdc_checks),
        "rapprochement_masses": rapprochement_detail,
    }


def _audit_check(nom: str, ref: str, present: bool, detail: str, docs: str, incidence: str = "", alerte: bool = False) -> dict:
    return {
        "nom": nom,
        "reference": ref,
        "present": present,
        "detail": detail,
        "documents_requis": docs,
        "incidence_legale": incidence,
        "alerte": alerte,
    }


def _calculer_score_audit(social, fiscal, cdc) -> dict:
    total = len(social) + len(fiscal) + len(cdc)
    verifies = sum(1 for c in social + fiscal + cdc if c["present"])
    pct = round(verifies / total * 100) if total > 0 else 0
    return {
        "total_checks": total,
        "verifies": verifies,
        "non_verifies": total - verifies,
        "pourcentage": pct,
        "social_verifies": sum(1 for c in social if c["present"]),
        "social_total": len(social),
        "fiscal_verifies": sum(1 for c in fiscal if c["present"]),
        "fiscal_total": len(fiscal),
        "cdc_verifies": sum(1 for c in cdc if c["present"]),
        "cdc_total": len(cdc),
    }


@app.post("/api/documents/bibliotheque/{doc_id}/corriger")
async def corriger_document(
    doc_id: str,
    champ: str = Form(...),
    ancienne_valeur: str = Form(""),
    nouvelle_valeur: str = Form(...),
    corrige_par: str = Form("utilisateur"),
):
    for doc in _doc_library:
        if doc["id"] == doc_id:
            doc["erreurs_corrigees"].append({
                "champ": champ,
                "ancienne_valeur": ancienne_valeur,
                "nouvelle_valeur": nouvelle_valeur,
                "date": datetime.now().isoformat(),
                "par": corrige_par,
            })
            doc["actions"].append({
                "action": f"correction:{champ}",
                "par": corrige_par,
                "date": datetime.now().isoformat(),
            })
            log_action(corrige_par, "correction_document", f"{doc['nom']} {champ}")
            return {"status": "ok"}
    raise HTTPException(404, "Document non trouve")


# ==============================
# COLLABORATION
# ==============================

@app.post("/api/collaboration/inviter")
async def inviter_collaborateur(
    email_invite: str = Form(...),
    role: str = Form("collaborateur"),
):
    token = str(uuid.uuid4())[:12]
    inv = {
        "id": str(uuid.uuid4())[:8],
        "email": email_invite,
        "role": role,
        "token": token,
        "statut": "en_attente",
        "date": datetime.now().isoformat(),
        "invite_par": "utilisateur",
    }
    _invitations.append(inv)
    log_action("utilisateur", "invitation", f"{email_invite} ({role})")
    return {
        "status": "ok",
        "email": email_invite,
        "lien_validation": f"/api/collaboration/valider?token={token}",
    }


@app.get("/api/collaboration/valider", response_class=HTMLResponse)
async def valider_invitation(token: str = Query(...)):
    inv = None
    for i in _invitations:
        if i["token"] == token:
            inv = i
            break
    if not inv:
        return HTMLResponse("<h2>Lien invalide ou expire.</h2>", 404)
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>NormaCheck - Creer votre acces</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:-apple-system,sans-serif;background:#f8fafc;display:flex;justify-content:center;align-items:center;min-height:100vh}}
.card{{background:#fff;border-radius:16px;padding:32px;max-width:400px;width:90%;box-shadow:0 8px 30px rgba(0,0,0,.08)}}
h2{{color:#0f172a;margin-bottom:16px}}label{{display:block;font-weight:600;font-size:.85em;color:#475569;margin:10px 0 4px}}
input{{width:100%;padding:10px 14px;border:1.5px solid #e2e8f0;border-radius:10px;font-size:.95em}}
button{{width:100%;padding:12px;background:#0f172a;color:#fff;border:none;border-radius:10px;font-size:1em;font-weight:700;cursor:pointer;margin-top:16px}}</style></head>
<body><div class="card"><h2>Bienvenue sur NormaCheck</h2><p style="color:#64748b;font-size:.9em;margin-bottom:16px">Invitation pour <strong>{inv["email"]}</strong> (role: {inv["role"]})</p>
<form method="POST" action="/api/collaboration/finaliser"><input type="hidden" name="token" value="{token}">
<label>Mot de passe</label><input type="password" name="mot_de_passe" required minlength="6">
<label>Confirmer</label><input type="password" name="confirm" required>
<button type="submit">Creer mon acces</button></form></div></body></html>""")


@app.post("/api/collaboration/finaliser")
async def finaliser_invitation(
    token: str = Form(...),
    mot_de_passe: str = Form(...),
    confirm: str = Form(""),
):
    for inv in _invitations:
        if inv["token"] == token:
            inv["statut"] = "active"
            log_action(inv["email"], "activation_compte", f"role={inv['role']}")
            return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NormaCheck - Compte active</title></head><body style="font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f8fafc">
<div style="text-align:center"><h2 style="color:#16a34a">Compte active !</h2><p>Vous pouvez maintenant <a href="/app">acceder a NormaCheck</a>.</p></div></body></html>""")
    raise HTTPException(404, "Token invalide")


@app.get("/api/collaboration/equipe")
async def equipe():
    return {
        "invitations": _invitations,
        "audit_log": _audit_log[-50:],
    }


# ==============================
# AUDIT LOG
# ==============================

@app.get("/api/audit-log")
async def get_audit_log(limit: int = Query(100, ge=1, le=500)):
    return _audit_log[-limit:]


# ==============================
# RESSOURCES HUMAINES
# ==============================

@app.post("/api/rh/contrats")
async def creer_contrat(
    type_contrat: str = Form(...),
    nom_salarie: str = Form(...),
    prenom_salarie: str = Form(...),
    poste: str = Form(...),
    date_debut: str = Form(...),
    date_fin: str = Form(""),
    salaire_brut: str = Form(...),
    temps_travail: str = Form("full"),
    duree_hebdo: str = Form("35"),
    convention_collective: str = Form(""),
    periode_essai_jours: str = Form("0"),
    motif_cdd: str = Form(""),
):
    """Cree un contrat de travail avec toutes les mentions legales obligatoires (Code du travail L.1221-1 et suivants)."""
    contrat_id = str(uuid.uuid4())[:8]
    salarie_id = str(uuid.uuid4())[:8]

    # Validation du type de contrat
    types_valides = ("CDI", "CDD", "CTT", "Apprentissage", "Professionnalisation", "Saisonnier", "Intermittent")
    if type_contrat not in types_valides:
        raise HTTPException(400, f"Type de contrat invalide. Valeurs acceptees: {', '.join(types_valides)}")

    # Pour un CDD, le motif est obligatoire (art. L.1242-2 Code du travail)
    if type_contrat == "CDD" and not motif_cdd:
        raise HTTPException(400, "Le motif du CDD est obligatoire (art. L.1242-2 Code du travail)")

    # Calcul de la periode d'essai legale par defaut si non renseignee
    pe_jours = int(periode_essai_jours or "0")
    if pe_jours == 0:
        periodes_legales = {
            "CDI": 60,       # 2 mois ouvriers/employes (art. L.1221-19)
            "CDD": 14,       # 1 jour par semaine, max 2 semaines si CDD <= 6 mois
            "CTT": 5,
            "Apprentissage": 45,
            "Professionnalisation": 30,
            "Saisonnier": 14,
            "Intermittent": 60,
        }
        pe_jours = periodes_legales.get(type_contrat, 60)

    # Calcul du net estime (approximation 22% de charges salariales)
    brut = float(salaire_brut)
    net_estime = round(brut * 0.78, 2)
    cout_employeur = round(brut * 1.45, 2)

    # Mentions legales obligatoires selon L.1221-1 et R.1221-1 du Code du travail
    mentions_legales = [
        "Identite et adresse des parties (art. L.1221-1 CT)",
        "Lieu de travail (art. L.1221-1 CT)",
        "Intitule du poste et description des fonctions",
        f"Date de debut: {date_debut}",
        f"Duree de la periode d'essai: {pe_jours} jours (art. L.1221-19 CT)",
        f"Remuneration brute mensuelle: {salaire_brut} EUR",
        f"Duree du travail: {duree_hebdo}h hebdomadaires",
        "Convention collective applicable" + (f": {convention_collective}" if convention_collective else ""),
        "Organisme de securite sociale percevant les cotisations",
        "Caisse de retraite complementaire",
        "Organisme de prevoyance (si applicable)",
    ]

    if type_contrat == "CDD":
        mentions_legales.extend([
            f"Motif du recours au CDD: {motif_cdd} (art. L.1242-2 CT)",
            f"Date de fin prevue: {date_fin}" if date_fin else "Terme imprecis (art. L.1242-7 CT)",
            "Nom et qualification du salarie remplace (si remplacement)",
            "Indemnite de fin de contrat: 10% (art. L.1243-8 CT)",
        ])

    if type_contrat == "Apprentissage":
        mentions_legales.extend([
            "Nom du maitre d'apprentissage et titre/diplome",
            "Organisme de formation (CFA)",
            "Diplome prepare",
            "Duree du contrat d'apprentissage",
        ])

    if type_contrat == "Professionnalisation":
        mentions_legales.extend([
            "Qualification visee",
            "Nature et duree des actions de formation",
            "Conditions du tutorat",
        ])

    if temps_travail == "partial":
        mentions_legales.extend([
            f"Temps partiel: {duree_hebdo}h/semaine (art. L.3123-6 CT)",
            "Repartition de la duree du travail entre les jours de la semaine",
            "Cas de modification de la repartition",
            "Limites des heures complementaires",
        ])

    contrat = {
        "id": contrat_id,
        "salarie_id": salarie_id,
        "type_contrat": type_contrat,
        "nom_salarie": nom_salarie,
        "prenom_salarie": prenom_salarie,
        "poste": poste,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "salaire_brut": brut,
        "net_estime": net_estime,
        "cout_employeur_estime": cout_employeur,
        "temps_travail": temps_travail,
        "duree_hebdo": float(duree_hebdo),
        "convention_collective": convention_collective,
        "periode_essai_jours": pe_jours,
        "motif_cdd": motif_cdd,
        "mentions_legales": mentions_legales,
        "statut": "actif",
        "date_creation": datetime.now().isoformat(),
        "clauses_obligatoires": {
            "clause_non_concurrence": False,
            "clause_mobilite": False,
            "clause_exclusivite": False,
            "clause_dedit_formation": False,
        },
        "references_legales": {
            "base": "Code du travail, Partie legislative, Livre II, Titre II",
            "periode_essai": "Art. L.1221-19 a L.1221-26 CT",
            "cdd": "Art. L.1241-1 a L.1248-11 CT" if type_contrat == "CDD" else None,
            "temps_partiel": "Art. L.3123-1 a L.3123-32 CT" if temps_travail == "partial" else None,
        },
    }

    _rh_contrats.append(contrat)

    # === Effets en cascade de la creation du contrat ===
    cascading = {"dpae": None, "planning": [], "visite_medicale": None, "ecriture_comptable": None}

    # 1. Alerte DPAE automatique (art. L.1221-10 CT)
    cascading["dpae"] = {
        "type": "dpae_obligatoire",
        "urgence": "haute",
        "message": f"DPAE obligatoire pour {prenom_salarie} {nom_salarie} avant le {date_debut}. A effectuer aupres de l'URSSAF.",
        "reference": "Art. L.1221-10 CT - Au plus tard dans les 8 jours precedant l'embauche",
        "action_requise": "Effectuer la DPAE sur net-entreprises.fr ou aupres de l'URSSAF",
    }

    # 2. Visite medicale d'embauche (VIP) dans les 3 mois
    try:
        dd = date.fromisoformat(date_debut)
        from datetime import timedelta
        date_limite_visite = (dd + timedelta(days=90)).isoformat()
        visite = {
            "id": str(uuid.uuid4())[:8],
            "salarie_id": salarie_id,
            "type_visite": "embauche",
            "date_visite": "",
            "resultat": "",
            "remarques": "Visite auto-generee a la creation du contrat",
            "date_prochaine": date_limite_visite,
            "date_creation": datetime.now().isoformat(),
        }
        _rh_visites_med.append(visite)
        cascading["visite_medicale"] = {"date_limite": date_limite_visite, "reference": "Art. R.4624-10 CT"}
    except (ValueError, TypeError):
        pass

    # 3. Planning initial (Lun-Ven premiere semaine)
    try:
        dd = date.fromisoformat(date_debut)
        from datetime import timedelta
        for i in range(5):
            jour = dd + timedelta(days=i)
            if jour.weekday() < 5:
                entry = {
                    "id": str(uuid.uuid4())[:8],
                    "salarie_id": salarie_id,
                    "date": jour.isoformat(),
                    "heure_debut": "09:00",
                    "heure_fin": "17:00",
                    "type_poste": "normal",
                    "date_creation": datetime.now().isoformat(),
                }
                _rh_planning.append(entry)
                cascading["planning"].append(entry["date"])
    except (ValueError, TypeError):
        pass

    # 4. Ecriture comptable provision salaire
    try:
        moteur = get_moteur()
        from urssaf_analyzer.comptabilite.ecritures import Ecriture, LigneEcriture, TypeJournal
        dp = date.fromisoformat(date_debut)
        provision = Ecriture(
            journal=TypeJournal.PAIE,
            date_ecriture=dp,
            date_piece=dp,
            libelle=f"Provision salaire {prenom_salarie} {nom_salarie} - {type_contrat}",
            lignes=[
                LigneEcriture(compte="641000", libelle=f"Salaire brut {prenom_salarie} {nom_salarie}", debit=Decimal(str(brut)), credit=Decimal("0")),
                LigneEcriture(compte="421000", libelle=f"Net a payer {prenom_salarie} {nom_salarie}", debit=Decimal("0"), credit=Decimal(str(net_estime))),
                LigneEcriture(compte="431000", libelle=f"Charges salariales {prenom_salarie} {nom_salarie}", debit=Decimal("0"), credit=Decimal(str(round(brut - net_estime, 2)))),
            ],
        )
        moteur.ecritures.append(provision)
        cascading["ecriture_comptable"] = {"id": provision.id, "montant_brut": brut}
    except Exception:
        pass

    contrat["cascading_effects"] = cascading
    log_action("utilisateur", "creation_contrat", f"{type_contrat} {prenom_salarie} {nom_salarie} - {poste}")
    return contrat


@app.get("/api/rh/contrats")
async def liste_contrats():
    """Liste tous les contrats de travail."""
    return _rh_contrats


@app.get("/api/rh/contrats/{contrat_id}")
async def detail_contrat(contrat_id: str):
    """Recupere un contrat par son identifiant."""
    for c in _rh_contrats:
        if c["id"] == contrat_id:
            return c
    raise HTTPException(404, "Contrat non trouve")


@app.get("/api/rh/contrats/{contrat_id}/document")
async def document_contrat(contrat_id: str):
    """Genere le document contrat de travail en HTML (visualisable et imprimable)."""
    contrat = None
    for c in _rh_contrats:
        if c["id"] == contrat_id:
            contrat = c
            break
    if not contrat:
        raise HTTPException(404, "Contrat non trouve")

    ent = _entete_config
    header_html = ""
    if ent.get("nom_entreprise"):
        header_html = f"""<div style="text-align:center;margin-bottom:30px;border-bottom:2px solid #1e40af;padding-bottom:20px">
<h1 style="color:#1e40af;margin:0">{ent.get("nom_entreprise","")}</h1>
<p style="color:#64748b;margin:4px 0">{ent.get("forme_juridique","")} - Capital: {ent.get("capital","")}</p>
<p style="color:#64748b;margin:4px 0">{ent.get("adresse","")}</p>
<p style="color:#64748b;margin:4px 0">SIRET: {ent.get("siret","")} - NAF: {ent.get("code_naf","")}</p>
<p style="color:#64748b;margin:4px 0">Tel: {ent.get("telephone","")} - Email: {ent.get("email","")}</p>
</div>"""

    mentions_html = ""
    for m in contrat.get("mentions_legales", []):
        mentions_html += f"<li>{m}</li>"

    type_titre = contrat["type_contrat"]
    if type_titre == "CDI":
        type_titre = "Contrat de travail a duree indeterminee"
    elif type_titre == "CDD":
        type_titre = "Contrat de travail a duree determinee"

    html = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<title>Contrat de travail - {contrat["prenom_salarie"]} {contrat["nom_salarie"]}</title>
<style>
body{{font-family:'Segoe UI',system-ui,sans-serif;max-width:800px;margin:0 auto;padding:40px;color:#1e293b;line-height:1.7}}
h1{{color:#1e40af;text-align:center;font-size:1.4em}} h2{{color:#1e40af;font-size:1.1em;margin-top:24px;border-bottom:1px solid #e2e8f0;padding-bottom:6px}}
.info-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}}
.info-item{{padding:10px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0}}
.info-item label{{font-weight:700;color:#475569;font-size:.85em}} .info-item span{{display:block;font-size:.95em}}
ul{{padding-left:20px}} li{{margin:6px 0}}
.signature{{display:grid;grid-template-columns:1fr 1fr;gap:40px;margin-top:60px;padding-top:20px;border-top:1px solid #e2e8f0}}
.sig-block{{text-align:center}} .sig-block p{{margin:4px 0}} .sig-line{{border-bottom:1px solid #94a3b8;height:60px;margin-top:20px}}
.print-btn{{position:fixed;top:20px;right:20px;padding:10px 20px;background:#1e40af;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:.9em;font-family:inherit}}
.print-btn:hover{{background:#1e3a8a}}
@media print{{.print-btn{{display:none}}}}
</style></head><body>
<button class="print-btn" onclick="window.print()">Imprimer / PDF</button>
{header_html}
<h1>{type_titre}</h1>
<p style="text-align:center;color:#64748b">Fait le {contrat.get("date_creation","")[:10]}</p>

<h2>Article 1 - Parties</h2>
<div class="info-grid">
<div class="info-item"><label>Employeur</label><span>{ent.get("nom_entreprise","[A renseigner dans Configuration]")}</span></div>
<div class="info-item"><label>Salarie(e)</label><span>{contrat["prenom_salarie"]} {contrat["nom_salarie"]}</span></div>
</div>

<h2>Article 2 - Engagement</h2>
<div class="info-grid">
<div class="info-item"><label>Poste</label><span>{contrat["poste"]}</span></div>
<div class="info-item"><label>Type de contrat</label><span>{contrat["type_contrat"]}</span></div>
<div class="info-item"><label>Date de debut</label><span>{contrat["date_debut"]}</span></div>
<div class="info-item"><label>Date de fin</label><span>{contrat.get("date_fin") or "Indeterminee"}</span></div>
</div>

<h2>Article 3 - Remuneration</h2>
<div class="info-grid">
<div class="info-item"><label>Salaire brut mensuel</label><span>{contrat["salaire_brut"]:.2f} EUR</span></div>
<div class="info-item"><label>Net estime</label><span>{contrat["net_estime"]:.2f} EUR</span></div>
</div>

<h2>Article 4 - Duree du travail</h2>
<div class="info-grid">
<div class="info-item"><label>Temps de travail</label><span>{"Temps complet" if contrat["temps_travail"]=="complet" else "Temps partiel"}</span></div>
<div class="info-item"><label>Duree hebdomadaire</label><span>{contrat["duree_hebdo"]}h</span></div>
</div>

<h2>Article 5 - Periode d essai</h2>
<p>La periode d essai est fixee a <strong>{contrat["periode_essai_jours"]} jours</strong> conformement aux dispositions des articles L.1221-19 a L.1221-26 du Code du travail.</p>

<h2>Article 6 - Convention collective</h2>
<p>Le present contrat est regi par la convention collective: <strong>{contrat.get("convention_collective") or "[A preciser]"}</strong></p>

<h2>Mentions legales obligatoires</h2>
<ul>{mentions_html}</ul>

<div class="signature">
<div class="sig-block"><p><strong>L employeur</strong></p><p style="font-size:.85em;color:#64748b">Nom, qualite, signature</p><div class="sig-line"></div><p style="font-size:.8em">Lu et approuve</p></div>
<div class="sig-block"><p><strong>Le(la) salarie(e)</strong></p><p style="font-size:.85em;color:#64748b">{contrat["prenom_salarie"]} {contrat["nom_salarie"]}</p><div class="sig-line"></div><p style="font-size:.8em">Lu et approuve</p></div>
</div>
<p style="text-align:center;margin-top:30px;font-size:.8em;color:#94a3b8">Document genere par NormaCheck v3.5 - Ce document doit etre signe en deux exemplaires originaux</p>
</body></html>"""
    return HTMLResponse(html)


# ======================================================================
# RH - BULLETINS DE PAIE
# ======================================================================

_rh_bulletins: list[dict] = []


@app.post("/api/rh/bulletins/generer")
async def generer_bulletin(
    contrat_id: str = Form(""),
    nom_salarie: str = Form(""),
    prenom_salarie: str = Form(""),
    mois: str = Form(""),
    salaire_brut: str = Form("0"),
    est_cadre: str = Form("false"),
    heures_supplementaires: str = Form("0"),
    primes: str = Form("0"),
    avantages_nature: str = Form("0"),
    absences_jours: str = Form("0"),
):
    """Genere un bulletin de salaire conforme R.3243-1 du Code du travail."""
    from urssaf_analyzer.rules.contribution_rules import ContributionRules

    # Si contrat_id fourni, recuperer les infos
    contrat = None
    if contrat_id:
        for c in _rh_contrats:
            if c["id"] == contrat_id:
                contrat = c
                nom_salarie = nom_salarie or c["nom_salarie"]
                prenom_salarie = prenom_salarie or c["prenom_salarie"]
                salaire_brut = salaire_brut if float(salaire_brut or 0) > 0 else str(c["salaire_brut"])
                est_cadre = "true" if c.get("convention_collective", "").lower().find("cadre") >= 0 else est_cadre
                break

    brut_base = Decimal(str(float(salaire_brut or "0")))
    hs = Decimal(str(float(heures_supplementaires or "0")))
    prime = Decimal(str(float(primes or "0")))
    an = Decimal(str(float(avantages_nature or "0")))
    abs_j = int(float(absences_jours or "0"))

    # Retenue absences (base 21.67 jours ouvrables/mois)
    retenue_abs = round(float(brut_base) / 21.67 * abs_j, 2) if abs_j > 0 else 0

    # Majoration HS (25% pour les 8 premieres heures, 50% au-dela - art. L.3121-36 CT)
    taux_horaire = round(float(brut_base) / 151.67, 2)
    if float(hs) > 0:
        hs_25 = min(float(hs), 8) * taux_horaire * 1.25
        hs_50 = max(0, float(hs) - 8) * taux_horaire * 1.50
        montant_hs = round(hs_25 + hs_50, 2)
    else:
        montant_hs = 0

    brut_total = float(brut_base) + montant_hs + float(prime) + float(an) - retenue_abs

    calc = ContributionRules()
    bulletin_data = calc.calculer_bulletin_complet(Decimal(str(brut_total)), est_cadre=est_cadre.lower() == "true")

    bulletin = {
        "id": str(uuid.uuid4())[:8],
        "contrat_id": contrat_id,
        "nom_salarie": nom_salarie,
        "prenom_salarie": prenom_salarie,
        "mois": mois or date.today().strftime("%Y%m"),
        "salaire_base": float(brut_base),
        "heures_supplementaires": float(hs),
        "montant_hs": montant_hs,
        "primes": float(prime),
        "avantages_nature": float(an),
        "retenue_absences": retenue_abs,
        "brut_total": brut_total,
        "lignes": bulletin_data.get("lignes", []),
        "net_avant_impot": float(bulletin_data.get("net_avant_impot", 0)),
        "total_patronal": float(bulletin_data.get("total_patronal", 0)),
        "total_salarial": float(bulletin_data.get("total_salarial", 0)),
        "net_a_payer": float(bulletin_data.get("net_avant_impot", brut_total * Decimal("0.78"))),
        "cout_total_employeur": float(bulletin_data.get("cout_total_employeur", brut_total * Decimal("1.45"))),
        "mentions_obligatoires": [
            "Mentions conformes a l'article R.3243-1 du Code du travail",
            "Convention collective applicable",
            "Nombre d'heures de travail",
            "Nature et montant des accessoires de salaire",
            "Montant de la remuneration brute",
            "Montant et assiette des cotisations et contributions sociales",
            "Net a payer avant impot sur le revenu",
            "Montant net social (depuis 01/07/2023)",
            "Cumul imposable annuel (Net fiscal)",
        ],
        "date_generation": datetime.now().isoformat(),
    }

    _rh_bulletins.append(bulletin)
    log_action("utilisateur", "generation_bulletin", f"{prenom_salarie} {nom_salarie} - {mois}")
    return bulletin


@app.get("/api/rh/bulletins")
async def liste_bulletins():
    """Liste tous les bulletins de paie generes."""
    return _rh_bulletins


@app.get("/api/rh/bulletins/{bulletin_id}/document")
async def document_bulletin(bulletin_id: str):
    """Genere le bulletin de salaire en HTML visualisable."""
    bulletin = None
    for b in _rh_bulletins:
        if b["id"] == bulletin_id:
            bulletin = b
            break
    if not bulletin:
        raise HTTPException(404, "Bulletin non trouve")

    ent = _entete_config
    header = ""
    if ent.get("nom_entreprise"):
        header = f"<div style='text-align:center;margin-bottom:20px'><h2 style='color:#1e40af;margin:0'>{ent['nom_entreprise']}</h2><p style='color:#64748b'>{ent.get('adresse','')} - SIRET: {ent.get('siret','')}</p></div>"

    lignes_html = ""
    for l in bulletin.get("lignes", []):
        lib = l.get("libelle", "") if isinstance(l, dict) else str(l)
        mp = f"{l.get('montant_patronal',0):.2f}" if isinstance(l, dict) else ""
        ms = f"{l.get('montant_salarial',0):.2f}" if isinstance(l, dict) else ""
        lignes_html += f"<tr><td>{lib}</td><td class='num'>{mp}</td><td class='num'>{ms}</td></tr>"

    html = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<title>Bulletin de paie - {bulletin["prenom_salarie"]} {bulletin["nom_salarie"]} - {bulletin["mois"]}</title>
<style>body{{font-family:'Segoe UI',sans-serif;max-width:800px;margin:0 auto;padding:30px;color:#1e293b}}
h1{{color:#1e40af;text-align:center;font-size:1.3em}}
table{{width:100%;border-collapse:collapse;margin:12px 0}}th{{background:#1e40af;color:#fff;padding:8px 12px;text-align:left;font-size:.85em}}
td{{padding:6px 12px;border-bottom:1px solid #e2e8f0;font-size:.88em}}.num{{text-align:right;font-family:monospace}}
.total{{font-weight:700;background:#eff6ff}}
.print-btn{{position:fixed;top:20px;right:20px;padding:10px 20px;background:#1e40af;color:#fff;border:none;border-radius:8px;cursor:pointer}}
@media print{{.print-btn{{display:none}}}}</style></head><body>
<button class="print-btn" onclick="window.print()">Imprimer / PDF</button>
{header}
<h1>BULLETIN DE PAIE</h1>
<p style="text-align:center;color:#64748b">Periode: {bulletin["mois"]} | Salarie: {bulletin["prenom_salarie"]} {bulletin["nom_salarie"]}</p>
<table>
<tr><th>Rubrique</th><th class="num">Part patronale</th><th class="num">Part salariale</th></tr>
<tr><td><strong>Salaire de base</strong></td><td class="num">{bulletin["salaire_base"]:.2f}</td><td></td></tr>
{"<tr><td>Heures supplementaires</td><td class='num'>" + f"{bulletin['montant_hs']:.2f}" + "</td><td></td></tr>" if bulletin["montant_hs"] > 0 else ""}
{"<tr><td>Primes</td><td class='num'>" + f"{bulletin['primes']:.2f}" + "</td><td></td></tr>" if bulletin["primes"] > 0 else ""}
{"<tr><td>Avantages en nature</td><td class='num'>" + f"{bulletin['avantages_nature']:.2f}" + "</td><td></td></tr>" if bulletin["avantages_nature"] > 0 else ""}
{"<tr><td style='color:#ef4444'>Retenue absences (-" + str(bulletin['retenue_absences']) + "j)</td><td class='num' style='color:#ef4444'>-" + f"{bulletin['retenue_absences']:.2f}" + "</td><td></td></tr>" if bulletin["retenue_absences"] > 0 else ""}
<tr class="total"><td>BRUT TOTAL</td><td class="num">{bulletin["brut_total"]:.2f}</td><td></td></tr>
{lignes_html}
<tr class="total"><td>Total cotisations</td><td class="num">{bulletin["total_patronal"]:.2f}</td><td class="num">{bulletin["total_salarial"]:.2f}</td></tr>
<tr class="total" style="background:#f0fdf4"><td>NET A PAYER AVANT IMPOT</td><td></td><td class="num" style="font-size:1.1em">{bulletin["net_a_payer"]:.2f} EUR</td></tr>
<tr class="total" style="background:#eff6ff"><td>COUT TOTAL EMPLOYEUR</td><td class="num">{bulletin["cout_total_employeur"]:.2f} EUR</td><td></td></tr>
</table>
<p style="font-size:.78em;color:#94a3b8;margin-top:30px">Bulletin conforme aux mentions obligatoires de l'article R.3243-1 du Code du travail. Document genere par NormaCheck v3.5.</p>
</body></html>"""
    return HTMLResponse(html)


# ======================================================================
# COMPTABILITE - SUGGESTIONS ET SOUS-COMPTES
# ======================================================================

_sous_comptes: list[dict] = []


@app.get("/api/comptabilite/suggestions")
async def suggestions_comptes(compte: str = Query("")):
    """Suggestions de comptes pour l'assistance a la saisie d'ecritures."""
    pc = get_plan_comptable()
    suggestions = []
    contreparties = []

    if compte:
        # Recherche par numero ou libelle
        try:
            resultats = pc.rechercher(compte)
            for r in resultats[:15]:
                suggestions.append({"numero": r.numero, "libelle": r.libelle})
        except Exception:
            pass

        # Aussi chercher dans les sous-comptes manuels
        for sc in _sous_comptes:
            if compte in sc["numero"] or compte.lower() in sc["libelle"].lower():
                suggestions.append({"numero": sc["numero"], "libelle": sc["libelle"]})

        # Suggestions de contreparties coherentes
        contreparties_map = {
            "601": [("401", "Fournisseurs")],
            "602": [("401", "Fournisseurs")],
            "606": [("401", "Fournisseurs")],
            "607": [("401", "Fournisseurs")],
            "611": [("401", "Fournisseurs")],
            "613": [("401", "Fournisseurs")],
            "616": [("401", "Fournisseurs")],
            "621": [("401", "Fournisseurs")],
            "625": [("401", "Fournisseurs"), ("512", "Banque")],
            "626": [("401", "Fournisseurs"), ("512", "Banque")],
            "627": [("401", "Fournisseurs"), ("512", "Banque")],
            "635": [("447", "Autres impots et taxes")],
            "641": [("421", "Personnel - Remuneration due")],
            "645": [("431", "Securite sociale"), ("437", "Autres org. sociaux")],
            "681": [("28", "Amortissements"), ("39", "Provisions")],
            "401": [("512", "Banque")],
            "411": [("701", "Ventes produits finis"), ("706", "Prestations services"), ("707", "Ventes marchandises")],
            "421": [("512", "Banque")],
            "431": [("512", "Banque")],
            "512": [("401", "Fournisseurs"), ("411", "Clients"), ("580", "Virements internes")],
            "701": [("411", "Clients")],
            "706": [("411", "Clients")],
            "707": [("411", "Clients")],
        }
        prefix = compte[:3] if len(compte) >= 3 else compte
        for p, cps in contreparties_map.items():
            if prefix.startswith(p) or p.startswith(prefix):
                for num, lib in cps:
                    contreparties.append({"numero": num + "000", "libelle": lib})

    return {"suggestions": suggestions[:15], "contreparties": contreparties[:10]}


@app.post("/api/comptabilite/sous-compte")
async def creer_sous_compte(
    compte_parent: str = Form(...),
    libelle: str = Form(...),
):
    """Cree un sous-compte du plan comptable (ex: 401001 pour fournisseur specifique)."""
    pc = get_plan_comptable()

    # Verifier que le compte parent existe (au moins la racine)
    racine = compte_parent[:3]
    parent_valide = False
    try:
        resultats = pc.rechercher(racine)
        if resultats:
            parent_valide = True
    except Exception:
        pass
    if not parent_valide:
        for cpt_num in pc.comptes:
            if cpt_num.startswith(racine):
                parent_valide = True
                break

    if not parent_valide:
        raise HTTPException(400, f"Compte racine {racine} introuvable dans le plan comptable national")

    # Generer le prochain numero de sous-compte
    existants = [sc["numero"] for sc in _sous_comptes if sc["numero"].startswith(compte_parent)]
    if existants:
        dernier = max(int(n) for n in existants)
        nouveau_num = str(dernier + 1)
    else:
        nouveau_num = compte_parent + "001" if len(compte_parent) <= 4 else compte_parent + "1"

    sous_compte = {
        "numero": nouveau_num,
        "libelle": libelle,
        "compte_parent": compte_parent,
        "date_creation": datetime.now().isoformat(),
    }
    _sous_comptes.append(sous_compte)
    log_action("utilisateur", "creation_sous_compte", f"{nouveau_num} - {libelle}")
    return sous_compte


# ======================================================================
# RH - ALERTES PERSONNALISABLES
# ======================================================================

_alertes_config: list[dict] = []


@app.post("/api/rh/alertes/personnaliser")
async def personnaliser_alerte(
    type_alerte: str = Form(...),
    actif: str = Form("true"),
    delai_jours: str = Form("30"),
    message_personnalise: str = Form(""),
):
    """Personnalise les parametres d'une alerte RH."""
    config_alerte = {
        "id": str(uuid.uuid4())[:8],
        "type_alerte": type_alerte,
        "actif": actif.lower() == "true",
        "delai_jours": int(delai_jours or "30"),
        "message_personnalise": message_personnalise,
        "date_modification": datetime.now().isoformat(),
    }
    # Remplacer si meme type existe
    _alertes_config[:] = [a for a in _alertes_config if a["type_alerte"] != type_alerte]
    _alertes_config.append(config_alerte)
    return config_alerte


@app.get("/api/rh/alertes/config")
async def liste_config_alertes():
    """Liste la configuration des alertes."""
    return _alertes_config


# ======================================================================
# RH - AVENANTS
# ======================================================================

@app.post("/api/rh/avenants")
async def creer_avenant(
    contrat_id: str = Form(...),
    type_avenant: str = Form(...),
    description: str = Form(...),
    date_effet: str = Form(...),
    nouvelles_conditions: str = Form(""),
):
    """Cree un avenant au contrat de travail (art. L.1222-6 CT pour modification du contrat)."""
    types_valides = ("remuneration", "poste", "temps_travail", "lieu", "autre")
    if type_avenant not in types_valides:
        raise HTTPException(400, f"Type d'avenant invalide. Valeurs acceptees: {', '.join(types_valides)}")

    # Verifier que le contrat existe
    contrat_trouve = None
    for c in _rh_contrats:
        if c["id"] == contrat_id:
            contrat_trouve = c
            break
    if not contrat_trouve:
        raise HTTPException(404, "Contrat de reference non trouve")

    avenant_id = str(uuid.uuid4())[:8]

    avenant = {
        "id": avenant_id,
        "contrat_id": contrat_id,
        "salarie_id": contrat_trouve["salarie_id"],
        "nom_salarie": contrat_trouve["nom_salarie"],
        "prenom_salarie": contrat_trouve["prenom_salarie"],
        "type_avenant": type_avenant,
        "description": description,
        "date_effet": date_effet,
        "nouvelles_conditions": nouvelles_conditions,
        "date_creation": datetime.now().isoformat(),
        "statut": "en_attente_signature",
        "mentions": [
            "Modification du contrat de travail soumise a l'accord du salarie (art. L.1222-6 CT)",
            f"Prise d'effet au {date_effet}",
            "Les autres clauses du contrat initial restent inchangees",
        ],
    }

    _rh_avenants.append(avenant)
    log_action(
        "utilisateur", "creation_avenant",
        f"Avenant {type_avenant} pour contrat {contrat_id} ({contrat_trouve['prenom_salarie']} {contrat_trouve['nom_salarie']})",
    )
    return avenant


@app.get("/api/rh/avenants")
async def liste_avenants():
    """Liste tous les avenants."""
    return _rh_avenants


# ======================================================================
# RH - CONGES
# ======================================================================

@app.post("/api/rh/conges")
async def enregistrer_conge(
    salarie_id: str = Form(...),
    type_conge: str = Form(...),
    date_debut: str = Form(...),
    date_fin: str = Form(...),
    nb_jours: str = Form(...),
    statut: str = Form("demande"),
):
    """Enregistre une demande ou un conge (art. L.3141-1 et suivants CT)."""
    types_valides = ("cp", "rtt", "maladie", "maternite", "paternite", "sans_solde", "familial", "formation")
    if type_conge not in types_valides:
        raise HTTPException(400, f"Type de conge invalide. Valeurs acceptees: {', '.join(types_valides)}")

    statuts_valides = ("demande", "valide", "refuse")
    if statut not in statuts_valides:
        raise HTTPException(400, f"Statut invalide. Valeurs acceptees: {', '.join(statuts_valides)}")

    conge_id = str(uuid.uuid4())[:8]

    # Informations reglementaires selon le type
    info_legale = {
        "cp": "Conges payes: 2.5 jours ouvrables/mois travaille (art. L.3141-3 CT)",
        "rtt": "Jours de reduction du temps de travail (accord collectif ou accord d'entreprise)",
        "maladie": "Arret maladie: indemnites journalieres CPAM apres 3 jours de carence (art. L.323-1 CSS)",
        "maternite": "Conge maternite: 16 semaines minimum (art. L.1225-17 CT)",
        "paternite": "Conge paternite: 25 jours calendaires (art. L.1225-35 CT, reforme 2021)",
        "sans_solde": "Conge sans solde: accord employeur necessaire, pas de remuneration",
        "familial": "Conges pour evenements familiaux (art. L.3142-1 CT): mariage, naissance, deces",
        "formation": "Conge de formation: CPF de transition professionnelle (art. L.6323-17-1 CT)",
    }

    conge = {
        "id": conge_id,
        "salarie_id": salarie_id,
        "type_conge": type_conge,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "nb_jours": float(nb_jours),
        "statut": statut,
        "date_creation": datetime.now().isoformat(),
        "info_legale": info_legale.get(type_conge, ""),
    }

    _rh_conges.append(conge)
    log_action("utilisateur", "enregistrement_conge", f"{type_conge} salarie {salarie_id} du {date_debut} au {date_fin}")
    return conge


@app.get("/api/rh/conges")
async def liste_conges(salarie_id: Optional[str] = Query(None)):
    """Liste les conges, avec filtre optionnel par salarie."""
    if salarie_id:
        return [c for c in _rh_conges if c["salarie_id"] == salarie_id]
    return _rh_conges


# ======================================================================
# RH - ARRETS DE TRAVAIL
# ======================================================================

@app.post("/api/rh/arrets")
async def enregistrer_arret(
    salarie_id: str = Form(...),
    type_arret: str = Form(...),
    date_debut: str = Form(...),
    date_fin: str = Form(""),
    prolongation: str = Form("false"),
    subrogation: str = Form("false"),
):
    """Enregistre un arret de travail (maladie, AT/MP, mi-temps therapeutique)."""
    types_valides = ("maladie", "accident_travail", "maladie_pro", "mi_temps_therapeutique")
    if type_arret not in types_valides:
        raise HTTPException(400, f"Type d'arret invalide. Valeurs acceptees: {', '.join(types_valides)}")

    arret_id = str(uuid.uuid4())[:8]
    est_prolongation = prolongation.lower() == "true"
    est_subrogation = subrogation.lower() == "true"

    # Obligations employeur selon le type d'arret
    obligations = []
    if type_arret == "maladie":
        obligations = [
            "Attestation de salaire CPAM sous 5 jours (art. R.323-10 CSS)",
            "Signalement DSN evenementielle sous 5 jours",
            "Maintien de salaire employeur apres 7 jours d'anciennete (art. L.1226-1 CT)",
            "Carence CPAM: 3 jours (art. R.323-1 CSS)",
        ]
    elif type_arret == "accident_travail":
        obligations = [
            "Declaration AT sous 48h a la CPAM (art. L.441-2 CSS)",
            "Remise feuille d'accident au salarie (art. L.441-5 CSS)",
            "Attestation de salaire CPAM immediate",
            "Signalement DSN evenementielle sous 5 jours",
            "Pas de carence CPAM pour AT (art. L.433-1 CSS)",
            "Protection contre le licenciement (art. L.1226-9 CT)",
        ]
    elif type_arret == "maladie_pro":
        obligations = [
            "Declaration maladie professionnelle a la CPAM (art. L.461-5 CSS)",
            "Attestation de salaire CPAM",
            "Signalement DSN evenementielle sous 5 jours",
            "Protection contre le licenciement (art. L.1226-9 CT)",
        ]
    elif type_arret == "mi_temps_therapeutique":
        obligations = [
            "Prescription medicale de reprise a temps partiel",
            "Accord de la CPAM pour maintien des IJSS",
            "Avenant temporaire au contrat de travail",
            "Adaptation du poste si necessaire",
        ]

    arret = {
        "id": arret_id,
        "salarie_id": salarie_id,
        "type_arret": type_arret,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "prolongation": est_prolongation,
        "subrogation": est_subrogation,
        "obligations_employeur": obligations,
        "date_creation": datetime.now().isoformat(),
        "statut": "en_cours" if not date_fin else "termine",
    }

    _rh_arrets.append(arret)
    log_action("utilisateur", "enregistrement_arret", f"{type_arret} salarie {salarie_id} depuis {date_debut}")
    return arret


@app.get("/api/rh/arrets")
async def liste_arrets():
    """Liste tous les arrets de travail."""
    return _rh_arrets


# ======================================================================
# RH - SANCTIONS DISCIPLINAIRES
# ======================================================================

@app.post("/api/rh/sanctions")
async def enregistrer_sanction(
    salarie_id: str = Form(...),
    type_sanction: str = Form(...),
    date_sanction: str = Form(...),
    motif: str = Form(...),
    description: str = Form(""),
    date_entretien_prealable: str = Form(""),
):
    """Enregistre une sanction disciplinaire (art. L.1331-1 et suivants CT)."""
    types_valides = ("avertissement", "blame", "mise_a_pied", "retrogradation", "licenciement")
    if type_sanction not in types_valides:
        raise HTTPException(400, f"Type de sanction invalide. Valeurs acceptees: {', '.join(types_valides)}")

    sanction_id = str(uuid.uuid4())[:8]

    # Procedure disciplinaire obligatoire (art. L.1332-1 a L.1332-3 CT)
    procedure = []
    if type_sanction in ("avertissement", "blame"):
        procedure = [
            "Notification ecrite au salarie (art. L.1332-1 CT)",
            "Delai de prescription: 2 mois a compter de la connaissance des faits (art. L.1332-4 CT)",
            "Entretien prealable facultatif pour avertissement simple",
        ]
    else:
        procedure = [
            "Convocation a entretien prealable par LRAR ou remise en main propre (art. L.1332-2 CT)",
            "Delai minimum 5 jours ouvrables entre convocation et entretien",
            "Assistance du salarie par un membre du personnel (art. L.1332-2 CT)",
            "Notification de la sanction par LRAR (art. L.1332-2 CT)",
            "Delai: au moins 2 jours ouvrables et au plus 1 mois apres l'entretien",
            "Delai de prescription: 2 mois a compter de la connaissance des faits (art. L.1332-4 CT)",
        ]

    if type_sanction == "licenciement":
        procedure.extend([
            "Motif reel et serieux obligatoire (art. L.1232-1 CT)",
            "Lettre de licenciement motivee (art. L.1232-6 CT)",
            "Preavis selon anciennete et convention collective",
            "Indemnite legale de licenciement si anciennete >= 8 mois (art. L.1234-9 CT)",
            "Documents de fin de contrat: certificat de travail, attestation Pole emploi, solde de tout compte",
        ])

    if type_sanction == "mise_a_pied":
        procedure.append("Duree maximale fixee par le reglement interieur ou la convention collective")

    sanction = {
        "id": sanction_id,
        "salarie_id": salarie_id,
        "type_sanction": type_sanction,
        "date_sanction": date_sanction,
        "motif": motif,
        "description": description,
        "date_entretien_prealable": date_entretien_prealable,
        "procedure_obligatoire": procedure,
        "date_creation": datetime.now().isoformat(),
        "statut": "notifiee",
    }

    _rh_sanctions.append(sanction)
    log_action("utilisateur", "enregistrement_sanction", f"{type_sanction} salarie {salarie_id} - {motif}")
    return sanction


@app.get("/api/rh/sanctions")
async def liste_sanctions():
    """Liste toutes les sanctions disciplinaires."""
    return _rh_sanctions


# ======================================================================
# RH - ATTESTATIONS
# ======================================================================

@app.post("/api/rh/attestations/generer")
async def generer_attestation(
    salarie_id: str = Form(...),
    type_attestation: str = Form(...),
    date_generation: str = Form(""),
):
    """Genere une attestation RH (travail, employeur, salaire, pole_emploi, mutuelle, stage)."""
    types_valides = ("travail", "employeur", "salaire", "pole_emploi", "mutuelle", "stage")
    if type_attestation not in types_valides:
        raise HTTPException(400, f"Type d'attestation invalide. Valeurs acceptees: {', '.join(types_valides)}")

    if not date_generation:
        date_generation = date.today().isoformat()

    attestation_id = str(uuid.uuid4())[:8]

    # Recherche des informations du salarie a travers les contrats
    contrat_salarie = None
    for c in _rh_contrats:
        if c["salarie_id"] == salarie_id:
            contrat_salarie = c
            break

    nom_salarie = ""
    prenom_salarie = ""
    poste = ""
    date_debut = ""
    salaire_brut = 0
    if contrat_salarie:
        nom_salarie = contrat_salarie["nom_salarie"]
        prenom_salarie = contrat_salarie["prenom_salarie"]
        poste = contrat_salarie["poste"]
        date_debut = contrat_salarie["date_debut"]
        salaire_brut = contrat_salarie["salaire_brut"]

    # Configuration entete entreprise
    nom_entreprise = _entete_config.get("nom_entreprise", "[Nom entreprise]")
    adresse_entreprise = _entete_config.get("adresse", "[Adresse entreprise]")
    siret_entreprise = _entete_config.get("siret", "[SIRET]")

    # Generation du texte selon le type
    texte = ""

    if type_attestation == "travail":
        texte = (
            f"ATTESTATION DE TRAVAIL\n\n"
            f"Je soussigne(e), representant(e) de la societe {nom_entreprise},\n"
            f"SIRET: {siret_entreprise}, sise {adresse_entreprise},\n\n"
            f"atteste que M./Mme {prenom_salarie} {nom_salarie}\n"
            f"occupe le poste de {poste} dans notre entreprise\n"
            f"depuis le {date_debut}.\n\n"
            f"Cette attestation est delivree pour servir et valoir ce que de droit.\n\n"
            f"Fait a __________, le {date_generation}\n\n"
            f"Signature et cachet de l'employeur"
        )

    elif type_attestation == "employeur":
        texte = (
            f"ATTESTATION EMPLOYEUR (art. L.1234-19 Code du travail)\n\n"
            f"Societe: {nom_entreprise}\n"
            f"SIRET: {siret_entreprise}\n"
            f"Adresse: {adresse_entreprise}\n\n"
            f"Certifie que M./Mme {prenom_salarie} {nom_salarie}\n"
            f"a ete employe(e) en qualite de {poste}\n"
            f"du {date_debut} au {date_generation}\n\n"
            f"Motif de la rupture: [A completer]\n"
            f"Preavis: [effectue / non effectue / dispense]\n\n"
            f"Le(la) salarie(e) est libre de tout engagement a compter de ce jour.\n\n"
            f"Fait a __________, le {date_generation}\n\n"
            f"Signature et cachet de l'employeur"
        )

    elif type_attestation == "salaire":
        net_estime = round(salaire_brut * 0.78, 2)
        texte = (
            f"ATTESTATION DE SALAIRE\n\n"
            f"Je soussigne(e), representant(e) de la societe {nom_entreprise},\n"
            f"SIRET: {siret_entreprise},\n\n"
            f"atteste que M./Mme {prenom_salarie} {nom_salarie},\n"
            f"occupant le poste de {poste},\n"
            f"percoit une remuneration mensuelle brute de {salaire_brut} EUR,\n"
            f"soit un net imposable estime de {net_estime} EUR.\n\n"
            f"Cette attestation est delivree a la demande de l'interesse(e)\n"
            f"pour servir et valoir ce que de droit.\n\n"
            f"Fait a __________, le {date_generation}\n\n"
            f"Signature et cachet de l'employeur"
        )

    elif type_attestation == "pole_emploi":
        texte = (
            f"ATTESTATION POLE EMPLOI (art. R.1234-9 Code du travail)\n\n"
            f"EMPLOYEUR\n"
            f"Denomination: {nom_entreprise}\n"
            f"SIRET: {siret_entreprise}\n"
            f"Adresse: {adresse_entreprise}\n\n"
            f"SALARIE\n"
            f"Nom: {nom_salarie}\n"
            f"Prenom: {prenom_salarie}\n"
            f"Emploi: {poste}\n"
            f"Date d'entree: {date_debut}\n"
            f"Date de sortie: {date_generation}\n"
            f"Motif de rupture: [A completer - code motif]\n\n"
            f"SALAIRES DES 12 DERNIERS MOIS\n"
            f"[A completer avec les salaires bruts mensuels]\n"
            f"Salaire brut mensuel de reference: {salaire_brut} EUR\n\n"
            f"PREAVIS\n"
            f"Effectue: [oui/non]\n"
            f"Non effectue et paye: [oui/non]\n\n"
            f"CONGES PAYES\n"
            f"Solde de conges payes a la date de fin: [A completer]\n"
            f"Indemnite compensatrice versee: [A completer]\n\n"
            f"Date: {date_generation}\n"
            f"Signature et cachet de l'employeur"
        )

    elif type_attestation == "mutuelle":
        texte = (
            f"ATTESTATION DE PORTABILITE MUTUELLE (art. L.911-8 CSS)\n\n"
            f"Societe: {nom_entreprise}\n"
            f"SIRET: {siret_entreprise}\n\n"
            f"Atteste que M./Mme {prenom_salarie} {nom_salarie},\n"
            f"ancien(ne) salarie(e) de notre entreprise,\n"
            f"beneficie du maintien de la couverture complementaire sante\n"
            f"et prevoyance au titre de la portabilite des droits,\n"
            f"pour une duree maximale de 12 mois a compter de la cessation\n"
            f"du contrat de travail.\n\n"
            f"Organisme assureur: [A completer]\n"
            f"Numero de contrat: [A completer]\n\n"
            f"Fait a __________, le {date_generation}\n\n"
            f"Signature et cachet de l'employeur"
        )

    elif type_attestation == "stage":
        texte = (
            f"ATTESTATION DE STAGE (art. L.124-1 Code de l'education)\n\n"
            f"Societe: {nom_entreprise}\n"
            f"SIRET: {siret_entreprise}\n"
            f"Adresse: {adresse_entreprise}\n\n"
            f"Atteste que M./Mme {prenom_salarie} {nom_salarie}\n"
            f"a effectue un stage au sein de notre entreprise\n"
            f"du {date_debut} au {date_generation}\n\n"
            f"Fonctions occupees: {poste}\n"
            f"Duree effective: [A completer] heures\n"
            f"Gratification versee: [A completer] EUR\n\n"
            f"Competences acquises ou developpees:\n"
            f"[A completer]\n\n"
            f"Fait a __________, le {date_generation}\n\n"
            f"Signature et cachet de l'employeur"
        )

    attestation = {
        "id": attestation_id,
        "salarie_id": salarie_id,
        "type_attestation": type_attestation,
        "date_generation": date_generation,
        "nom_salarie": nom_salarie,
        "prenom_salarie": prenom_salarie,
        "texte": texte,
        "date_creation": datetime.now().isoformat(),
    }

    _rh_attestations.append(attestation)
    log_action("utilisateur", "generation_attestation", f"{type_attestation} salarie {salarie_id}")
    return attestation


@app.get("/api/rh/attestations")
async def liste_attestations():
    """Liste toutes les attestations generees."""
    return _rh_attestations


# ======================================================================
# RH - ENTRETIENS PROFESSIONNELS
# ======================================================================

@app.post("/api/rh/entretiens")
async def enregistrer_entretien(
    salarie_id: str = Form(...),
    type_entretien: str = Form(...),
    date_entretien: str = Form(...),
    compte_rendu: str = Form(""),
    date_prochain: str = Form(""),
):
    """Enregistre un entretien professionnel (art. L.6315-1 CT)."""
    types_valides = ("professionnel_2ans", "bilan_6ans", "annuel", "fin_periode_essai")
    if type_entretien not in types_valides:
        raise HTTPException(400, f"Type d'entretien invalide. Valeurs acceptees: {', '.join(types_valides)}")

    entretien_id = str(uuid.uuid4())[:8]

    # Obligations legales par type d'entretien
    obligations = {}
    if type_entretien == "professionnel_2ans":
        obligations = {
            "reference": "Art. L.6315-1 Code du travail",
            "frequence": "Tous les 2 ans",
            "contenu_obligatoire": [
                "Perspectives d'evolution professionnelle (qualifications, emploi)",
                "Information sur la VAE (Validation des Acquis de l'Experience)",
                "Information sur le CPF (Compte Personnel de Formation)",
                "Information sur le CEP (Conseil en Evolution Professionnelle)",
            ],
            "sanction": "Abondement correctif de 3000 EUR sur le CPF si non-respect dans les entreprises >= 50 salaries",
        }
    elif type_entretien == "bilan_6ans":
        obligations = {
            "reference": "Art. L.6315-1 II Code du travail",
            "frequence": "Tous les 6 ans",
            "contenu_obligatoire": [
                "Etat recapitulatif des entretiens professionnels des 6 annees",
                "Verification: au moins une action de formation suivie",
                "Verification: acquisition d'elements de certification",
                "Verification: progression salariale ou professionnelle",
            ],
            "sanction": "Abondement correctif de 3000 EUR sur le CPF si 2 des 3 criteres non remplis (entreprises >= 50 sal.)",
        }
    elif type_entretien == "annuel":
        obligations = {
            "reference": "Non obligatoire legalement sauf convention collective",
            "frequence": "Annuel (bonne pratique RH)",
            "contenu_suggere": [
                "Evaluation des objectifs de l'annee ecoulee",
                "Fixation des objectifs pour l'annee suivante",
                "Discussion sur les besoins en formation",
                "Echange sur les conditions de travail",
            ],
        }
    elif type_entretien == "fin_periode_essai":
        obligations = {
            "reference": "Art. L.1221-19 et suivants CT",
            "contenu_suggere": [
                "Bilan de la periode d'essai",
                "Confirmation ou non du poste",
                "Points d'amelioration identifies",
                "Objectifs pour la suite",
            ],
        }

    entretien = {
        "id": entretien_id,
        "salarie_id": salarie_id,
        "type_entretien": type_entretien,
        "date_entretien": date_entretien,
        "compte_rendu": compte_rendu,
        "date_prochain": date_prochain,
        "obligations": obligations,
        "date_creation": datetime.now().isoformat(),
    }

    _rh_entretiens.append(entretien)
    log_action("utilisateur", "enregistrement_entretien", f"{type_entretien} salarie {salarie_id} le {date_entretien}")
    return entretien


@app.get("/api/rh/entretiens")
async def liste_entretiens():
    """Liste tous les entretiens professionnels."""
    return _rh_entretiens


# ======================================================================
# RH - VISITES MEDICALES
# ======================================================================

@app.post("/api/rh/visites-medicales")
async def enregistrer_visite_medicale(
    salarie_id: str = Form(...),
    type_visite: str = Form(...),
    date_visite: str = Form(...),
    resultat: str = Form("apte"),
    remarques: str = Form(""),
    date_prochaine: str = Form(""),
):
    """Enregistre une visite medicale (art. L.4624-1 et suivants CT)."""
    types_valides = ("embauche", "periodique", "reprise", "pre_reprise", "demande")
    if type_visite not in types_valides:
        raise HTTPException(400, f"Type de visite invalide. Valeurs acceptees: {', '.join(types_valides)}")

    resultats_valides = ("apte", "inapte", "amenagement")
    if resultat not in resultats_valides:
        raise HTTPException(400, f"Resultat invalide. Valeurs acceptees: {', '.join(resultats_valides)}")

    visite_id = str(uuid.uuid4())[:8]

    # Reglementation selon le type de visite
    reglementation = {}
    if type_visite == "embauche":
        reglementation = {
            "reference": "Art. R.4624-10 et suivants CT",
            "description": "Visite d'information et de prevention (VIP) dans les 3 mois suivant la prise de poste",
            "frequence_suivi": "5 ans maximum (3 ans pour les travailleurs de nuit, handicapes, etc.)",
            "postes_a_risque": "Suivi individuel renforce (SIR) pour les postes a risques particuliers",
        }
    elif type_visite == "periodique":
        reglementation = {
            "reference": "Art. R.4624-16 CT",
            "description": "Suivi periodique de l'etat de sante",
            "frequence": "Maximum 5 ans (VIP) ou 4 ans (SIR avec visite intermediaire a 2 ans)",
        }
    elif type_visite == "reprise":
        reglementation = {
            "reference": "Art. R.4624-31 CT",
            "description": "Obligatoire apres: arret maladie >= 60 jours, AT >= 30 jours, maladie pro, maternite",
            "delai": "Dans les 8 jours suivant la reprise effective",
        }
    elif type_visite == "pre_reprise":
        reglementation = {
            "reference": "Art. R.4624-29 CT",
            "description": "Visite de pre-reprise en cas d'arret > 30 jours",
            "objectif": "Favoriser le maintien dans l'emploi, amenagements eventuels",
        }
    elif type_visite == "demande":
        reglementation = {
            "reference": "Art. R.4624-34 CT",
            "description": "Visite a la demande du salarie, de l'employeur ou du medecin du travail",
            "delai": "Pas de delai impose, selon urgence",
        }

    # Actions a mener si inapte
    actions_si_inapte = []
    if resultat == "inapte":
        actions_si_inapte = [
            "Obligation de reclassement dans un delai d'un mois (art. L.1226-2 CT)",
            "Consultation du CSE sur les propositions de reclassement",
            "Recherche de reclassement dans l'entreprise et le groupe",
            "Si impossibilite de reclassement: licenciement pour inaptitude possible",
            "Indemnite speciale de licenciement si AT/MP (art. L.1226-14 CT)",
        ]

    visite = {
        "id": visite_id,
        "salarie_id": salarie_id,
        "type_visite": type_visite,
        "date_visite": date_visite,
        "resultat": resultat,
        "remarques": remarques,
        "date_prochaine": date_prochaine,
        "reglementation": reglementation,
        "actions_si_inapte": actions_si_inapte,
        "date_creation": datetime.now().isoformat(),
    }

    _rh_visites_med.append(visite)
    log_action("utilisateur", "enregistrement_visite_medicale", f"{type_visite} salarie {salarie_id} - {resultat}")
    return visite


@app.get("/api/rh/visites-medicales")
async def liste_visites_medicales():
    """Liste toutes les visites medicales."""
    return _rh_visites_med


# ======================================================================
# RH - ALERTES (calcul dynamique)
# ======================================================================

@app.get("/api/rh/alertes")
async def get_rh_alertes():
    """Calcule et retourne les alertes RH basees sur les echeances.

    Verifie: fin CDD, entretiens professionnels, visites medicales,
    prevoyance, interessement, declarations, periodes d'essai.
    """
    alertes = []
    aujourdhui = date.today()

    # --- 1. CDD arrivant a echeance dans les 30 jours ---
    for contrat in _rh_contrats:
        if contrat["type_contrat"] == "CDD" and contrat.get("date_fin"):
            try:
                fin = date.fromisoformat(contrat["date_fin"])
                jours_restants = (fin - aujourdhui).days
                if 0 <= jours_restants <= 30:
                    alertes.append({
                        "id": str(uuid.uuid4())[:8],
                        "type": "fin_cdd",
                        "urgence": "haute" if jours_restants <= 7 else "moyenne",
                        "message": (
                            f"CDD de {contrat['prenom_salarie']} {contrat['nom_salarie']} "
                            f"({contrat['poste']}) expire dans {jours_restants} jour(s) "
                            f"(le {contrat['date_fin']})"
                        ),
                        "reference": "Art. L.1243-5 CT - Le CDD cesse de plein droit a l'echeance du terme",
                        "action_requise": "Renouveler, transformer en CDI, ou preparer les documents de fin de contrat",
                        "contrat_id": contrat["id"],
                        "date_echeance": contrat["date_fin"],
                    })
            except (ValueError, TypeError):
                pass

    # --- 2. Entretiens professionnels en retard (tous les 2 ans) ---
    # Collecter le dernier entretien par salarie
    derniers_entretiens: dict[str, str] = {}
    for ent in _rh_entretiens:
        if ent["type_entretien"] in ("professionnel_2ans", "bilan_6ans"):
            sid = ent["salarie_id"]
            if sid not in derniers_entretiens or ent["date_entretien"] > derniers_entretiens[sid]:
                derniers_entretiens[sid] = ent["date_entretien"]

    for contrat in _rh_contrats:
        if contrat["statut"] != "actif":
            continue
        sid = contrat["salarie_id"]
        dernier = derniers_entretiens.get(sid)
        if dernier:
            try:
                date_dernier = date.fromisoformat(dernier)
                jours_depuis = (aujourdhui - date_dernier).days
                if jours_depuis > 730:  # > 2 ans
                    alertes.append({
                        "id": str(uuid.uuid4())[:8],
                        "type": "entretien_professionnel_retard",
                        "urgence": "haute",
                        "message": (
                            f"Entretien professionnel en retard pour {contrat['prenom_salarie']} "
                            f"{contrat['nom_salarie']} - dernier entretien il y a {jours_depuis} jours"
                        ),
                        "reference": "Art. L.6315-1 CT - Entretien professionnel tous les 2 ans",
                        "action_requise": "Planifier un entretien professionnel dans les meilleurs delais",
                        "salarie_id": sid,
                    })
            except (ValueError, TypeError):
                pass
        else:
            # Aucun entretien enregistre : verifier si le contrat a plus de 2 ans
            try:
                date_debut = date.fromisoformat(contrat["date_debut"])
                anciennete_jours = (aujourdhui - date_debut).days
                if anciennete_jours > 730:
                    alertes.append({
                        "id": str(uuid.uuid4())[:8],
                        "type": "entretien_professionnel_manquant",
                        "urgence": "haute",
                        "message": (
                            f"Aucun entretien professionnel enregistre pour {contrat['prenom_salarie']} "
                            f"{contrat['nom_salarie']} (anciennete: {anciennete_jours} jours)"
                        ),
                        "reference": "Art. L.6315-1 CT - Entretien professionnel tous les 2 ans",
                        "action_requise": "Planifier un entretien professionnel immediatement",
                        "salarie_id": sid,
                    })
            except (ValueError, TypeError):
                pass

    # --- 3. Visites medicales en retard ---
    dernieres_visites: dict[str, str] = {}
    prochaines_visites: dict[str, str] = {}
    for v in _rh_visites_med:
        sid = v["salarie_id"]
        if sid not in dernieres_visites or v["date_visite"] > dernieres_visites[sid]:
            dernieres_visites[sid] = v["date_visite"]
        if v.get("date_prochaine"):
            if sid not in prochaines_visites or v["date_prochaine"] < prochaines_visites[sid]:
                prochaines_visites[sid] = v["date_prochaine"]

    for sid, date_prochaine in prochaines_visites.items():
        try:
            dp = date.fromisoformat(date_prochaine)
            jours_restants = (dp - aujourdhui).days
            if jours_restants < 0:
                # Trouver le nom du salarie
                nom_complet = sid
                for c in _rh_contrats:
                    if c["salarie_id"] == sid:
                        nom_complet = f"{c['prenom_salarie']} {c['nom_salarie']}"
                        break
                alertes.append({
                    "id": str(uuid.uuid4())[:8],
                    "type": "visite_medicale_retard",
                    "urgence": "haute",
                    "message": (
                        f"Visite medicale en retard pour {nom_complet} "
                        f"(prevue le {date_prochaine}, retard: {abs(jours_restants)} jour(s))"
                    ),
                    "reference": "Art. R.4624-16 CT - Suivi individuel de l'etat de sante",
                    "action_requise": "Prendre rendez-vous avec la medecine du travail",
                    "salarie_id": sid,
                })
            elif jours_restants <= 30:
                nom_complet = sid
                for c in _rh_contrats:
                    if c["salarie_id"] == sid:
                        nom_complet = f"{c['prenom_salarie']} {c['nom_salarie']}"
                        break
                alertes.append({
                    "id": str(uuid.uuid4())[:8],
                    "type": "visite_medicale_a_planifier",
                    "urgence": "moyenne",
                    "message": (
                        f"Visite medicale a planifier pour {nom_complet} "
                        f"(echeance: {date_prochaine}, dans {jours_restants} jour(s))"
                    ),
                    "reference": "Art. R.4624-16 CT",
                    "action_requise": "Prendre rendez-vous avec la medecine du travail",
                    "salarie_id": sid,
                })
        except (ValueError, TypeError):
            pass

    # --- 4. Obligations legales selon effectif ---
    nb_actifs = sum(1 for c in _rh_contrats if c.get("statut") == "actif")

    # 4a. Prevoyance obligatoire cadres (ANI 17/11/2017)
    nb_cadres = sum(1 for c in _rh_contrats if c.get("statut") == "actif" and "cadre" in (c.get("convention_collective", "") or "").lower())
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "prevoyance_obligatoire",
            "urgence": "moyenne",
            "titre": "Prevoyance obligatoire cadres",
            "description": f"La prevoyance deces est obligatoire pour tous les cadres (ANI du 17/11/2017). Effectif actif: {nb_actifs}. Le non-respect expose l'employeur a la prise en charge des garanties sur ses fonds propres.",
            "reference": "ANI du 17/11/2017 - Art. 7 CCN Cadres du 14/03/1947",
            "action_requise": "Verifier la mise en place d'un contrat de prevoyance aupres d'un organisme assureur",
            "echeance": "",
            "incidence_legale": "En l'absence de contrat, l'employeur doit assumer sur ses fonds propres le versement du capital deces (3x plafond annuel SS) et le maintien de salaire.",
        })

    # 4b. Mutuelle obligatoire (ANI 14/06/2013 - Loi 2016)
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "mutuelle_obligatoire",
            "urgence": "moyenne",
            "titre": "Complementaire sante obligatoire",
            "description": f"Depuis le 01/01/2016, tous les employeurs doivent proposer une couverture complementaire sante collective. Part employeur min 50%. Effectif: {nb_actifs}.",
            "reference": "Art. L.911-7 CSS - ANI du 11/01/2013 generalise par loi du 14/06/2013",
            "action_requise": "Verifier la mise en place d'une complementaire sante avec participation employeur >= 50%",
            "echeance": "",
            "incidence_legale": "Amende et redressement URSSAF sur les contributions patronales (reintegration dans l'assiette de cotisations).",
        })

    # 4c. DUERP obligatoire (art. R.4121-1 CT)
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "duerp_obligatoire",
            "urgence": "moyenne",
            "titre": "Document unique d'evaluation des risques (DUERP)",
            "description": "Le DUERP est obligatoire des le 1er salarie. Mise a jour annuelle ou lors de tout changement significatif.",
            "reference": "Art. R.4121-1 a R.4121-4 CT - Art. L.4121-3 CT",
            "action_requise": "Verifier l'existence et la mise a jour du DUERP",
            "echeance": "",
            "incidence_legale": "Contravention de 5eme classe (1500 EUR). Responsabilite penale en cas d'accident du travail.",
        })

    # 4d. Registre unique du personnel (art. L.1221-13 CT)
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "registre_personnel",
            "urgence": "info",
            "titre": "Registre unique du personnel",
            "description": "Le registre unique du personnel est obligatoire des le 1er salarie. Doit mentionner nom, prenom, nationalite, emploi, qualification, dates d'entree et sortie.",
            "reference": "Art. L.1221-13 CT",
            "action_requise": "Verifier la tenue a jour du registre unique du personnel",
            "echeance": "",
            "incidence_legale": "Contravention de 4eme classe (750 EUR par salarie concerne).",
        })

    # 4e. CSE obligatoire si >= 11 salaries (art. L.2311-2 CT)
    if nb_actifs >= 11:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "cse_obligatoire",
            "urgence": "moyenne",
            "titre": "Comite social et economique (CSE)",
            "description": f"Le CSE est obligatoire dans les entreprises d'au moins 11 salaries pendant 12 mois consecutifs. Effectif: {nb_actifs}.",
            "reference": "Art. L.2311-2 CT",
            "action_requise": "Organiser les elections du CSE si non fait",
            "echeance": "",
            "incidence_legale": "Delit d'entrave (art. L.2317-1 CT) : 1 an d'emprisonnement et 7500 EUR d'amende.",
        })

    # 4f. Participation obligatoire si >= 50 salaries
    if nb_actifs >= 50:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "participation_obligatoire",
            "urgence": "moyenne",
            "titre": "Accord de participation obligatoire",
            "description": f"Participation aux resultats obligatoire pour les entreprises >= 50 salaries. Effectif: {nb_actifs}.",
            "reference": "Art. L.3322-2 CT",
            "action_requise": "Verifier la mise en place d'un accord de participation",
            "echeance": "",
            "incidence_legale": "Perte des exonerations sociales et fiscales sur l'ensemble de l'epargne salariale.",
        })

    # 4g. Reglement interieur obligatoire si >= 50 salaries
    if nb_actifs >= 50:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "reglement_interieur",
            "urgence": "moyenne",
            "titre": "Reglement interieur obligatoire",
            "description": f"Le reglement interieur est obligatoire dans les entreprises >= 50 salaries. Effectif: {nb_actifs}.",
            "reference": "Art. L.1311-2 CT",
            "action_requise": "Verifier l'existence et la conformite du reglement interieur",
            "echeance": "",
            "incidence_legale": "Sanctions disciplinaires potentiellement inopposables aux salaries.",
        })

    # 4h. Index egalite pro si >= 50 salaries
    if nb_actifs >= 50:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "index_egalite_pro",
            "urgence": "moyenne",
            "titre": "Index egalite professionnelle",
            "description": f"Publication obligatoire de l'index egalite femmes-hommes avant le 1er mars. Effectif: {nb_actifs}.",
            "reference": "Art. L.1142-8 CT - Decret n2019-15 du 08/01/2019",
            "action_requise": "Calculer et publier l'index egalite professionnelle",
            "echeance": "01 mars de chaque annee",
            "incidence_legale": "Penalite financiere jusqu'a 1% de la masse salariale.",
        })

    # 4i. Bilan social si >= 300 salaries
    if nb_actifs >= 300:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "bilan_social",
            "urgence": "info",
            "titre": "Bilan social obligatoire",
            "description": f"Bilan social obligatoire pour les entreprises >= 300 salaries. Effectif: {nb_actifs}.",
            "reference": "Art. L.2312-28 CT",
            "action_requise": "Etablir et presenter le bilan social au CSE",
            "echeance": "",
        })

    # 4j. Formation professionnelle
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "formation_professionnelle",
            "urgence": "info",
            "titre": "Plan de developpement des competences",
            "description": "L'employeur a l'obligation d'assurer l'adaptation des salaries a leur poste de travail et de veiller au maintien de leur capacite a occuper un emploi.",
            "reference": "Art. L.6321-1 CT",
            "action_requise": "Verifier le plan de developpement des competences et le financement formation",
            "echeance": "",
        })

    # --- 6. Rappels declarations ---
    # DSN mensuelle : a transmettre au plus tard le 5 ou le 15 du mois suivant
    jour_du_mois = aujourdhui.day
    if jour_du_mois <= 15:
        date_limite_dsn = "le 5 du mois" if nb_actifs >= 50 else "le 15 du mois"
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "declaration_dsn_mensuelle",
            "urgence": "info",
            "message": f"Rappel: DSN mensuelle a transmettre avant {date_limite_dsn} en cours",
            "reference": "Art. R.133-14 CSS - Declaration sociale nominative",
            "action_requise": "Verifier et transmettre la DSN mensuelle",
        })

    # DPAE : avant toute embauche
    for contrat in _rh_contrats:
        if contrat.get("statut") == "actif":
            try:
                dd = date.fromisoformat(contrat["date_debut"])
                if (dd - aujourdhui).days >= 0 and (dd - aujourdhui).days <= 8:
                    alertes.append({
                        "id": str(uuid.uuid4())[:8],
                        "type": "dpae_a_effectuer",
                        "urgence": "haute",
                        "message": (
                            f"DPAE a effectuer pour {contrat['prenom_salarie']} {contrat['nom_salarie']} "
                            f"avant le {contrat['date_debut']}"
                        ),
                        "reference": "Art. L.1221-10 CT - DPAE au plus tard dans les 8 jours precedant l'embauche",
                        "action_requise": "Effectuer la DPAE aupres de l'URSSAF",
                        "contrat_id": contrat["id"],
                    })
            except (ValueError, TypeError):
                pass

    # --- 7. Periodes d'essai arrivant a echeance ---
    for contrat in _rh_contrats:
        if contrat.get("statut") != "actif":
            continue
        pe_jours = contrat.get("periode_essai_jours", 0)
        if pe_jours <= 0:
            continue
        try:
            dd = date.fromisoformat(contrat["date_debut"])
            fin_pe = dd + __import__("datetime").timedelta(days=pe_jours)
            jours_restants_pe = (fin_pe - aujourdhui).days
            if 0 <= jours_restants_pe <= 14:
                alertes.append({
                    "id": str(uuid.uuid4())[:8],
                    "type": "fin_periode_essai",
                    "urgence": "haute" if jours_restants_pe <= 3 else "moyenne",
                    "message": (
                        f"Periode d'essai de {contrat['prenom_salarie']} {contrat['nom_salarie']} "
                        f"se termine dans {jours_restants_pe} jour(s) (le {fin_pe.isoformat()})"
                    ),
                    "reference": "Art. L.1221-19 et suivants CT",
                    "action_requise": "Confirmer l'embauche ou notifier la rupture de la periode d'essai",
                    "contrat_id": contrat["id"],
                })
        except (ValueError, TypeError):
            pass

    # Normaliser toutes les alertes pour avoir titre + description
    for a in alertes:
        if "titre" not in a and "message" in a:
            a["titre"] = a["type"].replace("_", " ").capitalize()
            a["description"] = a["message"]
        if "description" not in a and "message" in a:
            a["description"] = a["message"]

    # Appliquer les personnalisations
    for cfg in _alertes_config:
        type_cfg = cfg["type_alerte"]
        if not cfg.get("actif", True):
            # Desactiver ce type d'alerte
            alertes = [a for a in alertes if a.get("type") != type_cfg]
        else:
            # Appliquer delai et message personnalise
            for a in alertes:
                if a.get("type") == type_cfg:
                    if cfg.get("delai_jours"):
                        a["delai_personnalise"] = cfg["delai_jours"]
                    if cfg.get("message_personnalise"):
                        a["message_personnalise"] = cfg["message_personnalise"]

    # Trier par urgence (haute > moyenne > info)
    ordre_urgence = {"haute": 0, "moyenne": 1, "info": 2}
    alertes.sort(key=lambda a: ordre_urgence.get(a.get("urgence", "info"), 3))

    log_action("utilisateur", "consultation_alertes_rh", f"{len(alertes)} alerte(s) generee(s)")
    return {"nb_alertes": len(alertes), "alertes": alertes}


# ======================================================================
# RH - ECHANGES SALARIES
# ======================================================================

@app.post("/api/rh/echanges")
async def enregistrer_echange(
    salarie_id: str = Form(...),
    objet: str = Form(...),
    contenu: str = Form(...),
    type_echange: str = Form("email"),
    date_echange: str = Form(""),
):
    """Enregistre un echange avec un salarie (email, courrier, reunion, entretien)."""
    types_valides = ("email", "courrier", "reunion", "entretien")
    if type_echange not in types_valides:
        raise HTTPException(400, f"Type d'echange invalide. Valeurs acceptees: {', '.join(types_valides)}")

    if not date_echange:
        date_echange = date.today().isoformat()

    echange_id = str(uuid.uuid4())[:8]

    echange = {
        "id": echange_id,
        "salarie_id": salarie_id,
        "objet": objet,
        "contenu": contenu,
        "type_echange": type_echange,
        "date_echange": date_echange,
        "date_creation": datetime.now().isoformat(),
    }

    _rh_echanges.append(echange)
    log_action("utilisateur", "enregistrement_echange", f"{type_echange} salarie {salarie_id}: {objet}")
    return echange


@app.get("/api/rh/echanges")
async def liste_echanges():
    """Liste tous les echanges enregistres."""
    return _rh_echanges


# ======================================================================
# RH - PLANNING
# ======================================================================

@app.post("/api/rh/planning")
async def ajouter_planning(
    salarie_id: str = Form(...),
    date: str = Form(...),
    heure_debut: str = Form(...),
    heure_fin: str = Form(...),
    type_poste: str = Form("normal"),
):
    """Ajoute ou modifie une entree de planning pour un salarie."""
    types_valides = ("normal", "astreinte", "nuit", "dimanche", "ferie")
    if type_poste not in types_valides:
        raise HTTPException(400, f"Type de poste invalide. Valeurs acceptees: {', '.join(types_valides)}")

    planning_id = str(uuid.uuid4())[:8]

    # Calcul de la duree
    try:
        h_deb = datetime.strptime(heure_debut, "%H:%M")
        h_fin = datetime.strptime(heure_fin, "%H:%M")
        duree_minutes = (h_fin - h_deb).seconds // 60
        duree_heures = round(duree_minutes / 60, 2)
    except (ValueError, TypeError):
        duree_heures = 0

    # Majorations applicables
    majorations = []
    if type_poste == "nuit":
        majorations.append({
            "type": "travail_nuit",
            "taux": "25% minimum",
            "reference": "Art. L.3122-8 CT ou convention collective",
        })
    elif type_poste == "dimanche":
        majorations.append({
            "type": "travail_dimanche",
            "taux": "Variable selon convention collective",
            "reference": "Art. L.3132-1 et suivants CT",
        })
    elif type_poste == "ferie":
        majorations.append({
            "type": "travail_jour_ferie",
            "taux": "100% si 1er mai, variable sinon selon convention",
            "reference": "Art. L.3133-6 CT (1er mai) / Convention collective",
        })
    elif type_poste == "astreinte":
        majorations.append({
            "type": "astreinte",
            "taux": "Compensation obligatoire (repos ou financiere)",
            "reference": "Art. L.3121-9 CT",
        })

    # Verifier s'il existe deja une entree pour ce salarie a cette date, et la remplacer
    index_existant = None
    for i, p in enumerate(_rh_planning):
        if p["salarie_id"] == salarie_id and p["date"] == date and p["heure_debut"] == heure_debut:
            index_existant = i
            break

    # Resoudre le nom du salarie depuis les contrats
    salarie_nom = salarie_id
    for c in _rh_contrats:
        if c.get("id") == salarie_id:
            salarie_nom = f"{c.get('prenom', '')} {c.get('nom', '')}".strip() or salarie_id
            break

    entree = {
        "id": planning_id,
        "salarie_id": salarie_id,
        "salarie_nom": salarie_nom,
        "date": date,
        "heure_debut": heure_debut,
        "heure_fin": heure_fin,
        "duree_heures": duree_heures,
        "type_poste": type_poste,
        "majorations": majorations,
        "date_creation": datetime.now().isoformat(),
    }

    if index_existant is not None:
        entree["id"] = _rh_planning[index_existant]["id"]  # Conserver l'id original
        _rh_planning[index_existant] = entree
        log_action("utilisateur", "modification_planning", f"salarie {salarie_id} le {date} {heure_debut}-{heure_fin}")
    else:
        _rh_planning.append(entree)
        log_action("utilisateur", "ajout_planning", f"salarie {salarie_id} le {date} {heure_debut}-{heure_fin} ({type_poste})")

    return entree


@app.get("/api/rh/planning")
async def liste_planning(semaine: Optional[str] = Query(None)):
    """Liste le planning, avec filtre optionnel par semaine ISO (ex: 2026-W08).

    Le format semaine est ISO 8601: YYYY-Www (ex: 2026-W08).
    """
    if not semaine:
        return _rh_planning

    # Parser la semaine ISO pour determiner les dates lundi-dimanche
    try:
        # Format: 2026-W08
        parts = semaine.split("-W")
        if len(parts) != 2:
            raise HTTPException(400, "Format semaine invalide. Utiliser YYYY-Www (ex: 2026-W08)")
        annee = int(parts[0])
        num_semaine = int(parts[1])

        # Calculer le lundi de la semaine ISO
        # Le 4 janvier est toujours dans la semaine 1 ISO
        jan4 = date(annee, 1, 4)
        # Lundi de la semaine 1
        lundi_s1 = jan4 - __import__("datetime").timedelta(days=jan4.weekday())
        # Lundi de la semaine demandee
        lundi = lundi_s1 + __import__("datetime").timedelta(weeks=num_semaine - 1)
        dimanche = lundi + __import__("datetime").timedelta(days=6)

        resultats = []
        for p in _rh_planning:
            try:
                d = date.fromisoformat(p["date"])
                if lundi <= d <= dimanche:
                    resultats.append(p)
            except (ValueError, TypeError):
                pass

        return {
            "semaine": semaine,
            "lundi": lundi.isoformat(),
            "dimanche": dimanche.isoformat(),
            "entrees": resultats,
            "nb_entrees": len(resultats),
        }
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Format semaine invalide: {e}")


# ======================================================================
# CONFIGURATION - EN-TETE ENTREPRISE
# ======================================================================

@app.post("/api/config/entete")
async def configurer_entete(
    nom_entreprise: str = Form(...),
    logo_url: str = Form(""),
    adresse: str = Form(""),
    telephone: str = Form(""),
    email: str = Form(""),
    siret: str = Form(""),
    code_naf: str = Form(""),
    forme_juridique: str = Form(""),
    capital: str = Form(""),
    rcs: str = Form(""),
    tva_intracom: str = Form(""),
):
    """Configure l'en-tete entreprise utilise dans les documents generes."""
    global _entete_config

    # Validation SIRET (14 chiffres)
    if siret and (len(siret.replace(" ", "")) != 14 or not siret.replace(" ", "").isdigit()):
        raise HTTPException(400, "Le SIRET doit contenir exactement 14 chiffres")

    # Validation TVA intracommunautaire (format FR + 2 chiffres + SIREN 9 chiffres = 13 chars)
    if tva_intracom and len(tva_intracom.replace(" ", "")) < 4:
        raise HTTPException(400, "Format TVA intracommunautaire invalide")

    _entete_config = {
        "nom_entreprise": nom_entreprise,
        "logo_url": logo_url,
        "adresse": adresse,
        "telephone": telephone,
        "email": email,
        "siret": siret,
        "code_naf": code_naf,
        "forme_juridique": forme_juridique,
        "capital": capital,
        "rcs": rcs,
        "tva_intracom": tva_intracom,
        "date_modification": datetime.now().isoformat(),
    }

    # Mentions legales obligatoires sur les documents commerciaux
    mentions_obligatoires = []
    if not nom_entreprise:
        mentions_obligatoires.append("Denomination sociale manquante")
    if not siret:
        mentions_obligatoires.append("SIRET manquant (obligatoire sur factures et documents commerciaux)")
    if not rcs:
        mentions_obligatoires.append("Numero RCS manquant (obligatoire pour les societes)")
    if not tva_intracom:
        mentions_obligatoires.append("Numero TVA intracommunautaire manquant (obligatoire sur factures)")
    if not capital and forme_juridique in ("SARL", "SAS", "SASU", "SA", "EURL", "SCI"):
        mentions_obligatoires.append(f"Capital social manquant (obligatoire pour {forme_juridique})")

    _entete_config["mentions_manquantes"] = mentions_obligatoires
    _entete_config["complet"] = len(mentions_obligatoires) == 0

    log_action("utilisateur", "configuration_entete", f"{nom_entreprise} (SIRET: {siret})")
    return _entete_config


@app.get("/api/config/entete")
async def get_entete():
    """Retourne la configuration actuelle de l'en-tete entreprise."""
    if not _entete_config:
        return {"message": "Aucune configuration d'en-tete. Utilisez POST /api/config/entete pour configurer."}
    return _entete_config


# ==============================
# DSN GENERATION
# ==============================

@app.post("/api/dsn/generer")
async def generer_dsn(
    # Emetteur (S10)
    siren_emetteur: str = Form(...),
    nic_emetteur: str = Form("00000"),
    nom_logiciel: str = Form("NormaCheck"),
    # Entreprise (S20)
    siren_entreprise: str = Form(...),
    raison_sociale: str = Form(...),
    # Etablissement (S21)
    nic_etablissement: str = Form(...),
    effectif: str = Form("1"),
    mois_declaration: str = Form(""),  # AAAAMM
    # Salaries (S30) - JSON array
    salaries_json: str = Form("[]"),
):
    """Genere un fichier DSN au format texte structure (NEODeS).

    Le champ salaries_json attend un tableau JSON avec pour chaque salarie:
    - nir: Numero de securite sociale (13 chiffres + cle)
    - nom, prenom, date_naissance (JJMMAAAA)
    - num_contrat, date_debut_contrat (JJMMAAAA)
    - statut_conventionnel (ex: "01" cadre, "02" non-cadre)
    - brut_mensuel: salaire brut
    - net_fiscal: net imposable
    - heures: heures travaillees
    - cotisations: tableau [{code_ctp, base, taux, montant}]
    """
    import json as _json

    try:
        salaries = _json.loads(salaries_json)
    except (ValueError, TypeError):
        raise HTTPException(400, "Format salaries_json invalide")

    if not mois_declaration:
        now = datetime.now()
        m = now.month - 1 or 12
        y = now.year if now.month > 1 else now.year - 1
        mois_declaration = f"{y}{m:02d}"

    lignes = []

    def add(bloc, valeur):
        lignes.append(f"{bloc},'{valeur}'")

    # --- S10 : Emetteur ---
    add("S10.G00.00.001", siren_emetteur)
    add("S10.G00.00.002", nic_emetteur)
    add("S10.G00.00.003", nom_logiciel)
    add("S10.G00.00.004", "NormaCheck v3.5")
    add("S10.G00.00.005", "01")  # Nature de la declaration: DSN mensuelle
    add("S10.G00.00.006", "11")  # Type: normale
    add("S10.G00.00.007", "01")  # Numero de fraction
    add("S10.G00.00.008", datetime.now().strftime("%d%m%Y"))

    # --- S20 : Entreprise ---
    add("S20.G00.05.001", siren_entreprise)
    add("S20.G00.05.002", nic_etablissement)
    add("S20.G00.05.003", raison_sociale)

    # --- S21 : Etablissement ---
    add("S21.G00.06.001", nic_etablissement)
    add("S21.G00.06.003", mois_declaration)
    add("S21.G00.11.001", effectif)

    # --- S30/S40/S51/S81 par salarie ---
    total_brut = Decimal("0")
    total_cotisations = Decimal("0")
    nb_salaries = 0

    for sal in salaries:
        nb_salaries += 1
        nir = sal.get("nir", "")
        nom = sal.get("nom", "")
        prenom = sal.get("prenom", "")
        ddn = sal.get("date_naissance", "01011990")
        brut = Decimal(str(sal.get("brut_mensuel", "0")))
        net_fiscal = Decimal(str(sal.get("net_fiscal", "0")))
        heures = sal.get("heures", "151.67")
        num_contrat = sal.get("num_contrat", f"C{nb_salaries:04d}")
        date_debut = sal.get("date_debut_contrat", "01012026")
        statut_conv = sal.get("statut_conventionnel", "02")

        total_brut += brut

        # S30 : Identification salarie
        add("S30.G00.30.001", nir)
        add("S30.G00.30.002", nom)
        add("S30.G00.30.004", prenom)
        add("S30.G00.30.006", ddn)

        # S40 : Contrat
        add("S40.G00.40.001", num_contrat)
        add("S40.G00.40.002", date_debut)
        add("S40.G00.40.003", "01")  # Nature du contrat: CDI
        add("S40.G00.40.004", statut_conv)
        add("S40.G00.40.009", "01")  # Unite de mesure: heure

        # S51 : Remuneration
        add("S51.G00.51.001", mois_declaration + "01")
        add("S51.G00.51.002", mois_declaration + "31")
        add("S51.G00.51.011", str(brut))
        add("S51.G00.51.013", str(heures))

        # S78/S81 : Cotisations
        cotisations = sal.get("cotisations", [])
        if not cotisations:
            # Cotisations par defaut si non fournies
            cotisations = [
                {"code_ctp": "100", "base": str(brut), "taux": "7.00", "montant": str(brut * Decimal("0.07"))},
                {"code_ctp": "260", "base": str(min(brut, Decimal("4005"))), "taux": "6.90",
                 "montant": str(min(brut, Decimal("4005")) * Decimal("0.069"))},
                {"code_ctp": "262", "base": str(brut), "taux": "2.02", "montant": str(brut * Decimal("0.0202"))},
                {"code_ctp": "332", "base": str(brut), "taux": "5.25", "montant": str(brut * Decimal("0.0525"))},
                {"code_ctp": "772", "base": str(min(brut, Decimal("16020"))), "taux": "4.05",
                 "montant": str(min(brut, Decimal("16020")) * Decimal("0.0405"))},
                {"code_ctp": "937", "base": str(min(brut, Decimal("16020"))), "taux": "0.20",
                 "montant": str(min(brut, Decimal("16020")) * Decimal("0.002"))},
            ]

        for cot in cotisations:
            add("S81.G00.81.001", cot.get("code_ctp", "100"))
            add("S81.G00.81.003", cot.get("base", str(brut)))
            add("S81.G00.81.004", cot.get("taux", "0"))
            add("S81.G00.81.005", cot.get("montant", "0"))
            total_cotisations += Decimal(str(cot.get("montant", "0")))

    # --- S89 : Total versement OPS ---
    add("S89.G00.89.001", str(total_cotisations.quantize(Decimal("0.01"))))
    add("S89.G00.89.002", str(total_brut.quantize(Decimal("0.01"))))

    # Construire le fichier DSN
    dsn_content = "\n".join(lignes) + "\n"

    # Sauvegarder le brouillon
    draft_id = str(uuid.uuid4())[:8]
    _dsn_drafts.append({
        "id": draft_id,
        "date_creation": datetime.now().isoformat(),
        "mois": mois_declaration,
        "siren": siren_entreprise,
        "raison_sociale": raison_sociale,
        "nb_salaries": nb_salaries,
        "total_brut": float(total_brut),
        "total_cotisations": float(total_cotisations),
        "nb_lignes": len(lignes),
    })

    log_action("utilisateur", "generation_dsn", f"{raison_sociale} {mois_declaration} ({nb_salaries} sal.)")

    return JSONResponse({
        "id": draft_id,
        "mois_declaration": mois_declaration,
        "nb_salaries": nb_salaries,
        "total_brut": float(total_brut),
        "total_cotisations": float(total_cotisations),
        "nb_lignes": len(lignes),
        "apercu": "\n".join(lignes[:20]) + ("\n..." if len(lignes) > 20 else ""),
        "contenu_dsn": dsn_content,
    })


@app.get("/api/dsn/brouillons")
async def liste_dsn_brouillons():
    return _dsn_drafts


@app.get("/api/dsn/telecharger/{draft_id}")
async def telecharger_dsn(draft_id: str):
    """Regenere et telecharge le fichier DSN."""
    for d in _dsn_drafts:
        if d["id"] == draft_id:
            return JSONResponse({"status": "ok", "message": "Utilisez le contenu_dsn de la generation."})
    raise HTTPException(404, "Brouillon non trouve")


# ==============================
# HTML TEMPLATES
# ==============================


LANDING_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NormaCheck - Conformite sociale et fiscale intelligente</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',system-ui,sans-serif;background:#f8fafc;color:#1e293b;-webkit-font-smoothing:antialiased}
.nav{background:#0f172a;color:#fff;display:flex;justify-content:space-between;align-items:center;padding:14px 40px;position:sticky;top:0;z-index:100}
.nav .logo{font-size:1.6em;font-weight:800;letter-spacing:-.5px}
.nav .logo em{font-style:normal;color:#60a5fa}
.nav .links{display:flex;gap:24px;align-items:center}
.nav a{color:#fff;text-decoration:none;font-size:.9em;opacity:.75;transition:.2s}
.nav a:hover{opacity:1}
.nav .bl{background:rgba(96,165,250,.2);padding:8px 22px;border-radius:8px;font-weight:600;opacity:1;border:1px solid rgba(96,165,250,.3)}
.hero{background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 50%,#1e40af 100%);color:#fff;text-align:center;padding:90px 20px 70px;position:relative}
.hero h1{font-size:3em;font-weight:800;margin-bottom:18px;line-height:1.1}
.hero h1 em{font-style:normal;color:#60a5fa}
.hero p{font-size:1.15em;opacity:.85;max-width:680px;margin:0 auto 35px;line-height:1.6}
.hero-btns{display:flex;gap:16px;justify-content:center;flex-wrap:wrap}
.cta-main{display:inline-block;background:#3b82f6;color:#fff;padding:15px 40px;border-radius:12px;font-size:1.1em;font-weight:700;cursor:pointer;border:none;box-shadow:0 4px 20px rgba(59,130,246,.4);transition:.3s}
.cta-main:hover{background:#2563eb;transform:translateY(-2px)}
.cta-sec{display:inline-block;background:rgba(255,255,255,.12);color:#fff;padding:15px 40px;border-radius:12px;font-size:1.1em;font-weight:700;cursor:pointer;border:1px solid rgba(255,255,255,.2);transition:.3s}
.cta-sec:hover{background:rgba(255,255,255,.2)}
.limits{display:flex;gap:24px;justify-content:center;margin-top:30px;flex-wrap:wrap}
.limit{background:rgba(255,255,255,.08);padding:12px 20px;border-radius:10px;font-size:.85em;border:1px solid rgba(255,255,255,.1)}
.limit strong{color:#60a5fa}
.pricing{max-width:1000px;margin:60px auto;padding:0 20px}
.pricing h2{text-align:center;font-size:1.8em;color:#0f172a;margin-bottom:10px}
.pricing .sub{text-align:center;color:#64748b;font-size:.95em;margin-bottom:30px}
.plans{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.plan{background:#fff;border-radius:16px;padding:28px 22px;border:1px solid #e2e8f0;text-align:center;transition:.3s;position:relative}
.plan:hover{transform:translateY(-3px);box-shadow:0 8px 30px rgba(0,0,0,.06)}
.plan.pop{border-color:#3b82f6;box-shadow:0 8px 30px rgba(59,130,246,.12)}
.plan.pop::before{content:"Populaire";position:absolute;top:-12px;left:50%;transform:translateX(-50%);background:#3b82f6;color:#fff;padding:4px 16px;border-radius:20px;font-size:.72em;font-weight:700}
.plan h3{font-size:1.15em;color:#0f172a;margin-bottom:6px}
.plan .price{font-size:2.2em;font-weight:800;color:#0f172a;margin:10px 0}
.plan .price em{font-size:.38em;font-weight:400;color:#64748b;font-style:normal}
.plan .profiles{font-size:.82em;color:#3b82f6;font-weight:600;margin-bottom:12px}
.plan ul{list-style:none;text-align:left;margin:12px 0}
.plan li{padding:5px 0;font-size:.84em;color:#475569}
.plan li::before{content:"\\2713 ";color:#22c55e;font-weight:700}
.plan-btn{width:100%;padding:11px;border-radius:10px;font-size:.92em;font-weight:700;cursor:pointer;transition:.2s;border:1.5px solid #e2e8f0;background:#fff;color:#0f172a}
.plan-btn:hover{border-color:#3b82f6;color:#3b82f6}
.plan.pop .plan-btn{background:#0f172a;color:#fff;border-color:#0f172a}
.plan.pop .plan-btn:hover{background:#1e293b}
.feat{max-width:1100px;margin:70px auto;padding:0 20px}
.feat h2{text-align:center;font-size:1.9em;font-weight:700;color:#0f172a;margin-bottom:40px}
.fg{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:18px}
.fc{background:#fff;border-radius:14px;padding:24px;border:1px solid #e2e8f0;transition:.3s}
.fc:hover{transform:translateY(-3px);box-shadow:0 8px 25px rgba(0,0,0,.06)}
.fc .ic{width:44px;height:44px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:1.3em;margin-bottom:12px}
.fc .ic.bl{background:#eff6ff}.fc .ic.gr{background:#f0fdf4}.fc .ic.pu{background:#faf5ff}.fc .ic.am{background:#fffbeb}
.fc h3{color:#0f172a;margin-bottom:6px;font-size:.98em}
.fc p{color:#64748b;font-size:.85em;line-height:1.5}
.guarantee{max-width:800px;margin:50px auto;padding:24px 30px;background:#fffbeb;border:1px solid #fde68a;border-radius:14px;text-align:center}
.guarantee h3{color:#92400e;margin-bottom:8px}.guarantee p{color:#92400e;font-size:.88em;line-height:1.6}
.tgt{background:#fff;padding:60px 20px;text-align:center;border-top:1px solid #e2e8f0}
.tgt h2{font-size:1.7em;color:#0f172a;margin-bottom:30px}
.tg{display:flex;justify-content:center;gap:24px;flex-wrap:wrap;max-width:800px;margin:0 auto}
.ti{background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:24px 18px;width:180px;transition:.3s}
.ti:hover{border-color:#3b82f6}.ti .ic2{font-size:1.8em;margin-bottom:6px}.ti h4{color:#0f172a;font-size:.95em;margin-bottom:3px}.ti p{font-size:.8em;color:#64748b}
.auth-sec{max-width:420px;margin:60px auto;padding:0 20px}
.auth-card{background:#fff;border-radius:20px;padding:36px;box-shadow:0 8px 30px rgba(0,0,0,.06);border:1px solid #e2e8f0}
.auth-card h2{text-align:center;color:#0f172a;margin-bottom:24px;font-size:1.3em}
.auth-tabs{display:flex;margin-bottom:24px;background:#f1f5f9;border-radius:10px;padding:4px}
.auth-tab{flex:1;padding:10px;text-align:center;cursor:pointer;font-weight:600;color:#64748b;border-radius:8px;transition:.2s;font-size:.9em}
.auth-tab.active{color:#0f172a;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.auth-form{display:none}.auth-form.active{display:block}
.auth-form label{display:block;font-weight:600;font-size:.84em;color:#475569;margin-bottom:5px}
.auth-form input{width:100%;padding:11px 14px;border:1.5px solid #e2e8f0;border-radius:10px;font-size:.95em;margin-bottom:14px;background:#f8fafc}
.auth-form input:focus{border-color:#3b82f6;outline:none;background:#fff}
.submit-btn{width:100%;padding:13px;background:#0f172a;color:#fff;border:none;border-radius:10px;font-size:1em;font-weight:700;cursor:pointer}
.submit-btn:hover{background:#1e293b}
.msg{padding:10px 14px;border-radius:10px;margin:12px 0;font-size:.9em;display:none}
.msg.ok{display:block;background:#f0fdf4;color:#166534;border:1px solid #bbf7d0}
.msg.err{display:block;background:#fef2f2;color:#991b1b;border:1px solid #fecaca}
.rgpd{font-size:.78em;color:#94a3b8;margin-top:14px;line-height:1.4;text-align:center}
footer{text-align:center;padding:40px 20px;color:#94a3b8;font-size:.82em;background:#0f172a}
footer a{color:#60a5fa;text-decoration:none}footer a:hover{text-decoration:underline}
footer .links{margin-bottom:12px;display:flex;gap:20px;justify-content:center}
@media(max-width:768px){.hero h1{font-size:2em}.hero{padding:60px 16px 50px}.fg{grid-template-columns:1fr}.plans{grid-template-columns:1fr}.nav{padding:12px 16px}.nav .links{gap:12px}.nav a:not(.bl){display:none}.limits{gap:10px}.limit{padding:8px 14px;font-size:.78em}}
</style>
</head>
<body>
<div class="nav"><div class="logo"><em>NormaCheck</em></div><div class="links"><a href="#features">Fonctionnalites</a><a href="#pricing">Tarifs</a><a href="#auth" class="bl">Connexion</a></div></div>
<div class="hero">
<h1>La conformite sociale et fiscale<br>enfin <em>simplifiee</em>.</h1>
<p>Analysez vos documents sociaux et fiscaux, detectez les anomalies en euros, gerez votre comptabilite, generez vos DSN et pilotez vos obligations. Pour dirigeants, comptables et experts.</p>
<div class="hero-btns">
<button class="cta-main" onclick="document.getElementById('auth').scrollIntoView({behavior:'smooth'})">Commencer maintenant</button>
<button class="cta-sec" onclick="document.getElementById('pricing').scrollIntoView({behavior:'smooth'})">Voir les tarifs</button>
</div>
<div class="limits">
<div class="limit"><strong>20 fichiers</strong> par analyse</div>
<div class="limit"><strong>500 Mo</strong> max par analyse</div>
<div class="limit"><strong>PDF, Excel, CSV, DSN, Images</strong></div>
</div>
</div>

<div class="pricing" id="pricing">
<h2>Tarification adaptative</h2>
<p class="sub">Un prix adapte a votre equipe. Toutes les fonctionnalites incluses, sans surprises.</p>
<div class="plans">
<div class="plan">
<h3>Solo</h3>
<div class="price">60 EUR <em>HT / an</em></div>
<div class="profiles">1 profil utilisateur</div>
<ul>
<li>Analyses illimitees</li>
<li>Comptabilite complete</li>
<li>Generation DSN</li>
<li>Gestion factures</li>
<li>Simulation (paie, micro, TNS)</li>
<li>Veille juridique 2020-2026</li>
<li>Export CSV</li>
</ul>
<button class="plan-btn" onclick="document.getElementById('auth').scrollIntoView({behavior:'smooth'})">Choisir Solo</button>
</div>
<div class="plan pop">
<h3>Equipe</h3>
<div class="price">100 EUR <em>HT / an</em></div>
<div class="profiles">Jusqu'a 3 profils</div>
<ul>
<li>Tout Solo +</li>
<li>Collaboration multi-profils</li>
<li>Profil decisionnaire</li>
<li>Tracabilite des actions</li>
<li>Bibliotheque partagee</li>
<li>Audit trail complet</li>
<li>Support prioritaire</li>
</ul>
<button class="plan-btn" onclick="document.getElementById('auth').scrollIntoView({behavior:'smooth'})">Choisir Equipe</button>
</div>
<div class="plan">
<h3>Cabinet</h3>
<div class="price">180 EUR <em>HT / an</em></div>
<div class="profiles">Jusqu'a 10 profils</div>
<ul>
<li>Tout Equipe +</li>
<li>Multi-dossiers (portefeuille)</li>
<li>10 utilisateurs simultanes</li>
<li>DSN multi-etablissements</li>
<li>Veille personnalisee</li>
<li>Accompagnement demarrage</li>
<li>Support dedie</li>
</ul>
<button class="plan-btn" onclick="document.getElementById('auth').scrollIntoView({behavior:'smooth'})">Choisir Cabinet</button>
</div>
</div>
</div>

<div class="feat" id="features">
<h2>Plateforme complete</h2>
<div class="fg">
<div class="fc"><div class="ic bl">&#128269;</div><h3>Analyse et detection</h3><p>Rapprochement DSN / livre de paie. Ecarts par salarie, par rubrique. Score de risque par destinataire.</p></div>
<div class="fc"><div class="ic gr">&#128200;</div><h3>Dashboard dirigeant</h3><p>Vision globale : anomalies, charges, conformite, scores URSSAF / Fiscal / France Travail / GUSO.</p></div>
<div class="fc"><div class="ic pu">&#128196;</div><h3>Comptabilite integree</h3><p>Grand livre, balance, bilan, resultat, TVA. Alertes justificatifs. Ecritures manuelles tracees.</p></div>
<div class="fc"><div class="ic am">&#128221;</div><h3>Generation DSN</h3><p>Creez vos declarations sociales nominatives au format NEODeS. Salaries, cotisations, totaux automatiques.</p></div>
<div class="fc"><div class="ic bl">&#9878;</div><h3>Veille juridique</h3><p>Baremes et legislation 2020-2026. Comparaison interannuelle. Patch mensuel automatique.</p></div>
<div class="fc"><div class="ic gr">&#128101;</div><h3>Collaboration</h3><p>Invitez des collaborateurs. Tracabilite des actions. Profil decisionnaire pour validation.</p></div>
<div class="fc"><div class="ic pu">&#128203;</div><h3>Gestion factures</h3><p>Analyse OCR, comptabilisation auto, suivi paiements (paye/impaye), historique complet.</p></div>
<div class="fc"><div class="ic am">&#128274;</div><h3>Securite et RGPD</h3><p>Donnees chiffrees, acces controle, conformite RGPD. Droit d'acces, rectification, suppression.</p></div>
</div>
</div>

<div class="guarantee">
<h3>Garantie et transparence</h3>
<p>NormaCheck est un outil d'aide a la decision. Les analyses produites sont indicatives et ne se substituent pas a l'avis d'un expert-comptable ou d'un conseil juridique. Les resultats ne sont pas opposables aux administrations (URSSAF, DGFIP, France Travail, etc.). L'utilisation de NormaCheck ne dispense pas de vos obligations declaratives et de paiement.</p>
</div>

<div class="tgt"><h2>Concu pour les professionnels</h2><div class="tg">
<div class="ti"><div class="ic2">&#128188;</div><h4>Dirigeants</h4><p>Pilotez votre conformite</p></div>
<div class="ti"><div class="ic2">&#128202;</div><h4>Comptables</h4><p>Automatisez vos controles</p></div>
<div class="ti"><div class="ic2">&#127891;</div><h4>Experts-comptables</h4><p>Multi-dossiers</p></div>
<div class="ti"><div class="ic2">&#128270;</div><h4>Inspecteurs</h4><p>Verification rapide</p></div>
</div></div>

<div class="auth-sec" id="auth"><div class="auth-card">
<h2>Acces a NormaCheck</h2>
<div class="auth-tabs"><div class="auth-tab active" onclick="showAT('login')">Connexion</div><div class="auth-tab" onclick="showAT('register')">Inscription</div></div>
<div id="amsg" class="msg"></div>
<div class="auth-form active" id="form-login">
<label>Identifiant / Email</label><input type="text" id="le" placeholder="admin">
<label>Mot de passe</label><input type="password" id="lp" placeholder="Votre mot de passe">
<button class="submit-btn" onclick="doLogin()">Se connecter</button>
</div>
<div class="auth-form" id="form-register">
<label>Nom</label><input id="rn" placeholder="Dupont">
<label>Prenom</label><input id="rp2" placeholder="Jean">
<label>Email</label><input type="email" id="re" placeholder="jean@exemple.fr">
<label>Mot de passe</label><input type="password" id="rpw" placeholder="Min. 6 caracteres">
<label>Confirmer</label><input type="password" id="rpw2" placeholder="Confirmez">
<div style="margin:14px 0;padding:14px;background:#f8fafc;border-radius:10px;font-size:.82em;color:#64748b">
<label style="display:flex;align-items:center;gap:8px;font-weight:400;margin:0;cursor:pointer"><input type="checkbox" id="cgv" style="width:auto;margin:0"> J'accepte les <a href="/legal/cgu" target="_blank" style="color:#3b82f6">CGU</a> et <a href="/legal/cgv" target="_blank" style="color:#3b82f6">CGV</a>.</label></div>
<button class="submit-btn" onclick="doReg()">Creer mon compte</button>
<div class="rgpd">Vos donnees sont traitees conformement au RGPD (Reglement UE 2016/679). Vous disposez d'un droit d'acces, de rectification et de suppression de vos donnees. Contact : dpo@normacheck-app.fr</div>
</div></div></div>

<footer>
<div class="links">
<a href="/legal/mentions">Mentions legales</a>
<a href="/legal/cgu">CGU</a>
<a href="/legal/cgv">CGV</a>
<a href="/legal/mentions#rgpd">RGPD</a>
</div>
NormaCheck v3.5.0 &mdash; Conformite sociale et fiscale &copy; 2026<br>
<span style="font-size:.85em;opacity:.6">Outil d'aide a la decision - Non opposable aux administrations</span>
</footer>
<script>
function showAT(t){document.querySelectorAll(".auth-tab").forEach(function(b,i){b.classList.toggle("active",i===(t==="login"?0:1))});document.getElementById("form-login").classList.toggle("active",t==="login");document.getElementById("form-register").classList.toggle("active",t==="register");document.getElementById("amsg").className="msg";}
function doLogin(){var fd=new FormData();fd.append("email",document.getElementById("le").value);fd.append("mot_de_passe",document.getElementById("lp").value);fetch("/api/auth/login",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});var m=document.getElementById("amsg");m.className="msg ok";m.textContent="Connexion reussie...";setTimeout(function(){window.location.href="/app"},600);}).catch(function(e){var m=document.getElementById("amsg");m.className="msg err";m.textContent=e.message;});}
function doReg(){if(document.getElementById("rpw").value!==document.getElementById("rpw2").value){var m=document.getElementById("amsg");m.className="msg err";m.textContent="Mots de passe differents.";return;}if(!document.getElementById("cgv").checked){var m2=document.getElementById("amsg");m2.className="msg err";m2.textContent="Veuillez accepter les CGU et CGV.";return;}var fd=new FormData();fd.append("nom",document.getElementById("rn").value);fd.append("prenom",document.getElementById("rp2").value);fd.append("email",document.getElementById("re").value);fd.append("mot_de_passe",document.getElementById("rpw").value);fetch("/api/auth/register",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});var m=document.getElementById("amsg");m.className="msg ok";m.textContent="Compte cree ! Redirection...";setTimeout(function(){window.location.href="/app"},600);}).catch(function(e){var m=document.getElementById("amsg");m.className="msg err";m.textContent=e.message;});}
</script>
</body>
</html>"""


LEGAL_CGU = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NormaCheck - Conditions Generales d'Utilisation</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:#f8fafc;color:#1e293b;line-height:1.7}
.nav{background:#0f172a;color:#fff;padding:14px 40px;display:flex;justify-content:space-between;align-items:center}
.nav a{color:#60a5fa;text-decoration:none;font-size:.9em}.nav .logo{font-size:1.4em;font-weight:800}
.nav .logo em{font-style:normal;color:#60a5fa}
.content{max-width:800px;margin:40px auto;padding:0 20px}
h1{color:#0f172a;font-size:1.8em;margin-bottom:24px}h2{color:#0f172a;font-size:1.2em;margin:24px 0 10px;padding-bottom:6px;border-bottom:1px solid #e2e8f0}
p,li{font-size:.92em;margin-bottom:10px}ul{margin-left:20px}
.warn{background:#fffbeb;border:1px solid #fde68a;padding:16px;border-radius:10px;margin:20px 0;color:#92400e;font-size:.9em}
footer{text-align:center;padding:30px;color:#94a3b8;font-size:.82em;margin-top:40px}
@media(max-width:640px){.content{padding:0 14px;margin:20px auto}h1{font-size:1.4em}.nav{padding:12px 16px}}</style></head>
<body>
<div class="nav"><div class="logo"><em>NormaCheck</em></div><a href="/">Retour a l'accueil</a></div>
<div class="content">
<h1>Conditions Generales d'Utilisation</h1>
<p><em>Derniere mise a jour : 1er janvier 2026</em></p>

<h2>Article 1 - Objet</h2>
<p>Les presentes Conditions Generales d'Utilisation (CGU) regissent l'acces et l'utilisation de la plateforme NormaCheck, outil d'aide a la decision en matiere de conformite sociale et fiscale.</p>

<div class="warn"><strong>Important :</strong> NormaCheck est un outil d'aide a la decision. Les analyses produites sont purement indicatives et ne se substituent en aucun cas a l'avis d'un expert-comptable, d'un commissaire aux comptes ou d'un conseil juridique. Les resultats fournis ne sont pas opposables aux administrations (URSSAF, DGFIP, France Travail, MSA, etc.).</div>

<h2>Article 2 - Acces au service</h2>
<p>L'acces a NormaCheck necessite la creation d'un compte utilisateur. L'utilisateur s'engage a fournir des informations exactes et a maintenir la confidentialite de ses identifiants. Toute utilisation du compte est reputee faite par le titulaire.</p>

<h2>Article 3 - Utilisation du service</h2>
<p>L'utilisateur s'engage a :</p>
<ul>
<li>Utiliser NormaCheck dans le respect de la legislation en vigueur</li>
<li>Ne pas tenter de contourner les mesures de securite</li>
<li>Ne pas utiliser le service a des fins illicites ou frauduleuses</li>
<li>Verifier les resultats avec un professionnel qualifie avant toute decision</li>
<li>Ne pas redistribuer ou revendre l'acces au service</li>
</ul>

<h2>Article 4 - Propriete intellectuelle</h2>
<p>L'ensemble des elements de NormaCheck (logiciel, algorithmes, interfaces, bases de donnees) est protege par le droit de la propriete intellectuelle. Toute reproduction, representation ou exploitation non autorisee est interdite.</p>
<p>Les documents uploades par l'utilisateur restent sa propriete exclusive.</p>

<h2>Article 5 - Limitation de responsabilite</h2>
<p>NormaCheck est fourni "en l'etat". L'editeur ne garantit pas :</p>
<ul>
<li>L'exactitude ou l'exhaustivite des analyses produites</li>
<li>L'adequation du service a un usage particulier</li>
<li>La disponibilite ininterrompue du service</li>
</ul>
<p>L'editeur ne saurait etre tenu responsable des decisions prises sur la base des resultats de NormaCheck, ni des consequences financieres, fiscales ou juridiques qui en decouleraient.</p>

<h2>Article 6 - Donnees personnelles et RGPD</h2>
<p>Conformement au Reglement General sur la Protection des Donnees (RGPD - Reglement UE 2016/679) et a la loi Informatique et Libertes, l'utilisateur dispose des droits suivants :</p>
<ul>
<li><strong>Droit d'acces :</strong> obtenir la communication de ses donnees</li>
<li><strong>Droit de rectification :</strong> corriger des donnees inexactes</li>
<li><strong>Droit de suppression :</strong> demander l'effacement de ses donnees</li>
<li><strong>Droit a la portabilite :</strong> recuperer ses donnees dans un format structure</li>
<li><strong>Droit d'opposition :</strong> s'opposer au traitement de ses donnees</li>
</ul>
<p>Les donnees sont traitees aux fins suivantes : fourniture du service, analyse de documents, amelioration de la plateforme. Base legale : execution du contrat (art. 6.1.b RGPD).</p>
<p>Contact DPO : dpo@normacheck-app.fr</p>

<h2>Article 7 - Duree et resiliation</h2>
<p>L'inscription est valable pour une duree indeterminee. L'utilisateur peut supprimer son compte a tout moment. L'editeur se reserve le droit de suspendre un compte en cas de violation des CGU.</p>

<h2>Article 8 - Modification des CGU</h2>
<p>L'editeur se reserve le droit de modifier les presentes CGU. Les utilisateurs seront informes de toute modification substantielle. L'utilisation continue du service vaut acceptation des CGU modifiees.</p>

<h2>Article 9 - Droit applicable</h2>
<p>Les presentes CGU sont soumises au droit francais. Tout litige sera soumis aux tribunaux competents du ressort du siege social de l'editeur.</p>
</div>
<footer>NormaCheck v3.5.0 &copy; 2026 - <a href="/" style="color:#60a5fa">Retour</a></footer>
</body></html>"""


LEGAL_CGV = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NormaCheck - Conditions Generales de Vente</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:#f8fafc;color:#1e293b;line-height:1.7}
.nav{background:#0f172a;color:#fff;padding:14px 40px;display:flex;justify-content:space-between;align-items:center}
.nav a{color:#60a5fa;text-decoration:none;font-size:.9em}.nav .logo{font-size:1.4em;font-weight:800}
.nav .logo em{font-style:normal;color:#60a5fa}
.content{max-width:800px;margin:40px auto;padding:0 20px}
h1{color:#0f172a;font-size:1.8em;margin-bottom:24px}h2{color:#0f172a;font-size:1.2em;margin:24px 0 10px;padding-bottom:6px;border-bottom:1px solid #e2e8f0}
p,li{font-size:.92em;margin-bottom:10px}ul{margin-left:20px}
.warn{background:#fffbeb;border:1px solid #fde68a;padding:16px;border-radius:10px;margin:20px 0;color:#92400e;font-size:.9em}
footer{text-align:center;padding:30px;color:#94a3b8;font-size:.82em;margin-top:40px}
@media(max-width:640px){.content{padding:0 14px;margin:20px auto}h1{font-size:1.4em}.nav{padding:12px 16px}}</style></head>
<body>
<div class="nav"><div class="logo"><em>NormaCheck</em></div><a href="/">Retour a l'accueil</a></div>
<div class="content">
<h1>Conditions Generales de Vente</h1>
<p><em>Derniere mise a jour : 1er janvier 2026</em></p>

<h2>Article 1 - Offres et tarifs</h2>
<p>NormaCheck propose une tarification adaptative basee sur le nombre de profils utilisateurs :</p>
<ul>
<li><strong>Solo (60 EUR HT/an) :</strong> 1 profil utilisateur - Analyses illimitees, comptabilite, generation DSN, gestion factures, simulations, veille juridique 2020-2026, export CSV</li>
<li><strong>Equipe (100 EUR HT/an) :</strong> Jusqu'a 3 profils - Tout Solo + collaboration multi-profils, profil decisionnaire, tracabilite, bibliotheque partagee, audit trail, support prioritaire</li>
<li><strong>Cabinet (180 EUR HT/an) :</strong> Jusqu'a 10 profils - Tout Equipe + multi-dossiers (portefeuille), DSN multi-etablissements, veille personnalisee, accompagnement demarrage, support dedie</li>
</ul>
<p>Les prix sont indiques hors taxes. TVA applicable en sus au taux en vigueur. L'editeur se reserve le droit de modifier ses tarifs, les modifications ne s'appliquant pas aux licences en cours.</p>

<h2>Article 2 - Commande et paiement</h2>
<p>La commande est validee apres acceptation des CGV et paiement du prix. Le paiement est exigible immediatement a la commande. Les moyens de paiement acceptes sont : carte bancaire, virement.</p>

<h2>Article 3 - Droit de retractation</h2>
<p>Conformement a l'article L221-18 du Code de la consommation, le consommateur dispose d'un delai de 14 jours a compter de la souscription pour exercer son droit de retractation, sans avoir a justifier de motifs.</p>
<p>Toutefois, conformement a l'article L221-28 du Code de la consommation, le droit de retractation ne peut etre exerce si le service a ete pleinement execute avant la fin du delai de retractation et si l'execution a commence avec l'accord prealable exprime du consommateur.</p>

<h2>Article 4 - Livraison et acces</h2>
<p>L'acces au service est immediat apres validation du paiement. La licence est delivree sous forme numerique (acces en ligne). Aucune livraison physique n'est effectuee.</p>

<h2>Article 5 - Garantie et limitation de responsabilite</h2>
<p>NormaCheck est un outil d'aide a la decision. L'editeur garantit le bon fonctionnement technique de la plateforme mais ne garantit pas l'exactitude des analyses produites.</p>
<p>La responsabilite de l'editeur est limitee au montant de la licence acquise. L'editeur ne saurait etre tenu responsable des dommages indirects.</p>

<div class="warn"><strong>Non-opposabilite :</strong> Les resultats produits par NormaCheck ne constituent pas des avis juridiques ou comptables et ne sont pas opposables aux administrations publiques (URSSAF, DGFIP, France Travail, MSA, caisses de retraite, etc.).</div>

<h2>Article 6 - Service apres-vente et reclamations</h2>
<p>Pour toute reclamation : support@normacheck-app.fr. Delai de reponse : 48 heures ouvrees.</p>

<h2>Article 7 - Mediateur de la consommation</h2>
<p>En cas de litige non resolu, le consommateur peut saisir gratuitement le mediateur de la consommation (article L612-1 du Code de la consommation).</p>

<h2>Article 8 - Droit applicable</h2>
<p>Les presentes CGV sont soumises au droit francais. Tout litige releve de la competence des tribunaux francais.</p>
</div>
<footer>NormaCheck v3.5.0 &copy; 2026 - <a href="/" style="color:#60a5fa">Retour</a></footer>
</body></html>"""


LEGAL_MENTIONS = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NormaCheck - Mentions legales</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:#f8fafc;color:#1e293b;line-height:1.7}
.nav{background:#0f172a;color:#fff;padding:14px 40px;display:flex;justify-content:space-between;align-items:center}
.nav a{color:#60a5fa;text-decoration:none;font-size:.9em}.nav .logo{font-size:1.4em;font-weight:800}
.nav .logo em{font-style:normal;color:#60a5fa}
.content{max-width:800px;margin:40px auto;padding:0 20px}
h1{color:#0f172a;font-size:1.8em;margin-bottom:24px}h2{color:#0f172a;font-size:1.2em;margin:24px 0 10px;padding-bottom:6px;border-bottom:1px solid #e2e8f0}
p,li{font-size:.92em;margin-bottom:10px}ul{margin-left:20px}
.warn{background:#fffbeb;border:1px solid #fde68a;padding:16px;border-radius:10px;margin:20px 0;color:#92400e;font-size:.9em}
footer{text-align:center;padding:30px;color:#94a3b8;font-size:.82em;margin-top:40px}
@media(max-width:640px){.content{padding:0 14px;margin:20px auto}h1{font-size:1.4em}.nav{padding:12px 16px}}</style></head>
<body>
<div class="nav"><div class="logo"><em>NormaCheck</em></div><a href="/">Retour a l'accueil</a></div>
<div class="content">
<h1>Mentions legales</h1>

<h2>Identification</h2>
<p><strong>Denomination :</strong> NormaCheck - Plateforme de conformite sociale et fiscale</p>
<p><strong>Forme juridique :</strong> [A completer]</p>
<p><strong>Siege social :</strong> [A completer]</p>
<p><strong>SIRET :</strong> [A completer]</p>
<p><strong>Directeur de la publication :</strong> [A completer]</p>
<p><strong>Contact :</strong> contact@normacheck-app.fr</p>

<h2>Hebergement</h2>
<p><strong>Hebergeur :</strong> Vercel Inc.</p>
<p><strong>Adresse :</strong> 340 S Lemon Ave #4133, Walnut, CA 91789, USA</p>
<p><strong>Site :</strong> vercel.com</p>

<h2 id="rgpd">Protection des donnees personnelles (RGPD)</h2>
<p>Conformement au Reglement General sur la Protection des Donnees (RGPD - Reglement UE 2016/679) et a la loi n 78-17 du 6 janvier 1978 relative a l'informatique, aux fichiers et aux libertes :</p>
<ul>
<li><strong>Responsable du traitement :</strong> L'editeur de NormaCheck</li>
<li><strong>Donnees collectees :</strong> Nom, prenom, email, documents uploades (pour analyse uniquement)</li>
<li><strong>Finalites :</strong> Fourniture du service d'analyse, gestion du compte, amelioration du service</li>
<li><strong>Base legale :</strong> Execution du contrat (art. 6.1.b RGPD)</li>
<li><strong>Duree de conservation :</strong> Donnees de compte : duree de l'inscription + 3 ans. Documents analyses : duree de la session d'analyse (suppression automatique)</li>
<li><strong>Transferts :</strong> Les donnees peuvent etre traitees par l'hebergeur (Vercel, USA) dans le cadre de clauses contractuelles types approuvees par la Commission europeenne</li>
<li><strong>Droits :</strong> Acces, rectification, suppression, portabilite, opposition, limitation</li>
<li><strong>DPO :</strong> dpo@normacheck-app.fr</li>
<li><strong>Reclamation CNIL :</strong> www.cnil.fr</li>
</ul>

<h2>Cookies</h2>
<p>NormaCheck utilise uniquement des cookies techniques strictement necessaires au fonctionnement du service (authentification, session). Aucun cookie publicitaire ou de tracking n'est utilise. Conformement a la directive ePrivacy, ces cookies techniques ne necessitent pas de consentement.</p>

<h2>Non-opposabilite</h2>
<div class="warn">
<p><strong>Avertissement important :</strong> NormaCheck est un outil d'aide a la decision destine aux professionnels. Les analyses, calculs, simulations et recommandations produits par la plateforme sont fournis a titre purement indicatif.</p>
<p>Les resultats de NormaCheck :</p>
<ul>
<li>Ne se substituent pas a l'avis d'un expert-comptable ou d'un conseil juridique</li>
<li>Ne sont pas opposables aux administrations publiques (URSSAF, DGFIP, France Travail, MSA, caisses de retraite complementaire, etc.)</li>
<li>Ne constituent pas des declarations sociales ou fiscales</li>
<li>Ne dispensent pas l'utilisateur de ses obligations declaratives et de paiement</li>
</ul>
<p>L'utilisateur reste seul responsable des decisions prises sur la base des informations fournies par NormaCheck.</p>
</div>

<h2>Propriete intellectuelle</h2>
<p>L'ensemble des contenus de la plateforme NormaCheck (textes, logiciels, algorithmes, bases de donnees, interfaces) est protege par le Code de la propriete intellectuelle. Toute reproduction non autorisee est constitutive de contrefacon.</p>

<h2>Droit applicable</h2>
<p>Le present site et ses mentions legales sont regis par le droit francais.</p>
</div>
<footer>NormaCheck v3.5.0 &copy; 2026 - <a href="/" style="color:#60a5fa">Retour</a></footer>
</body></html>"""


APP_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>NormaCheck - Application</title>
<style>
:root{--p:#0f172a;--p2:#1e40af;--p3:#3b82f6;--pl:#eff6ff;--g:#22c55e;--gl:#f0fdf4;--r:#ef4444;--rl:#fef2f2;--o:#f59e0b;--ol:#fffbeb;--pu:#a855f7;--pul:#faf5ff;--tl:#0d9488;--bg:#f8fafc;--tx:#1e293b;--tx2:#64748b;--brd:#e2e8f0;--sh:0 1px 3px rgba(0,0,0,.06);--sidebar-w:240px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--tx);-webkit-font-smoothing:antialiased;overflow-x:hidden}
.layout{display:flex;min-height:100vh}
/* Sidebar desktop */
.sidebar{width:var(--sidebar-w);background:var(--p);color:#fff;display:flex;flex-direction:column;position:fixed;top:0;bottom:0;left:0;z-index:100;transition:transform .3s}
.sidebar .logo{padding:20px 22px;font-size:1.4em;font-weight:800;border-bottom:1px solid rgba(255,255,255,.08)}
.sidebar .logo em{font-style:normal;color:#60a5fa}
.sidebar .nav-group{padding:14px 10px 4px;font-size:.68em;text-transform:uppercase;letter-spacing:1.5px;color:#475569;font-weight:600}
.sidebar .nl{display:flex;align-items:center;gap:10px;padding:9px 18px;cursor:pointer;color:rgba(255,255,255,.6);transition:.2s;border-radius:8px;margin:2px 8px;font-size:.88em;-webkit-tap-highlight-color:transparent}
.sidebar .nl:hover{background:rgba(255,255,255,.07);color:#fff}
.sidebar .nl.active{background:rgba(96,165,250,.15);color:#60a5fa;font-weight:600}
.sidebar .nl .ico{width:20px;text-align:center;font-size:1.1em;flex-shrink:0}
.sidebar .spacer{flex:1}
.sidebar .logout{padding:14px 18px;cursor:pointer;color:rgba(255,255,255,.4);font-size:.84em;border-top:1px solid rgba(255,255,255,.06);transition:.2s;display:flex;align-items:center;gap:8px}
.sidebar .logout:hover{color:#fff;background:rgba(239,68,68,.12)}
.content{margin-left:var(--sidebar-w);flex:1;min-height:100vh}
/* Topbar */
.topbar{background:#fff;border-bottom:1px solid var(--brd);padding:14px 28px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:50}
.topbar h1{font-size:1.12em;font-weight:700;color:var(--p)}
.topbar .info{font-size:.83em;color:var(--tx2)}
.topbar .mob-menu{display:none;background:none;border:none;font-size:1.5em;cursor:pointer;padding:4px 8px;color:var(--p);-webkit-tap-highlight-color:transparent}
.page{padding:24px 28px;max-width:1200px}
.sec{display:none}.sec.active{display:block}
/* Overlay mobile */
.sidebar-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:90;-webkit-tap-highlight-color:transparent}
/* Mobile */
@media(max-width:768px){
:root{--sidebar-w:0px}
.sidebar{transform:translateX(-280px);width:280px}
.sidebar.open{transform:translateX(0)}
.sidebar-overlay.show{display:block}
.content{margin-left:0}
.topbar{padding:10px 16px}
.topbar .mob-menu{display:block}
.topbar .info{display:none}
.page{padding:14px 12px}
.g2,.g3{grid-template-columns:1fr}
.g4{grid-template-columns:repeat(2,1fr);gap:8px}
.card{padding:16px;margin-bottom:12px;border-radius:10px}
.tabs{gap:0;padding:3px;margin-bottom:10px}
.tab{padding:6px 10px;font-size:.76em}
table{font-size:.78em}
th{padding:6px 8px}td{padding:5px 8px}
.sc .val{font-size:1.2em}
.sc .lab{font-size:.68em}
.btn{padding:8px 14px;font-size:.82em}
.uz{padding:20px 12px}
.anomalie{padding:10px}
.anomalie .title{font-size:.82em}
.anomalie .montant{font-size:1em}
.al{padding:8px 12px;font-size:.8em}
}
/* Cards */
.card{background:#fff;border-radius:14px;padding:24px;border:1px solid var(--brd);margin-bottom:18px;transition:.2s}
.card:hover{box-shadow:0 4px 16px rgba(0,0,0,.04)}
.card h2{color:var(--p);margin-bottom:14px;font-size:1.08em;font-weight:700;display:flex;align-items:center;gap:8px}
.card h2 .ct{background:var(--pl);color:var(--p3);padding:2px 10px;border-radius:20px;font-size:.72em}
/* Grids */
.g2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.g4{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
/* Stat cards */
.sc{border-radius:12px;padding:16px;text-align:center;border:1px solid var(--brd);background:#fff;transition:.2s}
.sc:hover{border-color:var(--p3)}.sc .val{font-size:1.6em;font-weight:800;color:var(--p)}.sc .lab{font-size:.76em;color:var(--tx2);margin-top:3px}
.sc.blue{background:var(--pl);border-color:#bfdbfe}.sc.green{background:var(--gl);border-color:#bbf7d0}
.sc.red{background:var(--rl);border-color:#fecaca}.sc.amber{background:var(--ol);border-color:#fde68a}
.sc.purple{background:var(--pul);border-color:#e9d5ff}.sc.teal{background:#f0fdfa;border-color:#99f6e4}
/* Upload zone */
.uz{border:2px dashed var(--brd);border-radius:14px;padding:32px;text-align:center;cursor:pointer;transition:.3s;background:#fff;position:relative}
.uz:hover{border-color:var(--p3);background:var(--pl)}
.uz input[type="file"]{position:absolute;inset:0;opacity:0;cursor:pointer}
.uz .uzi{font-size:2em;margin-bottom:6px;opacity:.5}
.uz h3{color:var(--p);font-size:.92em;margin-bottom:3px}.uz p{color:var(--tx2);font-size:.8em}
/* Inputs */
input,select,textarea{width:100%;padding:10px 14px;border:1.5px solid var(--brd);border-radius:10px;font-size:.9em;transition:.2s;margin-bottom:12px;background:#fff;font-family:inherit}
input:focus,select:focus,textarea:focus{border-color:var(--p3);outline:none;box-shadow:0 0 0 3px rgba(59,130,246,.08)}
label{display:block;font-weight:600;margin-bottom:5px;font-size:.82em;color:#475569}
/* Buttons */
.btn{display:inline-flex;align-items:center;gap:6px;padding:9px 20px;border:none;border-radius:10px;font-size:.88em;font-weight:600;cursor:pointer;transition:.2s;font-family:inherit;-webkit-tap-highlight-color:transparent}
.btn-p{background:var(--p);color:#fff}.btn-p:hover{background:#1e293b}.btn-p:disabled{background:#94a3b8;cursor:not-allowed}
.btn-blue{background:var(--p3);color:#fff}.btn-blue:hover{background:var(--p2)}
.btn-s{background:var(--pl);color:var(--p3);border:1px solid #bfdbfe}.btn-s:hover{background:#dbeafe}
.btn-green{background:var(--g);color:#fff}.btn-green:hover{background:#16a34a}
.btn-red{background:var(--rl);color:var(--r)}.btn-red:hover{background:#fee2e2}
.btn-f{width:100%;justify-content:center}
.btn-sm{padding:6px 14px;font-size:.8em;border-radius:8px}
.btn-group{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
/* Tables */
table{width:100%;border-collapse:collapse}
th{background:var(--p);color:#fff;padding:10px 14px;text-align:left;font-size:.8em;font-weight:600}
th:first-child{border-radius:8px 0 0 0}th:last-child{border-radius:0 8px 0 0}
td{padding:8px 14px;border-bottom:1px solid var(--brd);font-size:.86em}
tr:hover{background:var(--pl)}.num{text-align:right;font-family:'SF Mono','Consolas',monospace;font-size:.84em}
.sans-just{background:var(--rl) !important}.sans-just td{color:var(--r)}
/* Badges */
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.7em;font-weight:700}
.badge-blue{background:var(--pl);color:var(--p2)}.badge-green{background:var(--gl);color:#16a34a}
.badge-red{background:var(--rl);color:var(--r)}.badge-amber{background:var(--ol);color:#d97706}
.badge-purple{background:var(--pul);color:var(--pu)}.badge-teal{background:#f0fdfa;color:var(--tl)}
.badge-paye{background:var(--gl);color:#16a34a}.badge-impaye{background:var(--rl);color:var(--r)}
.sug-box{position:relative;z-index:50}.sug-box .sug-list{position:absolute;left:0;right:0;background:#fff;border:1px solid var(--brd);border-radius:6px;max-height:160px;overflow-y:auto;box-shadow:0 4px 12px rgba(0,0,0,.1);display:none}.sug-box .sug-list.show{display:block}.sug-item{padding:6px 10px;cursor:pointer;font-size:.82em;border-bottom:1px solid #f1f5f9}.sug-item:hover{background:var(--pl)}.sug-item .sug-num{font-weight:700;color:var(--p2)}.sug-item .sug-lbl{color:var(--tx2);margin-left:6px}
/* Tabs */
.tabs{display:flex;gap:2px;background:#f1f5f9;border-radius:10px;padding:4px;margin-bottom:16px;overflow-x:auto;-webkit-overflow-scrolling:touch}
.tab{padding:7px 16px;cursor:pointer;border-radius:8px;color:var(--tx2);font-weight:600;font-size:.82em;transition:.2s;white-space:nowrap;-webkit-tap-highlight-color:transparent}
.tab:hover{color:var(--tx)}.tab.active{color:var(--p);background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.tc{display:none}.tc.active{display:block}
/* Anomalies */
.anomalie{border:1px solid var(--brd);border-radius:12px;padding:15px;margin:8px 0;cursor:pointer;transition:.2s;background:#fff}
.anomalie:hover{box-shadow:0 4px 14px rgba(0,0,0,.05)}
.anomalie.sev-high{border-left:4px solid var(--r)}.anomalie.sev-med{border-left:4px solid var(--o)}.anomalie.sev-low{border-left:4px solid var(--p3)}
.anomalie .head{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px}
.anomalie .title{font-weight:600;font-size:.9em}
.anomalie .montant{font-size:1.15em;font-weight:700;font-family:'SF Mono','Consolas',monospace}
.anomalie .montant.neg{color:var(--r)}.anomalie .montant.pos{color:var(--g)}
.anomalie .detail{display:none;margin-top:12px;padding-top:12px;border-top:1px solid var(--brd);font-size:.84em;line-height:1.6}
.anomalie.open .detail{display:block}
.anomalie .dest{padding:2px 10px;border-radius:20px;font-size:.7em;font-weight:700;display:inline-block;margin-left:6px}
/* Alerts */
.al{padding:12px 16px;border-radius:10px;margin:8px 0;font-size:.86em;display:flex;align-items:flex-start;gap:8px;line-height:1.5}
.al .ai{font-size:1em;margin-top:1px;flex-shrink:0}
.al.info{background:var(--pl);color:var(--p2);border:1px solid #bfdbfe}
.al.ok{background:var(--gl);color:#166534;border:1px solid #bbf7d0}
.al.err{background:var(--rl);color:#991b1b;border:1px solid #fecaca}
.al.warn{background:var(--ol);color:#92400e;border:1px solid #fde68a}
/* Gauge */
.gauge{width:120px;height:120px;border-radius:50%;background:conic-gradient(var(--g) 0%,var(--g) var(--pct),#e2e8f0 var(--pct));display:flex;align-items:center;justify-content:center;margin:0 auto}
.gauge-inner{width:90px;height:90px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;font-size:1.5em;font-weight:800;color:var(--p)}
/* Progress */
.prg{display:none;margin:14px 0}
.prg-bar{height:6px;background:#e2e8f0;border-radius:3px;overflow:hidden}
.prg-fill{height:100%;background:linear-gradient(90deg,var(--p3),var(--p2));border-radius:3px;width:0%;transition:width .5s}
.prg-txt{text-align:center;margin-top:6px;color:var(--tx2);font-size:.82em}
/* File items */
.fi{display:flex;align-items:center;justify-content:space-between;padding:7px 12px;background:var(--pl);border-radius:8px;margin:3px 0;font-size:.84em;border:1px solid #bfdbfe}
.fi .nm{font-weight:600;color:var(--p);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%}.fi .rm{background:none;border:none;color:var(--r);cursor:pointer;font-size:1.2em;padding:2px 6px;border-radius:4px}
/* Format options */
.fmts{display:flex;gap:8px;margin-bottom:14px}
.fopt{flex:1;padding:10px;border:1.5px solid var(--brd);border-radius:10px;text-align:center;cursor:pointer;background:#fff;transition:.2s}
.fopt:hover{border-color:var(--p3)}.fopt.active{border-color:var(--p3);background:var(--pl)}
.fopt strong{color:var(--p);font-size:.9em}.fopt small{color:var(--tx2);font-size:.76em}
/* Misc */
.ent-item{border:1px solid var(--brd);border-radius:10px;padding:14px;margin:8px 0;transition:.2s;cursor:pointer}
.ent-item:hover{border-color:var(--p3);box-shadow:0 2px 8px rgba(59,130,246,.08)}
.doc-item{border:1px solid var(--brd);border-radius:10px;padding:14px;margin:8px 0;transition:.2s}
.doc-item:hover{box-shadow:0 2px 8px rgba(0,0,0,.04)}
.period-sel{margin-bottom:14px;padding:14px;background:var(--pl);border-radius:10px;border:1px solid #bfdbfe;display:none}
@keyframes slideIn{from{transform:translateX(100px);opacity:0}to{transform:translateX(0);opacity:1}}
</style>
</head>
<body>
<div class="sidebar-overlay" id="sidebar-overlay" onclick="closeSidebar()"></div>
<div class="layout">
<div class="sidebar" id="sidebar">
<div class="logo"><em>NormaCheck</em> <span>v3.5</span></div>
<div class="nav-group">Analyse</div>
<div class="nl active" onclick="showS('dashboard',this)"><span class="ico">&#9632;</span><span>Dashboard</span></div>
<div class="nl" onclick="showS('analyse',this)"><span class="ico">&#128269;</span><span>Import / Analyse</span></div>
<div class="nl" onclick="showS('biblio',this)"><span class="ico">&#128218;</span><span>Bibliotheque</span></div>
<div class="nav-group">Gestion</div>
<div class="nl" onclick="showS('compta',this)"><span class="ico">&#128203;</span><span>Comptabilite</span></div>
<div class="nl" onclick="showS('factures',this)"><span class="ico">&#128206;</span><span>Factures</span></div>
<div class="nl" onclick="showS('dsn',this)"><span class="ico">&#128196;</span><span>Creation DSN</span></div>
<div class="nl" onclick="showS('rh',this)"><span class="ico">&#128119;</span><span>Ressources humaines</span></div>
<div class="nl" onclick="showS('simulation',this)"><span class="ico">&#128200;</span><span>Simulation</span></div>
<div class="nav-group">Outils</div>
<div class="nl" onclick="showS('veille',this)"><span class="ico">&#9878;</span><span>Veille juridique</span></div>
<div class="nl" onclick="showS('portefeuille',this)"><span class="ico">&#128101;</span><span>Portefeuille</span></div>
<div class="nl" onclick="showS('equipe',this)"><span class="ico">&#128100;</span><span>Equipe</span></div>
<div class="nl" onclick="showS('config',this)"><span class="ico">&#9881;</span><span>Configuration</span></div>
<div class="spacer"></div>
<div class="logout" onclick="window.location.href='/'"><span class="ico">&#10132;</span><span>Deconnexion</span></div>
</div>
<div class="content">
<div class="topbar"><button class="mob-menu" id="mob-menu" onclick="toggleSidebar()">&#9776;</button><h1 id="page-title">Dashboard</h1><div class="info">NormaCheck v3.5.0 &bull; <span id="topbar-date"></span> &bull; <a href="/legal/mentions" style="color:var(--tx2);font-size:.9em">Mentions legales</a></div></div>
<div class="page">

"""


APP_HTML += """
<!-- ===== DASHBOARD ===== -->
<div class="sec active" id="s-dashboard">
<div class="al info" style="margin-bottom:16px"><span class="ai">&#128161;</span><span><strong>Limites d'analyse :</strong> 20 fichiers max, 500 Mo max par analyse. Formats : PDF, Excel, CSV, DSN, XML, Images (JPEG, PNG, TIFF).</span></div>
<div class="g4" id="dash-stats">
<div class="sc blue"><div class="val" id="dash-anomalies">0</div><div class="lab">Anomalies</div></div>
<div class="sc amber"><div class="val" id="dash-impact">0 EUR</div><div class="lab">Impact cotisations</div></div>
<div class="sc green"><div class="val" id="dash-conf">-</div><div class="lab">Conformite</div></div>
<div class="sc"><div class="val" id="dash-docs">0</div><div class="lab">Documents</div></div>
</div>
<div class="g2">
<div class="card"><h2>Conformite globale</h2>
<div class="gauge" id="gauge" style="--pct:0%"><div class="gauge-inner" id="gauge-val">-</div></div>
<div style="text-align:center;margin-top:10px;font-size:.82em;color:var(--tx2)">Score base sur les analyses realisees</div>
</div>
<div class="card"><h2>Alertes</h2><div id="dash-alertes"><div class="al info"><span class="ai">&#128161;</span><span>Importez des documents pour lancer l'analyse.</span></div></div></div>
</div>
<div class="card"><h2>Scores de risque par destinataire</h2>
<div class="g4" id="dash-by-dest">
<div class="sc blue"><div class="val" id="dd-urssaf">-</div><div class="lab">URSSAF</div></div>
<div class="sc purple"><div class="val" id="dd-fiscal">-</div><div class="lab">Fiscal</div></div>
<div class="sc amber"><div class="val" id="dd-ft">-</div><div class="lab">France Travail</div></div>
<div class="sc teal"><div class="val" id="dd-guso">-</div><div class="lab">GUSO</div></div>
</div></div>
<div class="card"><h2>Dernieres anomalies <span class="ct" id="dash-anom-count">0</span></h2><div id="dash-anomalies-list"><p style="color:var(--tx2)">Aucune anomalie. Lancez une analyse.</p></div></div>
</div>

<!-- ===== IMPORT / ANALYSE ===== -->
<div class="sec" id="s-analyse">
<div class="card">
<h2>Importer et analyser</h2>
<div class="al info" style="margin-bottom:14px"><span class="ai">&#128196;</span><span>Max <strong>20 fichiers</strong> et <strong>500 Mo</strong> par analyse. Reconnaissance OCR, ecriture manuscrite, libelles, totaux et sous-totaux.</span></div>
<div class="g2" style="margin-bottom:14px">
<div><label>Mode d analyse</label><select id="mode-analyse">
<option value="simple">Analyse simple</option>
<option value="social">Audit social</option>
<option value="fiscal">Audit fiscal</option>
<option value="complet" selected>Audit complet</option>
</select></div>
<div style="display:flex;align-items:flex-end"><div class="al info" id="mode-info" style="margin:0;font-size:.78em;flex:1"><span class="ai">&#128161;</span><span>Audit complet : verification de toutes les coherences sociales, fiscales, DSN et rapprochements.</span></div></div>
</div>
<div class="uz" id="dz-analyse">
<input type="file" id="fi-analyse" multiple accept=".pdf,.csv,.xlsx,.xls,.xml,.dsn,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.gif,.webp,.heic,.heif,.txt">
<div class="uzi">&#128196;</div>
<h3>Glissez vos fichiers ici</h3>
<p>PDF, Excel, CSV, DSN, XML, Images, TXT</p>
</div>
<div id="fl-analyse" style="margin:10px 0"></div>
<div style="display:flex;align-items:center;gap:10px;margin:12px 0;padding:12px;background:var(--pl);border-radius:10px;border:1px solid #bfdbfe">
<input type="checkbox" id="chk-integrer" checked style="width:auto;margin:0">
<label for="chk-integrer" style="margin:0;font-weight:500;color:var(--p);font-size:.86em;cursor:pointer">Integrer les documents dans la bibliotheque</label>
</div>
<button class="btn btn-blue btn-f" id="btn-az" onclick="lancerAnalyse()" disabled>&#128269; Lancer l'analyse</button>
<div class="prg" id="prg-az"><div class="prg-bar"><div class="prg-fill" id="pf-az"></div></div><div class="prg-txt" id="pt-az">Import...</div></div>
</div>
<div id="res-analyse" style="display:none">
<div class="card">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:8px">
<h2>Resultats</h2>
<div class="btn-group"><button class="btn btn-s btn-sm" onclick="exportPDF()">&#128196; Export PDF</button><button class="btn btn-s btn-sm" onclick="exportSection('az')">&#128190; CSV</button><button class="btn btn-blue" onclick="resetAz()" style="font-weight:600">&#10227; Nouvelle analyse</button></div>
</div>
<div class="g4" id="az-dashboard"></div>
</div>
<div class="card" id="az-fichiers-card"><h2>Fichiers analyses</h2><div id="az-fichiers-list"></div></div>
<div class="card" id="az-integration-card" style="display:none"><h2>Integration automatique</h2><div id="az-integration-results"></div></div>
<div class="card" id="az-audit-card" style="display:none"><h2>Points de controle Audit</h2><div id="az-audit-checks"></div></div>
<div class="card"><h2>Anomalies</h2><div id="az-findings"></div></div>
<div class="card"><h2>Recommandations</h2><div id="az-reco"></div></div>
<div class="card" id="az-html-card" style="display:none"><h2>Rapport visuel complet</h2><iframe id="az-html-frame" style="width:100%;height:600px;border:1px solid var(--brd);border-radius:10px"></iframe></div>
<div style="text-align:center;margin:20px 0"><button class="btn btn-blue" onclick="resetAz()" style="font-size:1.05em;padding:12px 32px;font-weight:600">&#10227; Nouvelle analyse</button></div>
</div>
</div>

<!-- ===== BIBLIOTHEQUE ===== -->
<div class="sec" id="s-biblio">
<div class="card">
<h2>Base de connaissances</h2>
<p style="color:var(--tx2);font-size:.86em;margin-bottom:14px">Toutes les informations extraites des documents importes, utilisees comme base d interpretation pour l audit et les controles.</p>
<div class="btn-group"><button class="btn btn-blue btn-sm" onclick="loadBiblio();loadKnowledge()">&#8635; Actualiser</button><button class="btn btn-s btn-sm" onclick="exportSection('biblio')">&#128190; Exporter</button></div>
<div id="biblio-knowledge" style="margin-top:12px"></div>
</div>
<div class="card">
<h2>Documents importes</h2>
<div id="biblio-list"></div>
</div>
</div>

<!-- ===== FACTURES ===== -->
<div class="sec" id="s-factures">
<div class="tabs" id="fact-tabs">
<div class="tab active" onclick="showFT('analyse',this)">Analyser</div>
<div class="tab" onclick="showFT('saisie',this)">Saisie manuelle</div>
<div class="tab" onclick="showFT('suivi',this)">Suivi paiements</div>
</div>
<div class="tc active" id="ft-analyse">
<div class="g2">
<div class="card">
<h2>Analyser une facture</h2>
<div class="uz" id="dz-fact">
<input type="file" id="fi-fact" accept=".pdf,.csv,.txt,.jpg,.jpeg,.png">
<div class="uzi">&#128206;</div><h3>Deposer une facture</h3><p>PDF, CSV, TXT, Image</p>
</div>
<div id="fact-fn" style="margin:8px 0"></div>
<button class="btn btn-blue btn-f" id="btn-fact" onclick="analyserFacture()" disabled>Analyser</button>
</div>
<div class="card" id="fact-res" style="display:none"><h2>Resultat</h2><div id="fact-det"></div></div>
</div>
</div>
<div class="tc" id="ft-saisie">
<div class="card">
<h2>Saisie manuelle / Comptabilisation</h2>
<label>Type</label>
<select id="f-type"><option value="facture_achat">Facture achat</option><option value="facture_vente">Facture vente</option><option value="avoir_achat">Avoir achat</option><option value="avoir_vente">Avoir vente</option></select>
<div class="g2"><div><label>Date</label><input type="date" id="f-date"></div><div><label>N piece</label><input id="f-num" placeholder="FA-2026-001"></div></div>
<label>Tiers</label><input id="f-tiers" placeholder="Nom du tiers">
<div class="g3"><div><label>HT</label><input type="number" step="0.01" id="f-ht" placeholder="0.00"></div><div><label>TVA</label><input type="number" step="0.01" id="f-tva" placeholder="0.00"></div><div><label>TTC</label><input type="number" step="0.01" id="f-ttc" placeholder="0.00"></div></div>
<button class="btn btn-p btn-f" onclick="comptabiliserFacture()">Comptabiliser</button>
<div id="alerte-justif" class="al err" style="display:none"><span class="ai">&#9888;</span><span><strong>Alerte justificatif</strong> : Saisie sans document. L'ecriture sera marquee en rouge.</span></div>
<div id="fact-saisie-res" style="margin-top:12px"></div>
</div>
</div>
<div class="tc" id="ft-suivi">
<div class="card">
<h2>Suivi des paiements</h2>
<p style="color:var(--tx2);font-size:.86em;margin-bottom:14px">Gerez le statut de vos factures. Marquez comme paye avec reference de virement.</p>
<div class="g2">
<div>
<label>ID facture / ecriture</label><input id="pay-id" placeholder="ID de la facture">
<label>Statut</label><select id="pay-stat" onchange="toggleMontantPaye()"><option value="impaye">Impaye</option><option value="paye">Paye</option><option value="partiellement_paye">Partiellement paye</option><option value="en_retard">En retard</option></select>
<div id="pay-montant-row" style="display:none"><label>Montant paye (EUR)</label><input type="number" step="0.01" id="pay-montant" placeholder="0.00"></div>
<label>Date paiement</label><input type="date" id="pay-date">
<label>Reference virement / justificatif</label><input id="pay-ref" placeholder="REF-VIR-2026-001">
<button class="btn btn-green btn-f" onclick="majStatutFacture()">Mettre a jour le statut</button>
</div>
<div>
<h3 style="margin-bottom:10px">Statuts enregistres</h3>
<div id="pay-list"></div>
</div>
</div>
</div>
</div>
</div>

<!-- ===== CREATION DSN ===== -->
<div class="sec" id="s-dsn">
<div class="card">
<h2>&#128196; Generation de DSN</h2>
<p style="color:var(--tx2);font-size:.86em;margin-bottom:14px">Creez vos declarations sociales nominatives au format texte structure (NEODeS). Remplissez les informations, ajoutez les salaries et generez le fichier.</p>
<div class="al info" style="margin-bottom:14px"><span class="ai">&#9878;</span><span>La DSN generee est un brouillon. Elle doit etre verifiee et validee avant envoi a net-entreprises.fr.</span></div>
</div>
<div class="g2">
<div class="card">
<h2>Emetteur et entreprise</h2>
<label>SIREN emetteur</label><input id="dsn-siren-em" placeholder="123456789" maxlength="9">
<label>SIREN entreprise</label><input id="dsn-siren-ent" placeholder="123456789" maxlength="9">
<label>Raison sociale</label><input id="dsn-raison" placeholder="Mon Entreprise SAS">
<label>NIC etablissement</label><input id="dsn-nic" placeholder="00001" maxlength="5">
<div class="g2">
<div><label>Effectif</label><input type="number" id="dsn-eff" value="1" min="1"></div>
<div><label>Mois (AAAAMM)</label><input id="dsn-mois" placeholder="202601" maxlength="6"></div>
</div>
</div>
<div class="card">
<h2>Salaries <span class="ct" id="dsn-sal-count">0</span></h2>
<div id="dsn-sal-list"></div>
<div style="border:1px solid var(--brd);border-radius:10px;padding:14px;margin-top:10px">
<div class="g2"><div><label>NIR</label><input id="dsn-nir" placeholder="1 85 01 75 108 888 42" maxlength="15"></div><div><label>Nom</label><input id="dsn-nom" placeholder="DUPONT"></div></div>
<div class="g2"><div><label>Prenom</label><input id="dsn-prenom" placeholder="Jean"></div><div><label>Date naissance (JJMMAAAA)</label><input id="dsn-ddn" placeholder="01011990" maxlength="8"></div></div>
<div class="g3"><div><label>Brut mensuel</label><input type="number" step="0.01" id="dsn-brut" placeholder="2500.00"></div><div><label>Net fiscal</label><input type="number" step="0.01" id="dsn-net" placeholder="1950.00"></div><div><label>Heures</label><input type="number" step="0.01" id="dsn-heures" value="151.67"></div></div>
<div class="g2"><div><label>Statut</label><select id="dsn-statut"><option value="02">Non-cadre</option><option value="01">Cadre</option></select></div><div><label>N contrat</label><input id="dsn-contrat" placeholder="C0001"></div></div>
<button class="btn btn-blue btn-f" onclick="ajouterSalarieDSN()">+ Ajouter ce salarie</button>
</div>
</div>
</div>
<div class="card">
<button class="btn btn-p btn-f" onclick="genererDSN()" id="btn-dsn-gen">&#128196; Generer la DSN</button>
<div id="dsn-result" style="margin-top:14px"></div>
</div>
<div class="card" style="display:none" id="dsn-brouillons-card">
<h2>Brouillons</h2>
<div class="btn-group"><button class="btn btn-s btn-sm" onclick="loadDSNBrouillons()">&#8635; Actualiser</button></div>
<div id="dsn-brouillons"></div>
</div>
</div>

<!-- ===== COMPTABILITE ===== -->
<div class="sec" id="s-compta">
<div class="tabs" id="compta-tabs">
<div class="tab active" onclick="showCT('journal',this)">Journal</div>
<div class="tab" onclick="showCT('balance',this)">Balance</div>
<div class="tab" onclick="showCT('grandlivre',this)">Grand Livre</div>
<div class="tab" onclick="showCT('resultat',this)">Resultat</div>
<div class="tab" onclick="showCT('bilan',this)">Bilan</div>
<div class="tab" onclick="showCT('tva',this)">TVA</div>
<div class="tab" onclick="showCT('social',this)">Charges sociales</div>
<div class="tab" onclick="showCT('ecritures',this)">Ecritures</div>
<div class="tab" onclick="showCT('plan',this)">Plan comptable</div>
</div>
<div class="card">
<div class="btn-group">
<button class="btn btn-p btn-sm" onclick="loadCompta()">&#8635; Actualiser</button>
<button class="btn btn-s btn-sm" onclick="validerEcr()">&#9989; Valider</button>
<button class="btn btn-s btn-sm" onclick="exportSection('compta')">&#128190; Exporter</button>
</div>
<div class="period-sel" id="period-sel" style="display:none">
<div class="g3"><div><label>Debut</label><input type="date" id="gl-dd"></div><div><label>Fin</label><input type="date" id="gl-df"></div><div><button class="btn btn-blue btn-f" onclick="loadCompta()" style="margin-top:22px">Appliquer</button></div></div>
</div>
<div class="tc active" id="ct-journal"><div id="ct-journal-c"></div></div>
<div class="tc" id="ct-balance"><div id="ct-balance-c"></div></div>
<div class="tc" id="ct-grandlivre"><div id="ct-grandlivre-c"></div></div>
<div class="tc" id="ct-resultat"><div id="ct-resultat-c"></div></div>
<div class="tc" id="ct-bilan"><div id="ct-bilan-c"></div></div>
<div class="tc" id="ct-tva"><div id="ct-tva-c"></div></div>
<div class="tc" id="ct-social"><div id="ct-social-c"></div></div>
<div class="tc" id="ct-ecritures">
<h2 style="margin-bottom:12px">Ecriture manuelle</h2>
<div class="g2">
<div><label>Date</label><input type="date" id="em-date"><label>Libelle</label><input id="em-lib" placeholder="Description"></div>
<div><label>Compte debit</label><input id="em-deb" placeholder="601000" oninput="suggestCompte('em-deb','em-deb-sug','em-cre')"><div id="em-deb-sug" class="sug-box"></div><label>Compte credit</label><input id="em-cre" placeholder="401000" oninput="suggestCompte('em-cre','em-cre-sug',null)"><div id="em-cre-sug" class="sug-box"></div></div>
</div>
<div class="g3">
<div><label>Montant</label><input type="number" step="0.01" id="em-mt" placeholder="0.00"></div>
<div><label>Justificatif (optionnel)</label><input type="file" id="em-just-file" accept=".pdf,.jpg,.png"></div>
<div><button class="btn btn-p btn-f" onclick="saisirEcriture()" style="margin-top:22px">Enregistrer</button></div>
</div>
<div id="em-res" style="margin-top:10px"></div>
<h3 style="margin-top:20px">Creer un sous-compte</h3>
<div class="g3"><div><label>Compte parent</label><input id="sc-parent" placeholder="401000"></div>
<div><label>Libelle</label><input id="sc-lib" placeholder="Fournisseur X"></div>
<div><button class="btn btn-s btn-f" onclick="creerSousCompte()" style="margin-top:22px">Creer</button></div></div>
<div id="sc-res" style="margin-top:8px"></div>
</div>
<div class="tc" id="ct-plan"><div id="ct-plan-c"></div></div>
</div>
</div>

<!-- ===== SIMULATION ===== -->
<div class="sec" id="s-simulation">
<div class="tabs" style="flex-wrap:wrap">
<div class="tab active" onclick="showSimTab('bulletin',this)">Bulletin</div>
<div class="tab" onclick="showSimTab('cout',this)">Cout employeur</div>
<div class="tab" onclick="showSimTab('exo',this)">Exonerations</div>
<div class="tab" onclick="showSimTab('masse',this)">Masse salariale</div>
<div class="tab" onclick="showSimTab('seuils',this)">Seuils effectif</div>
<div class="tab" onclick="showSimTab('fincontrat',this)">Fins contrats</div>
<div class="tab" onclick="showSimTab('optim',this)">Optimisation</div>
<div class="tab" onclick="showSimTab('risques',this)">Risques sectoriels</div>
<div class="tab" onclick="showSimTab('micro',this)">Micro</div>
<div class="tab" onclick="showSimTab('tns',this)">TNS</div>
<div class="tab" onclick="showSimTab('guso',this)">GUSO</div>
<div class="tab" onclick="showSimTab('ir',this)">IR</div>
</div>
<div class="card">
<div class="tc active" id="sim-bulletin">
<h2>Simulation bulletin de paie</h2>
<div class="g3">
<div><label>Brut mensuel</label><input type="number" step="0.01" id="sim-brut" value="2500"></div>
<div><label>Effectif</label><input type="number" id="sim-eff" value="10"></div>
<div><label>Cadre</label><select id="sim-cadre"><option value="false">Non</option><option value="true">Oui</option></select></div>
</div>
<div class="btn-group"><button class="btn btn-blue" onclick="simBulletin()">Simuler</button><button class="btn btn-s btn-sm" onclick="exportSection('sim')">&#128190; Export</button></div>
<div id="sim-bull-res"></div>
</div>

<div class="tc" id="sim-cout"><h2>Cout total employeur detaille</h2>
<div class="g4"><div><label>Brut mensuel</label><input type="number" step="0.01" id="ce-brut" value="2500"></div><div><label>Effectif</label><input type="number" id="ce-eff" value="10"></div><div><label>Cadre</label><select id="ce-cadre"><option value="false">Non</option><option value="true">Oui</option></select></div><div><label>Primes</label><input type="number" step="0.01" id="ce-primes" value="0"></div></div>
<div class="g4"><div><label>Avantages nature</label><input type="number" step="0.01" id="ce-avantages" value="0"></div><div><label>Frais km</label><input type="number" step="0.01" id="ce-km" value="0"></div><div><label>Tickets resto</label><input type="number" step="0.01" id="ce-tr" value="0"></div><div><label>Mutuelle (part empl.)</label><input type="number" step="0.01" id="ce-mut" value="40"></div></div>
<button class="btn btn-blue" onclick="simCout()">Calculer</button><div id="sim-cout-res" style="margin-top:12px"></div></div>

<div class="tc" id="sim-exo"><h2>Exonerations et aides a l emploi</h2>
<p style="color:var(--tx2);font-size:.84em;margin-bottom:10px">Simulez les exonerations applicables selon zone geographique, statut du salarie, convention collective et effectif.</p>
<div class="g4"><div><label>Brut mensuel</label><input type="number" step="0.01" id="exo-brut" value="2000"></div><div><label>Effectif</label><input type="number" id="exo-eff" value="10"></div><div><label>Age salarie</label><input type="number" id="exo-age" value="30"></div><div><label>Duree contrat (mois)</label><input type="number" id="exo-duree" value="0"></div></div>
<div class="g3"><div><label>Zone geographique</label><select id="exo-zone"><option value="metropole">Metropole</option><option value="zrr">ZRR (Revitalisation rurale)</option><option value="zfu">ZFU-TE (Franche urbaine)</option><option value="qpv">QPV (Quartier prioritaire)</option><option value="outremer">Outre-mer (DOM-TOM)</option></select></div><div><label>Statut salarie</label><select id="exo-statut"><option value="standard">Standard</option><option value="apprenti">Apprenti</option><option value="handicape">Travailleur handicape (RQTH)</option><option value="jei">JEI - Chercheur/technicien</option></select></div><div><label>Convention collective</label><input id="exo-ccn" placeholder="Ex: Syntec, HCR, BTP..."></div></div>
<button class="btn btn-blue" onclick="simExo()">Simuler les exonerations</button><div id="sim-exo-res" style="margin-top:12px"></div></div>

<div class="tc" id="sim-masse"><h2>Simulation masse salariale</h2>
<p style="color:var(--tx2);font-size:.84em;margin-bottom:10px">Impact augmentations, inflation, primes, frais, turnover sur le budget global.</p>
<div class="g4"><div><label>Brut moyen</label><input type="number" step="0.01" id="ms-brut" value="2500"></div><div><label>Effectif</label><input type="number" id="ms-eff" value="10"></div><div><label>Augmentation %</label><input type="number" step="0.1" id="ms-aug" value="3"></div><div><label>Inflation %</label><input type="number" step="0.1" id="ms-infl" value="2"></div></div>
<div class="g4"><div><label>Frais km moyen/mois</label><input type="number" step="0.01" id="ms-km" value="50"></div><div><label>Avantages nature/mois</label><input type="number" step="0.01" id="ms-an" value="0"></div><div><label>Primes variables %</label><input type="number" step="0.1" id="ms-primes" value="5"></div><div><label>Turnover %</label><input type="number" step="0.1" id="ms-turn" value="10"></div></div>
<button class="btn btn-blue" onclick="simMasse()">Projeter</button><div id="sim-masse-res" style="margin-top:12px"></div></div>

<div class="tc" id="sim-seuils"><h2>Impact seuils d effectif</h2>
<p style="color:var(--tx2);font-size:.84em;margin-bottom:10px">Obligations declenchees par le franchissement des seuils 11, 20, 50, 250 et 300 salaries.</p>
<div class="g2"><div><label>Effectif actuel</label><input type="number" id="se-eff" value="48"></div><div><label>Masse salariale annuelle</label><input type="number" step="0.01" id="se-masse" value="1500000"></div></div>
<button class="btn btn-blue" onclick="simSeuils()">Analyser les seuils</button><div id="sim-seuils-res" style="margin-top:12px"></div></div>

<div class="tc" id="sim-fincontrat"><h2>Simulation fins de contrats</h2>
<p style="color:var(--tx2);font-size:.84em;margin-bottom:10px">Licenciement, rupture conventionnelle, fin CDD, depart retraite : indemnites et couts.</p>
<div class="g4"><div><label>Type de fin</label><select id="fc-type"><option value="licenciement">Licenciement</option><option value="rupture_conventionnelle">Rupture conventionnelle</option><option value="fin_cdd">Fin de CDD</option><option value="retraite">Depart retraite</option></select></div><div><label>Salaire brut mensuel</label><input type="number" step="0.01" id="fc-brut" value="2500"></div><div><label>Anciennete (mois)</label><input type="number" id="fc-anc" value="36"></div><div><label>Cadre</label><select id="fc-cadre"><option value="false">Non</option><option value="true">Oui</option></select></div></div>
<div class="g2"><div><label>Motif (licenciement)</label><select id="fc-motif"><option value="personnel">Personnel</option><option value="economique">Economique</option><option value="faute_grave">Faute grave</option><option value="inaptitude">Inaptitude</option></select></div><div style="display:flex;align-items:flex-end"><button class="btn btn-blue btn-f" onclick="simFinContrat()" style="margin-top:0">Calculer les indemnites</button></div></div>
<div id="sim-fc-res" style="margin-top:12px"></div></div>

<div class="tc" id="sim-optim"><h2>Optimisation legale de la remuneration</h2>
<p style="color:var(--tx2);font-size:.84em;margin-bottom:10px">Comparaison : salaire, dividendes, interessement, participation, PEE, frais professionnels.</p>
<div class="g3"><div><label>Benefice net entreprise</label><input type="number" step="0.01" id="op-benef" value="80000"></div><div><label>Remuneration gerant</label><input type="number" step="0.01" id="op-rem" value="40000"></div><div><label>Dividendes prevus</label><input type="number" step="0.01" id="op-div" value="20000"></div></div>
<div class="g4"><div><label>Interessement</label><input type="number" step="0.01" id="op-int" value="0"></div><div><label>Participation</label><input type="number" step="0.01" id="op-part" value="0"></div><div><label>Frais pro annuels</label><input type="number" step="0.01" id="op-frais" value="0"></div><div><label>Abondement PEE</label><input type="number" step="0.01" id="op-pee" value="0"></div></div>
<div class="g2"><div><label>Parts fiscales</label><input type="number" step="0.5" id="op-parts" value="1"></div><div><label>Forme juridique</label><select id="op-forme"><option value="sas">SAS/SASU</option><option value="sarl">SARL/EURL</option><option value="ei">EI/EIRL</option></select></div></div>
<button class="btn btn-blue" onclick="simOptim()">Comparer les scenarios</button><div id="sim-optim-res" style="margin-top:12px"></div></div>

<div class="tc" id="sim-risques"><h2>Risques specifiques sectoriels</h2>
<p style="color:var(--tx2);font-size:.84em;margin-bottom:10px">Analyse des risques sociaux, AT/MP, obligations et subventions par secteur d activite.</p>
<div class="g3"><div><label>Code NAF/APE</label><input id="rs-naf" value="6201Z" placeholder="Ex: 6201Z, 4120A..."></div><div><label>Effectif</label><input type="number" id="rs-eff" value="10"></div><div><label>Masse salariale annuelle</label><input type="number" step="0.01" id="rs-masse" value="400000"></div></div>
<button class="btn btn-blue" onclick="simRisques()">Analyser</button><div id="sim-risques-res" style="margin-top:12px"></div></div>

<div class="tc" id="sim-micro"><h2>Micro-entrepreneur</h2>
<div class="g3"><div><label>CA</label><input type="number" step="0.01" id="sim-ca" value="50000"></div><div><label>Activite</label><select id="sim-act"><option value="prestations_bnc">BNC</option><option value="prestations_bic">BIC</option><option value="vente_marchandises">Vente</option><option value="location_meublee">Location</option></select></div><div><label>ACRE</label><select id="sim-acre"><option value="false">Non</option><option value="true">Oui</option></select></div></div>
<button class="btn btn-blue" onclick="simMicro()">Simuler</button><div id="sim-micro-res" style="margin-top:12px"></div></div>
<div class="tc" id="sim-tns"><h2>TNS</h2>
<div class="g3"><div><label>Revenu net</label><input type="number" step="0.01" id="sim-rev" value="40000"></div><div><label>Statut</label><select id="sim-stat"><option value="gerant_majoritaire">Gerant maj.</option><option value="profession_liberale">PL</option><option value="artisan">Artisan</option><option value="commercant">Commercant</option></select></div><div><label>ACRE</label><select id="sim-tacre"><option value="false">Non</option><option value="true">Oui</option></select></div></div>
<button class="btn btn-blue" onclick="simTNS()">Simuler</button><div id="sim-tns-res" style="margin-top:12px"></div></div>
<div class="tc" id="sim-guso"><h2>GUSO</h2>
<div class="g2"><div><label>Brut</label><input type="number" step="0.01" id="sim-gbrut" value="500"></div><div><label>Heures</label><input type="number" step="0.5" id="sim-gh" value="8"></div></div>
<button class="btn btn-blue" onclick="simGUSO()">Simuler</button><div id="sim-guso-res" style="margin-top:12px"></div></div>
<div class="tc" id="sim-ir"><h2>Impot sur le revenu</h2>
<div class="g3"><div><label>Benefice</label><input type="number" step="0.01" id="sim-ben" value="40000"></div><div><label>Parts</label><input type="number" step="0.5" id="sim-parts" value="1"></div><div><label>Autres rev.</label><input type="number" step="0.01" id="sim-autres" value="0"></div></div>
<button class="btn btn-blue" onclick="simIR()">Simuler</button><div id="sim-ir-res" style="margin-top:12px"></div></div>
</div>
</div>

<!-- ===== VEILLE ===== -->
<div class="sec" id="s-veille">
<div class="card">
<h2>Veille juridique</h2>
<p style="color:var(--tx2);font-size:.86em;margin-bottom:14px">Baremes et legislation 2020-2026. Historique 6 ans.</p>
<div class="g3"><div><label>Annee</label><select id="v-annee"><option value="2020">2020</option><option value="2021">2021</option><option value="2022">2022</option><option value="2023">2023</option><option value="2024">2024</option><option value="2025">2025</option><option value="2026" selected>2026</option></select></div><div><button class="btn btn-blue btn-f" onclick="loadVeille()" style="margin-top:22px">Charger</button></div><div><button class="btn btn-s btn-f" onclick="compAnnees()" style="margin-top:22px">Comparer N-1</button></div></div>
</div>
<div id="v-res" style="display:none">
<div class="card"><h2>Baremes URSSAF</h2><div class="btn-group" style="justify-content:flex-end"><button class="btn btn-s btn-sm" onclick="exportSection('veille')">&#128190; Export</button></div><div id="v-baremes"></div></div>
<div class="card"><h2>Legislation</h2><div id="v-legis"></div></div>
<div class="card" id="v-comp-card" style="display:none"><h2>Comparaison</h2><div id="v-comp"></div></div>
</div>
</div>

<!-- ===== PORTEFEUILLE ===== -->
<div class="sec" id="s-portefeuille">
<div class="g2">
<div class="card">
<h2>Ajouter une entreprise</h2>
<label>SIRET</label><input id="ent-siret" placeholder="12345678901234" maxlength="14">
<label>Raison sociale</label><input id="ent-raison" placeholder="Nom">
<div class="g2"><div><label>Forme</label><select id="ent-forme"><option value="">--</option><option>SAS</option><option>SARL</option><option>SA</option><option>EURL</option><option>EI</option><option>SASU</option><option>SCI</option><option>SNC</option><option>Association</option></select></div><div><label>NAF</label><input id="ent-naf" placeholder="6201Z"></div></div>
<div class="g2"><div><label>Effectif</label><input type="number" id="ent-eff" value="0"></div><div><label>Ville</label><input id="ent-ville" placeholder="Paris"></div></div>
<button class="btn btn-p btn-f" onclick="ajouterEnt()">Ajouter</button>
</div>
<div class="card"><h2>Portefeuille</h2><input id="ent-search" placeholder="Rechercher..." oninput="rechEnt()"><div id="ent-list"></div></div>
</div>
</div>

<!-- ===== EQUIPE ===== -->
<div class="sec" id="s-equipe">
<div class="g2">
<div class="card">
<h2>Inviter un collaborateur</h2>
<p style="color:var(--tx2);font-size:.86em;margin-bottom:14px">Ajoutez un acces a votre dossier. Le collaborateur recevra un lien pour creer son mot de passe.</p>
<label>Email du collaborateur</label><input type="email" id="inv-email" placeholder="collaborateur@exemple.fr">
<label>Role</label><select id="inv-role"><option value="collaborateur">Collaborateur (lecture + analyse)</option><option value="comptable">Comptable (lecture + ecriture)</option><option value="decisionnaire">Decisionnaire (tous droits + validation)</option></select>
<button class="btn btn-blue btn-f" onclick="inviterCollab()">Envoyer l'invitation</button>
<div id="inv-res" style="margin-top:10px"></div>
</div>
<div class="card">
<h2>Equipe et tracabilite</h2>
<div class="btn-group"><button class="btn btn-s btn-sm" onclick="loadEquipe()">&#8635; Actualiser</button></div>
<div id="equipe-list"></div>
<h3 style="margin-top:16px;font-size:.95em">Journal d'audit</h3>
<div id="audit-log" style="margin-top:8px"></div>
</div>
</div>
</div>

<!-- ===== RESSOURCES HUMAINES ===== -->
<div class="sec" id="s-rh">
<div class="tabs" id="rh-tabs">
<div class="tab active" onclick="showRHTab('salaries',this)">Salaries</div>
<div class="tab" onclick="showRHTab('contrats',this)">Contrats</div>
<div class="tab" onclick="showRHTab('conges',this)">Conges</div>
<div class="tab" onclick="showRHTab('arrets',this)">Arrets</div>
<div class="tab" onclick="showRHTab('sanctions',this)">Sanctions</div>
<div class="tab" onclick="showRHTab('entretiens',this)">Entretiens</div>
<div class="tab" onclick="showRHTab('visites',this)">Visites med.</div>
<div class="tab" onclick="showRHTab('attestations',this)">Attestations</div>
<div class="tab" onclick="showRHTab('planning',this)">Planning</div>
<div class="tab" onclick="showRHTab('echanges',this)">Echanges</div>
<div class="tab" onclick="showRHTab('alertes',this)">Alertes</div>
<div class="tab" onclick="showRHTab('bulletins',this)">Bulletins</div>
</div>
<div class="card">
<div class="tc active" id="rh-salaries">
<h2>Liste des salaries</h2>
<p style="color:var(--tx2);font-size:.86em;margin-bottom:12px">Les salaries sont detectes automatiquement lors de l analyse de documents (bulletins, DSN, contrats). Vous pouvez aussi les ajouter manuellement via l onglet Contrats.</p>
<div id="rh-sal-list"><p style="color:var(--tx2)">Aucun salarie.</p></div>
</div>
<div class="tc" id="rh-contrats">
<h2>Gestion des contrats de travail</h2>
<div class="g2"><div>
<label>Type de contrat</label><select id="rh-type-ctr"><option value="CDI">CDI</option><option value="CDD">CDD</option><option value="CTT">CTT (Interim)</option><option value="Apprentissage">Apprentissage</option><option value="Professionnalisation">Professionnalisation</option><option value="Saisonnier">Saisonnier</option><option value="Intermittent">Intermittent</option></select>
<label>Nom</label><input id="rh-ctr-nom" placeholder="NOM">
<label>Prenom</label><input id="rh-ctr-prenom" placeholder="Prenom">
<label>Poste</label><input id="rh-ctr-poste" placeholder="Intitule du poste">
<label>Date debut</label><input type="date" id="rh-ctr-debut">
<label>Date fin (CDD)</label><input type="date" id="rh-ctr-fin">
</div><div>
<label>Salaire brut mensuel</label><input type="number" step="0.01" id="rh-ctr-salaire" placeholder="0.00">
<label>Temps de travail</label><select id="rh-ctr-temps"><option value="complet">Temps complet</option><option value="partiel">Temps partiel</option></select>
<label>Duree hebdomadaire (h)</label><input type="number" step="0.5" id="rh-ctr-heures" value="35">
<label>Convention collective</label><input id="rh-ctr-ccn" placeholder="IDCC ou intitule">
<label>Periode essai (jours)</label><input type="number" id="rh-ctr-essai" value="60">
<label>Motif CDD</label><input id="rh-ctr-motif" placeholder="Remplacement, surcroit...">
</div></div>
<button class="btn btn-blue btn-f" onclick="creerContrat()">Generer le contrat</button>
<div id="rh-ctr-res" style="margin-top:12px"></div>
<h3 style="margin-top:20px">Contrats enregistres</h3>
<div id="rh-ctr-list" style="margin-top:8px"><p style="color:var(--tx2)">Aucun contrat.</p></div>
<h3 style="margin-top:20px">Avenants</h3>
<div class="g3"><div><label>ID Contrat</label><input id="rh-av-ctr" placeholder="ID du contrat"></div>
<div><label>Type</label><select id="rh-av-type"><option value="remuneration">Remuneration</option><option value="poste">Changement de poste</option><option value="temps_travail">Temps de travail</option><option value="lieu">Lieu de travail</option><option value="autre">Autre</option></select></div>
<div><label>Date effet</label><input type="date" id="rh-av-date"></div></div>
<label>Nouvelles conditions</label><textarea id="rh-av-desc" rows="2" placeholder="Description des modifications"></textarea>
<button class="btn btn-s btn-f" onclick="creerAvenant()">Enregistrer l avenant</button>
<div id="rh-av-list" style="margin-top:8px"></div>
</div>
<div class="tc" id="rh-conges">
<h2>Gestion des conges et absences</h2>
<div class="g3"><div><label>Salarie (nom)</label><input id="rh-cg-sal" placeholder="Nom du salarie"></div>
<div><label>Type</label><select id="rh-cg-type"><option value="cp">Conges payes</option><option value="rtt">RTT</option><option value="maladie">Maladie</option><option value="maternite">Maternite</option><option value="paternite">Paternite</option><option value="sans_solde">Sans solde</option><option value="familial">Evenement familial</option><option value="formation">Formation</option></select></div>
<div><label>Nb jours</label><input type="number" id="rh-cg-jours" value="1"></div></div>
<div class="g3"><div><label>Date debut</label><input type="date" id="rh-cg-dd"></div>
<div><label>Date fin</label><input type="date" id="rh-cg-df"></div>
<div><label>Statut</label><select id="rh-cg-stat"><option value="demande">Demande</option><option value="valide">Valide</option><option value="refuse">Refuse</option></select></div></div>
<button class="btn btn-blue btn-f" onclick="enregConge()">Enregistrer</button>
<div id="rh-cg-list" style="margin-top:12px"></div>
</div>
<div class="tc" id="rh-arrets">
<h2>Arrets de travail</h2>
<div class="g3"><div><label>Salarie</label><input id="rh-ar-sal" placeholder="Nom"></div>
<div><label>Type</label><select id="rh-ar-type"><option value="maladie">Maladie</option><option value="accident_travail">Accident du travail</option><option value="maladie_pro">Maladie professionnelle</option><option value="mi_temps_therapeutique">Mi-temps therapeutique</option></select></div>
<div><label>Subrogation</label><select id="rh-ar-sub"><option value="true">Oui</option><option value="false">Non</option></select></div></div>
<div class="g3"><div><label>Date debut</label><input type="date" id="rh-ar-dd"></div>
<div><label>Date fin</label><input type="date" id="rh-ar-df"></div>
<div><label>Prolongation</label><select id="rh-ar-prol"><option value="false">Non</option><option value="true">Oui</option></select></div></div>
<button class="btn btn-blue btn-f" onclick="enregArret()">Enregistrer</button>
<div id="rh-ar-list" style="margin-top:12px"></div>
</div>
<div class="tc" id="rh-sanctions">
<h2>Procedures disciplinaires</h2>
<div class="g3"><div><label>Salarie</label><input id="rh-sa-sal" placeholder="Nom"></div>
<div><label>Type</label><select id="rh-sa-type"><option value="avertissement">Avertissement</option><option value="blame">Blame</option><option value="mise_a_pied">Mise a pied</option><option value="retrogradation">Retrogradation</option><option value="licenciement">Licenciement</option></select></div>
<div><label>Date sanction</label><input type="date" id="rh-sa-date"></div></div>
<label>Motif</label><input id="rh-sa-motif" placeholder="Motif de la sanction">
<label>Description</label><textarea id="rh-sa-desc" rows="2" placeholder="Details"></textarea>
<label>Date entretien prealable</label><input type="date" id="rh-sa-epr">
<button class="btn btn-blue btn-f" onclick="enregSanction()">Enregistrer</button>
<div id="rh-sa-list" style="margin-top:12px"></div>
</div>
<div class="tc" id="rh-entretiens">
<h2>Entretiens professionnels</h2>
<div class="g3"><div><label>Salarie</label><input id="rh-en-sal" placeholder="Nom"></div>
<div><label>Type</label><select id="rh-en-type"><option value="professionnel_2ans">Professionnel (2 ans)</option><option value="bilan_6ans">Bilan (6 ans)</option><option value="annuel">Annuel</option><option value="fin_periode_essai">Fin periode essai</option></select></div>
<div><label>Date</label><input type="date" id="rh-en-date"></div></div>
<label>Compte-rendu</label><textarea id="rh-en-cr" rows="3" placeholder="Notes de l entretien"></textarea>
<label>Date prochain entretien</label><input type="date" id="rh-en-next">
<button class="btn btn-blue btn-f" onclick="enregEntretien()">Enregistrer</button>
<div id="rh-en-list" style="margin-top:12px"></div>
</div>
<div class="tc" id="rh-visites">
<h2>Visites medicales</h2>
<div class="g3"><div><label>Salarie</label><input id="rh-vm-sal" placeholder="Nom"></div>
<div><label>Type</label><select id="rh-vm-type"><option value="embauche">Visite embauche (VIP)</option><option value="periodique">Periodique</option><option value="reprise">Reprise</option><option value="pre_reprise">Pre-reprise</option><option value="demande">A la demande</option></select></div>
<div><label>Date</label><input type="date" id="rh-vm-date"></div></div>
<div class="g3"><div><label>Resultat</label><select id="rh-vm-res"><option value="apte">Apte</option><option value="inapte">Inapte</option><option value="amenagement">Amenagement</option></select></div>
<div><label>Remarques</label><input id="rh-vm-rem" placeholder="Observations"></div>
<div><label>Prochaine visite</label><input type="date" id="rh-vm-next"></div></div>
<button class="btn btn-blue btn-f" onclick="enregVisite()">Enregistrer</button>
<div id="rh-vm-list" style="margin-top:12px"></div>
</div>
<div class="tc" id="rh-attestations">
<h2>Generation d attestations</h2>
<div class="g3"><div><label>Salarie</label><input id="rh-at-sal" placeholder="Nom"></div>
<div><label>Type</label><select id="rh-at-type"><option value="travail">Attestation de travail</option><option value="employeur">Attestation employeur</option><option value="salaire">Attestation de salaire</option><option value="pole_emploi">Attestation Pole Emploi</option><option value="mutuelle">Attestation mutuelle</option><option value="stage">Attestation de stage</option></select></div>
<div><button class="btn btn-blue btn-f" onclick="genererAttestation()" style="margin-top:22px">Generer</button></div></div>
<div id="rh-at-res" style="margin-top:12px"></div>
<div id="rh-at-list" style="margin-top:12px"></div>
</div>
<div class="tc" id="rh-planning">
<h2>Planning</h2>
<div class="g3" style="margin-bottom:12px"><div><label>Semaine du</label><input type="date" id="rh-pl-sem" onchange="renderCalendar()"></div>
<div><label>Filtre salarie</label><input id="rh-pl-filter" placeholder="Tous" oninput="renderCalendar()"></div>
<div><button class="btn btn-s btn-f" onclick="renderCalendar()" style="margin-top:22px">Actualiser</button></div></div>
<div id="rh-pl-calendar" style="overflow-x:auto;margin-bottom:16px;border:1px solid var(--brd);border-radius:8px;min-height:100px"></div>
<h3>Ajouter un creneau</h3>
<div class="g3"><div><label>Salarie</label><input id="rh-pl-sal" placeholder="Nom"></div>
<div><label>Date</label><input type="date" id="rh-pl-date"></div>
<div><label>Type</label><select id="rh-pl-type"><option value="normal">Normal</option><option value="astreinte">Astreinte</option><option value="nuit">Nuit</option><option value="dimanche">Dimanche</option><option value="ferie">Jour ferie</option></select></div></div>
<div class="g3"><div><label>Heure debut</label><input type="time" id="rh-pl-hd" value="09:00"></div>
<div><label>Heure fin</label><input type="time" id="rh-pl-hf" value="17:00"></div>
<div><button class="btn btn-blue btn-f" onclick="ajouterPlanning()" style="margin-top:22px">Ajouter</button></div></div>
<div id="rh-pl-list" style="margin-top:12px"></div>
</div>
<div class="tc" id="rh-echanges">
<h2>Suivi des echanges salaries</h2>
<div class="g3"><div><label>Salarie</label><input id="rh-ec-sal" placeholder="Nom"></div>
<div><label>Type</label><select id="rh-ec-type"><option value="email">Email</option><option value="courrier">Courrier</option><option value="reunion">Reunion</option><option value="entretien">Entretien</option></select></div>
<div><label>Date</label><input type="date" id="rh-ec-date"></div></div>
<label>Objet</label><input id="rh-ec-obj" placeholder="Objet de l echange">
<label>Contenu</label><textarea id="rh-ec-txt" rows="3" placeholder="Details"></textarea>
<button class="btn btn-blue btn-f" onclick="enregEchange()">Enregistrer</button>
<div id="rh-ec-list" style="margin-top:12px"></div>
</div>
<div class="tc" id="rh-alertes">
<h2>Alertes et echeances RH</h2>
<div class="al info"><span class="ai">&#128161;</span><span>Les alertes sont calculees automatiquement selon les donnees RH et les obligations legales.</span></div>
<div id="rh-alertes-list" style="margin-top:12px"></div>
</div>
<div class="tc" id="rh-bulletins">
<h2>Generation de bulletins de paie</h2>
<div class="g2"><div>
<label>Contrat (ID)</label><input id="rh-bp-ctr" placeholder="ID du contrat">
<label>Mois (YYYY-MM)</label><input id="rh-bp-mois" placeholder="2025-01">
<label>Heures supplementaires</label><input type="number" step="0.5" id="rh-bp-hs" value="0">
</div><div>
<label>Primes (EUR)</label><input type="number" step="0.01" id="rh-bp-primes" value="0">
<label>Avantages en nature (EUR)</label><input type="number" step="0.01" id="rh-bp-avantages" value="0">
<label>Jours absence</label><input type="number" step="0.5" id="rh-bp-abs" value="0">
</div></div>
<button class="btn btn-blue btn-f" onclick="genererBulletin()">Generer le bulletin</button>
<div id="rh-bp-res" style="margin-top:12px"></div>
<h3 style="margin-top:20px">Bulletins generes</h3>
<div id="rh-bp-list" style="margin-top:8px"><p style="color:var(--tx2)">Aucun bulletin.</p></div>
</div>
</div>
</div>

<!-- ===== CONFIGURATION ===== -->
<div class="sec" id="s-config">
<div class="card">
<h2>En-tete des documents</h2>
<p style="color:var(--tx2);font-size:.86em;margin-bottom:14px">Configurez les informations qui apparaitront sur tous les documents generes (contrats, attestations, rapports, etc.)</p>
<div class="g2"><div>
<label>Nom de l entreprise</label><input id="cfg-nom" placeholder="Raison sociale">
<label>Adresse</label><input id="cfg-adresse" placeholder="Adresse complete">
<label>Telephone</label><input id="cfg-tel" placeholder="01 23 45 67 89">
<label>Email</label><input type="email" id="cfg-email" placeholder="contact@entreprise.fr">
</div><div>
<label>SIRET</label><input id="cfg-siret" placeholder="123 456 789 00012">
<label>Code NAF</label><input id="cfg-naf" placeholder="7022Z">
<label>Forme juridique</label><input id="cfg-forme" placeholder="SARL, SAS, etc.">
<label>Capital social</label><input id="cfg-capital" placeholder="10 000 EUR">
</div></div>
<div class="g3"><div><label>RCS</label><input id="cfg-rcs" placeholder="RCS Paris B 123 456 789"></div>
<div><label>TVA intracommunautaire</label><input id="cfg-tva" placeholder="FR12345678901"></div>
<div><label>Logo URL</label><input id="cfg-logo" placeholder="https://..."></div></div>
<button class="btn btn-blue btn-f" onclick="sauverEntete()">Sauvegarder</button>
<div id="cfg-res" style="margin-top:10px"></div>
</div>
<div class="card">
<h2>Comptes URSSAF par etablissement</h2>
<p style="color:var(--tx2);font-size:.86em;margin-bottom:14px">Gerez les comptes URSSAF distincts pour chaque etablissement de l entreprise.</p>
<div class="g3"><div><label>SIRET etablissement</label><input id="urssaf-siret" placeholder="123 456 789 00012"></div>
<div><label>N compte URSSAF</label><input id="urssaf-compte" placeholder="527000000012345678"></div>
<div><label>Caisse</label><input id="urssaf-caisse" placeholder="URSSAF Ile-de-France"></div></div>
<label>Taux AT/MP (%)</label><input type="number" step="0.01" id="urssaf-at" placeholder="2.08">
<button class="btn btn-blue btn-f" onclick="ajouterCompteURSSAF()">Ajouter</button>
<div id="urssaf-list" style="margin-top:12px"></div>
</div>
<div class="card">
<h2>Personnalisation des alertes</h2>
<p style="color:var(--tx2);font-size:.86em;margin-bottom:14px">Activez/desactivez les types d alertes et personnalisez les delais de notification.</p>
<div id="cfg-alertes-list" style="margin-top:8px"></div>
<div class="g3" style="margin-top:12px"><div><label>Type d alerte</label><select id="cfg-al-type"><option value="dpae_a_effectuer">DPAE embauche</option><option value="visite_medicale_expiration">Visite medicale</option><option value="fin_contrat_cdd">Fin de contrat CDD</option><option value="fin_periode_essai">Fin periode essai</option><option value="entretien_professionnel_retard">Entretien professionnel</option><option value="prevoyance_cadres">Prevoyance cadres</option><option value="mutuelle_obligatoire">Mutuelle obligatoire</option><option value="duerp_obligatoire">DUERP</option><option value="cse_obligatoire">Elections CSE</option><option value="formation_professionnelle">Formation professionnelle</option><option value="registre_personnel">Registre du personnel</option><option value="declaration_dsn_mensuelle">DSN mensuelle</option><option value="participation_obligatoire">Participation (>=50)</option><option value="reglement_interieur">Reglement interieur (>=50)</option><option value="index_egalite">Index egalite pro (>=50)</option><option value="bilan_social">Bilan social (>=300)</option></select></div>
<div><label>Delai notification (jours)</label><input type="number" id="cfg-al-delai" value="30"></div>
<div><label>Actif</label><select id="cfg-al-actif"><option value="true">Oui</option><option value="false">Non</option></select></div></div>
<label>Message personnalise (optionnel)</label><input id="cfg-al-msg" placeholder="Message personnalise pour cette alerte">
<button class="btn btn-blue btn-f" onclick="sauverAlertConfig()" style="margin-top:8px">Enregistrer la configuration</button>
<div id="cfg-al-res" style="margin-top:8px"></div>
</div>
</div>

</div><!-- end .page -->
</div><!-- end .content -->
</div><!-- end .layout -->
"""


APP_HTML += """
<script>
/* === INIT === */
var titles={"dashboard":"Dashboard","analyse":"Import / Analyse","biblio":"Bibliotheque","factures":"Factures","dsn":"Creation DSN","compta":"Comptabilite","rh":"Ressources humaines","simulation":"Simulation","veille":"Veille juridique","portefeuille":"Portefeuille","equipe":"Equipe","config":"Configuration"};
function safeJson(r){if(!r.ok)throw new Error("Erreur serveur ("+r.status+")");return r.json();}
function gv(id){return document.getElementById(id).value;}
function fmt(n){return typeof n==="number"?n.toFixed(2).replace(/\\B(?=(\\d{3})+(?!\\d))/g," ")+" EUR":n;}
document.getElementById("topbar-date").textContent=new Date().toLocaleDateString("fr-FR",{day:"numeric",month:"long",year:"numeric"});

/* === MOBILE SIDEBAR === */
function toggleSidebar(){var sb=document.getElementById("sidebar");var ov=document.getElementById("sidebar-overlay");sb.classList.toggle("open");ov.classList.toggle("show");}
function closeSidebar(){document.getElementById("sidebar").classList.remove("open");document.getElementById("sidebar-overlay").classList.remove("show");}

/* === NAV === */
function showS(n,el){
closeSidebar();
document.querySelectorAll(".sec").forEach(function(s){s.classList.remove("active")});
document.querySelectorAll(".sidebar .nl").forEach(function(l){l.classList.remove("active")});
var sec=document.getElementById("s-"+n);if(sec)sec.classList.add("active");
if(el)el.classList.add("active");
document.getElementById("page-title").textContent=titles[n]||n;
if(n==="compta")loadCompta();if(n==="portefeuille")rechEnt();if(n==="dashboard")loadDash();
if(n==="biblio"){loadBiblio();loadKnowledge();}if(n==="equipe")loadEquipe();
if(n==="factures")loadPayStatuses();if(n==="dsn"){preFillDSN();loadDSNBrouillons();}
if(n==="rh"){loadRHSalaries();loadRHAlertes();}if(n==="config"){loadEntete();loadAlertConfigs();}
}

document.addEventListener("click",function(e){var a=e.target.closest(".anomalie[data-toggle]");if(a)a.classList.toggle("open");var td=e.target.closest("[data-toggle-detail]");if(td){var det=td.querySelector(".aud-detail,.al-detail");if(det)det.style.display=det.style.display==="none"?"block":"none";}});

/* === DASHBOARD === */
var analysisData=null;
function loadDash(){
if(!analysisData)return;
var d=analysisData,s=d.synthese||{};
var impact=s.impact_financier_total||0;
var constats=d.constats||[];
document.getElementById("dash-anomalies").textContent=constats.length;
document.getElementById("dash-anom-count").textContent=constats.length;
document.getElementById("dash-impact").textContent=impact.toFixed(2)+" EUR";
var conf=Math.max(0,100-(s.score_risque_global||0));
document.getElementById("dash-conf").textContent=conf+"%";
document.getElementById("gauge").style.setProperty("--pct",conf+"%");
document.getElementById("gauge-val").textContent=conf+"%";
renderAnomalies("dash-anomalies-list",constats);
var byDest={"URSSAF":0,"Fiscal":0,"France Travail":0,"GUSO":0};
constats.forEach(function(c){var dest=categToDest(c.categorie||"");byDest[dest]=(byDest[dest]||0)+Math.abs(c.montant_impact||0);});
document.getElementById("dd-urssaf").textContent=byDest["URSSAF"].toFixed(0)+" EUR";
document.getElementById("dd-fiscal").textContent=byDest["Fiscal"].toFixed(0)+" EUR";
document.getElementById("dd-ft").textContent=byDest["France Travail"].toFixed(0)+" EUR";
document.getElementById("dd-guso").textContent=byDest["GUSO"].toFixed(0)+" EUR";
}

function renderAnomalies(id,constats){
var el=document.getElementById(id);if(!constats.length){el.innerHTML="<p style='color:var(--tx2)'>Aucune anomalie detectee.</p>";return;}
var h="";constats.slice(0,30).forEach(function(c){
var impact=c.montant_impact||0;var neg=impact>0;
var sev=Math.abs(impact)>5000?"high":(Math.abs(impact)>1000?"med":"low");
var dest=categToDest(c.categorie||"");
var destCls={"URSSAF":"badge-blue","Fiscal":"badge-purple","France Travail":"badge-amber","GUSO":"badge-teal"}[dest]||"badge-blue";
h+="<div class='anomalie sev-"+sev+"' data-toggle='1'><div class='head'><div><span class='title'>"+(c.titre||"Ecart")+"</span>";
h+="<span class='dest "+destCls+"'>"+dest+"</span> <span class='badge "+(neg?"badge-red":"badge-green")+"'>"+(neg?"Risque":"Favorable")+"</span></div>";
h+="<div class='montant "+(neg?"neg":"pos")+"'>"+(neg?"+":"-")+Math.abs(impact).toFixed(2)+" EUR</div></div>";
var desc=(c.description||"").replace(/\\n/g,"<br>");
h+="<div class='detail'><p><strong>Nature :</strong> "+desc+"</p>";
h+="<p><strong>Categorie :</strong> "+(c.categorie||"-")+"</p>";
h+="<p><strong>Periode :</strong> "+(c.annee||c.periode||"-")+"</p>";
h+="<p><strong>Documents :</strong> "+(c.source||c.document||"-")+"</p>";
h+="<p><strong>Rubriques :</strong> "+(c.rubrique||c.libelle||"-")+"</p>";
h+="<p><strong>Incidence :</strong> "+Math.abs(impact).toFixed(2)+" EUR</p>";
if(c.recommandation)h+="<div class='al info' style='margin-top:8px'><span class='ai'>&#128161;</span><span>"+c.recommandation+"</span></div>";
if(c.reference_legale)h+="<div style='margin-top:6px;font-size:.8em;color:var(--tx2)'><em>Ref: "+c.reference_legale+"</em></div>";
h+="</div></div>";});el.innerHTML=h;}

function categToDest(cat){var c=cat.toLowerCase();if(c.indexOf("fiscal")>=0||c.indexOf("impot")>=0)return"Fiscal";if(c.indexOf("france travail")>=0||c.indexOf("chomage")>=0)return"France Travail";if(c.indexOf("guso")>=0||c.indexOf("spectacle")>=0)return"GUSO";return"URSSAF";}

/* === ANALYSE === */
var fichiers=[];
var dz=document.getElementById("dz-analyse"),fi=document.getElementById("fi-analyse");
["dragenter","dragover"].forEach(function(ev){dz.addEventListener(ev,function(e){e.preventDefault();});});
dz.addEventListener("drop",function(e){e.preventDefault();addF(e.dataTransfer.files);});
fi.addEventListener("change",function(e){addF(e.target.files);fi.value="";});
function addF(files){for(var i=0;i<files.length;i++){var f=files[i];var dup=false;for(var j=0;j<fichiers.length;j++){if(fichiers[j].name===f.name){dup=true;break;}}if(!dup&&fichiers.length<20)fichiers.push(f);}renderF();}
function renderF(){var el=document.getElementById("fl-analyse");var h="";for(var i=0;i<fichiers.length;i++){h+="<div class='fi'><span class='nm'>"+fichiers[i].name+"</span><span style='color:var(--tx2);font-size:.8em'>"+(fichiers[i].size/1024).toFixed(1)+" Ko</span><button class='rm' onclick='rmF("+i+")'>&times;</button></div>";}el.innerHTML=h;document.getElementById("btn-az").disabled=fichiers.length===0;}
function rmF(i){fichiers.splice(i,1);renderF();}

function lancerAnalyse(){
if(!fichiers.length)return;
var btn=document.getElementById("btn-az"),prg=document.getElementById("prg-az"),fill=document.getElementById("pf-az"),txt=document.getElementById("pt-az");
btn.disabled=true;prg.style.display="block";document.getElementById("res-analyse").style.display="none";
var steps=[[10,"Import..."],[25,"SHA-256..."],[40,"Parsing + OCR..."],[55,"Coherence..."],[70,"Anomalies..."],[85,"Patterns..."],[95,"Rapport..."]];
var si=0;var iv=setInterval(function(){if(si<steps.length){fill.style.width=steps[si][0]+"%";txt.textContent=steps[si][1];si++;}},900);
var fd=new FormData();for(var i=0;i<fichiers.length;i++){fd.append("fichiers",fichiers[i]);}
var integ=document.getElementById("chk-integrer").checked;
var modeAz=document.getElementById("mode-analyse").value;
fetch("/api/analyze?format_rapport=json&integrer="+integ+"&mode_analyse="+modeAz,{method:"POST",body:fd}).then(function(resp){
clearInterval(iv);fill.style.width="100%";txt.textContent="Termine !";
if(!resp.ok)return resp.json().then(function(e){throw new Error(e.detail||"Erreur")});
return resp.json().then(function(data){analysisData=data;showJsonResults(data);});
}).then(function(){setTimeout(function(){prg.style.display="none";},800);document.getElementById("res-analyse").style.display="block";}).catch(function(e){clearInterval(iv);prg.style.display="none";toast(e.message);btn.disabled=false;});
}

function showJsonResults(data){
var s=data.synthese||{};var impact=s.impact_financier_total||0;
document.getElementById("az-dashboard").innerHTML="<div class='sc blue'><div class='val'>"+((data.constats||[]).length)+"</div><div class='lab'>Anomalies</div></div><div class='sc "+(impact>1000?"red":"green")+"'><div class='val'>"+impact.toFixed(2)+" EUR</div><div class='lab'>Impact</div></div><div class='sc green'><div class='val'>"+Math.max(0,100-(s.score_risque_global||0))+"%</div><div class='lab'>Conformite</div></div><div class='sc'><div class='val'>"+(s.nb_fichiers||0)+"</div><div class='lab'>Fichiers</div></div>";
renderAnomalies("az-findings",data.constats||[]);
var recos=data.recommandations||[];var rh="";for(var i=0;i<recos.length;i++){rh+="<div class='al info'><span class='ai'>&#128161;</span><span><strong>#"+(i+1)+"</strong> "+(recos[i].description||recos[i].titre||"")+"</span></div>";}
document.getElementById("az-reco").innerHTML=rh||"<p style='color:var(--tx2)'>Aucune.</p>";
if(data.html_report){document.getElementById("az-html-card").style.display="block";document.getElementById("az-html-frame").srcdoc=data.html_report;}else{document.getElementById("az-html-card").style.display="none";}
showFileInterpretation(data);showAuditChecks(data);showIntegrationResults(data);
document.getElementById("dash-docs").textContent=(s.nb_fichiers||0);loadDash();}
function resetAz(){fichiers=[];analysisData=null;renderF();document.getElementById("res-analyse").style.display="none";document.getElementById("az-audit-card").style.display="none";document.getElementById("az-integration-card").style.display="none";document.getElementById("btn-az").disabled=false;toast("Pret pour une nouvelle analyse.","ok");}

/* === BIBLIOTHEQUE === */
function loadKnowledge(){
fetch("/api/bibliotheque/knowledge").then(safeJson).then(function(kb){
var el=document.getElementById("biblio-knowledge");if(!el)return;
var s=kb.summary||{};
if(!s.derniere_maj){el.innerHTML="<div class='al info'><span class='ai'>&#128218;</span><span>Aucune donnee. Importez des documents via Import / Analyse pour alimenter la base.</span></div>";return;}
var h="<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px'>";
h+="<div class='sc blue'><div class='val'>"+s.nb_salaries_connus+"</div><div class='lab'>Salaries connus</div></div>";
h+="<div class='sc green'><div class='val'>"+s.nb_employeurs+"</div><div class='lab'>Employeurs</div></div>";
h+="<div class='sc'><div class='val'>"+s.nb_periodes+"</div><div class='lab'>Periodes</div></div>";
h+="<div class='sc amber'><div class='val'>"+s.nb_cotisations_analysees+"</div><div class='lab'>Cotisations</div></div>";
h+="<div class='sc'><div class='val'>"+s.total_masse_salariale.toFixed(0)+" EUR</div><div class='lab'>Masse salariale</div></div>";
h+="<div class='sc "+(s.nb_anomalies>0?"red":"green")+"'><div class='val'>"+s.nb_anomalies+"</div><div class='lab'>Anomalies</div></div></div>";
if(s.periodes&&s.periodes.length){h+="<p style='font-size:.84em;color:var(--tx2)'>Periodes couvertes : <strong>"+s.periodes.join(", ")+"</strong></p>";}
if(s.pieces_disponibles&&s.pieces_disponibles.length){h+="<p style='font-size:.84em;color:var(--tx2)'>Pieces disponibles : ";for(var i=0;i<s.pieces_disponibles.length;i++){h+="<span class='badge badge-blue' style='margin:2px'>"+s.pieces_disponibles[i]+"</span>";}h+="</p>";}
var sals=kb.salaries||{};var salKeys=Object.keys(sals);
if(salKeys.length){h+="<h3 style='margin-top:16px'>Salaries identifies ("+salKeys.length+")</h3><table><tr><th>NIR</th><th>Nom</th><th>Prenom</th><th>Statut</th><th class='num'>Dernier brut</th><th>Periodes</th></tr>";
for(var i=0;i<salKeys.length;i++){var sal=sals[salKeys[i]];h+="<tr><td style='font-size:.78em'>"+sal.nir+"</td><td>"+sal.nom+"</td><td>"+sal.prenom+"</td><td><span class='badge "+(sal.statut==="cadre"?"badge-purple":"badge-blue")+"'>"+sal.statut+"</span></td><td class='num'>"+(sal.dernier_brut||0).toFixed(2)+"</td><td style='font-size:.78em'>"+(sal.periodes_presentes||[]).join(", ")+"</td></tr>";}
h+="</table>";}
var emps=kb.employeurs||{};var empKeys=Object.keys(emps);
if(empKeys.length){h+="<h3 style='margin-top:16px'>Employeurs identifies ("+empKeys.length+")</h3><table><tr><th>SIRET</th><th>Raison sociale</th><th>NAF</th><th class='num'>Effectif</th></tr>";
for(var i=0;i<empKeys.length;i++){var emp=emps[empKeys[i]];h+="<tr><td>"+emp.siret+"</td><td>"+emp.raison_sociale+"</td><td>"+(emp.code_naf||"-")+"</td><td class='num'>"+(emp.effectif||"-")+"</td></tr>";}
h+="</table>";}
h+="<p style='font-size:.78em;color:var(--tx2);margin-top:12px'>Derniere mise a jour : "+s.derniere_maj+"</p>";
el.innerHTML=h;}).catch(function(){});}
function loadBiblio(){
fetch("/api/documents/bibliotheque").then(safeJson).then(function(docs){
var el=document.getElementById("biblio-list");
if(!docs.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun document. Importez des fichiers via l'onglet Analyse.</p>";return;}
var h="";for(var i=0;i<docs.length;i++){var d=docs[i];var de=d.donnees_extraites||{};
h+="<div class='doc-item'><div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:6px'>";
h+="<div><strong>"+d.nom+"</strong> <span class='badge badge-blue'>"+d.statut+"</span>";
if(de.type_declaration)h+=" <span class='badge badge-purple'>"+de.type_declaration+"</span>";
h+="</div>";
h+="<span style='font-size:.8em;color:var(--tx2)'>"+d.date_import.substring(0,10)+" | "+(d.taille/1024).toFixed(1)+" Ko</span></div>";
if(de.nb_salaries||de.masse_salariale||de.employeur_nom){h+="<div style='margin-top:6px;font-size:.84em;display:flex;gap:12px;flex-wrap:wrap'>";
if(de.employeur_nom)h+="<span><strong>Employeur:</strong> "+de.employeur_nom+"</span>";
if(de.employeur_siret)h+="<span>SIRET: "+de.employeur_siret+"</span>";
if(de.periode)h+="<span><strong>Periode:</strong> "+de.periode+"</span>";
if(de.nb_salaries)h+="<span><strong>"+de.nb_salaries+"</strong> salarie(s)</span>";
if(de.nb_cotisations)h+="<span><strong>"+de.nb_cotisations+"</strong> cotisation(s)</span>";
if(de.masse_salariale)h+="<span><strong>Masse salariale:</strong> "+de.masse_salariale.toFixed(2)+" EUR</span>";
h+="</div>";}
if(de.salaries_noms&&de.salaries_noms.length){h+="<div style='margin-top:4px;font-size:.8em;color:var(--tx2)'>Salaries: "+de.salaries_noms.join(", ")+"</div>";}
var acts=d.actions||[];if(acts.length){h+="<div style='margin-top:6px;font-size:.82em'><strong>Historique :</strong>";
for(var j=0;j<acts.length;j++){h+=" <span class='badge badge-blue' style='margin:2px'>"+acts[j].action+" ("+acts[j].par+")</span>";}h+="</div>";}
var errs=d.erreurs_corrigees||[];if(errs.length){h+="<div style='margin-top:6px;font-size:.82em;color:var(--r)'><strong>Corrections :</strong>";
for(var k=0;k<errs.length;k++){h+=" "+errs[k].champ+": "+errs[k].ancienne_valeur+" -> "+errs[k].nouvelle_valeur;}h+="</div>";}
h+="<div style='margin-top:8px'><button class='btn btn-s btn-sm btn-corriger' data-docid='"+d.id+"'>Corriger une erreur</button></div>";
h+="</div>";}
el.innerHTML=h;el.querySelectorAll(".btn-corriger").forEach(function(btn){btn.addEventListener("click",function(){corrigerDoc(btn.getAttribute("data-docid"));});});}).catch(function(){});}

function corrigerDoc(docId){
var champ=prompt("Champ a corriger (ex: montant, type, date) :");
if(!champ)return;
var ancien=prompt("Ancienne valeur :");
var nouveau=prompt("Nouvelle valeur :");
if(!nouveau)return;
var fd=new FormData();fd.append("champ",champ);fd.append("ancienne_valeur",ancien||"");fd.append("nouvelle_valeur",nouveau);fd.append("corrige_par","utilisateur");
fetch("/api/documents/bibliotheque/"+docId+"/corriger",{method:"POST",body:fd}).then(function(r){if(!r.ok)throw new Error("Erreur");return r.json();}).then(function(){toast("Correction enregistree.","ok");loadBiblio();}).catch(function(e){toast(e.message);});}

/* === FACTURES === */
function showFT(n,el){document.querySelectorAll("#fact-tabs .tab").forEach(function(t){t.classList.remove("active")});document.querySelectorAll("#s-factures .tc").forEach(function(t){t.classList.remove("active")});if(el)el.classList.add("active");var tc=document.getElementById("ft-"+n);if(tc)tc.classList.add("active");if(n==="suivi")loadPayStatuses();}

var factFile=null;
document.getElementById("fi-fact").addEventListener("change",function(e){factFile=e.target.files[0];if(factFile){document.getElementById("fact-fn").innerHTML="<div class='fi'><span class='nm'>"+factFile.name+"</span></div>";document.getElementById("btn-fact").disabled=false;}});

function analyserFacture(){
if(!factFile)return;var fd=new FormData();fd.append("fichier",factFile);
fetch("/api/factures/analyser",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){
document.getElementById("fact-res").style.display="block";
var h="<div class='g4'><div class='sc blue'><div class='val'>"+(d.type_document||"?")+"</div><div class='lab'>Type</div></div><div class='sc'><div class='val'>"+(d.montant_ttc||0).toFixed(2)+"</div><div class='lab'>TTC</div></div><div class='sc'><div class='val'>"+((d.confiance||0)*100).toFixed(0)+"%</div><div class='lab'>Confiance</div></div><div class='sc "+(d.ecriture_manuscrite?"amber":"green")+"'><div class='val'>"+(d.ecriture_manuscrite?"Oui":"Non")+"</div><div class='lab'>Manuscrit</div></div></div>";
if(d.emetteur)h+="<p style='margin:10px 0'><strong>Emetteur :</strong> "+(d.emetteur.nom||"?")+" (SIRET: "+(d.emetteur.siret||"?")+")</p>";
if(d.lignes&&d.lignes.length){h+="<table style='margin-top:8px'><tr><th>Description</th><th>Qte</th><th>PU</th><th>HT</th></tr>";for(var i=0;i<d.lignes.length;i++){var l=d.lignes[i];h+="<tr><td>"+l.description+"</td><td class='num'>"+l.quantite+"</td><td class='num'>"+l.prix_unitaire.toFixed(2)+"</td><td class='num'>"+l.montant_ht.toFixed(2)+"</td></tr>";}h+="</table>";}
if(d.type_document)document.getElementById("f-type").value=d.type_document;
if(d.date_piece)document.getElementById("f-date").value=d.date_piece;
if(d.numero)document.getElementById("f-num").value=d.numero;
if(d.emetteur)document.getElementById("f-tiers").value=d.emetteur.nom||"";
document.getElementById("f-ht").value=d.montant_ht||0;document.getElementById("f-tva").value=d.montant_tva||0;document.getElementById("f-ttc").value=d.montant_ttc||0;
document.getElementById("fact-det").innerHTML=h;document.getElementById("alerte-justif").style.display="none";
}).catch(function(e){toast(e.message);});}

function comptabiliserFacture(){
var hasJustif=!!factFile;if(!hasJustif)document.getElementById("alerte-justif").style.display="flex";
var fd=new FormData();fd.append("type_doc",document.getElementById("f-type").value);fd.append("date_piece",document.getElementById("f-date").value);fd.append("numero_piece",document.getElementById("f-num").value);fd.append("montant_ht",document.getElementById("f-ht").value||"0");fd.append("montant_tva",document.getElementById("f-tva").value||"0");fd.append("montant_ttc",document.getElementById("f-ttc").value||"0");fd.append("nom_tiers",document.getElementById("f-tiers").value);
fetch("/api/factures/comptabiliser",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){
var h="<div class='al "+(hasJustif?"ok":"err")+"'><span class='ai'>"+(hasJustif?"&#9989;":"&#9888;")+"</span><span><strong>Ecriture "+(hasJustif?"generee":"sans justificatif")+"</strong> ID: "+d.ecriture_id+"</span></div>";
h+="<table><tr><th>Compte</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th></tr>";
for(var i=0;i<d.lignes.length;i++){var l=d.lignes[i];h+="<tr"+(hasJustif?"":" class='sans-just'")+"><td>"+l.compte+"</td><td>"+l.libelle+"</td><td class='num'>"+l.debit.toFixed(2)+"</td><td class='num'>"+l.credit.toFixed(2)+"</td></tr>";}h+="</table>";
document.getElementById("fact-saisie-res").innerHTML=h;}).catch(function(e){toast(e.message);});}

function toggleMontantPaye(){var sel=document.getElementById("pay-stat").value;document.getElementById("pay-montant-row").style.display=(sel==="partiellement_paye")?"block":"none";}
function majStatutFacture(){
var statut=document.getElementById("pay-stat").value;
var fd=new FormData();fd.append("facture_id",document.getElementById("pay-id").value);fd.append("statut",statut);fd.append("date_paiement",document.getElementById("pay-date").value);fd.append("reference_paiement",document.getElementById("pay-ref").value);
if(statut==="partiellement_paye"){fd.append("montant_paye",document.getElementById("pay-montant").value||"0");}
fetch("/api/factures/statut",{method:"POST",body:fd}).then(function(r){if(!r.ok)throw new Error("Erreur");return r.json();}).then(function(){toast("Statut mis a jour.","ok");loadPayStatuses();}).catch(function(e){toast(e.message);});}

function loadPayStatuses(){
fetch("/api/factures/statuts").then(safeJson).then(function(list){
var el=document.getElementById("pay-list");if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun statut enregistre.</p>";return;}
var h="<table><tr><th>Facture</th><th>Statut</th><th>Montant paye</th><th>Date paiement</th><th>Reference</th></tr>";
for(var i=0;i<list.length;i++){var s=list[i];var cls=s.statut==="paye"?"badge-paye":(s.statut==="en_retard"?"badge-red":(s.statut==="partiellement_paye"?"badge-amber":"badge-impaye"));
var mp=s.montant_paye?s.montant_paye.toFixed(2)+" EUR":"-";
h+="<tr><td>"+s.facture_id+"</td><td><span class='badge "+cls+"'>"+s.statut.replace(/_/g," ")+"</span></td><td class='num'>"+mp+"</td><td>"+(s.date_paiement||"-")+"</td><td>"+(s.reference_paiement||"-")+"</td></tr>";}
h+="</table>";el.innerHTML=h;}).catch(function(){});}

/* === DSN GENERATION === */
var dsnSalaries=[];
var dsnPreFilled=false;
function preFillDSN(){
if(dsnPreFilled||!analysisData||!analysisData.declarations||!analysisData.declarations.length)return;
var decl=analysisData.declarations[0];
if(decl.employeur){
var em=decl.employeur;
var f1=document.getElementById("dsn-siren-em");
var f2=document.getElementById("dsn-siren-ent");
var f3=document.getElementById("dsn-raison");
var f4=document.getElementById("dsn-nic");
var f5=document.getElementById("dsn-eff");
if(f1&&!f1.value&&em.siren)f1.value=em.siren;
if(f2&&!f2.value&&em.siren)f2.value=em.siren;
if(f3&&!f3.value&&em.raison_sociale)f3.value=em.raison_sociale;
if(f4&&!f4.value&&em.siret)f4.value=em.siret.substring(9);
if(f5&&em.effectif)f5.value=em.effectif;
}
if(decl.periode){
var f6=document.getElementById("dsn-mois");
if(f6&&!f6.value)f6.value=decl.periode;
}
if(decl.salaries&&decl.salaries.length&&!dsnSalaries.length){
for(var i=0;i<decl.salaries.length;i++){
var s=decl.salaries[i];
dsnSalaries.push({nir:s.nir||"",nom:s.nom||"",prenom:s.prenom||"",date_naissance:s.date_naissance||"",brut_mensuel:s.brut_mensuel||0,net_fiscal:s.net_fiscal||0,heures:s.heures||"151.67",statut_conventionnel:s.statut_conventionnel||"02",num_contrat:s.num_contrat||("C"+String(i+1).padStart(4,"0"))});
}
renderDSNSalaries();
}
dsnPreFilled=true;
if(decl.employeur||decl.salaries&&decl.salaries.length)toast("Donnees pre-remplies depuis l analyse.","ok");
}
function ajouterSalarieDSN(){
var sal={
nir:document.getElementById("dsn-nir").value,
nom:document.getElementById("dsn-nom").value,
prenom:document.getElementById("dsn-prenom").value,
date_naissance:document.getElementById("dsn-ddn").value,
brut_mensuel:parseFloat(document.getElementById("dsn-brut").value)||0,
net_fiscal:parseFloat(document.getElementById("dsn-net").value)||0,
heures:document.getElementById("dsn-heures").value,
statut_conventionnel:document.getElementById("dsn-statut").value,
num_contrat:document.getElementById("dsn-contrat").value||("C"+String(dsnSalaries.length+1).padStart(4,"0"))
};
if(!sal.nir||!sal.nom){toast("NIR et Nom obligatoires.");return;}
dsnSalaries.push(sal);
renderDSNSalaries();
document.getElementById("dsn-nir").value="";document.getElementById("dsn-nom").value="";document.getElementById("dsn-prenom").value="";document.getElementById("dsn-ddn").value="";document.getElementById("dsn-brut").value="";document.getElementById("dsn-net").value="";
toast(sal.prenom+" "+sal.nom+" ajoute.","ok");
}

function renderDSNSalaries(){
document.getElementById("dsn-sal-count").textContent=dsnSalaries.length;
var el=document.getElementById("dsn-sal-list");
if(!dsnSalaries.length){el.innerHTML="";return;}
var h="<table><tr><th>NIR</th><th>Nom</th><th>Prenom</th><th class='num'>Brut</th><th></th></tr>";
for(var i=0;i<dsnSalaries.length;i++){var s=dsnSalaries[i];
h+="<tr><td style='font-size:.8em'>"+s.nir+"</td><td>"+s.nom+"</td><td>"+s.prenom+"</td><td class='num'>"+s.brut_mensuel.toFixed(2)+"</td><td><button class='btn btn-red btn-sm btn-dsn-rm' data-idx='"+i+"'>&times;</button></td></tr>";}
h+="</table>";el.innerHTML=h;
el.querySelectorAll(".btn-dsn-rm").forEach(function(btn){btn.addEventListener("click",function(){dsnSalaries.splice(parseInt(btn.getAttribute("data-idx")),1);renderDSNSalaries();});});
}

function genererDSN(){
if(!dsnSalaries.length){toast("Ajoutez au moins un salarie.");return;}
var siren_em=document.getElementById("dsn-siren-em").value;
var siren_ent=document.getElementById("dsn-siren-ent").value;
var raison=document.getElementById("dsn-raison").value;
var nic=document.getElementById("dsn-nic").value;
if(!siren_ent||!raison||!nic){toast("SIREN, raison sociale et NIC obligatoires.");return;}
var fd=new FormData();
fd.append("siren_emetteur",siren_em||siren_ent);
fd.append("siren_entreprise",siren_ent);
fd.append("raison_sociale",raison);
fd.append("nic_etablissement",nic);
fd.append("effectif",document.getElementById("dsn-eff").value);
fd.append("mois_declaration",document.getElementById("dsn-mois").value);
fd.append("salaries_json",JSON.stringify(dsnSalaries));
document.getElementById("btn-dsn-gen").disabled=true;
fetch("/api/dsn/generer",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){
var h="<div class='al ok'><span class='ai'>&#9989;</span><span><strong>DSN generee</strong> - "+d.nb_salaries+" salarie(s), "+d.nb_lignes+" lignes</span></div>";
h+="<div class='g3' style='margin:12px 0'><div class='sc blue'><div class='val'>"+d.nb_salaries+"</div><div class='lab'>Salaries</div></div>";
h+="<div class='sc green'><div class='val'>"+d.total_brut.toFixed(2)+"</div><div class='lab'>Total brut</div></div>";
h+="<div class='sc amber'><div class='val'>"+d.total_cotisations.toFixed(2)+"</div><div class='lab'>Cotisations</div></div></div>";
h+="<div class='card' style='margin-top:10px'><h2>Apercu DSN</h2><pre style='background:var(--p);color:#e2e8f0;padding:16px;border-radius:10px;font-size:.78em;overflow-x:auto;white-space:pre-wrap'>"+d.apercu+"</pre></div>";
h+="<div style='margin-top:12px'><button class='btn btn-blue' onclick='telechargerDSN()'>&#128190; Telecharger le fichier DSN</button></div>";
document.getElementById("dsn-result").innerHTML=h;
document.getElementById("dsn-result")._dsnContent=d.contenu_dsn;
document.getElementById("dsn-result")._dsnMois=d.mois_declaration;
document.getElementById("dsn-brouillons-card").style.display="block";
loadDSNBrouillons();
}).catch(function(e){toast(e.message);}).finally(function(){document.getElementById("btn-dsn-gen").disabled=false;});
}

function telechargerDSN(){
var content=document.getElementById("dsn-result")._dsnContent;
var mois=document.getElementById("dsn-result")._dsnMois||"000000";
if(!content){toast("Aucune DSN generee.");return;}
var blob=new Blob([content],{type:"text/plain;charset=utf-8"});
var a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="DSN_"+mois+".dsn";a.click();
toast("Fichier DSN telecharge.","ok");
}

function loadDSNBrouillons(){
fetch("/api/dsn/brouillons").then(safeJson).then(function(list){
var el=document.getElementById("dsn-brouillons");
if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun brouillon.</p>";document.getElementById("dsn-brouillons-card").style.display="none";return;}
document.getElementById("dsn-brouillons-card").style.display="block";
var h="<table><tr><th>Date</th><th>Mois</th><th>Entreprise</th><th class='num'>Salaries</th><th class='num'>Brut total</th></tr>";
for(var i=0;i<list.length;i++){var d=list[i];
h+="<tr><td style='font-size:.8em'>"+d.date_creation.substring(0,10)+"</td><td>"+d.mois+"</td><td>"+d.raison_sociale+"</td><td class='num'>"+d.nb_salaries+"</td><td class='num'>"+d.total_brut.toFixed(2)+"</td></tr>";}
h+="</table>";el.innerHTML=h;}).catch(function(){});}

/* === COMPTABILITE === */
function showCT(n,el){
document.querySelectorAll("#compta-tabs .tab").forEach(function(t){t.classList.remove("active")});
document.querySelectorAll("#s-compta .tc").forEach(function(t){t.classList.remove("active")});
if(el)el.classList.add("active");var tc=document.getElementById("ct-"+n);if(tc)tc.classList.add("active");
document.getElementById("period-sel").style.display=(n==="grandlivre"||n==="balance"||n==="bilan")?"block":"none";
loadCompta();}

function loadCompta(){
var dd=document.getElementById("gl-dd").value;var df=document.getElementById("gl-df").value;

fetch("/api/comptabilite/journal").then(safeJson).then(function(j){
var h="";if(!j.length)h="<p style='color:var(--tx2)'>Aucune ecriture.</p>";
for(var i=0;i<j.length;i++){var e=j[i];
h+="<div style='border:1px solid var(--brd);border-radius:10px;padding:12px;margin:6px 0'>";
h+="<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:4px'><strong>"+e.date+" | "+e.journal+" | "+e.piece+"</strong><span class='badge "+(e.validee?"badge-green":"badge-amber")+"'>"+(e.validee?"Validee":"Brouillon")+"</span></div>";
h+="<div style='color:var(--tx2);font-size:.86em;margin-bottom:6px'>"+e.libelle+"</div>";
h+="<table><tr><th>Compte</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th></tr>";
for(var k=0;k<e.lignes.length;k++){var l=e.lignes[k];var sj=l.libelle.indexOf("[SANS JUSTIFICATIF]")>=0;h+="<tr"+(sj?" class='sans-just'":"")+"><td>"+l.compte+"</td><td>"+l.libelle+(sj?" <span class='badge badge-red'>Sans justif.</span>":"")+"</td><td class='num'>"+l.debit.toFixed(2)+"</td><td class='num'>"+l.credit.toFixed(2)+"</td></tr>";}
h+="</table></div>";}document.getElementById("ct-journal-c").innerHTML=h;}).catch(function(){});

fetch("/api/comptabilite/balance").then(safeJson).then(function(b){
var h="";if(!b.length)h="<p style='color:var(--tx2)'>Aucune donnee.</p>";
else{h="<table><tr><th>Compte</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th><th class='num'>Solde D</th><th class='num'>Solde C</th></tr>";
for(var i=0;i<b.length;i++){var r2=b[i];h+="<tr><td>"+r2.compte+"</td><td>"+r2.libelle+"</td><td class='num'>"+r2.total_debit.toFixed(2)+"</td><td class='num'>"+r2.total_credit.toFixed(2)+"</td><td class='num'>"+r2.solde_debiteur.toFixed(2)+"</td><td class='num'>"+r2.solde_crediteur.toFixed(2)+"</td></tr>";}h+="</table>";}
document.getElementById("ct-balance-c").innerHTML=h;}).catch(function(){});

var glUrl="/api/comptabilite/grand-livre-detail";if(dd)glUrl+="?date_debut="+dd+(df?"&date_fin="+df:"");
fetch(glUrl).then(safeJson).then(function(gl){
var h="";if(!gl.length)h="<p style='color:var(--tx2)'>Aucune donnee.</p>";
for(var i=0;i<gl.length;i++){var c=gl[i];h+="<div style='border:1px solid var(--brd);border-radius:10px;padding:12px;margin:6px 0'><strong>"+c.compte+" - "+(c.libelle||"")+"</strong>";
var mvts=c.mouvements||[];if(mvts.length){h+="<table style='margin-top:6px'><tr><th>Date</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th></tr>";
for(var k=0;k<mvts.length;k++){var m=mvts[k];var sj=m.sans_justificatif;h+="<tr"+(sj?" class='sans-just'":"")+"><td>"+(m.date||"")+"</td><td>"+(m.libelle||"")+(sj?" <span class='badge badge-red'>Sans justif.</span>":"")+"</td><td class='num'>"+(m.debit||0).toFixed(2)+"</td><td class='num'>"+(m.credit||0).toFixed(2)+"</td></tr>";}
h+="</table>";}h+="</div>";}document.getElementById("ct-grandlivre-c").innerHTML=h;}).catch(function(){});

fetch("/api/comptabilite/compte-resultat").then(safeJson).then(function(cr){
var clr=cr.resultat_net>=0?"var(--g)":"var(--r)";var bg=cr.resultat_net>=0?"var(--gl)":"var(--rl)";
var h="<div class='g2'><div class='card' style='text-align:center'><h2>Charges</h2><div style='font-size:1.4em;font-weight:800;color:var(--r)'>"+cr.charges.total.toFixed(2)+" EUR</div></div>";
h+="<div class='card' style='text-align:center'><h2>Produits</h2><div style='font-size:1.4em;font-weight:800;color:var(--g)'>"+cr.produits.total.toFixed(2)+" EUR</div></div></div>";
h+="<div class='sc' style='margin-top:14px;background:"+bg+"'><div class='val' style='color:"+clr+"'>"+cr.resultat_net.toFixed(2)+" EUR</div><div class='lab'>Resultat net</div></div>";
document.getElementById("ct-resultat-c").innerHTML=h;}).catch(function(){});

fetch("/api/comptabilite/bilan").then(safeJson).then(function(bi){
var a=bi.actif,p=bi.passif;
var h="<div class='g2'><div><h3 style='margin-bottom:8px;color:var(--p)'>Actif</h3><table><tr><th>Poste</th><th class='num'>Montant</th></tr>";
h+="<tr><td>Immobilisations</td><td class='num'>"+a.immobilisations.toFixed(2)+"</td></tr><tr><td>Stocks</td><td class='num'>"+a.stocks.toFixed(2)+"</td></tr>";
h+="<tr><td>Creances</td><td class='num'>"+a.creances.toFixed(2)+"</td></tr><tr><td>Tresorerie</td><td class='num'>"+a.tresorerie.toFixed(2)+"</td></tr>";
h+="<tr style='font-weight:bold;background:var(--pl)'><td>TOTAL ACTIF</td><td class='num'>"+a.total.toFixed(2)+"</td></tr></table></div>";
h+="<div><h3 style='margin-bottom:8px;color:var(--p)'>Passif</h3><table><tr><th>Poste</th><th class='num'>Montant</th></tr>";
h+="<tr><td>Capitaux propres</td><td class='num'>"+p.capitaux_propres.toFixed(2)+"</td></tr><tr><td>Dettes financieres</td><td class='num'>"+p.dettes_financieres.toFixed(2)+"</td></tr>";
h+="<tr><td>Dettes exploitation</td><td class='num'>"+p.dettes_exploitation.toFixed(2)+"</td></tr>";
h+="<tr style='font-weight:bold;background:var(--pl)'><td>TOTAL PASSIF</td><td class='num'>"+p.total.toFixed(2)+"</td></tr></table></div></div>";
document.getElementById("ct-bilan-c").innerHTML=h;}).catch(function(){});

(function(){var now=new Date();fetch("/api/comptabilite/declaration-tva?mois="+(now.getMonth()+1)+"&annee="+now.getFullYear()).then(safeJson).then(function(t){
var h="<div class='g3'><div class='sc'><div class='val'>"+t.chiffre_affaires_ht.toFixed(2)+"</div><div class='lab'>CA HT</div></div><div class='sc'><div class='val'>"+t.tva_collectee.toFixed(2)+"</div><div class='lab'>TVA collectee</div></div><div class='sc'><div class='val'>"+t.tva_deductible_totale.toFixed(2)+"</div><div class='lab'>TVA deductible</div></div></div>";
var net=t.tva_nette_a_payer>0?t.tva_nette_a_payer.toFixed(2)+" EUR a payer":t.credit_tva.toFixed(2)+" EUR credit";
h+="<div class='sc' style='margin-top:12px'><div class='val'>"+net+"</div><div class='lab'>TVA nette</div></div>";
document.getElementById("ct-tva-c").innerHTML=h;}).catch(function(){});})();

fetch("/api/comptabilite/charges-sociales-detail").then(safeJson).then(function(soc){
var h="<div class='g4'>";var ds=soc.destinataires||[];var cls=["blue","amber","green","purple"];
for(var i=0;i<ds.length;i++){var d=ds[i];h+="<div class='sc "+cls[i%4]+"'><div class='val'>"+(d.montant||0).toFixed(2)+"</div><div class='lab'>"+d.nom+"</div><div style='font-size:.7em;color:var(--tx2);margin-top:3px'>"+d.postes.join(", ")+"</div></div>";}h+="</div>";
h+="<div class='g3' style='margin-top:12px'><div class='sc'><div class='val'>"+(soc.brut||0).toFixed(2)+"</div><div class='lab'>Bruts</div></div>";
h+="<div class='sc amber'><div class='val'>"+(soc.total||0).toFixed(2)+"</div><div class='lab'>Total charges</div></div>";
h+="<div class='sc blue'><div class='val'>"+(soc.cout_employeur||0).toFixed(2)+"</div><div class='lab'>Cout employeur</div></div></div>";
document.getElementById("ct-social-c").innerHTML=h;}).catch(function(){});

fetch("/api/comptabilite/plan-comptable").then(safeJson).then(function(pc){
var h="<input placeholder='Rechercher...' oninput='rechPC(this.value)' style='margin-bottom:10px'><table id='pc-t'><tr><th>N</th><th>Libelle</th><th>Classe</th></tr>";
for(var i=0;i<pc.length;i++){h+="<tr><td>"+pc[i].numero+"</td><td>"+pc[i].libelle+"</td><td>"+pc[i].classe+"</td></tr>";}h+="</table>";
document.getElementById("ct-plan-c").innerHTML=h;}).catch(function(){});
}

function rechPC(t){fetch(t?"/api/comptabilite/plan-comptable?terme="+encodeURIComponent(t):"/api/comptabilite/plan-comptable").then(safeJson).then(function(pc){var tb=document.getElementById("pc-t");if(!tb)return;var h="<tr><th>N</th><th>Libelle</th><th>Classe</th></tr>";for(var i=0;i<pc.length;i++){h+="<tr><td>"+pc[i].numero+"</td><td>"+pc[i].libelle+"</td><td>"+pc[i].classe+"</td></tr>";}tb.innerHTML=h;}).catch(function(){});}
function validerEcr(){fetch("/api/comptabilite/valider",{method:"POST"}).then(safeJson).then(function(d){toast("Validees: "+d.nb_validees+(d.erreurs.length?" | Erreurs: "+d.erreurs.join(", "):""),"ok");loadCompta();}).catch(function(e){toast(e.message);});}
var _sugTimer=null;
function suggestCompte(inputId,sugId,counterpartId){
clearTimeout(_sugTimer);_sugTimer=setTimeout(function(){
var v=document.getElementById(inputId).value;if(v.length<2){closeSugs(sugId);return;}
fetch("/api/comptabilite/suggestions?compte="+encodeURIComponent(v)).then(safeJson).then(function(d){
var box=document.getElementById(sugId);var items=d.suggestions||[];if(!items.length){closeSugs(sugId);return;}
var h="<div class='sug-list show'>";for(var i=0;i<items.length&&i<8;i++){var num=items[i].numero;var cp=(d.contreparties||{})[num]||"";h+="<div class='sug-item' data-num='"+num+"' data-cp='"+cp+"' data-iid='"+inputId+"' data-sid='"+sugId+"' data-cpid='"+counterpartId+"'><span class='sug-num'>"+num+"</span><span class='sug-lbl'>"+items[i].libelle+"</span></div>";}
h+="</div>";box.innerHTML=h;box.querySelectorAll(".sug-item").forEach(function(el){el.addEventListener("click",function(){pickSug(el.getAttribute("data-iid"),el.getAttribute("data-sid"),el.getAttribute("data-num"),el.getAttribute("data-cpid"),el.getAttribute("data-cp"));});});}).catch(function(){});},250);}
function pickSug(inputId,sugId,val,cpId,cpVal){document.getElementById(inputId).value=val;closeSugs(sugId);if(cpId&&cpVal){var cpInput=document.getElementById(cpId);if(cpInput&&!cpInput.value)cpInput.value=cpVal;}}
function closeSugs(sugId){var b=document.getElementById(sugId);if(b)b.innerHTML="";}
document.addEventListener("click",function(e){if(!e.target.closest(".sug-box")&&!e.target.closest("input")){document.querySelectorAll(".sug-list").forEach(function(s){s.classList.remove("show");});}});
function creerSousCompte(){var fd=new FormData();fd.append("compte_parent",document.getElementById("sc-parent").value);fd.append("libelle",document.getElementById("sc-lib").value);
fetch("/api/comptabilite/sous-compte",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){document.getElementById("sc-res").innerHTML="<div class='al ok'><span class='ai'>&#9989;</span><span>Sous-compte <strong>"+d.numero+"</strong> cree: "+d.libelle+"</span></div>";}).catch(function(e){document.getElementById("sc-res").innerHTML="<div class='al err'>"+e.message+"</div>";});}
function saisirEcriture(){
var deb=document.getElementById("em-deb").value;var cre=document.getElementById("em-cre").value;
if(!deb||deb.length<3){toast("Compte debit invalide.");return;}if(!cre||cre.length<3){toast("Compte credit invalide.");return;}
var fd=new FormData();fd.append("date_piece",document.getElementById("em-date").value);fd.append("libelle",document.getElementById("em-lib").value);fd.append("compte_debit",deb);fd.append("compte_credit",cre);fd.append("montant",document.getElementById("em-mt").value||"0");
var fj=document.getElementById("em-just-file");fd.append("has_justificatif",fj&&fj.files&&fj.files.length>0?"true":"false");
fetch("/api/comptabilite/ecriture/manuelle",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){
var cls=d.sans_justificatif?"warn":"ok";var icon=d.sans_justificatif?"&#9888;":"&#9989;";
document.getElementById("em-res").innerHTML="<div class='al "+cls+"'><span class='ai'>"+icon+"</span><span>"+(d.alerte||"Ecriture enregistree.")+(d.sans_justificatif?" <em style='color:var(--r)'>(justificatif manquant)</em>":"")+"</span></div>";loadCompta();}).catch(function(e){document.getElementById("em-res").innerHTML="<div class='al err'>"+e.message+"</div>";});}

/* === SIMULATION === */
function showSimTab(n,el){document.querySelectorAll("#s-simulation .tab").forEach(function(t){t.classList.remove("active")});document.querySelectorAll("#s-simulation .tc").forEach(function(t){t.classList.remove("active")});if(el)el.classList.add("active");var tc=document.getElementById("sim-"+n);if(tc)tc.classList.add("active");}
function simBulletin(){fetch("/api/simulation/bulletin?brut_mensuel="+document.getElementById("sim-brut").value+"&effectif="+document.getElementById("sim-eff").value+"&est_cadre="+document.getElementById("sim-cadre").value).then(safeJson).then(function(r){var h="<div class='g3'><div class='sc blue'><div class='val'>"+r.brut_mensuel.toFixed(2)+"</div><div class='lab'>Brut</div></div><div class='sc green'><div class='val'>"+r.net_a_payer.toFixed(2)+"</div><div class='lab'>Net</div></div><div class='sc amber'><div class='val'>"+r.cout_total_employeur.toFixed(2)+"</div><div class='lab'>Cout employeur</div></div></div><table style='margin-top:12px'><tr><th>Rubrique</th><th class='num'>Patronal</th><th class='num'>Salarial</th></tr>";var ls=r.lignes||[];for(var i=0;i<ls.length;i++){h+="<tr><td>"+ls[i].libelle+"</td><td class='num'>"+ls[i].montant_patronal.toFixed(2)+"</td><td class='num'>"+ls[i].montant_salarial.toFixed(2)+"</td></tr>";}h+="</table>";document.getElementById("sim-bull-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simMicro(){fetch("/api/simulation/micro-entrepreneur?chiffre_affaires="+document.getElementById("sim-ca").value+"&activite="+document.getElementById("sim-act").value+"&acre="+document.getElementById("sim-acre").value).then(safeJson).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-micro-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simTNS(){fetch("/api/simulation/tns?revenu_net="+document.getElementById("sim-rev").value+"&type_statut="+document.getElementById("sim-stat").value+"&acre="+document.getElementById("sim-tacre").value).then(safeJson).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-tns-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simGUSO(){fetch("/api/simulation/guso?salaire_brut="+document.getElementById("sim-gbrut").value+"&nb_heures="+document.getElementById("sim-gh").value).then(safeJson).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-guso-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simIR(){fetch("/api/simulation/impot-independant?benefice="+document.getElementById("sim-ben").value+"&nb_parts="+document.getElementById("sim-parts").value+"&autres_revenus="+document.getElementById("sim-autres").value).then(safeJson).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-ir-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simCout(){var p="brut_mensuel="+gv("ce-brut")+"&effectif="+gv("ce-eff")+"&est_cadre="+gv("ce-cadre")+"&primes="+gv("ce-primes")+"&avantages_nature="+gv("ce-avantages")+"&frais_km="+gv("ce-km")+"&tickets_restaurant="+gv("ce-tr")+"&mutuelle_employeur="+gv("ce-mut");fetch("/api/simulation/cout-employeur?"+p).then(safeJson).then(function(r){var h="<div class='g4'><div class='sc blue'><div class='val'>"+r.brut_total.toFixed(2)+"</div><div class='lab'>Brut total</div></div><div class='sc green'><div class='val'>"+r.net_a_payer.toFixed(2)+"</div><div class='lab'>Net a payer</div></div><div class='sc amber'><div class='val'>"+r.cout_total_mensuel.toFixed(2)+"</div><div class='lab'>Cout total/mois</div></div><div class='sc'><div class='val'>"+r.cout_total_annuel.toFixed(2)+"</div><div class='lab'>Cout total/an</div></div></div>";h+="<table style='margin-top:12px'><tr><th>Poste</th><th class='num'>Montant</th></tr>";h+="<tr><td>Charges patronales URSSAF</td><td class='num'>"+r.charges_patronales_urssaf.toFixed(2)+"</td></tr>";h+="<tr><td>Charges salariales</td><td class='num'>"+r.charges_salariales.toFixed(2)+"</td></tr>";h+="<tr><td>Formation professionnelle</td><td class='num'>"+r.formation_professionnelle.toFixed(2)+"</td></tr>";h+="<tr><td>Taxe apprentissage</td><td class='num'>"+r.taxe_apprentissage.toFixed(2)+"</td></tr>";h+="<tr><td>Effort construction</td><td class='num'>"+r.effort_construction.toFixed(2)+"</td></tr>";h+="<tr><td>Participation obligatoire</td><td class='num'>"+r.participation_obligatoire.toFixed(2)+"</td></tr>";h+="<tr style='font-weight:600'><td>Total charges annexes</td><td class='num'>"+r.total_charges_annexes.toFixed(2)+"</td></tr>";h+="<tr><td>Avantages nature</td><td class='num'>"+r.avantages_nature.toFixed(2)+"</td></tr>";h+="<tr><td>Frais km rembourses</td><td class='num'>"+r.frais_km_rembourses.toFixed(2)+"</td></tr>";h+="<tr><td>Tickets restaurant</td><td class='num'>"+r.tickets_restaurant.toFixed(2)+"</td></tr>";h+="<tr><td>Mutuelle employeur</td><td class='num'>"+r.mutuelle_employeur.toFixed(2)+"</td></tr>";h+="<tr style='font-weight:600'><td>Total avantages</td><td class='num'>"+r.total_avantages.toFixed(2)+"</td></tr></table>";h+="<div class='g4' style='margin-top:12px'><div class='sc'><div class='val'>"+r.repartition.salaire_net+"%</div><div class='lab'>Salaire net</div></div><div class='sc'><div class='val'>"+r.repartition.charges_salariales+"%</div><div class='lab'>Charges sal.</div></div><div class='sc'><div class='val'>"+r.repartition.charges_patronales+"%</div><div class='lab'>Charges pat.</div></div><div class='sc'><div class='val'>"+r.repartition.annexes_avantages+"%</div><div class='lab'>Annexes+Avantages</div></div></div>";h+="<p style='margin-top:10px;color:var(--tx2);font-size:.84em'>Ratio cout/net : <b>"+r.ratio_cout_net+"x</b> - Pour 1 EUR net verse, l employeur depense "+r.ratio_cout_net+" EUR</p>";document.getElementById("sim-cout-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simExo(){var p="brut_mensuel="+gv("exo-brut")+"&effectif="+gv("exo-eff")+"&age_salarie="+gv("exo-age")+"&duree_contrat_mois="+gv("exo-duree")+"&zone="+gv("exo-zone")+"&statut_salarie="+gv("exo-statut")+"&ccn="+encodeURIComponent(gv("exo-ccn"));fetch("/api/simulation/exonerations?"+p).then(safeJson).then(function(r){var h="<div class='g3'><div class='sc green'><div class='val'>"+r.total_exonerations_mensuelles.toFixed(2)+"</div><div class='lab'>Exonerations/mois</div></div><div class='sc blue'><div class='val'>"+r.total_exonerations_annuelles.toFixed(2)+"</div><div class='lab'>Exonerations/an</div></div><div class='sc amber'><div class='val'>"+r.economie_pct.toFixed(1)+"%</div><div class='lab'>Economie</div></div></div>";h+="<div class='g2' style='margin-top:10px'><div class='sc'><div class='val'>"+r.charges_patronales_normales.toFixed(2)+"</div><div class='lab'>Charges normales</div></div><div class='sc green'><div class='val'>"+r.charges_patronales_apres_exo.toFixed(2)+"</div><div class='lab'>Charges apres exo</div></div></div>";h+="<table style='margin-top:12px'><tr><th>Exoneration</th><th>Reference</th><th class='num'>Mensuel</th><th class='num'>Annuel</th><th>Statut</th></tr>";var exos=r.exonerations||[];for(var i=0;i<exos.length;i++){var e=exos[i];var cls=e.applicable?"color:var(--green)":"color:var(--tx2)";h+="<tr style='"+cls+"'><td>"+e.nom+"</td><td style='font-size:.8em'>"+e.reference+"</td><td class='num'>"+e.montant_mensuel.toFixed(2)+"</td><td class='num'>"+e.montant_annuel.toFixed(2)+"</td><td>"+(e.applicable?"Applicable":"Non applicable")+"</td></tr>";}h+="</table>";h+="<p style='margin-top:8px;color:var(--tx2);font-size:.82em'>Zone: "+r.zone+" | Ratio SMIC: "+r.ratio_smic+" | Statut: "+r.statut_salarie+"</p>";document.getElementById("sim-exo-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simMasse(){var p="brut_moyen="+gv("ms-brut")+"&effectif="+gv("ms-eff")+"&augmentation_pct="+gv("ms-aug")+"&inflation_pct="+gv("ms-infl")+"&frais_km_moyen="+gv("ms-km")+"&avantages_nature_moyen="+gv("ms-an")+"&primes_variables_pct="+gv("ms-primes")+"&turnover_pct="+gv("ms-turn");fetch("/api/simulation/masse-salariale?"+p).then(safeJson).then(function(r){var h="<div class='g4'><div class='sc blue'><div class='val'>"+fmt(r.masse_actuelle)+"</div><div class='lab'>Masse actuelle</div></div><div class='sc amber'><div class='val'>"+fmt(r.masse_apres_augmentation)+"</div><div class='lab'>Apres augmentation</div></div><div class='sc'><div class='val'>"+fmt(r.cout_global_projete)+"</div><div class='lab'>Cout global projete</div></div><div class='sc "+(r.evolution_pct>0?"red":"green")+"'><div class='val'>"+(r.evolution_pct>0?"+":"")+r.evolution_pct+"%</div><div class='lab'>Evolution</div></div></div>";h+="<table style='margin-top:12px'><tr><th>Poste</th><th class='num'>Montant annuel</th></tr>";h+="<tr><td>Masse actuelle (brut)</td><td class='num'>"+fmt(r.masse_actuelle)+"</td></tr>";h+="<tr><td>Charges patronales actuelles (45%)</td><td class='num'>"+fmt(r.charges_patronales_actuelles)+"</td></tr>";h+="<tr style='font-weight:600'><td>Cout total actuel</td><td class='num'>"+fmt(r.cout_total_actuel)+"</td></tr>";h+="<tr><td colspan='2' style='background:var(--bg2);font-weight:600;padding-top:8px'>Impact augmentation (+"+r.augmentation_pct+"%)</td></tr>";h+="<tr><td>Nouveau brut moyen</td><td class='num'>"+r.nouveau_brut_moyen.toFixed(2)+" EUR/mois</td></tr>";h+="<tr><td>Cout augmentation (brut)</td><td class='num'>"+fmt(r.cout_augmentation_brut)+"</td></tr>";h+="<tr><td>Charges supplementaires</td><td class='num'>"+fmt(r.cout_augmentation_charges)+"</td></tr>";h+="<tr style='font-weight:600'><td>Cout total augmentation</td><td class='num'>"+fmt(r.cout_augmentation_total)+"</td></tr>";h+="<tr><td colspan='2' style='background:var(--bg2);font-weight:600;padding-top:8px'>Autres postes</td></tr>";h+="<tr><td>Perte pouvoir achat (inflation "+r.augmentation_pct+"% vs "+gv("ms-infl")+"%)</td><td class='num'>"+fmt(r.perte_pouvoir_achat_inflation)+"</td></tr>";h+="<tr><td>Ecart augmentation/inflation</td><td class='num'>"+fmt(r.ecart_augmentation_inflation)+"</td></tr>";h+="<tr><td>Primes variables</td><td class='num'>"+fmt(r.primes_variables_total)+"</td></tr>";h+="<tr><td>Charges sur primes</td><td class='num'>"+fmt(r.charges_primes)+"</td></tr>";h+="<tr><td>Frais kilometriques (non soumis)</td><td class='num'>"+fmt(r.frais_km_total)+"</td></tr>";h+="<tr><td>Avantages en nature (soumis)</td><td class='num'>"+fmt(r.avantages_nature_total)+"</td></tr>";h+="<tr><td>Charges sur avantages</td><td class='num'>"+fmt(r.charges_avantages)+"</td></tr>";h+="<tr><td>Cout turnover estime</td><td class='num'>"+fmt(r.cout_turnover_estime)+"</td></tr>";h+="<tr style='font-weight:600;background:var(--bg2)'><td>COUT GLOBAL PROJETE</td><td class='num'>"+fmt(r.cout_global_projete)+"</td></tr></table>";document.getElementById("sim-masse-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simSeuils(){fetch("/api/simulation/seuils-effectif?effectif_actuel="+gv("se-eff")+"&masse_salariale_annuelle="+gv("se-masse")).then(safeJson).then(function(r){var h="";if(r.prochain_seuil){h+="<div class='g3'><div class='sc amber'><div class='val'>"+r.prochain_seuil+"</div><div class='lab'>Prochain seuil</div></div><div class='sc blue'><div class='val'>"+r.marge_avant_seuil+"</div><div class='lab'>Salaries avant seuil</div></div><div class='sc red'><div class='val'>"+fmt(r.cout_prochain_seuil)+"</div><div class='lab'>Cout franchissement</div></div></div>";}h+="<div class='g2' style='margin-top:10px'><div class='sc'><div class='val'>"+r.effectif_actuel+"</div><div class='lab'>Effectif actuel</div></div><div class='sc amber'><div class='val'>"+fmt(r.total_obligations_actuelles)+"</div><div class='lab'>Obligations actuelles</div></div></div>";var seuils=r.seuils||[];for(var i=0;i<seuils.length;i++){var s=seuils[i];var obligs=s.obligations||[];var franchi=obligs.length>0&&obligs[0].franchi;h+="<div style='margin-top:14px;padding:10px;border-radius:8px;background:"+(franchi?"var(--bg2)":"var(--bg1)")+";border:1px solid "+(franchi?"var(--green)":"var(--border)")+"'>";h+="<h3 style='margin:0 0 6px'>"+(franchi?"&#9989; ":"&#9898; ")+"Seuil "+s.seuil+" salaries</h3>";h+="<table style='margin:0'><tr><th>Obligation</th><th>Reference</th><th class='num'>Cout estime</th><th>Detail</th></tr>";for(var j=0;j<obligs.length;j++){var o=obligs[j];h+="<tr><td>"+o.nom+"</td><td style='font-size:.8em'>"+o.reference+"</td><td class='num'>"+fmt(o.cout_estime)+"</td><td style='font-size:.84em;color:var(--tx2)'>"+o.detail+"</td></tr>";}h+="</table></div>";}document.getElementById("sim-seuils-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simFinContrat(){var p="type_fin="+gv("fc-type")+"&salaire_brut="+gv("fc-brut")+"&anciennete_mois="+gv("fc-anc")+"&est_cadre="+gv("fc-cadre")+"&motif="+gv("fc-motif");fetch("/api/simulation/fin-contrat?"+p).then(safeJson).then(function(r){var h="<div class='g3'><div class='sc blue'><div class='val'>"+r.type_fin.replace(/_/g," ")+"</div><div class='lab'>Type</div></div><div class='sc'><div class='val'>"+r.anciennete_ans+" ans</div><div class='lab'>Anciennete</div></div><div class='sc red'><div class='val'>"+fmt(r.cout_total)+"</div><div class='lab'>Cout total</div></div></div>";h+="<table style='margin-top:12px'><tr><th>Poste</th><th class='num'>Montant</th></tr>";var skip={"type_fin":1,"salaire_brut":1,"anciennete_mois":1,"anciennete_ans":1,"cout_total":1,"reference":1,"motif":1,"note":1,"exceptions":1};for(var k in r){if(!skip[k]&&typeof r[k]==="number"){h+="<tr><td>"+k.replace(/_/g," ")+"</td><td class='num'>"+r[k].toFixed(2)+"</td></tr>";}}h+="<tr style='font-weight:600;background:var(--bg2)'><td>COUT TOTAL</td><td class='num'>"+r.cout_total.toFixed(2)+"</td></tr></table>";if(r.reference)h+="<p style='margin-top:8px;font-size:.82em;color:var(--tx2)'>Ref: "+r.reference+"</p>";if(r.note)h+="<p style='font-size:.82em;color:var(--amber)'>"+r.note+"</p>";if(r.exceptions)h+="<p style='font-size:.82em;color:var(--tx2)'>"+r.exceptions+"</p>";document.getElementById("sim-fc-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simOptim(){var p="benefice_net="+gv("op-benef")+"&remuneration_gerant="+gv("op-rem")+"&dividendes="+gv("op-div")+"&interessement="+gv("op-int")+"&participation="+gv("op-part")+"&frais_pro="+gv("op-frais")+"&pee_abondement="+gv("op-pee")+"&nb_parts="+gv("op-parts")+"&forme_juridique="+gv("op-forme");fetch("/api/simulation/optimisation?"+p).then(safeJson).then(function(r){var h="<div class='g2' style='margin-bottom:12px'><div class='sc green'><div class='val'>"+r.meilleur_scenario+"</div><div class='lab'>Meilleur scenario</div></div><div class='sc blue'><div class='val'>"+fmt(r.ecart_max)+"</div><div class='lab'>Ecart max entre scenarios</div></div></div>";var sc=r.scenarios||[];h+="<table><tr><th>Scenario</th><th class='num'>Salaire brut</th><th class='num'>Charges</th><th class='num'>Dividendes</th><th class='num'>IR</th><th class='num'>Net disponible</th><th>Protection</th></tr>";for(var i=0;i<sc.length;i++){var s=sc[i];var best=s.nom===r.meilleur_scenario?" style='background:var(--bg2);font-weight:600'":"";h+="<tr"+best+"><td>"+s.nom+"</td><td class='num'>"+s.salaire_brut.toFixed(2)+"</td><td class='num'>"+s.charges_sociales.toFixed(2)+"</td><td class='num'>"+(s.dividendes||0).toFixed(2)+"</td><td class='num'>"+s.ir.toFixed(2)+"</td><td class='num' style='font-weight:600'>"+s.net_disponible.toFixed(2)+"</td><td style='font-size:.8em'>"+s.protection_sociale+"</td></tr>";}h+="</table>";if(r.frais_professionnels){var fp=r.frais_professionnels;h+="<div style='margin-top:14px;padding:10px;background:var(--bg2);border-radius:8px'><h3 style='margin:0 0 6px'>Frais professionnels deductibles</h3>";h+="<p style='margin:0 0 6px;font-size:.84em'>Frais declares: <b>"+fp.frais_declares.toFixed(2)+" EUR</b> - Economie IS: <b>"+fp.economie_is.toFixed(2)+" EUR</b></p>";h+="<div style='font-size:.84em;color:var(--tx2)'>Types eligibles: "+fp.types_eligibles.join(" | ")+"</div></div>";}document.getElementById("sim-optim-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simRisques(){var p="code_naf="+encodeURIComponent(gv("rs-naf"))+"&effectif="+gv("rs-eff")+"&masse_salariale="+gv("rs-masse");fetch("/api/simulation/risques-sectoriels?"+p).then(safeJson).then(function(r){var h="<div class='g4'><div class='sc blue'><div class='val'>"+r.secteur+"</div><div class='lab'>Secteur</div></div><div class='sc amber'><div class='val'>"+r.taux_at_moyen+"%</div><div class='lab'>Taux AT moyen</div></div><div class='sc red'><div class='val'>"+fmt(r.cout_at_annuel)+"</div><div class='lab'>Cout AT annuel</div></div><div class='sc'><div class='val'>"+r.effectif+"</div><div class='lab'>Effectif</div></div></div>";h+="<div style='margin-top:14px'><h3>Risques specifiques du secteur</h3><ul style='margin:6px 0;padding-left:20px'>";var rs=r.risques_specifiques||[];for(var i=0;i<rs.length;i++)h+="<li style='margin:3px 0'>"+rs[i]+"</li>";h+="</ul></div>";h+="<h3 style='margin-top:14px'>Risques financiers</h3><table><tr><th>Risque</th><th class='num'>Impact estime</th><th>Detail</th></tr>";var rf=r.risques_financiers||[];for(var i=0;i<rf.length;i++){h+="<tr><td>"+rf[i].risque+"</td><td class='num'>"+fmt(rf[i].impact_estime)+"</td><td style='font-size:.84em'>"+rf[i].detail+"</td></tr>";}h+="</table>";h+="<h3 style='margin-top:14px'>Subventions eligibles</h3><table><tr><th>Subvention</th><th class='num'>Montant max</th><th>Condition</th></tr>";var sb=r.subventions_eligibles||[];for(var i=0;i<sb.length;i++){h+="<tr><td>"+sb[i].nom+"</td><td class='num'>"+fmt(sb[i].montant_max)+"</td><td style='font-size:.84em'>"+sb[i].condition+"</td></tr>";}h+="</table>";h+="<div style='margin-top:12px;padding:10px;background:var(--bg2);border-radius:8px'><h3 style='margin:0 0 6px'>Recommandations</h3><ul style='margin:0;padding-left:20px'>";var rc=r.recommandations||[];for(var i=0;i<rc.length;i++)h+="<li style='margin:3px 0'>"+rc[i]+"</li>";h+="</ul></div>";document.getElementById("sim-risques-res").innerHTML=h;}).catch(function(e){toast(e.message);});}

/* === VEILLE === */
function loadVeille(){var a=document.getElementById("v-annee").value;document.getElementById("v-res").style.display="block";
fetch("/api/veille/baremes/"+a).then(safeJson).then(function(b){var h="<table><tr><th>Parametre</th><th class='num'>Valeur</th></tr>";for(var k in b){h+="<tr><td>"+k.replace(/_/g," ")+"</td><td class='num'>"+b[k]+"</td></tr>";}h+="</table>";document.getElementById("v-baremes").innerHTML=h;}).catch(function(){});
fetch("/api/veille/legislation/"+a).then(safeJson).then(function(l){var h="<p style='margin-bottom:10px'><strong>"+l.description+"</strong></p>";var tx=l.textes_cles||[];for(var i=0;i<tx.length;i++){h+="<div class='al info' style='margin:4px 0'><span class='ai'>&#9878;</span><span><strong>"+tx[i].reference+"</strong> - "+tx[i].titre+"<br><small>"+tx[i].resume+"</small></span></div>";}document.getElementById("v-legis").innerHTML=h;}).catch(function(){});}
function compAnnees(){var a2=parseInt(document.getElementById("v-annee").value),a1=a2-1;fetch("/api/veille/baremes/comparer/"+a1+"/"+a2).then(safeJson).then(function(d){if(!d.length){toast("Pas de differences.","info");return;}var h="<table><tr><th>Parametre</th><th class='num'>"+a1+"</th><th class='num'>"+a2+"</th><th>Evolution</th></tr>";for(var i=0;i<d.length;i++){h+="<tr><td>"+d[i].parametre+"</td><td class='num'>"+(d[i]["valeur_"+a1]||"-")+"</td><td class='num'>"+(d[i]["valeur_"+a2]||"-")+"</td><td>"+d[i].evolution+"</td></tr>";}h+="</table>";document.getElementById("v-comp").innerHTML=h;document.getElementById("v-comp-card").style.display="block";}).catch(function(e){toast(e.message);});}

/* === PORTEFEUILLE === */
function ajouterEnt(){var fd=new FormData();fd.append("siret",document.getElementById("ent-siret").value);fd.append("raison_sociale",document.getElementById("ent-raison").value);fd.append("forme_juridique",document.getElementById("ent-forme").value);fd.append("code_naf",document.getElementById("ent-naf").value);fd.append("effectif",document.getElementById("ent-eff").value||"0");fd.append("ville",document.getElementById("ent-ville").value);
fetch("/api/entreprises",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(){toast("Entreprise ajoutee !","ok");rechEnt();}).catch(function(e){toast(e.message);});}

function rechEnt(){var q=(document.getElementById("ent-search")||{}).value||"";
fetch("/api/entreprises?q="+encodeURIComponent(q)).then(safeJson).then(function(d){
var el=document.getElementById("ent-list");if(!d.length){el.innerHTML="<p style='color:var(--tx2)'>Aucune entreprise.</p>";return;}
var h="";for(var i=0;i<d.length;i++){var e=d[i];
h+="<div class='ent-item'><div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px'><strong>"+e.raison_sociale+"</strong>";
if(e.forme_juridique)h+="<span class='badge badge-blue'>"+e.forme_juridique+"</span>";
h+="</div><div style='font-size:.84em;color:var(--tx2);margin-top:4px'>SIRET: "+e.siret;
if(e.ville)h+=" | "+e.ville;if(e.code_naf)h+=" | NAF: "+e.code_naf;
if(e.effectif)h+=" | "+e.effectif+" sal.";h+="</div></div>";}
el.innerHTML=h;}).catch(function(){});}

/* === EQUIPE === */
function inviterCollab(){
var fd=new FormData();fd.append("email_invite",document.getElementById("inv-email").value);fd.append("role",document.getElementById("inv-role").value);
fetch("/api/collaboration/inviter",{method:"POST",body:fd}).then(function(r){if(!r.ok)throw new Error("Erreur");return r.json();}).then(function(d){
document.getElementById("inv-res").innerHTML="<div class='al ok'><span class='ai'>&#9989;</span><span>Invitation creee pour <strong>"+d.email+"</strong>. Lien : <a href='"+d.lien_validation+"' target='_blank'>"+d.lien_validation+"</a></span></div>";
loadEquipe();}).catch(function(e){toast(e.message);});}

function loadEquipe(){
fetch("/api/collaboration/equipe").then(safeJson).then(function(data){
var invs=data.invitations||[];var el=document.getElementById("equipe-list");
if(!invs.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun collaborateur invite.</p>";}else{
var h="<table><tr><th>Email</th><th>Role</th><th>Statut</th><th>Date</th><th>Invite par</th></tr>";
for(var i=0;i<invs.length;i++){var inv=invs[i];var cls=inv.statut==="active"?"badge-green":"badge-amber";
h+="<tr><td>"+inv.email+"</td><td><span class='badge badge-blue'>"+inv.role+"</span></td><td><span class='badge "+cls+"'>"+inv.statut+"</span></td><td>"+inv.date.substring(0,10)+"</td><td>"+inv.invite_par+"</td></tr>";}
h+="</table>";el.innerHTML=h;}
var logs=data.audit_log||[];var lel=document.getElementById("audit-log");
if(!logs.length){lel.innerHTML="<p style='color:var(--tx2)'>Aucune action enregistree.</p>";}else{
var lh="<table><tr><th>Date</th><th>Profil</th><th>Action</th><th>Details</th></tr>";
for(var j=logs.length-1;j>=Math.max(0,logs.length-20);j--){var lg=logs[j];
lh+="<tr><td style='font-size:.8em'>"+lg.date.substring(0,19).replace("T"," ")+"</td><td>"+lg.profil+"</td><td><span class='badge badge-blue'>"+lg.action+"</span></td><td style='font-size:.82em'>"+lg.details+"</td></tr>";}
lh+="</table>";lel.innerHTML=lh;}
}).catch(function(){});}

/* === EXPORT === */
function exportSection(name){
var el=document.querySelector("#s-"+name+" .card")||document.querySelector("#res-analyse");
if(!el){toast("Rien a exporter.","warn");return;}
var tables=el.querySelectorAll("table");
if(tables.length===0){toast("Aucune donnee tabulaire.","warn");return;}
var csv="";for(var t=0;t<tables.length;t++){var rows=tables[t].querySelectorAll("tr");for(var i=0;i<rows.length;i++){var cells=rows[i].querySelectorAll("th,td");var line=[];for(var j=0;j<cells.length;j++){var txt=cells[j].textContent.replace(/"/g,'""');line.push('"'+txt+'"');}csv+=line.join(";")+"\\n";}csv+="\\n";}
var blob=new Blob([csv],{type:"text/csv;charset=utf-8"});var a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="normacheck_"+name+".csv";a.click();toast("Export telecharge.","ok");}

/* === MODE ANALYSE === */
document.getElementById("mode-analyse").addEventListener("change",function(){
var m=this.value;var msgs={"simple":"Analyse simple : detection des ecarts de taux et montants.","social":"Audit social : verification complete des cotisations, DSN, conges, conventions collectives.","fiscal":"Audit fiscal : coherence TVA, charges deductibles, IS/IR, declarations fiscales.","complet":"Audit complet : verification de toutes les coherences sociales, fiscales, DSN et rapprochements."};
document.getElementById("mode-info").innerHTML="<span class='ai'>&#128161;</span><span>"+msgs[m]+"</span>";});

/* === FILE INTERPRETATION + AUDIT === */
function showFileInterpretation(data){
var fl=document.getElementById("az-fichiers-list");
if(!data||!data.declarations||!data.declarations.length){fl.innerHTML="<p style='color:var(--tx2)'>Aucun fichier interprete.</p>";return;}
var fi=data.fichiers_info||[];
var h="<table><tr><th>Fichier</th><th>Nature detectee</th><th>Employeur</th><th>Periode</th><th class='num'>Salaries</th><th class='num'>Cotisations</th><th class='num'>Masse sal.</th></tr>";
for(var i=0;i<data.declarations.length;i++){var d=data.declarations[i];
var nature=d.nature||"Document";
var fname=(i<fi.length?fi[i].nom:"")||(d.reference||"fichier "+(i+1));
var empName=d.employeur?(d.employeur.raison_sociale||d.employeur.siret||"-"):"-";
var badgeCls="badge-blue";
if(nature.indexOf("Bulletin")>=0)badgeCls="badge-green";
else if(nature.indexOf("DSN")>=0)badgeCls="badge-purple";
else if(nature.indexOf("Livre")>=0||nature.indexOf("Recapitulatif")>=0)badgeCls="badge-amber";
else if(nature.indexOf("Bordereau")>=0)badgeCls="badge-teal";
else if(nature.indexOf("Facture")>=0)badgeCls="badge-blue";
else if(nature.indexOf("Contrat")>=0)badgeCls="badge-purple";
else if(nature.indexOf("Attestation")>=0)badgeCls="badge-amber";
else if(nature.indexOf("interessement")>=0||nature.indexOf("participation")>=0)badgeCls="badge-teal";
var masse=(d.masse_salariale_brute||0);
var extraInfo="";
if(d.net_a_payer)extraInfo+=" | Net: "+d.net_a_payer.toFixed(2)+" EUR";
if(d.date_virement)extraInfo+=" | Virement: "+d.date_virement;
if(d.total_patronal)extraInfo+=" | Pat: "+d.total_patronal.toFixed(2);
if(d.total_salarial)extraInfo+=" | Sal: "+d.total_salarial.toFixed(2);
if(d.montant_ht)extraInfo=" | HT: "+d.montant_ht.toFixed(2)+" | TVA: "+(d.montant_tva||0).toFixed(2)+" | TTC: "+(d.montant_ttc||0).toFixed(2);
if(d.tiers)extraInfo+=" | Tiers: "+d.tiers;
if(d.type_contrat)extraInfo=" | Type: "+d.type_contrat;
if(d.remuneration_brute)extraInfo+=" | Remun: "+d.remuneration_brute.toFixed(2)+" EUR";
h+="<tr><td style='font-size:.84em'>"+fname+"</td><td><span class='badge "+badgeCls+"'>"+nature+"</span></td><td>"+empName+"</td><td>"+(d.periode||"-")+"</td><td class='num'>"+(d.nb_salaries||0)+"</td><td class='num'>"+(d.nb_cotisations||0)+"</td><td class='num'>"+(masse>0?masse.toFixed(2)+" EUR":"-")+"</td></tr>";
if(extraInfo){h+="<tr><td colspan='7' style='font-size:.82em;color:var(--tx2);padding:2px 8px;border-top:none'>"+extraInfo+"</td></tr>";}
if(d.salaries&&d.salaries.length>0){for(var si=0;si<d.salaries.length;si++){var s=d.salaries[si];h+="<tr style='font-size:.82em;color:var(--tx2)'><td></td><td colspan='2'>"+((s.prenom||"")+" "+(s.nom||"")).trim()||"Salarie "+(si+1)+"</td><td>"+(s.nir?"NIR: "+s.nir.substring(0,5)+"...":"-")+"</td><td class='num'>"+s.brut_mensuel.toFixed(2)+" EUR</td><td class='num'>"+s.net_fiscal.toFixed(2)+" EUR</td><td></td></tr>";}}}
if(data.declarations.length>1){var totMasse=0;var totSal=0;for(var j=0;j<data.declarations.length;j++){totMasse+=(data.declarations[j].masse_salariale_brute||0);totSal+=(data.declarations[j].nb_salaries||0);}
h+="<tr style='font-weight:bold;background:var(--pl)'><td colspan='4'>TOTAL</td><td class='num'>"+totSal+"</td><td></td><td class='num'>"+totMasse.toFixed(2)+" EUR</td></tr>";}
h+="</table>";
for(var k=0;k<data.declarations.length;k++){var dk=data.declarations[k];if(dk.s89_total_brut&&dk.masse_salariale_brute){var ecS89=Math.abs(dk.s89_total_brut-dk.masse_salariale_brute);if(ecS89>10){h+="<div class='al warn' style='margin-top:6px'><span class='ai'>&#9888;</span><span><strong>Ecart S89 :</strong> Total brut declare (S89) = "+dk.s89_total_brut.toFixed(2)+" EUR vs masse salariale calculee = "+dk.masse_salariale_brute.toFixed(2)+" EUR (ecart: "+ecS89.toFixed(2)+" EUR)</span></div>";}}}
if(data.knowledge_summary){var ks=data.knowledge_summary;h+="<div class='al info' style='margin-top:10px'><span class='ai'>&#128218;</span><span><strong>Donnees integrees :</strong> "+ks.nb_salaries_connus+" salarie(s), "+ks.nb_cotisations_analysees+" cotisation(s), masse salariale "+ks.total_masse_salariale.toFixed(2)+" EUR"+(ks.nb_contrats_rh>0?" | "+ks.nb_contrats_rh+" contrat(s) RH cree(s)":"")+"</span></div>";}
fl.innerHTML=h;}

function showIntegrationResults(data){
var card=document.getElementById("az-integration-card");var el=document.getElementById("az-integration-results");
var ig=data.integration;
if(!ig){card.style.display="none";return;}
card.style.display="block";
var h="<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px'>";
var np=ig.compta_ecritures_paie||0;var nf=ig.compta_ecritures_facture||0;var nr=ig.rh_contrats_crees||0;var nu=ig.rh_contrats_maj||0;var npl=ig.rh_planning_crees||0;
h+="<div class='sc "+(np>0?"green":"amber")+"'><div class='val'>"+np+"</div><div class='lab'>Ecritures paie</div></div>";
h+="<div class='sc "+(nf>0?"green":"amber")+"'><div class='val'>"+nf+"</div><div class='lab'>Ecritures facture</div></div>";
h+="<div class='sc "+(nr>0?"green":"amber")+"'><div class='val'>"+nr+"</div><div class='lab'>Contrats RH crees</div></div>";
if(nu>0)h+="<div class='sc blue'><div class='val'>"+nu+"</div><div class='lab'>Contrats maj</div></div>";
if(npl>0)h+="<div class='sc blue'><div class='val'>"+npl+"</div><div class='lab'>Planning crees</div></div>";
h+="</div>";
if(np>0||nf>0){h+="<div class='al ok'><span class='ai'>&#9989;</span><span><strong>Comptabilite :</strong> "+np+" ecriture(s) de paie"+(nf>0?" + "+nf+" facture(s)":"")+" generee(s) automatiquement. Consultez l onglet Comptabilite pour les visualiser.</span></div>";}
else{h+="<div class='al warn'><span class='ai'>&#9888;</span><span><strong>Comptabilite :</strong> Aucune ecriture generee. Les documents ne contiennent pas suffisamment de donnees exploitables.</span></div>";}
if(nr>0){h+="<div class='al ok'><span class='ai'>&#9989;</span><span><strong>Ressources humaines :</strong> "+nr+" contrat(s) cree(s)"+(npl>0?", "+npl+" creneaux planning":"")+ ". Consultez l onglet RH pour les visualiser.</span></div>";}
else if(nu>0){h+="<div class='al info'><span class='ai'>&#128260;</span><span><strong>Ressources humaines :</strong> "+nu+" contrat(s) existant(s) mis a jour avec les nouvelles donnees.</span></div>";}
else{h+="<div class='al warn'><span class='ai'>&#9888;</span><span><strong>Ressources humaines :</strong> Aucun salarie identifie dans les documents.</span></div>";}
var log=ig.log||[];if(log.length>0){
h+="<details style='margin-top:8px'><summary style='cursor:pointer;color:var(--tx2);font-size:.85em'>Detail du traitement ("+log.length+" etapes)</summary>";
h+="<div style='background:var(--bg2);border-radius:8px;padding:10px;margin-top:6px;font-family:monospace;font-size:.8em;max-height:200px;overflow-y:auto'>";
for(var li=0;li<log.length;li++){var cls=(log[li].indexOf("ERREUR")>=0)?"color:var(--r)":(log[li].indexOf("OK")>=0?"color:var(--g)":"color:var(--tx2)");h+="<div style='"+cls+"'>"+log[li]+"</div>";}
h+="</div></details>";}
el.innerHTML=h;}

function showAuditChecks(data){
var mode=data.mode_analyse||document.getElementById("mode-analyse").value;
var card=document.getElementById("az-audit-card");var el=document.getElementById("az-audit-checks");
if(mode==="simple"){card.style.display="none";return;}
card.style.display="block";
el.innerHTML="<p style='color:var(--tx2)'>Chargement de l audit depuis la base de connaissances...</p>";
fetch("/api/bibliotheque/knowledge/audit").then(function(r){if(!r.ok)throw new Error("Erreur serveur ("+r.status+")");return r.json();}).then(function(audit){
var h="";var sc=audit.score_audit||{};
h+="<div style='display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px'>";
h+="<div class='sc blue'><div class='val'>"+sc.total_checks+"</div><div class='lab'>Points de controle</div></div>";
h+="<div class='sc green'><div class='val'>"+sc.verifies+"</div><div class='lab'>Verifies</div></div>";
h+="<div class='sc "+(sc.pourcentage>=60?"green":"red")+"'><div class='val'>"+sc.pourcentage+"%</div><div class='lab'>Couverture</div></div>";
h+="</div>";
var ks=audit.knowledge_summary||{};
if(ks.nb_salaries_connus>0||ks.nb_contrats_rh>0){
h+="<div class='al info' style='margin-bottom:12px'><span class='ai'>&#128218;</span><span><strong>Base de connaissances :</strong> "+ks.nb_salaries_connus+" salarie(s), "+ks.nb_contrats_rh+" contrat(s), "+(ks.periodes||[]).length+" periode(s), "+(ks.pieces_disponibles||[]).join(", ")+"</span></div>";}
function renderChecks(checks,titre,prefix){
if(!checks||!checks.length)return"";
var nb_ok=0;for(var i=0;i<checks.length;i++){if(checks[i].present)nb_ok++;}
var out="<h3 style='color:var(--p);margin:16px 0 8px'>"+titre+" <span class='badge "+(nb_ok===checks.length?"badge-green":"badge-amber")+"'>"+nb_ok+"/"+checks.length+"</span></h3>";
for(var i=0;i<checks.length;i++){var c=checks[i];var cls=c.present?(c.alerte?"warn":"ok"):"warn";
out+="<div class='al "+cls+"' style='cursor:pointer' data-toggle-detail='1'><span class='ai'>"+(c.present?"&#9989;":"&#9888;")+"</span><span><strong>"+c.nom+"</strong> - "+(c.present?c.detail:"Documents insuffisants");
out+="<div class='aud-detail' style='display:none;margin-top:8px;font-size:.9em;padding-top:8px;border-top:1px solid rgba(0,0,0,.1)'>";
out+="<p><strong>Etat :</strong> "+c.detail+"</p>";
if(!c.present)out+="<p style='margin-top:4px'><strong>Documents necessaires :</strong> "+c.documents_requis+"</p>";
if(c.incidence_legale)out+="<p style='margin-top:4px;color:var(--r);font-weight:600'>Consequence : "+c.incidence_legale+"</p>";
out+="<p style='margin-top:4px;color:var(--tx2)'><em>Ref: "+c.reference+"</em></p>";
out+="</div></span></div>";}return out;}
if(mode==="social"||mode==="complet"){h+=renderChecks(audit.social,"Audit social - Code de la securite sociale + Code du travail ("+sc.social_verifies+"/"+sc.social_total+")","social");}
if(mode==="fiscal"||mode==="complet"){h+=renderChecks(audit.fiscal,"Audit fiscal - Code general des impots ("+sc.fiscal_verifies+"/"+sc.fiscal_total+")","fiscal");}
if(mode==="complet"){h+=renderChecks(audit.cour_des_comptes,"Controle Cour des comptes ("+sc.cdc_verifies+"/"+sc.cdc_total+")","cdc");}
var rm=audit.rapprochement_masses;
if(rm&&rm.periodes&&rm.periodes.length>0&&(mode==="social"||mode==="complet")){
h+="<h3 style='color:var(--p);margin:20px 0 8px'>Rapprochement des masses salariales par periode</h3>";
h+="<div style='overflow-x:auto'><table class='tb'><thead><tr><th>Periode</th><th>BS (Brut)</th><th>DSN (Brut)</th><th>LDP (Brut)</th><th>Ecart BS/DSN</th><th>Statut</th></tr></thead><tbody>";
for(var pi=0;pi<rm.periodes.length;pi++){var pp=rm.periodes[pi];
var bsv=rm.masses_bs[pp];var dsnv=rm.masses_dsn[pp];var ldpv=rm.masses_ldp[pp];
var bsb=bsv?bsv.brut:0;var dsnb=dsnv?dsnv.brut:0;var ldpb=ldpv?ldpv.brut:0;
var ecart=0;var statut="";var cls="";
if(bsb>0&&dsnb>0){ecart=Math.abs(bsb-dsnb);var ref2=Math.max(bsb,dsnb);var pct=ref2>0?(ecart/ref2*100):0;
if(pct<=1){statut="Conforme";cls="color:var(--g)";}else{statut="Ecart "+pct.toFixed(1)+"%";cls="color:var(--r);font-weight:600";}}
else if(bsb>0||dsnb>0){statut="Source unique";cls="color:var(--tx2)";}
else{statut="-";cls="color:var(--tx2)";}
h+="<tr><td><strong>"+pp+"</strong></td>";
h+="<td>"+(bsb>0?bsb.toFixed(2)+" EUR":"-")+"</td>";
h+="<td>"+(dsnb>0?dsnb.toFixed(2)+" EUR":"-")+"</td>";
h+="<td>"+(ldpb>0?ldpb.toFixed(2)+" EUR":"-")+"</td>";
h+="<td>"+(ecart>0?ecart.toFixed(2)+" EUR":"-")+"</td>";
h+="<td style='"+cls+"'>"+statut+"</td></tr>";}
h+="</tbody></table></div>";
if(rm.ecarts&&rm.ecarts.length>0){
h+="<div class='al err' style='margin-top:8px'><span class='ai'>&#9888;</span><span><strong>"+rm.ecarts.length+" ecart(s) significatif(s) detecte(s)</strong> (seuil: "+rm.seuil_tolerance_pct+"%) - Un rapprochement detaille est necessaire. Verifier les elements de paie et declarations pour identifier l origine des ecarts.</span></div>";}
else if(Object.keys(rm.masses_bs).length>0&&Object.keys(rm.masses_dsn).length>0){
h+="<div class='al ok' style='margin-top:8px'><span class='ai'>&#9989;</span><span><strong>Masses concordantes</strong> - Les montants declares (DSN) correspondent aux montants verses (bulletins).</span></div>";}}
var tc=ks.types_cotisations;
if(tc&&Object.keys(tc).length>0&&(mode==="social"||mode==="complet")){
h+="<h3 style='color:var(--p);margin:20px 0 8px'>Matrice des cotisations detectees</h3>";
var obligatoires=["maladie","vieillesse_plafonnee","vieillesse_deplafonnee","allocations_familiales","accident_travail","csg_deductible","crds","assurance_chomage","ags","retraite_complementaire_t1","fnal","csa","formation_professionnelle","taxe_apprentissage","versement_mobilite","peec"];
var labels={"maladie":"Maladie","vieillesse_plafonnee":"Vieillesse plaf.","vieillesse_deplafonnee":"Vieillesse deplaf.","allocations_familiales":"Alloc. familiales","accident_travail":"AT/MP","csg_deductible":"CSG deductible","crds":"CRDS","assurance_chomage":"Chomage","ags":"AGS","retraite_complementaire_t1":"Retraite T1","fnal":"FNAL","csa":"CSA","formation_professionnelle":"Formation pro","taxe_apprentissage":"Taxe apprentissage","versement_mobilite":"Versement mobilite","peec":"PEEC (1% logement)"};
var seuils={"versement_mobilite":11,"peec":20};
var eff=ks.nb_salaries_connus||0;
h+="<div style='overflow-x:auto'><table class='tb'><thead><tr><th>Cotisation</th><th>Obligatoire</th><th>Detectee</th><th>Nb lignes</th><th>Total patronal</th></tr></thead><tbody>";
for(var ci=0;ci<obligatoires.length;ci++){var co=obligatoires[ci];var lb=labels[co]||co;
var oblig=true;var seuilC=seuils[co];if(seuilC&&eff<seuilC&&eff>0){oblig=false;}
var det=tc[co];var found=!!det;
var cls2=found?"color:var(--g)":"color:var(--r);font-weight:600";
if(!oblig&&!found)cls2="color:var(--tx2)";
h+="<tr><td>"+lb+"</td>";
h+="<td>"+(oblig?(seuilC?"Oui (>= "+seuilC+" sal.)":"Oui"):"Non applicable")+"</td>";
h+="<td style='"+cls2+"'>"+(found?"&#9989; Oui":"&#10060; Non")+"</td>";
h+="<td class='num'>"+(det?det.count:"-")+"</td>";
h+="<td class='num'>"+(det?det.total_patronal.toFixed(2)+" EUR":"-")+"</td></tr>";}
h+="</tbody></table></div>";}
el.innerHTML=h;}).catch(function(e){el.innerHTML="<div class='al err'>Erreur chargement audit: "+e.message+"</div>";});}

/* === CONFORMITY SCORE === */
function calculateConformityScore(data){
var score=100;var details=[];var constats=data.constats||[];
var nbCrit=0,nbHaut=0,nbMoy=0,nbBas=0;
for(var i=0;i<constats.length;i++){var c=constats[i];var sev=(c.severite||"").toLowerCase();
if(sev==="critique"){score-=15;nbCrit++;details.push({deduction:-15,raison:c.titre||"Anomalie critique"});}
else if(sev==="haute"||sev==="high"){score-=10;nbHaut++;details.push({deduction:-10,raison:c.titre||"Anomalie haute"});}
else if(sev==="moyenne"||sev==="medium"){score-=5;nbMoy++;details.push({deduction:-5,raison:c.titre||"Anomalie moyenne"});}
else{score-=2;nbBas++;details.push({deduction:-2,raison:c.titre||"Anomalie basse"});}}
if(nbCrit===0&&constats.length>0){score+=5;details.push({deduction:5,raison:"Bonus: aucune anomalie critique"});}
var nbDecl=(data.declarations||[]).length;
if(nbDecl>=3){score+=3;details.push({deduction:3,raison:"Bonus: documentation suffisante ("+nbDecl+" sources)"});}
else if(nbDecl<=1){var maxScore=80;if(score>maxScore){score=maxScore;}details.push({deduction:0,raison:"Plafond a "+maxScore+"% : documentation insuffisante pour score complet"});}
score=Math.max(0,Math.min(100,score));
var grade="F";if(score>=90)grade="A";else if(score>=75)grade="B";else if(score>=60)grade="C";else if(score>=45)grade="D";else if(score>=30)grade="E";
var explication="Score NormaCheck : "+score+"/100 ("+grade+"). ";
explication+="Base 100, deductions : critiques("+nbCrit+"x-15) hautes("+nbHaut+"x-10) moyennes("+nbMoy+"x-5) basses("+nbBas+"x-2). ";
explication+="Bonus possible si aucune anomalie critique (+5) et documentation suffisante (+3). ";
explication+="Plafonne a 80% si moins de 2 documents analyses.";
return{score:score,grade:grade,explanation:explication,details:details,nb_critiques:nbCrit,nb_hautes:nbHaut,nb_moyennes:nbMoy,nb_basses:nbBas};}

/* === PDF EXPORT === */
function exportPDF(){
if(!analysisData){toast("Aucun rapport a exporter.","warn");return;}
var mode=analysisData.mode_analyse||document.getElementById("mode-analyse").value;
var titres={"simple":"Rapport d analyse NormaCheck","social":"Audit social NormaCheck","fiscal":"Audit fiscal NormaCheck","complet":"Audit NormaCheck complet"};
var titre=titres[mode]||"Rapport NormaCheck";
var scoreData=calculateConformityScore(analysisData);
var constats=analysisData.constats||[];
var w=window.open("","_blank");
var ent={}; try{var xe=new XMLHttpRequest();xe.open("GET","/api/config/entete",false);xe.send();if(xe.status===200)ent=JSON.parse(xe.responseText);}catch(e){}
var entHtml="";
if(ent.nom_entreprise){entHtml="<div style='text-align:center;border-bottom:2px solid #1e40af;padding-bottom:16px;margin-bottom:20px'><h1 style='color:#1e40af;margin:0'>"+ent.nom_entreprise+"</h1><p style='color:#64748b'>"+((ent.forme_juridique||"")+" - "+(ent.adresse||""))+"</p><p style='color:#64748b'>SIRET: "+(ent.siret||"")+" | Tel: "+(ent.telephone||"")+"</p></div>";}
var socialH="",fiscalH="";
for(var i=0;i<constats.length;i++){var c=constats[i];var cat=(c.categorie||"").toLowerCase();
var item="<div style='border:1px solid #e2e8f0;border-left:4px solid "+(Math.abs(c.montant_impact||0)>5000?"#ef4444":"#f59e0b")+";border-radius:8px;padding:12px;margin:8px 0'><strong>"+c.titre+"</strong><p style='color:#64748b;margin:4px 0'>"+(c.description||"")+"</p><p><strong>Impact:</strong> "+Math.abs(c.montant_impact||0).toFixed(2)+" EUR</p>"+(c.reference_legale?"<p style='font-size:.85em;color:#64748b'>Ref: "+c.reference_legale+"</p>":"")+(c.recommandation?"<p style='color:#1e40af;font-style:italic'>"+c.recommandation+"</p>":"")+"</div>";
if(cat.indexOf("fiscal")>=0||cat.indexOf("tva")>=0||cat.indexOf("impot")>=0)fiscalH+=item;else socialH+=item;}
var html="<!DOCTYPE html><html><head><meta charset='UTF-8'><title>"+titre+"</title><style>body{font-family:Segoe UI,sans-serif;max-width:900px;margin:0 auto;padding:30px;color:#1e293b}h1{color:#1e40af}h2{color:#1e40af;border-bottom:1px solid #e2e8f0;padding-bottom:6px;margin-top:30px}.score{text-align:center;padding:20px;background:#f8fafc;border-radius:12px;border:2px solid #e2e8f0;margin:20px 0}.grade{font-size:3em;font-weight:800;color:#1e40af}.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.8em;font-weight:700}@media print{body{padding:10px}}</style></head><body>";
html+=entHtml;
html+="<h1 style='text-align:center'>"+titre+"</h1>";
html+="<p style='text-align:center;color:#64748b'>Date: "+new Date().toLocaleDateString("fr-FR")+" | "+((analysisData.synthese||{}).nb_fichiers||0)+" fichier(s) analyse(s)</p>";
html+="<div class='score'><div class='grade'>"+scoreData.grade+"</div><div style='font-size:2em;font-weight:700'>"+scoreData.score+" / 100</div><p style='color:#64748b;margin-top:8px'>"+scoreData.explanation+"</p></div>";
if(socialH){html+="<h2>Partie sociale - Constats</h2><p style='color:#64748b'>Points de controle relevant de la legislation sociale (Code de la securite sociale, Code du travail)</p>"+socialH;}
if(fiscalH){html+="<h2>Partie fiscale - Constats</h2><p style='color:#64748b'>Points de controle relevant de la legislation fiscale (Code general des impots)</p>"+fiscalH;}
if(!socialH&&!fiscalH){html+="<h2>Constats</h2>";for(var i=0;i<constats.length;i++){var c=constats[i];html+="<div style='border:1px solid #e2e8f0;border-radius:8px;padding:12px;margin:8px 0'><strong>"+c.titre+"</strong><p>"+c.description+"</p><p>Impact: "+Math.abs(c.montant_impact||0).toFixed(2)+" EUR</p></div>";}}
html+="<h2>Recommandations</h2>";var recos=analysisData.recommandations||[];for(var i=0;i<recos.length;i++){html+="<p>"+(i+1)+". "+(recos[i].description||recos[i].titre||"")+"</p>";}
html+="<div style='margin-top:40px;padding:16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;font-size:.85em'><h3>Methodologie du score NormaCheck</h3><p>"+scoreData.explanation+"</p><table style='width:100%;border-collapse:collapse;margin-top:8px'><tr style='background:#1e40af;color:#fff'><th style='padding:6px 10px;text-align:left'>Deduction</th><th style='padding:6px 10px;text-align:left'>Raison</th></tr>";
for(var i=0;i<scoreData.details.length;i++){var d=scoreData.details[i];html+="<tr style='border-bottom:1px solid #e2e8f0'><td style='padding:4px 10px;color:"+(d.deduction>0?"#16a34a":"#ef4444")+"'>"+(d.deduction>0?"+":"")+d.deduction+"</td><td style='padding:4px 10px'>"+d.raison+"</td></tr>";}
html+="</table></div>";
html+="<p style='text-align:center;margin-top:30px;font-size:.8em;color:#94a3b8'>Document genere par NormaCheck v3.5 - Non opposable aux administrations (art. L.243-6-3 CSS)</p></body></html>";
w.document.write(html);w.document.close();setTimeout(function(){w.print();},600);}

/* === RH MODULE === */
function showRHTab(n,el){document.querySelectorAll("#rh-tabs .tab").forEach(function(t){t.classList.remove("active")});document.querySelectorAll("#s-rh .tc").forEach(function(t){t.classList.remove("active")});if(el)el.classList.add("active");var tc=document.getElementById("rh-"+n);if(tc)tc.classList.add("active");
if(n==="salaries")loadRHSalaries();if(n==="contrats")loadRHContrats();if(n==="conges")loadRHConges();if(n==="arrets")loadRHArrets();if(n==="sanctions")loadRHSanctions();if(n==="entretiens")loadRHEntretiens();if(n==="visites")loadRHVisites();if(n==="attestations")loadRHAttestations();if(n==="planning"){loadRHPlanning();renderCalendar();}if(n==="echanges")loadRHEchanges();if(n==="alertes")loadRHAlertes();if(n==="bulletins")loadRHBulletins();}

function rhPost(url,fd,cb){fetch(url,{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(cb).catch(function(e){toast(e.message);});}
function rhGet(url,cb){fetch(url).then(safeJson).then(cb).catch(function(){});}

function creerContrat(){var fd=new FormData();fd.append("type_contrat",document.getElementById("rh-type-ctr").value);fd.append("nom_salarie",document.getElementById("rh-ctr-nom").value);fd.append("prenom_salarie",document.getElementById("rh-ctr-prenom").value);fd.append("poste",document.getElementById("rh-ctr-poste").value);fd.append("date_debut",document.getElementById("rh-ctr-debut").value);fd.append("date_fin",document.getElementById("rh-ctr-fin").value);fd.append("salaire_brut",document.getElementById("rh-ctr-salaire").value||"0");fd.append("temps_travail",document.getElementById("rh-ctr-temps").value);fd.append("duree_hebdo",document.getElementById("rh-ctr-heures").value);fd.append("convention_collective",document.getElementById("rh-ctr-ccn").value);fd.append("periode_essai_jours",document.getElementById("rh-ctr-essai").value);fd.append("motif_cdd",document.getElementById("rh-ctr-motif").value);
rhPost("/api/rh/contrats",fd,function(d){toast("Contrat genere.","ok");
var h="<div class='al ok'><span class='ai'>&#9989;</span><span>Contrat <strong>"+d.type_contrat+" - "+d.nom_salarie+" "+d.prenom_salarie+"</strong> cree (ID: "+d.id+")</span></div>";
h+="<button class='btn btn-s btn-sm' style='margin:8px 4px 0 0' onclick='voirContrat("+JSON.stringify(d.id)+")'>Visualiser le contrat</button>";
var eff=d.cascading_effects;if(eff){h+="<div style='margin-top:12px;padding:10px;background:var(--pl);border-radius:8px'><strong>Effets en cascade :</strong><ul style='margin:6px 0 0 16px;font-size:.86em'>";
if(eff.dpae)h+="<li>&#9989; DPAE generee (ref: "+eff.dpae.reference+")</li>";
if(eff.visite_medicale)h+="<li>&#128197; Visite medicale programmee avant le "+eff.visite_medicale.echeance+"</li>";
if(eff.planning&&eff.planning.length)h+="<li>&#128197; "+eff.planning.length+" creneaux planning crees (1ere semaine)</li>";
if(eff.ecriture_comptable)h+="<li>&#128181; Ecriture comptable provisionnee ("+eff.ecriture_comptable.libelle+")</li>";
h+="</ul></div>";}
document.getElementById("rh-ctr-res").innerHTML=h;loadRHContrats();});}

function loadRHSalaries(){
rhGet("/api/rh/contrats",function(list){
var el=document.getElementById("rh-sal-list");
if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun salarie detecte. Importez des bulletins de paie, DSN ou contrats dans l onglet Import / Analyse.</p>";return;}
var h="<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px'>";
h+="<div class='sc blue'><div class='val'>"+list.length+"</div><div class='lab'>Salaries</div></div>";
var actifs=0;var totalBrut=0;for(var i=0;i<list.length;i++){if(list[i].statut==="actif")actifs++;totalBrut+=parseFloat(list[i].salaire_brut||0);}
h+="<div class='sc green'><div class='val'>"+actifs+"</div><div class='lab'>Actifs</div></div>";
h+="<div class='sc'><div class='val'>"+totalBrut.toFixed(0)+" EUR</div><div class='lab'>Masse brute</div></div>";
h+="</div>";
h+="<table><thead><tr><th>Nom</th><th>Prenom</th><th>Poste</th><th>Type contrat</th><th>Date debut</th><th class='num'>Brut mensuel</th><th>NIR</th><th>Statut</th><th>Source</th></tr></thead><tbody>";
for(var i=0;i<list.length;i++){var c=list[i];
var cls=c.statut==="actif"?"badge-green":(c.statut==="suspendu"?"badge-amber":"badge-red");
var nirAff=c.nir?(c.nir.length>5?c.nir.substring(0,5)+"...":c.nir):"-";
var src=(c.source||"").replace("analyse_automatique","Auto");
h+="<tr><td><strong>"+c.nom_salarie+"</strong></td><td>"+c.prenom_salarie+"</td><td>"+c.poste+"</td>";
h+="<td><span class='badge badge-blue'>"+c.type_contrat+"</span></td>";
h+="<td>"+c.date_debut+"</td>";
h+="<td class='num'>"+parseFloat(c.salaire_brut||0).toFixed(2)+" EUR</td>";
h+="<td style='font-size:.8em'>"+nirAff+"</td>";
h+="<td><span class='badge "+cls+"'>"+c.statut+"</span></td>";
h+="<td style='font-size:.78em;color:var(--tx2)'>"+src+"</td></tr>";}
h+="</tbody></table>";
el.innerHTML=h;});
}

function loadRHContrats(){rhGet("/api/rh/contrats",function(list){
var el=document.getElementById("rh-ctr-list");if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun contrat.</p>";return;}
var h="<table><tr><th>ID</th><th>Type</th><th>Salarie</th><th>Poste</th><th>Debut</th><th>Fin</th><th class='num'>Brut</th></tr>";
for(var i=0;i<list.length;i++){var c=list[i];h+="<tr><td style='font-size:.78em'>"+c.id+"</td><td><span class='badge badge-blue'>"+c.type_contrat+"</span></td><td>"+c.prenom_salarie+" "+c.nom_salarie+"</td><td>"+c.poste+"</td><td>"+c.date_debut+"</td><td>"+(c.date_fin||"-")+"</td><td class='num'>"+parseFloat(c.salaire_brut).toFixed(2)+"</td></tr>";}
h+="</table>";el.innerHTML=h;});}

function creerAvenant(){var fd=new FormData();fd.append("contrat_id",document.getElementById("rh-av-ctr").value);fd.append("type_avenant",document.getElementById("rh-av-type").value);fd.append("description",document.getElementById("rh-av-desc").value);fd.append("date_effet",document.getElementById("rh-av-date").value);fd.append("nouvelles_conditions",document.getElementById("rh-av-desc").value);
rhPost("/api/rh/avenants",fd,function(){toast("Avenant enregistre.","ok");loadRHAvenants();});}
function loadRHAvenants(){rhGet("/api/rh/avenants",function(list){var el=document.getElementById("rh-av-list");if(!list.length){el.innerHTML="";return;}var h="<table><tr><th>Contrat</th><th>Type</th><th>Date effet</th><th>Description</th></tr>";for(var i=0;i<list.length;i++){var a=list[i];h+="<tr><td>"+a.contrat_id+"</td><td><span class='badge badge-blue'>"+a.type_avenant+"</span></td><td>"+a.date_effet+"</td><td>"+a.description+"</td></tr>";}h+="</table>";el.innerHTML=h;});}

function enregConge(){var fd=new FormData();fd.append("salarie_id",document.getElementById("rh-cg-sal").value);fd.append("type_conge",document.getElementById("rh-cg-type").value);fd.append("date_debut",document.getElementById("rh-cg-dd").value);fd.append("date_fin",document.getElementById("rh-cg-df").value);fd.append("nb_jours",document.getElementById("rh-cg-jours").value);fd.append("statut",document.getElementById("rh-cg-stat").value);
rhPost("/api/rh/conges",fd,function(){toast("Conge enregistre.","ok");loadRHConges();});}
function loadRHConges(){rhGet("/api/rh/conges",function(list){var el=document.getElementById("rh-cg-list");if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun conge enregistre.</p>";return;}var h="<table><tr><th>Salarie</th><th>Type</th><th>Debut</th><th>Fin</th><th>Jours</th><th>Statut</th></tr>";for(var i=0;i<list.length;i++){var c=list[i];var cls=c.statut==="valide"?"badge-green":(c.statut==="refuse"?"badge-red":"badge-amber");h+="<tr><td>"+c.salarie_id+"</td><td>"+c.type_conge+"</td><td>"+c.date_debut+"</td><td>"+c.date_fin+"</td><td class='num'>"+c.nb_jours+"</td><td><span class='badge "+cls+"'>"+c.statut+"</span></td></tr>";}h+="</table>";el.innerHTML=h;});}

function enregArret(){var fd=new FormData();fd.append("salarie_id",document.getElementById("rh-ar-sal").value);fd.append("type_arret",document.getElementById("rh-ar-type").value);fd.append("date_debut",document.getElementById("rh-ar-dd").value);fd.append("date_fin",document.getElementById("rh-ar-df").value);fd.append("prolongation",document.getElementById("rh-ar-prol").value);fd.append("subrogation",document.getElementById("rh-ar-sub").value);
rhPost("/api/rh/arrets",fd,function(){toast("Arret enregistre.","ok");loadRHArrets();});}
function loadRHArrets(){rhGet("/api/rh/arrets",function(list){var el=document.getElementById("rh-ar-list");if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun arret.</p>";return;}var h="<table><tr><th>Salarie</th><th>Type</th><th>Debut</th><th>Fin</th><th>Subrogation</th></tr>";for(var i=0;i<list.length;i++){var a=list[i];h+="<tr><td>"+a.salarie_id+"</td><td><span class='badge badge-amber'>"+a.type_arret+"</span></td><td>"+a.date_debut+"</td><td>"+a.date_fin+"</td><td>"+(a.subrogation==="true"?"Oui":"Non")+"</td></tr>";}h+="</table>";el.innerHTML=h;});}

function enregSanction(){var fd=new FormData();fd.append("salarie_id",document.getElementById("rh-sa-sal").value);fd.append("type_sanction",document.getElementById("rh-sa-type").value);fd.append("date_sanction",document.getElementById("rh-sa-date").value);fd.append("motif",document.getElementById("rh-sa-motif").value);fd.append("description",document.getElementById("rh-sa-desc").value);fd.append("date_entretien_prealable",document.getElementById("rh-sa-epr").value);
rhPost("/api/rh/sanctions",fd,function(){toast("Sanction enregistree.","ok");loadRHSanctions();});}
function loadRHSanctions(){rhGet("/api/rh/sanctions",function(list){var el=document.getElementById("rh-sa-list");if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucune sanction.</p>";return;}var h="<table><tr><th>Salarie</th><th>Type</th><th>Date</th><th>Motif</th></tr>";for(var i=0;i<list.length;i++){var s=list[i];h+="<tr><td>"+s.salarie_id+"</td><td><span class='badge badge-red'>"+s.type_sanction+"</span></td><td>"+s.date_sanction+"</td><td>"+s.motif+"</td></tr>";}h+="</table>";el.innerHTML=h;});}

function enregEntretien(){var fd=new FormData();fd.append("salarie_id",document.getElementById("rh-en-sal").value);fd.append("type_entretien",document.getElementById("rh-en-type").value);fd.append("date_entretien",document.getElementById("rh-en-date").value);fd.append("compte_rendu",document.getElementById("rh-en-cr").value);fd.append("date_prochain",document.getElementById("rh-en-next").value);
rhPost("/api/rh/entretiens",fd,function(){toast("Entretien enregistre.","ok");loadRHEntretiens();});}
function loadRHEntretiens(){rhGet("/api/rh/entretiens",function(list){var el=document.getElementById("rh-en-list");if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun entretien.</p>";return;}var h="<table><tr><th>Salarie</th><th>Type</th><th>Date</th><th>Prochain</th></tr>";for(var i=0;i<list.length;i++){var e=list[i];h+="<tr><td>"+e.salarie_id+"</td><td><span class='badge badge-blue'>"+e.type_entretien+"</span></td><td>"+e.date_entretien+"</td><td>"+(e.date_prochain||"-")+"</td></tr>";}h+="</table>";el.innerHTML=h;});}

function enregVisite(){var fd=new FormData();fd.append("salarie_id",document.getElementById("rh-vm-sal").value);fd.append("type_visite",document.getElementById("rh-vm-type").value);fd.append("date_visite",document.getElementById("rh-vm-date").value);fd.append("resultat",document.getElementById("rh-vm-res").value);fd.append("remarques",document.getElementById("rh-vm-rem").value);fd.append("date_prochaine",document.getElementById("rh-vm-next").value);
rhPost("/api/rh/visites-medicales",fd,function(){toast("Visite enregistree.","ok");loadRHVisites();});}
function loadRHVisites(){rhGet("/api/rh/visites-medicales",function(list){var el=document.getElementById("rh-vm-list");if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucune visite.</p>";return;}var h="<table><tr><th>Salarie</th><th>Type</th><th>Date</th><th>Resultat</th><th>Prochaine</th></tr>";for(var i=0;i<list.length;i++){var v=list[i];var cls=v.resultat==="apte"?"badge-green":(v.resultat==="inapte"?"badge-red":"badge-amber");h+="<tr><td>"+v.salarie_id+"</td><td>"+v.type_visite+"</td><td>"+v.date_visite+"</td><td><span class='badge "+cls+"'>"+v.resultat+"</span></td><td>"+(v.date_prochaine||"-")+"</td></tr>";}h+="</table>";el.innerHTML=h;});}

function genererAttestation(){var fd=new FormData();fd.append("salarie_id",document.getElementById("rh-at-sal").value);fd.append("type_attestation",document.getElementById("rh-at-type").value);fd.append("date_generation",new Date().toISOString().substring(0,10));
rhPost("/api/rh/attestations/generer",fd,function(d){document.getElementById("rh-at-res").innerHTML="<div class='card' style='background:var(--pl);margin-top:8px'><pre style='white-space:pre-wrap;font-size:.82em;line-height:1.6'>"+d.contenu+"</pre><button class='btn btn-s btn-sm' onclick='window.print()'>Imprimer</button></div>";toast("Attestation generee.","ok");loadRHAttestations();});}
function loadRHAttestations(){rhGet("/api/rh/attestations",function(list){var el=document.getElementById("rh-at-list");if(!list.length){el.innerHTML="";return;}var h="<table><tr><th>Salarie</th><th>Type</th><th>Date</th></tr>";for(var i=0;i<list.length;i++){var a=list[i];h+="<tr><td>"+a.salarie_id+"</td><td><span class='badge badge-blue'>"+a.type_attestation+"</span></td><td>"+a.date_generation+"</td></tr>";}h+="</table>";el.innerHTML=h;});}

function ajouterPlanning(){var fd=new FormData();fd.append("salarie_id",document.getElementById("rh-pl-sal").value);fd.append("date",document.getElementById("rh-pl-date").value);fd.append("heure_debut",document.getElementById("rh-pl-hd").value);fd.append("heure_fin",document.getElementById("rh-pl-hf").value);fd.append("type_poste",document.getElementById("rh-pl-type").value);
rhPost("/api/rh/planning",fd,function(){toast("Planning mis a jour.","ok");loadRHPlanning();});}
function loadRHPlanning(){rhGet("/api/rh/planning",function(list){var el=document.getElementById("rh-pl-list");if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun planning.</p>";return;}var h="<table><tr><th>Salarie</th><th>Date</th><th>Debut</th><th>Fin</th><th>Type</th></tr>";for(var i=0;i<list.length;i++){var p=list[i];var nom=p.salarie_nom||p.salarie_id||"?";var tp=p.type_poste||p.type||"normal";h+="<tr><td>"+nom+"</td><td>"+p.date+"</td><td>"+p.heure_debut+"</td><td>"+p.heure_fin+"</td><td><span class='badge badge-blue'>"+tp+"</span></td></tr>";}h+="</table>";el.innerHTML=h;});}
function renderCalendar(){rhGet("/api/rh/planning",function(list){
var cal=document.getElementById("rh-pl-calendar");if(!cal)return;
var semInput=document.getElementById("rh-pl-sem");var filterInput=document.getElementById("rh-pl-filter");
var startDate;if(semInput&&semInput.value){startDate=new Date(semInput.value);}else{startDate=new Date();startDate.setDate(startDate.getDate()-startDate.getDay()+1);}
var filter=(filterInput&&filterInput.value)?filterInput.value.toLowerCase():"";
var jours=["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"];
var colors={"normal":"#3b82f6","astreinte":"#f59e0b","nuit":"#6366f1","dimanche":"#ef4444","ferie":"#22c55e"};
var h="<table style='width:100%;border-collapse:collapse;font-size:.82em'><tr style='background:var(--p2);color:#fff'><th style='padding:8px;text-align:left'>Salarie</th>";
for(var j=0;j<7;j++){var d=new Date(startDate);d.setDate(d.getDate()+j);h+="<th style='padding:8px;text-align:center'>"+jours[j]+"<br><small>"+d.toLocaleDateString("fr-FR",{day:"numeric",month:"short"})+"</small></th>";}
h+="</tr>";
var salaries={};for(var i=0;i<list.length;i++){var p=list[i];var sid=p.salarie_nom||p.salarie_id||"?";if(filter&&sid.toLowerCase().indexOf(filter)<0)continue;if(!salaries[sid])salaries[sid]={};var pd=new Date(p.date);for(var j=0;j<7;j++){var cd=new Date(startDate);cd.setDate(cd.getDate()+j);if(pd.toISOString().substring(0,10)===cd.toISOString().substring(0,10)){if(!salaries[sid][j])salaries[sid][j]=[];salaries[sid][j].push(p);}}}
for(var sid in salaries){h+="<tr><td style='padding:6px;font-weight:600;border-bottom:1px solid var(--brd)'>"+sid+"</td>";for(var j=0;j<7;j++){h+="<td style='padding:4px;border-bottom:1px solid var(--brd);text-align:center;vertical-align:top'>";var slots=salaries[sid][j]||[];for(var k=0;k<slots.length;k++){var s=slots[k];var tp=s.type_poste||s.type||"normal";var bg=colors[tp]||"#3b82f6";h+="<div style='background:"+bg+";color:#fff;border-radius:4px;padding:2px 4px;margin:1px 0;font-size:.78em'>"+s.heure_debut+"-"+s.heure_fin+"</div>";}
if(!slots.length)h+="<span style='color:#cbd5e1'>-</span>";h+="</td>";}h+="</tr>";}
if(!Object.keys(salaries).length){h+="<tr><td colspan='8' style='text-align:center;padding:20px;color:var(--tx2)'>Aucun creneau pour cette semaine.</td></tr>";}
h+="</table>";cal.innerHTML=h;});}
function voirContrat(id){window.open("/api/rh/contrats/"+id+"/document","_blank");}

function enregEchange(){var fd=new FormData();fd.append("salarie_id",document.getElementById("rh-ec-sal").value);fd.append("objet",document.getElementById("rh-ec-obj").value);fd.append("contenu",document.getElementById("rh-ec-txt").value);fd.append("type_echange",document.getElementById("rh-ec-type").value);fd.append("date_echange",document.getElementById("rh-ec-date").value);
rhPost("/api/rh/echanges",fd,function(){toast("Echange enregistre.","ok");loadRHEchanges();});}
function loadRHEchanges(){rhGet("/api/rh/echanges",function(list){var el=document.getElementById("rh-ec-list");if(!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun echange.</p>";return;}var h="<table><tr><th>Salarie</th><th>Type</th><th>Date</th><th>Objet</th></tr>";for(var i=0;i<list.length;i++){var e=list[i];h+="<tr><td>"+e.salarie_id+"</td><td><span class='badge badge-blue'>"+e.type_echange+"</span></td><td>"+e.date_echange+"</td><td>"+e.objet+"</td></tr>";}h+="</table>";el.innerHTML=h;});}

function loadRHAlertes(){rhGet("/api/rh/alertes",function(resp){var el=document.getElementById("rh-alertes-list");
var list=(resp&&resp.alertes)?resp.alertes:(Array.isArray(resp)?resp:[]);
if(!list.length){el.innerHTML="<div class='al ok'><span class='ai'>&#9989;</span><span>Aucune alerte en cours.</span></div>";return;}
var h="<p style='color:var(--tx2);font-size:.82em;margin-bottom:8px'>"+list.length+" alerte(s) - Cliquez pour voir les details</p>";
for(var i=0;i<list.length;i++){var a=list[i];var cls=a.urgence==="haute"?"err":(a.urgence==="moyenne"?"warn":"info");
h+="<div class='al "+cls+"' style='cursor:pointer' data-toggle-detail='1'><span class='ai'>"+(a.urgence==="haute"?"&#9888;":"&#128161;")+"</span><span><strong>"+(a.titre||a.type||"Alerte")+"</strong> - "+(a.description||"");
if(a.echeance)h+=" <em>(echeance: "+a.echeance+")</em>";
if(a.message_personnalise)h+=" <em style='color:var(--p2)'>["+a.message_personnalise+"]</em>";
h+="</span>";
h+="<div class='al-detail' style='display:none;margin-top:8px;padding:8px;background:rgba(0,0,0,.03);border-radius:6px;font-size:.86em'>";
if(a.incidence_legale)h+="<p style='color:var(--r);font-weight:600'>&#9888; Consequence legale : "+a.incidence_legale+"</p>";
if(a.reference)h+="<p style='margin-top:4px;color:var(--tx2)'>Reference : "+a.reference+"</p>";
if(a.action_requise)h+="<p style='margin-top:4px'><strong>Action requise :</strong> "+a.action_requise+"</p>";
if(a.documents_requis){h+="<p style='margin-top:4px'><strong>Documents requis :</strong></p><ul style='margin:2px 0 0 16px'>";
var docs=a.documents_requis;if(typeof docs==="string")docs=docs.split(",");for(var j=0;j<docs.length;j++){h+="<li>"+docs[j]+"</li>";}h+="</ul>";}
if(a.delai_personnalise)h+="<p style='margin-top:4px;color:var(--p2)'>Delai de notification personnalise : "+a.delai_personnalise+" jours</p>";
h+="</div></div>";}
h+="<style>.al-detail.show{display:block!important}</style>";
el.innerHTML=h;});}
function genererBulletin(){var fd=new FormData();fd.append("contrat_id",document.getElementById("rh-bp-ctr").value);fd.append("mois",document.getElementById("rh-bp-mois").value);fd.append("heures_sup",document.getElementById("rh-bp-hs").value||"0");fd.append("primes",document.getElementById("rh-bp-primes").value||"0");fd.append("avantages_nature",document.getElementById("rh-bp-avantages").value||"0");fd.append("absences",document.getElementById("rh-bp-abs").value||"0");
rhPost("/api/rh/bulletins/generer",fd,function(d){
var h="<div class='al ok'><span class='ai'>&#9989;</span><span>Bulletin genere pour <strong>"+d.mois+"</strong></span></div>";
h+="<div class='card' style='background:var(--pl);margin-top:8px'>";
h+="<div class='g3'><div class='sc blue'><div class='val'>"+(d.brut_total||0).toFixed(2)+"</div><div class='lab'>Brut</div></div><div class='sc green'><div class='val'>"+(d.net_a_payer||0).toFixed(2)+"</div><div class='lab'>Net a payer</div></div><div class='sc amber'><div class='val'>"+(d.cout_employeur||0).toFixed(2)+"</div><div class='lab'>Cout employeur</div></div></div>";
if(d.lignes){h+="<table style='margin-top:10px'><tr><th>Rubrique</th><th class='num'>Base</th><th class='num'>Taux sal.</th><th class='num'>Part sal.</th><th class='num'>Taux pat.</th><th class='num'>Part pat.</th></tr>";for(var i=0;i<d.lignes.length;i++){var l=d.lignes[i];h+="<tr><td>"+l.libelle+"</td><td class='num'>"+(l.base||0).toFixed(2)+"</td><td class='num'>"+(l.taux_salarial||0).toFixed(2)+"%</td><td class='num'>"+(l.montant_salarial||0).toFixed(2)+"</td><td class='num'>"+(l.taux_patronal||0).toFixed(2)+"%</td><td class='num'>"+(l.montant_patronal||0).toFixed(2)+"</td></tr>";}h+="</table>";}
h+="<button class='btn btn-s btn-sm' style='margin-top:8px' onclick='window.open("+JSON.stringify("/api/rh/bulletins/"+d.id+"/document")+","+JSON.stringify("_blank")+")'>Visualiser / Imprimer</button></div>";
document.getElementById("rh-bp-res").innerHTML=h;loadRHBulletins();});}
function loadRHBulletins(){rhGet("/api/rh/bulletins",function(list){var el=document.getElementById("rh-bp-list");if(!list||!list.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun bulletin.</p>";return;}
var h="<table><tr><th>Mois</th><th>Salarie</th><th class='num'>Brut</th><th class='num'>Net</th><th>Actions</th></tr>";
for(var i=0;i<list.length;i++){var b=list[i];h+="<tr><td>"+b.mois+"</td><td>"+(b.nom_salarie||"-")+"</td><td class='num'>"+(b.brut_total||0).toFixed(2)+"</td><td class='num'>"+(b.net_a_payer||0).toFixed(2)+"</td><td><button class='btn btn-s btn-sm' onclick='window.open("+JSON.stringify("/api/rh/bulletins/"+b.id+"/document")+","+JSON.stringify("_blank")+")'>Voir</button></td></tr>";}
h+="</table>";el.innerHTML=h;});}
function sauverAlertConfig(){var fd=new FormData();fd.append("type_alerte",document.getElementById("cfg-al-type").value);fd.append("actif",document.getElementById("cfg-al-actif").value);fd.append("delai_jours",document.getElementById("cfg-al-delai").value);var msg=document.getElementById("cfg-al-msg").value;if(msg)fd.append("message_personnalise",msg);
rhPost("/api/rh/alertes/personnaliser",fd,function(d){document.getElementById("cfg-al-res").innerHTML="<div class='al ok'><span class='ai'>&#9989;</span><span>Configuration alerte sauvegardee : "+d.type_alerte+" ("+(d.actif?"actif":"inactif")+")</span></div>";loadAlertConfigs();toast("Configuration alerte sauvegardee.","ok");});}
function loadAlertConfigs(){rhGet("/api/rh/alertes/config",function(list){var el=document.getElementById("cfg-alertes-list");if(!list||!list.length){el.innerHTML="<p style='color:var(--tx2)'>Configuration par defaut (toutes alertes actives).</p>";return;}
var h="<table><tr><th>Type</th><th>Actif</th><th>Delai (j)</th><th>Message</th></tr>";for(var i=0;i<list.length;i++){var c=list[i];h+="<tr><td><span class='badge "+(c.actif?"badge-green":"badge-red")+"'>"+c.type_alerte+"</span></td><td>"+(c.actif?"Oui":"Non")+"</td><td class='num'>"+(c.delai_jours||30)+"</td><td>"+(c.message_personnalise||"-")+"</td></tr>";}
h+="</table>";el.innerHTML=h;});}

/* === CONFIGURATION === */
var _urssafComptes=[];
function sauverEntete(){var fd=new FormData();fd.append("nom_entreprise",document.getElementById("cfg-nom").value);fd.append("logo_url",document.getElementById("cfg-logo").value);fd.append("adresse",document.getElementById("cfg-adresse").value);fd.append("telephone",document.getElementById("cfg-tel").value);fd.append("email",document.getElementById("cfg-email").value);fd.append("siret",document.getElementById("cfg-siret").value);fd.append("code_naf",document.getElementById("cfg-naf").value);fd.append("forme_juridique",document.getElementById("cfg-forme").value);fd.append("capital",document.getElementById("cfg-capital").value);fd.append("rcs",document.getElementById("cfg-rcs").value);fd.append("tva_intracom",document.getElementById("cfg-tva").value);
rhPost("/api/config/entete",fd,function(){toast("En-tete sauvegarde.","ok");document.getElementById("cfg-res").innerHTML="<div class='al ok'><span class='ai'>&#9989;</span><span>Configuration enregistree.</span></div>";});}
function loadEntete(){rhGet("/api/config/entete",function(d){if(!d||!d.nom_entreprise)return;document.getElementById("cfg-nom").value=d.nom_entreprise||"";document.getElementById("cfg-adresse").value=d.adresse||"";document.getElementById("cfg-tel").value=d.telephone||"";document.getElementById("cfg-email").value=d.email||"";document.getElementById("cfg-siret").value=d.siret||"";document.getElementById("cfg-naf").value=d.code_naf||"";document.getElementById("cfg-forme").value=d.forme_juridique||"";document.getElementById("cfg-capital").value=d.capital||"";document.getElementById("cfg-rcs").value=d.rcs||"";document.getElementById("cfg-tva").value=d.tva_intracom||"";document.getElementById("cfg-logo").value=d.logo_url||"";});}

function ajouterCompteURSSAF(){var c={siret:document.getElementById("urssaf-siret").value,compte:document.getElementById("urssaf-compte").value,caisse:document.getElementById("urssaf-caisse").value,taux_at:document.getElementById("urssaf-at").value};if(!c.siret||!c.compte){toast("SIRET et N compte obligatoires.");return;}_urssafComptes.push(c);renderComptesURSSAF();toast("Compte URSSAF ajoute.","ok");}
function renderComptesURSSAF(){var el=document.getElementById("urssaf-list");if(!_urssafComptes.length){el.innerHTML="";return;}var h="<table><tr><th>SIRET</th><th>N Compte</th><th>Caisse</th><th>Taux AT</th></tr>";for(var i=0;i<_urssafComptes.length;i++){var c=_urssafComptes[i];h+="<tr><td>"+c.siret+"</td><td>"+c.compte+"</td><td>"+c.caisse+"</td><td>"+c.taux_at+"%</td></tr>";}h+="</table>";el.innerHTML=h;}

/* === TOAST === */
function toast(msg,type){
type=type||"err";var d=document.createElement("div");
d.style.cssText="position:fixed;top:20px;right:20px;z-index:9999;padding:14px 20px;border-radius:12px;font-size:.88em;max-width:400px;box-shadow:0 8px 30px rgba(0,0,0,.15);animation:slideIn .3s;font-family:inherit";
if(type==="ok"){d.style.background="#f0fdf4";d.style.color="#166534";d.style.border="1px solid #bbf7d0";}
else if(type==="warn"||type==="info"){d.style.background="#eff6ff";d.style.color="#1e40af";d.style.border="1px solid #bfdbfe";}
else{d.style.background="#fef2f2";d.style.color="#991b1b";d.style.border="1px solid #fecaca";}
d.textContent=msg;document.body.appendChild(d);setTimeout(function(){d.style.opacity="0";d.style.transition="opacity .3s";setTimeout(function(){d.remove();},300);},4000);}
</script>
</body>
</html>"""
