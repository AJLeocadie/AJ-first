"""URSSAF Analyzer - API FastAPI pour Vercel.

Point d'entree web : upload de documents, analyse automatisee,
gestion portefeuille, veille juridique, comptabilite.
"""

import io
import json
import tempfile
import time
import shutil
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
    title="URSSAF Analyzer",
    description="Analyse securisee de documents sociaux et fiscaux URSSAF",
    version="2.0.0",
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


# ==============================
# PAGE D'ACCUEIL
# ==============================

@app.get("/", response_class=HTMLResponse)
async def accueil():
    return FRONTEND_HTML


# ==============================
# API ANALYSE DOCUMENTS
# ==============================

@app.post("/api/analyze")
async def analyser(
    fichiers: list[UploadFile] = File(...),
    format_rapport: str = "json",
):
    """Analyse les documents uploades et retourne le rapport."""
    if not fichiers:
        raise HTTPException(400, "Aucun fichier fourni.")

    for f in fichiers:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                400,
                f"Format non supporte : '{ext}' pour '{f.filename}'. "
                f"Acceptes : {', '.join(SUPPORTED_EXTENSIONS.keys())}",
            )

    with tempfile.TemporaryDirectory(prefix="urssaf_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        chemins = []
        for f in fichiers:
            chemin = tmp_path / f.filename
            contenu = await f.read()
            chemin.write_bytes(contenu)
            chemins.append(chemin)

        config = AppConfig(
            base_dir=tmp_path, data_dir=tmp_path / "data",
            reports_dir=tmp_path / "reports", temp_dir=tmp_path / "temp",
            audit_log_path=tmp_path / "audit.log",
        )
        orchestrator = Orchestrator(config)

        try:
            chemin_rapport = orchestrator.analyser_documents(chemins, format_rapport=format_rapport)
            if format_rapport == "html":
                return HTMLResponse(content=chemin_rapport.read_text(encoding="utf-8"))
            return JSONResponse(content=json.loads(chemin_rapport.read_text(encoding="utf-8")))
        except URSSAFAnalyzerError as e:
            raise HTTPException(422, str(e))
        except Exception as e:
            raise HTTPException(500, f"Erreur interne : {str(e)}")


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "formats_supportes": list(SUPPORTED_EXTENSIONS.keys())}


@app.get("/api/formats")
async def formats():
    return {"formats": [{"extension": ext, "type": typ} for ext, typ in SUPPORTED_EXTENSIONS.items()]}


# ==============================
# API VEILLE JURIDIQUE
# ==============================

@app.get("/api/veille/baremes/{annee}")
async def baremes_annee(annee: int):
    """Retourne les baremes URSSAF pour une annee."""
    return get_baremes_annee(annee)


@app.get("/api/veille/baremes/comparer/{annee1}/{annee2}")
async def comparer_baremes_api(annee1: int, annee2: int):
    """Compare les baremes entre deux annees."""
    return comparer_baremes(annee1, annee2)


@app.get("/api/veille/legislation/{annee}")
async def legislation_annee(annee: int):
    """Retourne la legislation applicable pour une annee."""
    return get_legislation_par_annee(annee)


@app.get("/api/veille/annees-disponibles")
async def annees_disponibles():
    """Liste les annees disponibles pour la veille."""
    return {
        "baremes": sorted(BAREMES_PAR_ANNEE.keys()),
        "legislation": sorted(ARTICLES_CSS_COTISATIONS.keys()),
    }


@app.get("/api/veille/alertes")
async def alertes_recentes(limit: int = Query(50, ge=1, le=200)):
    """Recupere les alertes de veille recentes."""
    db = get_db()
    vm = VeilleManager(db)
    return vm.get_alertes_recentes(limit=limit)


@app.post("/api/veille/executer")
async def executer_veille(annee: int = Form(...), mois: int = Form(...)):
    """Execute une veille mensuelle."""
    db = get_db()
    vm = VeilleManager(db)
    return vm.executer_veille_mensuelle(annee, mois)


# ==============================
# API PORTEFEUILLE
# ==============================

@app.post("/api/profils")
async def creer_profil(
    nom: str = Form(...), prenom: str = Form(...),
    email: str = Form(...), mot_de_passe: str = Form(...),
    role: str = Form("analyste"),
):
    """Cree un nouveau profil."""
    db = get_db()
    pm = PortfolioManager(db)
    try:
        return pm.creer_profil(nom, prenom, email, mot_de_passe, role)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/profils/auth")
async def authentifier(email: str = Form(...), mot_de_passe: str = Form(...)):
    """Authentifie un utilisateur."""
    db = get_db()
    pm = PortfolioManager(db)
    profil = pm.authentifier(email, mot_de_passe)
    if not profil:
        raise HTTPException(401, "Email ou mot de passe incorrect.")
    return profil


@app.get("/api/profils")
async def lister_profils():
    db = get_db()
    return PortfolioManager(db).lister_profils()


@app.post("/api/entreprises")
async def ajouter_entreprise(
    siret: str = Form(...), raison_sociale: str = Form(...),
    forme_juridique: str = Form(""), code_naf: str = Form(""),
    effectif: int = Form(0), ville: str = Form(""),
):
    """Ajoute une entreprise."""
    db = get_db()
    pm = PortfolioManager(db)
    return pm.ajouter_entreprise(
        siret, raison_sociale, forme_juridique=forme_juridique,
        code_naf=code_naf, effectif=effectif, ville=ville,
    )


@app.get("/api/entreprises")
async def lister_entreprises(q: str = Query("", max_length=100)):
    db = get_db()
    pm = PortfolioManager(db)
    if q:
        return pm.rechercher_entreprises(q)
    return pm.lister_entreprises()


@app.get("/api/entreprises/{entreprise_id}")
async def get_entreprise(entreprise_id: str):
    db = get_db()
    ent = PortfolioManager(db).get_entreprise(entreprise_id)
    if not ent:
        raise HTTPException(404, "Entreprise non trouvee.")
    return ent


@app.get("/api/entreprises/{entreprise_id}/dashboard")
async def dashboard_entreprise(entreprise_id: str):
    db = get_db()
    return PortfolioManager(db).get_dashboard_entreprise(entreprise_id)


@app.get("/api/portefeuille/{profil_id}")
async def get_portefeuille(profil_id: str):
    db = get_db()
    return PortfolioManager(db).get_portefeuille(profil_id)


