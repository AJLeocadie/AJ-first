"""NormaCheck v3.4 - Plateforme professionnelle de conformite sociale et fiscale.

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
    version="3.4.0",
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
_invitations: list[dict] = []
_facture_statuses: dict[str, dict] = {}
_audit_log: list[dict] = []
_dsn_drafts: list[dict] = []


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
# ANALYSE
# ==============================

@app.post("/api/analyze")
async def analyser_documents(
    fichiers: list[UploadFile] = File(...),
    format_rapport: str = Query("json"),
    integrer: bool = Query(True),
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

        if integrer:
            for f in fichiers:
                await f.seek(0)
                raw = await f.read()
                sha = hashlib.sha256(raw).hexdigest()[:16]
                _doc_library.append({
                    "id": str(uuid.uuid4())[:8],
                    "nom": f.filename,
                    "taille": len(raw),
                    "sha256": sha,
                    "date_import": datetime.now().isoformat(),
                    "statut": "analyse",
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
            declarations_out.append({
                "type": decl.type_declaration,
                "reference": decl.reference,
                "periode": periode_str,
                "employeur": emp,
                "salaries": salaries,
                "masse_salariale_brute": float(decl.masse_salariale_brute),
                "effectif_declare": decl.effectif_declare,
            })

        # Auto-generer les ecritures comptables a partir des declarations
        try:
            moteur = get_moteur()
            for decl in result.declarations:
                if not decl.employes:
                    continue
                for emp in decl.employes:
                    cots = [c for c in decl.cotisations if c.employe_id == emp.id]
                    brut = float(sum(c.base_brute for c in cots)) if cots else 0
                    if brut <= 0:
                        continue
                    net = round(brut * 0.78, 2)
                    charges_pat = round(brut * 0.45, 2)
                    date_piece = ""
                    if decl.periode and decl.periode.debut:
                        date_piece = decl.periode.debut.strftime("%Y-%m-%d")
                    elif decl.periode and decl.periode.fin:
                        date_piece = decl.periode.fin.strftime("%Y-%m-%d")
                    else:
                        date_piece = date.today().isoformat()
                    lib = f"Salaire {emp.prenom} {emp.nom}"
                    try:
                        moteur.saisir_ecriture_manuelle(
                            date_piece=date_piece,
                            libelle=lib,
                            compte_debit="641000",
                            compte_credit="421000",
                            montant=Decimal(str(brut)),
                            has_justificatif=True,
                        )
                        moteur.saisir_ecriture_manuelle(
                            date_piece=date_piece,
                            libelle=f"Charges patronales {emp.prenom} {emp.nom}",
                            compte_debit="645000",
                            compte_credit="431000",
                            montant=Decimal(str(charges_pat)),
                            has_justificatif=True,
                        )
                    except Exception:
                        pass
        except Exception:
            pass

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
            "html_report": html_report,
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
        ecriture = moteur.comptabiliser_facture(
            type_document=type_doc, date_piece=date_piece,
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
    ecritures = moteur.get_journal()
    return [
        {"id": e.id, "date": str(e.date_piece), "journal": e.journal.value,
         "piece": e.numero_piece, "libelle": e.libelle, "validee": e.validee,
         "lignes": [{"compte": l.compte, "libelle": l.libelle,
                      "debit": float(l.debit), "credit": float(l.credit)}
                     for l in e.lignes]}
        for e in ecritures
    ]


@app.get("/api/comptabilite/balance")
async def balance_comptable():
    moteur = get_moteur()
    return moteur.calculer_balance()


@app.get("/api/comptabilite/grand-livre-detail")
async def grand_livre_detail(
    date_debut: Optional[str] = None,
    date_fin: Optional[str] = None,
):
    moteur = get_moteur()
    return moteur.grand_livre_detail(date_debut=date_debut, date_fin=date_fin)


@app.get("/api/comptabilite/compte-resultat")
async def compte_resultat():
    gen = GenerateurRapports()
    moteur = get_moteur()
    return gen.compte_resultat(moteur)


@app.get("/api/comptabilite/bilan")
async def bilan():
    gen = GenerateurRapports()
    moteur = get_moteur()
    return gen.bilan(moteur)


@app.get("/api/comptabilite/declaration-tva")
async def declaration_tva(mois: int = Query(1), annee: int = Query(2026)):
    gen = GenerateurRapports()
    moteur = get_moteur()
    return gen.declaration_tva(moteur, mois=mois, annee=annee)


@app.get("/api/comptabilite/charges-sociales-detail")
async def charges_sociales_detail():
    gen = GenerateurRapports()
    moteur = get_moteur()
    return gen.charges_sociales_detail(moteur)


@app.get("/api/comptabilite/plan-comptable")
async def plan_comptable_api(terme: Optional[str] = None):
    pc = PlanComptable()
    comptes = pc.rechercher(terme) if terme else pc.tous_les_comptes()
    return [{"numero": c.numero, "libelle": c.libelle, "classe": c.classe} for c in comptes]


@app.post("/api/comptabilite/ecriture/manuelle")
async def ecriture_manuelle(
    date_piece: str = Form(...), libelle: str = Form(...),
    compte_debit: str = Form(...), compte_credit: str = Form(...),
    montant: str = Form("0"), has_justificatif: str = Form("false"),
):
    moteur = get_moteur()
    mt = Decimal(montant or "0")
    has_j = has_justificatif.lower() == "true"
    result = moteur.saisie_manuelle(
        date_piece=date_piece, libelle=libelle,
        compte_debit=compte_debit, compte_credit=compte_credit,
        montant=mt, has_justificatif=has_j,
    )
    log_action("utilisateur", "ecriture_manuelle", f"{compte_debit}/{compte_credit} {mt}")
    return result


@app.post("/api/comptabilite/valider")
async def valider_ecritures():
    moteur = get_moteur()
    result = moteur.valider_ecritures()
    log_action("utilisateur", "validation_ecritures", f"{result.get('nb_validees', 0)} ecritures")
    return result


# ==============================
# SIMULATION
# ==============================

@app.get("/api/simulation/bulletin")
async def sim_bulletin(
    brut_mensuel: float = Query(2500),
    effectif: int = Query(10),
    est_cadre: bool = Query(False),
):
    from urssaf_analyzer.contribution_rules import CalculateurCotisations
    calc = CalculateurCotisations()
    return calc.simuler_bulletin(
        brut_mensuel=Decimal(str(brut_mensuel)),
        effectif=effectif, est_cadre=est_cadre,
    )


@app.get("/api/simulation/micro-entrepreneur")
async def sim_micro(
    chiffre_affaires: float = Query(50000),
    activite: str = Query("prestations_bnc"),
    acre: bool = Query(False),
):
    from urssaf_analyzer.contribution_rules import CalculateurCotisations
    calc = CalculateurCotisations()
    return calc.simuler_micro_entrepreneur(
        chiffre_affaires=Decimal(str(chiffre_affaires)),
        activite=activite, acre=acre,
    )


@app.get("/api/simulation/tns")
async def sim_tns(
    revenu_net: float = Query(40000),
    type_statut: str = Query("gerant_majoritaire"),
    acre: bool = Query(False),
):
    from urssaf_analyzer.contribution_rules import CalculateurCotisations
    calc = CalculateurCotisations()
    return calc.simuler_tns(
        revenu_net=Decimal(str(revenu_net)),
        type_statut=type_statut, acre=acre,
    )


@app.get("/api/simulation/guso")
async def sim_guso(
    salaire_brut: float = Query(500),
    nb_heures: float = Query(8),
):
    from urssaf_analyzer.contribution_rules import CalculateurCotisations
    calc = CalculateurCotisations()
    return calc.simuler_guso(
        salaire_brut=Decimal(str(salaire_brut)),
        nb_heures=Decimal(str(nb_heures)),
    )


@app.get("/api/simulation/impot-independant")
async def sim_ir(
    benefice: float = Query(40000),
    nb_parts: float = Query(1),
    autres_revenus: float = Query(0),
):
    from urssaf_analyzer.contribution_rules import CalculateurCotisations
    calc = CalculateurCotisations()
    return calc.simuler_impot_independant(
        benefice=Decimal(str(benefice)),
        nb_parts=Decimal(str(nb_parts)),
        autres_revenus=Decimal(str(autres_revenus)),
    )


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
    return pm.rechercher(q)


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
    return pm.get_declarations(
        entreprise_id=entreprise_id, profil_id=profil_id, limit=limit,
    )


# ==============================
# DOCUMENTS / BIBLIOTHEQUE
# ==============================

@app.get("/api/documents/bibliotheque")
async def bibliotheque():
    return _doc_library


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
    add("S10.G00.00.004", "NormaCheck v3.4")
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
NormaCheck v3.4.0 &mdash; Conformite sociale et fiscale &copy; 2026<br>
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
<footer>NormaCheck v3.4.0 &copy; 2026 - <a href="/" style="color:#60a5fa">Retour</a></footer>
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
<footer>NormaCheck v3.4.0 &copy; 2026 - <a href="/" style="color:#60a5fa">Retour</a></footer>
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
<footer>NormaCheck v3.4.0 &copy; 2026 - <a href="/" style="color:#60a5fa">Retour</a></footer>
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
<div class="logo"><em>NormaCheck</em> <span>v3.4</span></div>
<div class="nav-group">Analyse</div>
<div class="nl active" onclick="showS('dashboard',this)"><span class="ico">&#9632;</span><span>Dashboard</span></div>
<div class="nl" onclick="showS('analyse',this)"><span class="ico">&#128269;</span><span>Import / Analyse</span></div>
<div class="nl" onclick="showS('biblio',this)"><span class="ico">&#128218;</span><span>Bibliotheque</span></div>
<div class="nav-group">Gestion</div>
<div class="nl" onclick="showS('compta',this)"><span class="ico">&#128203;</span><span>Comptabilite</span></div>
<div class="nl" onclick="showS('factures',this)"><span class="ico">&#128206;</span><span>Factures</span></div>
<div class="nl" onclick="showS('dsn',this)"><span class="ico">&#128196;</span><span>Creation DSN</span></div>
<div class="nl" onclick="showS('simulation',this)"><span class="ico">&#128200;</span><span>Simulation</span></div>
<div class="nav-group">Outils</div>
<div class="nl" onclick="showS('veille',this)"><span class="ico">&#9878;</span><span>Veille juridique</span></div>
<div class="nl" onclick="showS('portefeuille',this)"><span class="ico">&#128101;</span><span>Portefeuille</span></div>
<div class="nl" onclick="showS('equipe',this)"><span class="ico">&#128100;</span><span>Equipe</span></div>
<div class="spacer"></div>
<div class="logout" onclick="window.location.href='/'"><span class="ico">&#10132;</span><span>Deconnexion</span></div>
</div>
<div class="content">
<div class="topbar"><button class="mob-menu" id="mob-menu" onclick="toggleSidebar()">&#9776;</button><h1 id="page-title">Dashboard</h1><div class="info">NormaCheck v3.4.0 &bull; <span id="topbar-date"></span> &bull; <a href="/legal/mentions" style="color:var(--tx2);font-size:.9em">Mentions legales</a></div></div>
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
<div class="uz" id="dz-analyse">
<input type="file" id="fi-analyse" multiple accept=".pdf,.csv,.xlsx,.xls,.xml,.dsn,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.gif,.webp,.txt">
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
<div class="btn-group"><button class="btn btn-s btn-sm" onclick="exportSection('az')">&#128190; Exporter</button><button class="btn btn-s btn-sm" onclick="resetAz()">&#10227; Nouvelle</button></div>
</div>
<div class="g4" id="az-dashboard"></div>
</div>
<div class="card"><h2>Anomalies</h2><div id="az-findings"></div></div>
<div class="card"><h2>Recommandations</h2><div id="az-reco"></div></div>
<div class="card" id="az-html-card" style="display:none"><h2>Rapport</h2><iframe id="az-html-frame" style="width:100%;height:600px;border:1px solid var(--brd);border-radius:10px"></iframe></div>
</div>
</div>

<!-- ===== BIBLIOTHEQUE ===== -->
<div class="sec" id="s-biblio">
<div class="card">
<h2>Bibliotheque de documents</h2>
<p style="color:var(--tx2);font-size:.86em;margin-bottom:14px">Documents importes avec historique des actions et possibilite de corriger les erreurs d'analyse.</p>
<div class="btn-group"><button class="btn btn-blue btn-sm" onclick="loadBiblio()">&#8635; Actualiser</button><button class="btn btn-s btn-sm" onclick="exportSection('biblio')">&#128190; Exporter</button></div>
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
<div><label>Compte debit</label><input id="em-deb" placeholder="601000"><label>Compte credit</label><input id="em-cre" placeholder="401000"></div>
</div>
<div class="g3">
<div><label>Montant</label><input type="number" step="0.01" id="em-mt" placeholder="0.00"></div>
<div><label>Justificatif</label><select id="em-just"><option value="false">Non</option><option value="true">Oui</option></select></div>
<div><button class="btn btn-p btn-f" onclick="saisirEcriture()" style="margin-top:22px">Enregistrer</button></div>
</div>
<div id="em-res" style="margin-top:10px"></div>
</div>
<div class="tc" id="ct-plan"><div id="ct-plan-c"></div></div>
</div>
</div>

<!-- ===== SIMULATION ===== -->
<div class="sec" id="s-simulation">
<div class="tabs">
<div class="tab active" onclick="showSimTab('bulletin',this)">Bulletin</div>
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

</div><!-- end .page -->
</div><!-- end .content -->
</div><!-- end .layout -->
"""