@app.get("/api/analyses/historique")
async def historique_analyses(
    entreprise_id: str = Query(None), profil_id: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    db = get_db()
    return PortfolioManager(db).get_historique_analyses(
        entreprise_id=entreprise_id, profil_id=profil_id, limit=limit,
    )


# ==============================
# API COMPTABILITE
# ==============================

@app.get("/api/comptabilite/plan-comptable")
async def plan_comptable_api(terme: str = Query("", max_length=100)):
    """Recherche dans le plan comptable."""
    plan = get_moteur().plan
    if terme:
        comptes = plan.rechercher(terme)
    else:
        comptes = list(plan.comptes.values())
    return [{"numero": c.numero, "libelle": c.libelle, "classe": c.classe.value} for c in comptes[:100]]


@app.post("/api/comptabilite/ecriture/facture")
async def ecriture_facture(
    type_doc: str = Form(...),
    date_piece: str = Form(...),
    numero_piece: str = Form(""),
    montant_ht: float = Form(...),
    montant_tva: float = Form(0),
    montant_ttc: float = Form(0),
    nom_tiers: str = Form(""),
    libelle: str = Form(""),
):
    """Genere une ecriture comptable pour une facture."""
    moteur = get_moteur()
    try:
        d = date.fromisoformat(date_piece)
    except ValueError:
        raise HTTPException(400, "Date invalide (format YYYY-MM-DD).")

    e = moteur.generer_ecriture_facture(
        type_doc=type_doc, date_piece=d, numero_piece=numero_piece,
        montant_ht=Decimal(str(montant_ht)),
        montant_tva=Decimal(str(montant_tva)),
        montant_ttc=Decimal(str(montant_ttc)),
        nom_tiers=nom_tiers, libelle=libelle,
    )
    return {
        "id": e.id, "journal": e.journal.value, "libelle": e.libelle,
        "equilibree": e.est_equilibree,
        "lignes": [{"compte": l.compte, "libelle": l.libelle,
                     "debit": float(l.debit), "credit": float(l.credit)} for l in e.lignes],
    }


@app.post("/api/comptabilite/valider")
async def valider_ecritures():
    """Valide toutes les ecritures en brouillon."""
    moteur = get_moteur()
    erreurs = moteur.valider_ecritures()
    nb_validees = sum(1 for e in moteur.ecritures if e.validee)
    return {"nb_validees": nb_validees, "erreurs": erreurs}


@app.get("/api/comptabilite/journal")
async def journal_api(type_journal: str = Query(None)):
    moteur = get_moteur()
    tj = TypeJournal(type_journal) if type_journal else None
    return moteur.get_journal(tj)


@app.get("/api/comptabilite/balance")
async def balance_api():
    return get_moteur().get_balance()


@app.get("/api/comptabilite/grand-livre")
async def grand_livre_api():
    return get_moteur().get_grand_livre()


@app.get("/api/comptabilite/compte-resultat")
async def compte_resultat_api():
    return GenerateurRapports(get_moteur()).compte_resultat()


@app.get("/api/comptabilite/declaration-tva")
async def declaration_tva_api(mois: int = Query(...), annee: int = Query(...)):
    return GenerateurRapports(get_moteur()).declaration_tva(mois, annee)


@app.get("/api/comptabilite/charges-sociales")
async def charges_sociales_api():
    return GenerateurRapports(get_moteur()).recapitulatif_charges_sociales()


@app.get("/api/comptabilite/rapports/balance", response_class=HTMLResponse)
async def rapport_balance():
    return GenerateurRapports(get_moteur()).balance_html()


@app.get("/api/comptabilite/rapports/grand-livre", response_class=HTMLResponse)
async def rapport_grand_livre():
    return GenerateurRapports(get_moteur()).grand_livre_html()


@app.get("/api/comptabilite/rapports/journal", response_class=HTMLResponse)
async def rapport_journal():
    return GenerateurRapports(get_moteur()).journal_html()


@app.get("/api/comptabilite/rapports/compte-resultat", response_class=HTMLResponse)
async def rapport_compte_resultat():
    return GenerateurRapports(get_moteur()).compte_resultat_html()


@app.get("/api/comptabilite/rapports/charges-sociales", response_class=HTMLResponse)
async def rapport_charges_sociales():
    return GenerateurRapports(get_moteur()).recapitulatif_social_html()


# ==============================
# API SIMULATION PAIE / COTISATIONS
# ==============================

@app.get("/api/simulation/bulletin")
async def simulation_bulletin(
    brut_mensuel: float = Query(...),
    effectif: int = Query(10),
    est_cadre: bool = Query(False),
    taux_at: float = Query(0.0208),
    taux_vm: float = Query(0),
):
    """Simule un bulletin de paie complet avec toutes les cotisations."""
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    rules = ContributionRules(
        effectif_entreprise=effectif,
        taux_at=Decimal(str(taux_at)),
        taux_versement_mobilite=Decimal(str(taux_vm)),
    )
    bulletin = rules.calculer_bulletin_complet(Decimal(str(brut_mensuel)), est_cadre)
    # Convert Decimal in lignes
    for l in bulletin["lignes"]:
        l["montant_patronal"] = float(l["montant_patronal"])
        l["montant_salarial"] = float(l["montant_salarial"])
    return bulletin


@app.get("/api/simulation/rgdu")
async def simulation_rgdu(
    brut_annuel: float = Query(...),
    effectif: int = Query(10),
):
    """Simule le calcul de la RGDU (Reduction Generale Degressive Unique)."""
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    rules = ContributionRules(effectif_entreprise=effectif)
    return rules.detail_rgdu(Decimal(str(brut_annuel)))


@app.get("/api/simulation/net-imposable")
async def simulation_net_imposable(
    brut_mensuel: float = Query(...),
    effectif: int = Query(10),
    est_cadre: bool = Query(False),
):
    """Calcule le net imposable (assiette fiscale PAS)."""
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    rules = ContributionRules(effectif_entreprise=effectif)
    result = rules.calculer_net_imposable(Decimal(str(brut_mensuel)), est_cadre)
    # Ensure all values are float
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in result.items()}


@app.get("/api/simulation/taxe-salaires")
async def simulation_taxe_salaires(brut_annuel: float = Query(...)):
    """Simule la taxe sur les salaires (employeurs non assujettis TVA)."""
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    rules = ContributionRules()
    return rules.calculer_taxe_salaires(Decimal(str(brut_annuel)))


# ==============================
# API FACTURES / OCR
# ==============================

@app.post("/api/factures/analyser")
async def analyser_facture(fichier: UploadFile = File(...)):
    """Analyse une facture et retourne les champs detectes."""
    ext = Path(fichier.filename or "").suffix.lower()
    if ext not in (".pdf", ".csv", ".txt", ".jpg", ".jpeg", ".png"):
        raise HTTPException(400, f"Format non supporte pour les factures : {ext}")

    with tempfile.TemporaryDirectory(prefix="facture_") as tmp_dir:
        chemin = Path(tmp_dir) / fichier.filename
        chemin.write_bytes(await fichier.read())

        try:
            from urssaf_analyzer.ocr.invoice_detector import InvoiceDetector
            detector = InvoiceDetector()

            if ext == ".pdf":
                piece = detector.analyser_pdf(chemin)
            elif ext == ".csv":
                pieces = detector.analyser_csv_bancaire(chemin)
                return {"nb_pieces": len(pieces), "pieces": [_piece_to_dict(p) for p in pieces[:50]]}
            else:
                texte = chemin.read_text(encoding="utf-8", errors="replace")
                piece = detector.analyser_document(texte, fichier.filename)

            return _piece_to_dict(piece)
        except Exception as e:
            raise HTTPException(500, f"Erreur analyse facture : {str(e)}")


@app.post("/api/factures/comptabiliser")
async def comptabiliser_facture(
    type_doc: str = Form(...),
    date_piece: str = Form(...),
    numero_piece: str = Form(""),
    montant_ht: float = Form(...),
    montant_tva: float = Form(0),
    montant_ttc: float = Form(0),
    nom_tiers: str = Form(""),
):
    """Analyse une facture et genere l'ecriture comptable correspondante."""
    moteur = get_moteur()
    try:
        d = date.fromisoformat(date_piece)
    except ValueError:
        raise HTTPException(400, "Date invalide.")

    ecriture = moteur.generer_ecriture_facture(
        type_doc=type_doc, date_piece=d, numero_piece=numero_piece,
        montant_ht=Decimal(str(montant_ht)),
        montant_tva=Decimal(str(montant_tva)),
        montant_ttc=Decimal(str(montant_ttc)),
        nom_tiers=nom_tiers,
    )
    return {
        "ecriture_id": ecriture.id,
        "journal": ecriture.journal.value,
        "equilibree": ecriture.est_equilibree,
        "lignes": [{"compte": l.compte, "libelle": l.libelle,
                     "debit": float(l.debit), "credit": float(l.credit)} for l in ecriture.lignes],
    }


def _piece_to_dict(piece) -> dict:
    return {
        "type_document": piece.type_document.value if hasattr(piece.type_document, 'value') else str(piece.type_document),
        "numero": piece.numero,
        "date_piece": piece.date_piece.isoformat() if piece.date_piece else None,
        "emetteur": {"nom": piece.emetteur.nom, "siret": piece.emetteur.siret, "tva_intra": piece.emetteur.tva_intra} if piece.emetteur else None,
        "destinataire": {"nom": piece.destinataire.nom, "siret": piece.destinataire.siret, "tva_intra": piece.destinataire.tva_intra} if piece.destinataire else None,
        "montant_ht": float(piece.montant_ht),
        "montant_tva": float(piece.montant_tva),
        "montant_ttc": float(piece.montant_ttc),
        "confiance": float(piece.confiance),
        "ecriture_manuscrite": piece.ecriture_manuscrite,
        "lignes": [{"description": l.description, "quantite": float(l.quantite),
                     "prix_unitaire": float(l.prix_unitaire), "montant_ht": float(l.montant_ht)}
                    for l in piece.lignes] if piece.lignes else [],
    }


# ==============================
# FRONTEND HTML
# ==============================

FRONTEND_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>URSSAF Analyzer - Plateforme Complete</title>
<style>
:root {
    --bleu: #003d7a;
    --bleu-clair: #e8f0fe;
    --bleu-hover: #00509e;
    --rouge: #d32f2f;
    --orange: #f57c00;
    --jaune: #fbc02d;
    --vert: #388e3c;
    --gris: #757575;
    --bg: #f5f7fa;
    --card-bg: #ffffff;
    --shadow: 0 4px 12px rgba(0,0,0,0.08);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: #333; }

/* Navigation */
nav { background: var(--bleu); color: white; padding: 0 20px; display: flex; align-items: center; position: sticky; top: 0; z-index: 100; }
nav .logo { font-size: 1.3em; font-weight: 700; padding: 15px 0; margin-right: 30px; }
nav .nav-links { display: flex; gap: 0; }
nav .nav-link {
    padding: 15px 18px; cursor: pointer; opacity: 0.7; transition: all 0.2s;
    border-bottom: 3px solid transparent; font-size: 0.9em;
}
nav .nav-link:hover, nav .nav-link.active { opacity: 1; border-bottom-color: white; background: rgba(255,255,255,0.1); }

/* Main */
.main { max-width: 1100px; margin: 20px auto; padding: 0 20px; }
.section { display: none; }
.section.active { display: block; }

/* Cards */
.card { background: var(--card-bg); border-radius: 12px; padding: 25px; box-shadow: var(--shadow); margin-bottom: 20px; }
.card h2 { color: var(--bleu); margin-bottom: 15px; font-size: 1.2em; }

/* Grid */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }
.grid-4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }

/* Upload */
.upload-zone {
    border: 3px dashed #c5d3e8; border-radius: 12px; padding: 40px; text-align: center;
    cursor: pointer; transition: all 0.3s; background: var(--bleu-clair); position: relative;
}
.upload-zone:hover { border-color: var(--bleu); background: #d6e4f7; }
.upload-zone input[type="file"] { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.upload-zone h3 { color: var(--bleu); margin: 10px 0 5px; }
.upload-zone p { color: var(--gris); font-size: 0.85em; }

/* Forms */
input, select, textarea {
    width: 100%; padding: 10px 12px; border: 2px solid #e0e0e0; border-radius: 8px;
    font-size: 0.95em; transition: border-color 0.2s; margin-bottom: 12px;
}
input:focus, select:focus { border-color: var(--bleu); outline: none; }
label { display: block; font-weight: 600; margin-bottom: 4px; font-size: 0.9em; color: #555; }

/* Buttons */
.btn {
    display: inline-flex; align-items: center; gap: 8px; padding: 10px 24px;
    border: none; border-radius: 8px; font-size: 0.95em; font-weight: 600;
    cursor: pointer; transition: all 0.2s;
}
.btn-primary { background: var(--bleu); color: white; }
.btn-primary:hover { background: var(--bleu-hover); }
.btn-primary:disabled { background: #a0b4cc; cursor: not-allowed; }
.btn-secondary { background: var(--bleu-clair); color: var(--bleu); }
.btn-full { width: 100%; justify-content: center; }

/* Stat cards */
.stat-card { background: var(--bleu-clair); border-radius: 8px; padding: 15px; text-align: center; }
.stat-card .value { font-size: 1.8em; font-weight: 700; }
.stat-card .label { font-size: 0.8em; color: var(--gris); margin-top: 4px; }

/* Table */
table { width: 100%; border-collapse: collapse; }
th { background: var(--bleu); color: white; padding: 10px 12px; text-align: left; font-size: 0.85em; }
td { padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 0.88em; }
tr:hover { background: var(--bleu-clair); }
.num { text-align: right; font-family: 'Consolas', monospace; }

/* Badges */
.badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.75em; font-weight: 700; color: white; }
.badge.critique { background: var(--rouge); }
.badge.haute { background: var(--orange); }
.badge.moyenne { background: var(--jaune); color: #333; }
.badge.faible { background: var(--vert); }
.badge.info { background: #1976d2; }

/* Format selector */
.format-selector { display: flex; gap: 10px; margin-bottom: 15px; }
.format-option {
    flex: 1; padding: 12px; border: 2px solid #e0e0e0; border-radius: 8px;
    text-align: center; cursor: pointer; background: white;
}
.format-option:hover { border-color: var(--bleu); }
.format-option.active { border-color: var(--bleu); background: var(--bleu-clair); }

/* File list */
.file-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--bleu-clair); border-radius: 6px; margin: 4px 0; font-size: 0.88em; }
.file-item .name { font-weight: 600; color: var(--bleu); }
.file-item .remove { background: none; border: none; color: var(--rouge); cursor: pointer; font-size: 1.2em; }

/* Progress */
.progress-container { display: none; margin: 15px 0; }
.progress-bar { height: 6px; background: #e0e0e0; border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: linear-gradient(90deg, var(--bleu), #005bb5); border-radius: 3px; width: 0%; transition: width 0.5s; }
.progress-text { text-align: center; margin-top: 8px; color: var(--gris); font-size: 0.85em; }

/* Alert */
.alert { padding: 12px 15px; border-radius: 8px; margin: 10px 0; }
.alert.info { background: #e3f2fd; color: #1565c0; }
.alert.success { background: #e8f5e9; color: #2e7d32; }
.alert.error { background: #fde8e8; color: var(--rouge); }

/* Tabs */
.tabs { display: flex; gap: 0; border-bottom: 2px solid #e0e0e0; margin-bottom: 20px; }
.tab { padding: 10px 20px; cursor: pointer; border-bottom: 3px solid transparent; color: var(--gris); font-weight: 600; font-size: 0.9em; }
.tab:hover { color: var(--bleu); }
.tab.active { color: var(--bleu); border-bottom-color: var(--bleu); }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Responsive */
@media (max-width: 768px) {
    .grid-2 { grid-template-columns: 1fr; }
    .grid-3 { grid-template-columns: 1fr; }
    nav .nav-links { overflow-x: auto; }
}
</style>
</head>
<body>

<nav>
    <div class="logo">URSSAF Analyzer</div>
    <div class="nav-links">
        <div class="nav-link active" onclick="showSection('analyse')">Analyse</div>
        <div class="nav-link" onclick="showSection('factures')">Factures</div>
        <div class="nav-link" onclick="showSection('comptabilite')">Comptabilite</div>
        <div class="nav-link" onclick="showSection('veille')">Veille juridique</div>
        <div class="nav-link" onclick="showSection('portefeuille')">Portefeuille</div>
    </div>
</nav>

<div class="main">

<!-- ======== SECTION ANALYSE ======== -->
<div class="section active" id="section-analyse">
    <div class="card">
        <h2>Importer vos documents</h2>
        <div class="upload-zone" id="dropzone-analyse">
            <input type="file" id="file-input-analyse" multiple accept=".pdf,.csv,.xlsx,.xls,.xml,.dsn">
            <div style="font-size:2.5em">&#128196;</div>
            <h3>Glissez vos fichiers ici</h3>
            <p>CSV, Excel, PDF, XML, DSN</p>
        </div>
        <div id="file-list-analyse" style="margin:10px 0"></div>
        <div class="alert error" id="error-analyse" style="display:none"></div>
        <h2 style="margin-top:20px">Format du rapport</h2>
        <div class="format-selector">
            <div class="format-option active" data-format="json" onclick="selectFormat(this)"><strong>JSON</strong><br><small>Structure</small></div>
            <div class="format-option" data-format="html" onclick="selectFormat(this)"><strong>HTML</strong><br><small>Visuel</small></div>
        </div>
        <button class="btn btn-primary btn-full" id="btn-analyze" onclick="lancerAnalyse()" disabled>Lancer l'analyse</button>
        <div class="progress-container" id="progress-analyse">
            <div class="progress-bar"><div class="progress-fill" id="progress-fill-analyse"></div></div>
            <div class="progress-text" id="progress-text-analyse">Import...</div>
        </div>
    </div>
    <div id="results-analyse" style="display:none">
        <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px">
                <h2>Resultats</h2>
                <button class="btn btn-secondary" onclick="resetAnalyse()">Nouvelle analyse</button>
            </div>
            <div class="grid-4" id="dashboard-analyse"></div>
        </div>
        <div class="card"><h2>Constats</h2><div id="findings-analyse"></div></div>
        <div class="card"><h2>Recommandations</h2><div id="reco-analyse"></div></div>
        <div class="card" id="html-report-card" style="display:none">
            <h2>Rapport HTML</h2>
            <iframe id="html-report-frame" style="width:100%;height:600px;border:1px solid #eee;border-radius:8px"></iframe>
        </div>
    </div>
</div>

<!-- ======== SECTION FACTURES ======== -->
<div class="section" id="section-factures">
    <div class="grid-2">
        <div class="card">
            <h2>Analyser une facture</h2>
            <div class="upload-zone" id="dropzone-facture">
                <input type="file" id="file-input-facture" accept=".pdf,.csv,.txt,.jpg,.jpeg,.png">
                <div style="font-size:2.5em">&#128206;</div>
                <h3>Deposer une facture</h3>
                <p>PDF, CSV, TXT, Image</p>
            </div>
            <div id="facture-filename" style="margin:10px 0"></div>
            <button class="btn btn-primary btn-full" id="btn-facture" onclick="analyserFacture()" disabled>Analyser la facture</button>
        </div>
        <div class="card">
            <h2>Saisie manuelle</h2>
            <label>Type de document</label>
            <select id="f-type">
                <option value="facture_achat">Facture d'achat</option>
                <option value="facture_vente">Facture de vente</option>
                <option value="avoir_achat">Avoir d'achat</option>
                <option value="avoir_vente">Avoir de vente</option>
            </select>
            <div class="grid-2">
                <div><label>Date</label><input type="date" id="f-date"></div>
                <div><label>N° piece</label><input id="f-numero" placeholder="FA-2026-001"></div>
            </div>
            <label>Tiers (client/fournisseur)</label>
            <input id="f-tiers" placeholder="Nom du tiers">
            <div class="grid-3">
                <div><label>Montant HT</label><input type="number" step="0.01" id="f-ht" placeholder="0.00"></div>
                <div><label>TVA</label><input type="number" step="0.01" id="f-tva" placeholder="0.00"></div>
                <div><label>TTC</label><input type="number" step="0.01" id="f-ttc" placeholder="0.00"></div>
            </div>
            <button class="btn btn-primary btn-full" onclick="comptabiliserFacture()">Comptabiliser</button>
        </div>
    </div>
    <div class="card" id="facture-result" style="display:none">
        <h2>Resultat de l'analyse</h2>
        <div id="facture-detail"></div>
    </div>
</div>

<!-- ======== SECTION COMPTABILITE ======== -->
<div class="section" id="section-comptabilite">
    <div class="tabs">
        <div class="tab active" onclick="showComptaTab('journal')">Journal</div>
        <div class="tab" onclick="showComptaTab('balance')">Balance</div>
        <div class="tab" onclick="showComptaTab('resultat')">Compte de resultat</div>
        <div class="tab" onclick="showComptaTab('tva')">Declaration TVA</div>
        <div class="tab" onclick="showComptaTab('social')">Charges sociales</div>
        <div class="tab" onclick="showComptaTab('plan')">Plan comptable</div>
    </div>
    <div class="card">
        <div style="display:flex;gap:10px;margin-bottom:15px">
            <button class="btn btn-primary" onclick="chargerComptaData()">Actualiser</button>
            <button class="btn btn-secondary" onclick="validerEcritures()">Valider ecritures</button>
        </div>
        <div class="tab-content active" id="compta-journal"><div id="compta-journal-content"></div></div>
        <div class="tab-content" id="compta-balance"><div id="compta-balance-content"></div></div>
        <div class="tab-content" id="compta-resultat"><div id="compta-resultat-content"></div></div>
        <div class="tab-content" id="compta-tva"><div id="compta-tva-content"></div></div>
        <div class="tab-content" id="compta-social"><div id="compta-social-content"></div></div>
        <div class="tab-content" id="compta-plan"><div id="compta-plan-content"></div></div>
    </div>
</div>

<!-- ======== SECTION VEILLE ======== -->
<div class="section" id="section-veille">
    <div class="card">
        <h2>Veille Juridique URSSAF / Legifrance</h2>
        <div class="grid-3" style="margin-bottom:15px">
            <div>
                <label>Annee</label>
                <select id="veille-annee">
                    <option value="2024">2024</option>
                    <option value="2025">2025</option>
                    <option value="2026" selected>2026</option>
                </select>
            </div>
            <div><button class="btn btn-primary btn-full" onclick="chargerVeille()" style="margin-top:22px">Charger la veille</button></div>
            <div><button class="btn btn-secondary btn-full" onclick="comparerAnnees()" style="margin-top:22px">Comparer avec N-1</button></div>
        </div>
    </div>
    <div id="veille-results" style="display:none">
        <div class="card"><h2>Baremes URSSAF</h2><div id="veille-baremes"></div></div>
        <div class="card"><h2>Legislation applicable</h2><div id="veille-legislation"></div></div>
        <div class="card" id="veille-comparaison-card" style="display:none"><h2>Comparaison inter-annees</h2><div id="veille-comparaison"></div></div>
    </div>
</div>

<!-- ======== SECTION PORTEFEUILLE ======== -->
<div class="section" id="section-portefeuille">
    <div class="grid-2">
        <div class="card">
            <h2>Ajouter une entreprise</h2>
            <label>SIRET</label><input id="ent-siret" placeholder="12345678901234" maxlength="14">
            <label>Raison sociale</label><input id="ent-raison" placeholder="Nom de l'entreprise">
            <div class="grid-2">
                <div><label>Forme juridique</label><input id="ent-forme" placeholder="SAS, SARL..."></div>
                <div><label>Code NAF</label><input id="ent-naf" placeholder="6201Z"></div>
            </div>
            <div class="grid-2">
                <div><label>Effectif</label><input type="number" id="ent-effectif" value="0"></div>
                <div><label>Ville</label><input id="ent-ville" placeholder="Paris"></div>
            </div>
            <button class="btn btn-primary btn-full" onclick="ajouterEntreprise()">Ajouter</button>
        </div>
        <div class="card">
            <h2>Rechercher</h2>
            <input id="ent-search" placeholder="Rechercher par nom, SIRET, ville..." oninput="rechercherEntreprises()">
            <div id="ent-list"></div>
        </div>
    </div>
</div>

</div>

<footer style="text-align:center;padding:30px;color:var(--gris);font-size:0.85em">
    URSSAF Analyzer v2.0.0 &mdash; Plateforme complete d'analyse comptable, fiscale et sociale
</footer>

<script>
/* ---- Navigation ---- */
function showSection(name) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(n => n.classList.remove('active'));
    document.getElementById('section-' + name).classList.add('active');
    event.target.classList.add('active');
    if (name === 'comptabilite') chargerComptaData();
    if (name === 'portefeuille') rechercherEntreprises();
}

/* ---- ANALYSE ---- */
let fichiers = [];
let formatRapport = 'json';

const dz = document.getElementById('dropzone-analyse');
const fi = document.getElementById('file-input-analyse');
['dragenter','dragover'].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); }));
dz.addEventListener('drop', ev => { ev.preventDefault(); addFiles(ev.dataTransfer.files); });
fi.addEventListener('change', ev => { addFiles(ev.target.files); fi.value=''; });

function addFiles(files) {
    const exts = ['.pdf','.csv','.xlsx','.xls','.xml','.dsn'];
    for (const f of files) {
        const ext = '.' + f.name.split('.').pop().toLowerCase();
        if (!exts.includes(ext)) continue;
        if (!fichiers.find(x => x.name === f.name)) fichiers.push(f);
    }
    renderFiles();
}
function renderFiles() {
    document.getElementById('file-list-analyse').innerHTML = fichiers.map((f,i) =>
        '<div class="file-item"><span class="name">'+f.name+'</span><span>'+
        (f.size/1024).toFixed(1)+' Ko</span><button class="remove" onclick="removeFile('+i+')">&times;</button></div>'
    ).join('');
    document.getElementById('btn-analyze').disabled = fichiers.length === 0;
}
function removeFile(i) { fichiers.splice(i,1); renderFiles(); }
function selectFormat(el) {
    document.querySelectorAll('.format-option').forEach(o => o.classList.remove('active'));
    el.classList.add('active'); formatRapport = el.dataset.format;
}

async function lancerAnalyse() {
    if (!fichiers.length) return;
    const btn = document.getElementById('btn-analyze');
    const prog = document.getElementById('progress-analyse');
    const fill = document.getElementById('progress-fill-analyse');
    const txt = document.getElementById('progress-text-analyse');
    btn.disabled = true; prog.style.display = 'block';
    document.getElementById('results-analyse').style.display = 'none';

    const steps = [[10,'Import...'],[30,'Integrite SHA-256...'],[50,'Parsing...'],[70,'Anomalies...'],[85,'Patterns...'],[95,'Rapport...']];
    let si = 0;
    const iv = setInterval(() => { if(si<steps.length){fill.style.width=steps[si][0]+'%';txt.textContent=steps[si][1];si++;}},800);

    const fd = new FormData();
    fichiers.forEach(f => fd.append('fichiers', f));
    try {
        const resp = await fetch('/api/analyze?format_rapport='+formatRapport, {method:'POST', body:fd});
        clearInterval(iv); fill.style.width='100%'; txt.textContent='Termine !';
        if (!resp.ok) { const e = await resp.json().catch(()=>({})); throw new Error(e.detail||'Erreur'); }
        if (formatRapport==='html') { afficherHTML(await resp.text()); }
        else { afficherJSON(await resp.json()); }
        setTimeout(()=>{prog.style.display='none';},1000);
        document.getElementById('results-analyse').style.display='block';
    } catch(e) { clearInterval(iv); prog.style.display='none'; alert(e.message); btn.disabled=false; }
}

function afficherJSON(data) {
    const s = data.synthese || {};
    const sc = s.score_risque_global || 0;
    const cl = sc>=70?'critique':sc>=40?'haute':'vert';
    document.getElementById('dashboard-analyse').innerHTML =
        '<div class="stat-card '+cl+'"><div class="value">'+sc+'/100</div><div class="label">Score risque</div></div>'+
        '<div class="stat-card"><div class="value">'+(s.nb_constats||0)+'</div><div class="label">Constats</div></div>'+
        '<div class="stat-card"><div class="value">'+((s.par_severite||{}).critique||0)+'</div><div class="label">Critiques</div></div>'+
        '<div class="stat-card"><div class="value">'+(s.impact_financier_total||0)+' EUR</div><div class="label">Impact</div></div>';
    const c = data.constats||[];
    document.getElementById('findings-analyse').innerHTML = c.length===0?
        '<p style="color:var(--vert)">Aucun constat. Documents conformes.</p>' :
        '<table><tr><th>Severite</th><th>Categorie</th><th>Constat</th><th>Impact</th></tr>'+
        c.slice(0,50).map(f=>'<tr><td><span class="badge '+(f.severite||'')+'">'+(f.severite||'').toUpperCase()+
        '</span></td><td>'+(f.categorie||'')+'</td><td><strong>'+(f.titre||'')+'</strong><br><small>'+(f.description||'').substring(0,120)+
        '</small></td><td>'+(f.montant_impact?f.montant_impact+' EUR':'N/A')+'</td></tr>').join('')+'</table>';
    document.getElementById('reco-analyse').innerHTML = (data.recommandations||[]).map((r,i)=>
        '<div class="alert info"><strong>#'+(i+1)+' '+(r.titre||'')+'</strong><br>'+(r.description||'')+'</div>').join('') || '<p>Aucune.</p>';
    document.getElementById('html-report-card').style.display='none';
}

function afficherHTML(html) {
    document.getElementById('dashboard-analyse').innerHTML='';
    document.getElementById('findings-analyse').innerHTML='';
    document.getElementById('reco-analyse').innerHTML='';
    document.getElementById('html-report-card').style.display='block';
    document.getElementById('html-report-frame').srcdoc=html;
}

function resetAnalyse() {
    fichiers=[]; renderFiles();
    document.getElementById('results-analyse').style.display='none';
    window.scrollTo({top:0,behavior:'smooth'});
}

/* ---- FACTURES ---- */
let factureFile = null;
const ffi = document.getElementById('file-input-facture');
ffi.addEventListener('change', ev => {
    factureFile = ev.target.files[0];
    if(factureFile) {
        document.getElementById('facture-filename').innerHTML='<div class="file-item"><span class="name">'+factureFile.name+'</span></div>';
        document.getElementById('btn-facture').disabled=false;
    }
});

async function analyserFacture() {
    if(!factureFile) return;
    const fd = new FormData(); fd.append('fichier', factureFile);
    try {
        const resp = await fetch('/api/factures/analyser', {method:'POST',body:fd});
        if(!resp.ok) throw new Error((await resp.json()).detail||'Erreur');
        const data = await resp.json();
        document.getElementById('facture-result').style.display='block';
        let h = '<div class="grid-4">';
        h += '<div class="stat-card"><div class="value">'+(data.type_document||'?')+'</div><div class="label">Type</div></div>';
        h += '<div class="stat-card"><div class="value">'+(data.montant_ttc||0).toFixed(2)+'</div><div class="label">TTC (EUR)</div></div>';
        h += '<div class="stat-card"><div class="value">'+((data.confiance||0)*100).toFixed(0)+'%</div><div class="label">Confiance</div></div>';
        h += '<div class="stat-card"><div class="value">'+(data.ecriture_manuscrite?'Oui':'Non')+'</div><div class="label">Manuscrit</div></div>';
        h += '</div>';
        if(data.emetteur) h+='<p><strong>Emetteur:</strong> '+(data.emetteur.nom||'?')+' (SIRET: '+(data.emetteur.siret||'?')+')</p>';
        if(data.destinataire) h+='<p><strong>Destinataire:</strong> '+(data.destinataire.nom||'?')+'</p>';
        if(data.lignes && data.lignes.length) {
            h+='<table style="margin-top:10px"><tr><th>Description</th><th>Qte</th><th>PU</th><th>HT</th></tr>';
            data.lignes.forEach(l => { h+='<tr><td>'+l.description+'</td><td class="num">'+l.quantite+'</td><td class="num">'+l.prix_unitaire.toFixed(2)+'</td><td class="num">'+l.montant_ht.toFixed(2)+'</td></tr>'; });
            h+='</table>';
        }
        // Pre-fill manual form
        if(data.type_document) document.getElementById('f-type').value=data.type_document;
        if(data.date_piece) document.getElementById('f-date').value=data.date_piece;
        if(data.numero) document.getElementById('f-numero').value=data.numero;
        if(data.emetteur) document.getElementById('f-tiers').value=data.emetteur.nom||'';
        document.getElementById('f-ht').value=data.montant_ht||0;
        document.getElementById('f-tva').value=data.montant_tva||0;
        document.getElementById('f-ttc').value=data.montant_ttc||0;
        document.getElementById('facture-detail').innerHTML=h;
    } catch(e) { alert(e.message); }
}

async function comptabiliserFacture() {
    const fd = new FormData();
    fd.append('type_doc', document.getElementById('f-type').value);
    fd.append('date_piece', document.getElementById('f-date').value);
    fd.append('numero_piece', document.getElementById('f-numero').value);
    fd.append('montant_ht', document.getElementById('f-ht').value||'0');
    fd.append('montant_tva', document.getElementById('f-tva').value||'0');
    fd.append('montant_ttc', document.getElementById('f-ttc').value||'0');
    fd.append('nom_tiers', document.getElementById('f-tiers').value);
    try {
        const resp = await fetch('/api/factures/comptabiliser', {method:'POST',body:fd});
        if(!resp.ok) throw new Error((await resp.json()).detail||'Erreur');
        const data = await resp.json();
        let h = '<div class="alert success"><strong>Ecriture generee !</strong> ID: '+data.ecriture_id+'</div>';
        h += '<table><tr><th>Compte</th><th>Libelle</th><th class="num">Debit</th><th class="num">Credit</th></tr>';
        data.lignes.forEach(l => { h+='<tr><td>'+l.compte+'</td><td>'+l.libelle+'</td><td class="num">'+l.debit.toFixed(2)+'</td><td class="num">'+l.credit.toFixed(2)+'</td></tr>'; });
        h += '</table>';
        document.getElementById('facture-result').style.display='block';
        document.getElementById('facture-detail').innerHTML=h;
    } catch(e) { alert(e.message); }
}

/* ---- COMPTABILITE ---- */
function showComptaTab(name) {
    document.querySelectorAll('#section-comptabilite .tab').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('#section-comptabilite .tab-content').forEach(t=>t.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById('compta-'+name).classList.add('active');
    chargerComptaData();
}

async function chargerComptaData() {
    // Journal
    try {
        const j = await (await fetch('/api/comptabilite/journal')).json();
        let h = j.length?'':'<p>Aucune ecriture.</p>';
        j.forEach(e => {
            h+='<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px;margin:8px 0">';
            h+='<strong>'+e.date+' | '+e.journal+' | '+e.piece+'</strong> - '+e.libelle;
            h+=' <span class="badge '+(e.equilibree?'faible':'critique')+'">'+(e.validee?'Validee':'Brouillon')+'</span>';
            h+='<table style="margin-top:8px"><tr><th>Compte</th><th>Libelle</th><th class="num">Debit</th><th class="num">Credit</th></tr>';
            e.lignes.forEach(l=>{h+='<tr><td>'+l.compte+'</td><td>'+l.libelle+'</td><td class="num">'+l.debit.toFixed(2)+'</td><td class="num">'+l.credit.toFixed(2)+'</td></tr>';});
            h+='</table></div>';
        });
        document.getElementById('compta-journal-content').innerHTML=h;
    } catch(e) {}

    // Balance
    try {
        const b = await (await fetch('/api/comptabilite/balance')).json();
        let h = b.length?'<table><tr><th>Compte</th><th>Libelle</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Solde D</th><th class="num">Solde C</th></tr>':'<p>Aucune donnee.</p>';
        b.forEach(r=>{h+='<tr><td>'+r.compte+'</td><td>'+r.libelle+'</td><td class="num">'+r.total_debit.toFixed(2)+'</td><td class="num">'+r.total_credit.toFixed(2)+'</td><td class="num">'+r.solde_debiteur.toFixed(2)+'</td><td class="num">'+r.solde_crediteur.toFixed(2)+'</td></tr>';});
        if(b.length) h+='</table>';
        document.getElementById('compta-balance-content').innerHTML=h;
    } catch(e) {}

    // Compte de resultat
    try {
        const cr = await (await fetch('/api/comptabilite/compte-resultat')).json();
        let h='<div class="grid-2"><div><h3>Charges: '+cr.charges.total.toFixed(2)+' EUR</h3></div><div><h3>Produits: '+cr.produits.total.toFixed(2)+' EUR</h3></div></div>';
        const color = cr.resultat_net>=0?'var(--vert)':'var(--rouge)';
        h+='<div class="stat-card" style="margin-top:15px;background:'+(cr.resultat_net>=0?'#e8f5e9':'#fde8e8')+'"><div class="value" style="color:'+color+'">'+cr.resultat_net.toFixed(2)+' EUR</div><div class="label">Resultat net</div></div>';
        document.getElementById('compta-resultat-content').innerHTML=h;
    } catch(e) {}

    // TVA
    try {
        const now = new Date();
        const tva = await (await fetch('/api/comptabilite/declaration-tva?mois='+now.getMonth()+'&annee='+now.getFullYear())).json();
        let h='<div class="grid-3">';
        h+='<div class="stat-card"><div class="value">'+tva.chiffre_affaires_ht.toFixed(2)+'</div><div class="label">CA HT (EUR)</div></div>';
        h+='<div class="stat-card"><div class="value">'+tva.tva_collectee.toFixed(2)+'</div><div class="label">TVA collectee</div></div>';
        h+='<div class="stat-card"><div class="value">'+tva.tva_deductible_totale.toFixed(2)+'</div><div class="label">TVA deductible</div></div>';
        h+='</div>';
        h+='<div class="stat-card" style="margin-top:15px"><div class="value">'+(tva.tva_nette_a_payer>0?tva.tva_nette_a_payer.toFixed(2)+' a payer':tva.credit_tva.toFixed(2)+' credit')+'</div><div class="label">TVA nette</div></div>';
        document.getElementById('compta-tva-content').innerHTML=h;
    } catch(e) {}

    // Social
    try {
        const soc = await (await fetch('/api/comptabilite/charges-sociales')).json();
        let h='<table><tr><th>Poste</th><th class="num">Montant (EUR)</th></tr>';
        const labels = {'salaires_bruts':'Salaires bruts','cotisations_urssaf':'Cotisations URSSAF','cotisations_retraite':'Retraite','mutuelle_prevoyance':'Mutuelle','france_travail':'France Travail','total_charges_sociales':'TOTAL charges sociales','cout_total_employeur':'Cout total employeur'};
        for(const[k,l] of Object.entries(labels)){h+='<tr'+(k.startsWith('total')||k.startsWith('cout')?' style="font-weight:bold;background:var(--bleu-clair)"':'')+'><td>'+l+'</td><td class="num">'+(soc[k]||0).toFixed(2)+'</td></tr>';}
        h+='<tr style="font-weight:bold"><td>Taux de charges global</td><td class="num">'+(soc.taux_charges_global||0).toFixed(1)+'%</td></tr>';
        h+='</table>';
        document.getElementById('compta-social-content').innerHTML=h;
    } catch(e) {}

    // Plan comptable
    try {
        const pc = await (await fetch('/api/comptabilite/plan-comptable')).json();
        let h='<input placeholder="Rechercher un compte..." oninput="rechercherPlanComptable(this.value)" style="margin-bottom:10px">';
        h+='<table id="plan-table"><tr><th>N°</th><th>Libelle</th><th>Classe</th></tr>';
        pc.forEach(c=>{h+='<tr><td>'+c.numero+'</td><td>'+c.libelle+'</td><td>'+c.classe+'</td></tr>';});
        h+='</table>';
        document.getElementById('compta-plan-content').innerHTML=h;
    } catch(e) {}
}

async function rechercherPlanComptable(terme) {
    const url = terme ? '/api/comptabilite/plan-comptable?terme='+encodeURIComponent(terme) : '/api/comptabilite/plan-comptable';
    const pc = await (await fetch(url)).json();
    const t = document.getElementById('plan-table');
    if(!t) return;
    let h='<tr><th>N°</th><th>Libelle</th><th>Classe</th></tr>';
    pc.forEach(c=>{h+='<tr><td>'+c.numero+'</td><td>'+c.libelle+'</td><td>'+c.classe+'</td></tr>';});
    t.innerHTML=h;
}

async function validerEcritures() {
    try {
        const resp = await fetch('/api/comptabilite/valider', {method:'POST'});
        const data = await resp.json();
        alert('Ecritures validees: '+data.nb_validees+(data.erreurs.length?' | Erreurs: '+data.erreurs.join(', '):''));
        chargerComptaData();
    } catch(e) { alert(e.message); }
}

/* ---- VEILLE ---- */
async function chargerVeille() {
    const annee = document.getElementById('veille-annee').value;
    document.getElementById('veille-results').style.display='block';

    // Baremes
    try {
        const b = await (await fetch('/api/veille/baremes/'+annee)).json();
        let h='<table><tr><th>Parametre</th><th class="num">Valeur</th></tr>';
        for(const[k,v] of Object.entries(b)){h+='<tr><td>'+k.replace(/_/g,' ')+'</td><td class="num">'+v+'</td></tr>';}
        h+='</table>';
        document.getElementById('veille-baremes').innerHTML=h;
    } catch(e) {}

    // Legislation
    try {
        const l = await (await fetch('/api/veille/legislation/'+annee)).json();
        let h='<p><strong>'+l.description+'</strong></p>';
        (l.textes_cles||[]).forEach(t=>{
            h+='<div class="alert info" style="margin:8px 0"><strong>'+t.reference+'</strong> - '+t.titre+'<br><small>'+t.resume+'</small><br><a href="'+t.url+'" target="_blank" style="font-size:0.85em">Voir le texte</a></div>';
        });
        document.getElementById('veille-legislation').innerHTML=h;
    } catch(e) {}
}

async function comparerAnnees() {
    const a2 = parseInt(document.getElementById('veille-annee').value);
    const a1 = a2 - 1;
    try {
        const diffs = await (await fetch('/api/veille/baremes/comparer/'+a1+'/'+a2)).json();
        if(!diffs.length) { alert('Pas de differences trouvees.'); return; }
        let h='<p>Comparaison '+a1+' vs '+a2+'</p><table><tr><th>Parametre</th><th class="num">'+a1+'</th><th class="num">'+a2+'</th><th>Evolution</th></tr>';
        diffs.forEach(d=>{h+='<tr><td>'+d.parametre+'</td><td class="num">'+(d['valeur_'+a1]||'N/A')+'</td><td class="num">'+(d['valeur_'+a2]||'N/A')+'</td><td>'+d.evolution+'</td></tr>';});
        h+='</table>';
        document.getElementById('veille-comparaison').innerHTML=h;
        document.getElementById('veille-comparaison-card').style.display='block';
    } catch(e) { alert(e.message); }
}

/* ---- PORTEFEUILLE ---- */
async function ajouterEntreprise() {
    const fd = new FormData();
    fd.append('siret', document.getElementById('ent-siret').value);
    fd.append('raison_sociale', document.getElementById('ent-raison').value);
    fd.append('forme_juridique', document.getElementById('ent-forme').value);
    fd.append('code_naf', document.getElementById('ent-naf').value);
    fd.append('effectif', document.getElementById('ent-effectif').value||'0');
    fd.append('ville', document.getElementById('ent-ville').value);
    try {
        const resp = await fetch('/api/entreprises', {method:'POST',body:fd});
        if(!resp.ok) throw new Error((await resp.json()).detail||'Erreur');
        alert('Entreprise ajoutee !');
        rechercherEntreprises();
    } catch(e) { alert(e.message); }
}

async function rechercherEntreprises() {
    const q = (document.getElementById('ent-search')||{}).value || '';
    try {
        const data = await (await fetch('/api/entreprises?q='+encodeURIComponent(q))).json();
        let h = data.length ? '' : '<p style="color:var(--gris)">Aucune entreprise trouvee.</p>';
        data.forEach(e => {
            h+='<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px;margin:8px 0">';
            h+='<strong>'+e.raison_sociale+'</strong><br>';
            h+='<small>SIRET: '+e.siret+' | '+(e.ville||'')+(e.forme_juridique?' | '+e.forme_juridique:'')+'</small>';
            h+='</div>';
        });
        document.getElementById('ent-list').innerHTML=h;
    } catch(e) {}
}
</script>
</body>
</html>"""