APP_HTML += """
<script>
/* === INIT === */
var titles={"dashboard":"Dashboard","analyse":"Import / Analyse","biblio":"Bibliotheque","factures":"Factures","dsn":"Creation DSN","compta":"Comptabilite","simulation":"Simulation","veille":"Veille juridique","portefeuille":"Portefeuille","equipe":"Equipe"};
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
if(n==="biblio")loadBiblio();if(n==="equipe")loadEquipe();
if(n==="factures")loadPayStatuses();if(n==="dsn"){preFillDSN();loadDSNBrouillons();}
}

document.addEventListener("click",function(e){var a=e.target.closest(".anomalie[data-toggle]");if(a)a.classList.toggle("open");});

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
fetch("/api/analyze?format_rapport=json&integrer="+integ,{method:"POST",body:fd}).then(function(resp){
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
document.getElementById("dash-docs").textContent=(s.nb_fichiers||0);loadDash();}
function resetAz(){fichiers=[];renderF();document.getElementById("res-analyse").style.display="none";}

/* === BIBLIOTHEQUE === */
function loadBiblio(){
fetch("/api/documents/bibliotheque").then(function(r){return r.json();}).then(function(docs){
var el=document.getElementById("biblio-list");
if(!docs.length){el.innerHTML="<p style='color:var(--tx2)'>Aucun document. Importez des fichiers via l'onglet Analyse.</p>";return;}
var h="";for(var i=0;i<docs.length;i++){var d=docs[i];
h+="<div class='doc-item'><div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:6px'>";
h+="<div><strong>"+d.nom+"</strong> <span class='badge badge-blue'>"+d.statut+"</span></div>";
h+="<span style='font-size:.8em;color:var(--tx2)'>"+d.date_import.substring(0,10)+" | "+(d.taille/1024).toFixed(1)+" Ko</span></div>";
var acts=d.actions||[];if(acts.length){h+="<div style='margin-top:8px;font-size:.82em'><strong>Historique :</strong>";
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
fetch("/api/factures/statuts").then(function(r){return r.json();}).then(function(list){
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
fetch("/api/dsn/brouillons").then(function(r){return r.json();}).then(function(list){
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

fetch("/api/comptabilite/journal").then(function(r){return r.json();}).then(function(j){
var h="";if(!j.length)h="<p style='color:var(--tx2)'>Aucune ecriture.</p>";
for(var i=0;i<j.length;i++){var e=j[i];
h+="<div style='border:1px solid var(--brd);border-radius:10px;padding:12px;margin:6px 0'>";
h+="<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:4px'><strong>"+e.date+" | "+e.journal+" | "+e.piece+"</strong><span class='badge "+(e.validee?"badge-green":"badge-amber")+"'>"+(e.validee?"Validee":"Brouillon")+"</span></div>";
h+="<div style='color:var(--tx2);font-size:.86em;margin-bottom:6px'>"+e.libelle+"</div>";
h+="<table><tr><th>Compte</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th></tr>";
for(var k=0;k<e.lignes.length;k++){var l=e.lignes[k];var sj=l.libelle.indexOf("[SANS JUSTIFICATIF]")>=0;h+="<tr"+(sj?" class='sans-just'":"")+"><td>"+l.compte+"</td><td>"+l.libelle+(sj?" <span class='badge badge-red'>Sans justif.</span>":"")+"</td><td class='num'>"+l.debit.toFixed(2)+"</td><td class='num'>"+l.credit.toFixed(2)+"</td></tr>";}
h+="</table></div>";}document.getElementById("ct-journal-c").innerHTML=h;}).catch(function(){});

fetch("/api/comptabilite/balance").then(function(r){return r.json();}).then(function(b){
var h="";if(!b.length)h="<p style='color:var(--tx2)'>Aucune donnee.</p>";
else{h="<table><tr><th>Compte</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th><th class='num'>Solde D</th><th class='num'>Solde C</th></tr>";
for(var i=0;i<b.length;i++){var r2=b[i];h+="<tr><td>"+r2.compte+"</td><td>"+r2.libelle+"</td><td class='num'>"+r2.total_debit.toFixed(2)+"</td><td class='num'>"+r2.total_credit.toFixed(2)+"</td><td class='num'>"+r2.solde_debiteur.toFixed(2)+"</td><td class='num'>"+r2.solde_crediteur.toFixed(2)+"</td></tr>";}h+="</table>";}
document.getElementById("ct-balance-c").innerHTML=h;}).catch(function(){});

var glUrl="/api/comptabilite/grand-livre-detail";if(dd)glUrl+="?date_debut="+dd+(df?"&date_fin="+df:"");
fetch(glUrl).then(function(r){return r.json();}).then(function(gl){
var h="";if(!gl.length)h="<p style='color:var(--tx2)'>Aucune donnee.</p>";
for(var i=0;i<gl.length;i++){var c=gl[i];h+="<div style='border:1px solid var(--brd);border-radius:10px;padding:12px;margin:6px 0'><strong>"+c.compte+" - "+(c.libelle||"")+"</strong>";
var mvts=c.mouvements||[];if(mvts.length){h+="<table style='margin-top:6px'><tr><th>Date</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th></tr>";
for(var k=0;k<mvts.length;k++){var m=mvts[k];var sj=m.sans_justificatif;h+="<tr"+(sj?" class='sans-just'":"")+"><td>"+(m.date||"")+"</td><td>"+(m.libelle||"")+(sj?" <span class='badge badge-red'>Sans justif.</span>":"")+"</td><td class='num'>"+(m.debit||0).toFixed(2)+"</td><td class='num'>"+(m.credit||0).toFixed(2)+"</td></tr>";}
h+="</table>";}h+="</div>";}document.getElementById("ct-grandlivre-c").innerHTML=h;}).catch(function(){});

fetch("/api/comptabilite/compte-resultat").then(function(r){return r.json();}).then(function(cr){
var clr=cr.resultat_net>=0?"var(--g)":"var(--r)";var bg=cr.resultat_net>=0?"var(--gl)":"var(--rl)";
var h="<div class='g2'><div class='card' style='text-align:center'><h2>Charges</h2><div style='font-size:1.4em;font-weight:800;color:var(--r)'>"+cr.charges.total.toFixed(2)+" EUR</div></div>";
h+="<div class='card' style='text-align:center'><h2>Produits</h2><div style='font-size:1.4em;font-weight:800;color:var(--g)'>"+cr.produits.total.toFixed(2)+" EUR</div></div></div>";
h+="<div class='sc' style='margin-top:14px;background:"+bg+"'><div class='val' style='color:"+clr+"'>"+cr.resultat_net.toFixed(2)+" EUR</div><div class='lab'>Resultat net</div></div>";
document.getElementById("ct-resultat-c").innerHTML=h;}).catch(function(){});

fetch("/api/comptabilite/bilan").then(function(r){return r.json();}).then(function(bi){
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

(function(){var now=new Date();fetch("/api/comptabilite/declaration-tva?mois="+(now.getMonth()+1)+"&annee="+now.getFullYear()).then(function(r){return r.json();}).then(function(t){
var h="<div class='g3'><div class='sc'><div class='val'>"+t.chiffre_affaires_ht.toFixed(2)+"</div><div class='lab'>CA HT</div></div><div class='sc'><div class='val'>"+t.tva_collectee.toFixed(2)+"</div><div class='lab'>TVA collectee</div></div><div class='sc'><div class='val'>"+t.tva_deductible_totale.toFixed(2)+"</div><div class='lab'>TVA deductible</div></div></div>";
var net=t.tva_nette_a_payer>0?t.tva_nette_a_payer.toFixed(2)+" EUR a payer":t.credit_tva.toFixed(2)+" EUR credit";
h+="<div class='sc' style='margin-top:12px'><div class='val'>"+net+"</div><div class='lab'>TVA nette</div></div>";
document.getElementById("ct-tva-c").innerHTML=h;}).catch(function(){});})();

fetch("/api/comptabilite/charges-sociales-detail").then(function(r){return r.json();}).then(function(soc){
var h="<div class='g4'>";var ds=soc.destinataires||[];var cls=["blue","amber","green","purple"];
for(var i=0;i<ds.length;i++){var d=ds[i];h+="<div class='sc "+cls[i%4]+"'><div class='val'>"+(d.montant||0).toFixed(2)+"</div><div class='lab'>"+d.nom+"</div><div style='font-size:.7em;color:var(--tx2);margin-top:3px'>"+d.postes.join(", ")+"</div></div>";}h+="</div>";
h+="<div class='g3' style='margin-top:12px'><div class='sc'><div class='val'>"+(soc.brut||0).toFixed(2)+"</div><div class='lab'>Bruts</div></div>";
h+="<div class='sc amber'><div class='val'>"+(soc.total||0).toFixed(2)+"</div><div class='lab'>Total charges</div></div>";
h+="<div class='sc blue'><div class='val'>"+(soc.cout_employeur||0).toFixed(2)+"</div><div class='lab'>Cout employeur</div></div></div>";
document.getElementById("ct-social-c").innerHTML=h;}).catch(function(){});

fetch("/api/comptabilite/plan-comptable").then(function(r){return r.json();}).then(function(pc){
var h="<input placeholder='Rechercher...' oninput='rechPC(this.value)' style='margin-bottom:10px'><table id='pc-t'><tr><th>N</th><th>Libelle</th><th>Classe</th></tr>";
for(var i=0;i<pc.length;i++){h+="<tr><td>"+pc[i].numero+"</td><td>"+pc[i].libelle+"</td><td>"+pc[i].classe+"</td></tr>";}h+="</table>";
document.getElementById("ct-plan-c").innerHTML=h;}).catch(function(){});
}

function rechPC(t){fetch(t?"/api/comptabilite/plan-comptable?terme="+encodeURIComponent(t):"/api/comptabilite/plan-comptable").then(function(r){return r.json();}).then(function(pc){var tb=document.getElementById("pc-t");if(!tb)return;var h="<tr><th>N</th><th>Libelle</th><th>Classe</th></tr>";for(var i=0;i<pc.length;i++){h+="<tr><td>"+pc[i].numero+"</td><td>"+pc[i].libelle+"</td><td>"+pc[i].classe+"</td></tr>";}tb.innerHTML=h;}).catch(function(){});}
function validerEcr(){fetch("/api/comptabilite/valider",{method:"POST"}).then(function(r){return r.json();}).then(function(d){toast("Validees: "+d.nb_validees+(d.erreurs.length?" | Erreurs: "+d.erreurs.join(", "):""),"ok");loadCompta();}).catch(function(e){toast(e.message);});}
function saisirEcriture(){
var fd=new FormData();fd.append("date_piece",document.getElementById("em-date").value);fd.append("libelle",document.getElementById("em-lib").value);fd.append("compte_debit",document.getElementById("em-deb").value);fd.append("compte_credit",document.getElementById("em-cre").value);fd.append("montant",document.getElementById("em-mt").value||"0");fd.append("has_justificatif",document.getElementById("em-just").value);
fetch("/api/comptabilite/ecriture/manuelle",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){
document.getElementById("em-res").innerHTML="<div class='al "+(d.sans_justificatif?"err":"ok")+"'><span class='ai'>"+(d.sans_justificatif?"&#9888;":"&#9989;")+"</span><span>"+(d.alerte||"Enregistree.")+"</span></div>";loadCompta();}).catch(function(e){document.getElementById("em-res").innerHTML="<div class='al err'>"+e.message+"</div>";});}

/* === SIMULATION === */
function showSimTab(n,el){document.querySelectorAll("#s-simulation .tab").forEach(function(t){t.classList.remove("active")});document.querySelectorAll("#s-simulation .tc").forEach(function(t){t.classList.remove("active")});if(el)el.classList.add("active");var tc=document.getElementById("sim-"+n);if(tc)tc.classList.add("active");}
function simBulletin(){fetch("/api/simulation/bulletin?brut_mensuel="+document.getElementById("sim-brut").value+"&effectif="+document.getElementById("sim-eff").value+"&est_cadre="+document.getElementById("sim-cadre").value).then(function(r){return r.json();}).then(function(r){var h="<div class='g3'><div class='sc blue'><div class='val'>"+r.brut_mensuel.toFixed(2)+"</div><div class='lab'>Brut</div></div><div class='sc green'><div class='val'>"+r.net_a_payer.toFixed(2)+"</div><div class='lab'>Net</div></div><div class='sc amber'><div class='val'>"+r.cout_total_employeur.toFixed(2)+"</div><div class='lab'>Cout employeur</div></div></div><table style='margin-top:12px'><tr><th>Rubrique</th><th class='num'>Patronal</th><th class='num'>Salarial</th></tr>";var ls=r.lignes||[];for(var i=0;i<ls.length;i++){h+="<tr><td>"+ls[i].libelle+"</td><td class='num'>"+ls[i].montant_patronal.toFixed(2)+"</td><td class='num'>"+ls[i].montant_salarial.toFixed(2)+"</td></tr>";}h+="</table>";document.getElementById("sim-bull-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simMicro(){fetch("/api/simulation/micro-entrepreneur?chiffre_affaires="+document.getElementById("sim-ca").value+"&activite="+document.getElementById("sim-act").value+"&acre="+document.getElementById("sim-acre").value).then(function(r){return r.json();}).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-micro-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simTNS(){fetch("/api/simulation/tns?revenu_net="+document.getElementById("sim-rev").value+"&type_statut="+document.getElementById("sim-stat").value+"&acre="+document.getElementById("sim-tacre").value).then(function(r){return r.json();}).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-tns-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simGUSO(){fetch("/api/simulation/guso?salaire_brut="+document.getElementById("sim-gbrut").value+"&nb_heures="+document.getElementById("sim-gh").value).then(function(r){return r.json();}).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-guso-res").innerHTML=h;}).catch(function(e){toast(e.message);});}
function simIR(){fetch("/api/simulation/impot-independant?benefice="+document.getElementById("sim-ben").value+"&nb_parts="+document.getElementById("sim-parts").value+"&autres_revenus="+document.getElementById("sim-autres").value).then(function(r){return r.json();}).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-ir-res").innerHTML=h;}).catch(function(e){toast(e.message);});}

/* === VEILLE === */
function loadVeille(){var a=document.getElementById("v-annee").value;document.getElementById("v-res").style.display="block";
fetch("/api/veille/baremes/"+a).then(function(r){return r.json();}).then(function(b){var h="<table><tr><th>Parametre</th><th class='num'>Valeur</th></tr>";for(var k in b){h+="<tr><td>"+k.replace(/_/g," ")+"</td><td class='num'>"+b[k]+"</td></tr>";}h+="</table>";document.getElementById("v-baremes").innerHTML=h;}).catch(function(){});
fetch("/api/veille/legislation/"+a).then(function(r){return r.json();}).then(function(l){var h="<p style='margin-bottom:10px'><strong>"+l.description+"</strong></p>";var tx=l.textes_cles||[];for(var i=0;i<tx.length;i++){h+="<div class='al info' style='margin:4px 0'><span class='ai'>&#9878;</span><span><strong>"+tx[i].reference+"</strong> - "+tx[i].titre+"<br><small>"+tx[i].resume+"</small></span></div>";}document.getElementById("v-legis").innerHTML=h;}).catch(function(){});}
function compAnnees(){var a2=parseInt(document.getElementById("v-annee").value),a1=a2-1;fetch("/api/veille/baremes/comparer/"+a1+"/"+a2).then(function(r){return r.json();}).then(function(d){if(!d.length){toast("Pas de differences.","info");return;}var h="<table><tr><th>Parametre</th><th class='num'>"+a1+"</th><th class='num'>"+a2+"</th><th>Evolution</th></tr>";for(var i=0;i<d.length;i++){h+="<tr><td>"+d[i].parametre+"</td><td class='num'>"+(d[i]["valeur_"+a1]||"-")+"</td><td class='num'>"+(d[i]["valeur_"+a2]||"-")+"</td><td>"+d[i].evolution+"</td></tr>";}h+="</table>";document.getElementById("v-comp").innerHTML=h;document.getElementById("v-comp-card").style.display="block";}).catch(function(e){toast(e.message);});}

/* === PORTEFEUILLE === */
function ajouterEnt(){var fd=new FormData();fd.append("siret",document.getElementById("ent-siret").value);fd.append("raison_sociale",document.getElementById("ent-raison").value);fd.append("forme_juridique",document.getElementById("ent-forme").value);fd.append("code_naf",document.getElementById("ent-naf").value);fd.append("effectif",document.getElementById("ent-eff").value||"0");fd.append("ville",document.getElementById("ent-ville").value);
fetch("/api/entreprises",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(){toast("Entreprise ajoutee !","ok");rechEnt();}).catch(function(e){toast(e.message);});}

function rechEnt(){var q=(document.getElementById("ent-search")||{}).value||"";
fetch("/api/entreprises?q="+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(d){
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
fetch("/api/collaboration/equipe").then(function(r){return r.json();}).then(function(data){
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
