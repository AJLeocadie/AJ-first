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
    version="3.0.0",
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
# PAGES (LANDING + APP)
# ==============================

@app.get("/", response_class=HTMLResponse)
async def accueil():
    return LANDING_HTML


@app.get("/app", response_class=HTMLResponse)
async def application():
    return APP_HTML


# ==============================
# API AUTH + ADMIN
# ==============================

@app.on_event("startup")
async def create_admin():
    """Cree le profil admin au demarrage."""
    db = get_db()
    pm = PortfolioManager(db)
    try:
        pm.creer_profil("Admin", "System", "admin", "bossadmin", role="admin")
    except Exception:
        pass  # Deja cree


@app.post("/api/auth/login")
async def login(email: str = Form(...), mot_de_passe: str = Form(...)):
    db = get_db()
    pm = PortfolioManager(db)
    profil = pm.authentifier(email, mot_de_passe)
    if not profil:
        raise HTTPException(401, "Identifiants incorrects.")
    return profil


@app.post("/api/auth/register")
async def register(
    nom: str = Form(...), prenom: str = Form(...),
    email: str = Form(...), mot_de_passe: str = Form(...),
):
    db = get_db()
    pm = PortfolioManager(db)
    try:
        return pm.creer_profil(nom, prenom, email, mot_de_passe)
    except Exception as e:
        raise HTTPException(400, str(e))


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
        "numero": getattr(piece, 'numero_piece', '') or getattr(piece, 'numero', ''),
        "date_piece": piece.date_piece.isoformat() if piece.date_piece else None,
        "emetteur": {"nom": piece.emetteur.nom, "siret": piece.emetteur.siret, "tva_intra": piece.emetteur.tva_intra} if piece.emetteur else None,
        "destinataire": {"nom": piece.destinataire.nom, "siret": piece.destinataire.siret, "tva_intra": piece.destinataire.tva_intra} if piece.destinataire else None,
        "montant_ht": float(piece.montant_ht),
        "montant_tva": float(piece.montant_tva),
        "montant_ttc": float(piece.montant_ttc),
        "confiance": float(getattr(piece, 'confiance_extraction', 0) or getattr(piece, 'confiance', 0)),
        "ecriture_manuscrite": bool(getattr(piece, 'champs_manuscrits', None)),
        "lignes": [{"description": l.description, "quantite": float(l.quantite),
                     "prix_unitaire": float(l.prix_unitaire), "montant_ht": float(l.montant_ht)}
                    for l in piece.lignes] if piece.lignes else [],
    }


# ==============================
# API SIMULATION INDEPENDANTS
# ==============================

@app.get("/api/simulation/micro-entrepreneur")
async def simulation_micro(
    chiffre_affaires: float = Query(...),
    activite: str = Query("prestations_bnc"),
    acre: bool = Query(False),
    prelevement_liberatoire: bool = Query(False),
):
    """Simule les cotisations et impots d'un micro-entrepreneur."""
    from urssaf_analyzer.regimes.independant import calculer_cotisations_micro, ActiviteMicro
    try:
        act = ActiviteMicro(activite)
    except ValueError:
        raise HTTPException(400, f"Activite inconnue. Valeurs: {[a.value for a in ActiviteMicro]}")
    return calculer_cotisations_micro(
        Decimal(str(chiffre_affaires)), act, acre=acre,
        prelevement_liberatoire=prelevement_liberatoire,
    )


@app.get("/api/simulation/tns")
async def simulation_tns(
    revenu_net: float = Query(...),
    type_statut: str = Query("gerant_majoritaire"),
    acre: bool = Query(False),
):
    """Simule les cotisations TNS (travailleur non salarie)."""
    from urssaf_analyzer.regimes.independant import calculer_cotisations_tns, TypeIndependant
    try:
        ts = TypeIndependant(type_statut)
    except ValueError:
        raise HTTPException(400, f"Statut inconnu. Valeurs: {[t.value for t in TypeIndependant]}")
    return calculer_cotisations_tns(Decimal(str(revenu_net)), ts, acre=acre)


@app.get("/api/simulation/impot-independant")
async def simulation_impot_independant(
    benefice: float = Query(...),
    nb_parts: float = Query(1),
    autres_revenus: float = Query(0),
):
    """Simule l'impot sur le revenu d'un independant."""
    from urssaf_analyzer.regimes.independant import calculer_impot_independant
    return calculer_impot_independant(
        Decimal(str(benefice)), nb_parts=Decimal(str(nb_parts)),
        autres_revenus_foyer=Decimal(str(autres_revenus)),
    )


@app.get("/api/simulation/guso")
async def simulation_guso(
    salaire_brut: float = Query(...),
    nb_heures: float = Query(8),
):
    """Simule les cotisations GUSO (spectacle occasionnel)."""
    from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_guso
    return calculer_cotisations_guso(Decimal(str(salaire_brut)), Decimal(str(nb_heures)))


@app.get("/api/simulation/artistes-auteurs")
async def simulation_artistes_auteurs(
    revenus_bruts: float = Query(...),
    est_bda: bool = Query(True),
):
    """Simule les cotisations artistes-auteurs (ex-AGESSA/MDA)."""
    from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_artistes_auteurs
    return calculer_cotisations_artistes_auteurs(Decimal(str(revenus_bruts)), est_bda=est_bda)


# ==============================
# API CONVENTIONS COLLECTIVES
# ==============================

@app.get("/api/conventions-collectives")
async def lister_conventions_api():
    """Liste toutes les conventions collectives disponibles."""
    from urssaf_analyzer.regimes.guso_agessa import lister_conventions
    return lister_conventions()


@app.get("/api/conventions-collectives/recherche")
async def rechercher_conventions_api(q: str = Query(..., min_length=2)):
    from urssaf_analyzer.regimes.guso_agessa import rechercher_conventions
    resultats = rechercher_conventions(q)
    return [{"idcc": cc.idcc, "titre": cc.titre, "brochure": cc.brochure,
             "specificites": cc.specificites} for cc in resultats]


@app.get("/api/conventions-collectives/{idcc}")
async def get_convention_api(idcc: str):
    from urssaf_analyzer.regimes.guso_agessa import get_convention_collective
    cc = get_convention_collective(idcc)
    if not cc:
        raise HTTPException(404, f"Convention IDCC {idcc} non trouvee.")
    return {"idcc": cc.idcc, "titre": cc.titre, "brochure": cc.brochure,
            "code_naf_principaux": cc.code_naf_principaux, "specificites": cc.specificites}


# ==============================
# API DOCUMENTS JURIDIQUES (KBIS, STATUTS)
# ==============================

@app.post("/api/documents/extraire")
async def extraire_document_juridique(fichier: UploadFile = File(...)):
    """Extrait les informations d'un document juridique (KBIS, statuts, etc.)."""
    from urssaf_analyzer.ocr.image_reader import LecteurMultiFormat
    from urssaf_analyzer.ocr.legal_document_extractor import LegalDocumentExtractor
    contenu = await fichier.read()
    lecteur = LecteurMultiFormat()
    resultat = lecteur.lire_contenu_brut(contenu, fichier.filename or "")
    avertissements = list(resultat.avertissements)
    if resultat.manuscrit_detecte:
        avertissements += [a.message for a in resultat.avertissements_manuscrit[:5]]
    extracteur = LegalDocumentExtractor()
    info = extracteur.extraire(resultat.texte)
    return {
        "info_entreprise": extracteur.info_to_dict(info),
        "document": {"format": resultat.format_detecte.value, "est_scan": resultat.est_scan,
                      "manuscrit_detecte": resultat.manuscrit_detecte, "confiance_ocr": resultat.confiance_ocr},
        "avertissements": avertissements,
    }


@app.post("/api/documents/lire")
async def lire_document(fichier: UploadFile = File(...)):
    """Lit un document de tout format et retourne le texte + metadonnees."""
    from urssaf_analyzer.ocr.image_reader import LecteurMultiFormat
    lecteur = LecteurMultiFormat()
    contenu = await fichier.read()
    resultat = lecteur.lire_contenu_brut(contenu, fichier.filename or "")
    return {
        "texte": resultat.texte[:10000], "format": resultat.format_detecte.value,
        "taille": resultat.taille_octets, "nb_pages": resultat.nb_pages,
        "est_image": resultat.est_image, "est_scan": resultat.est_scan,
        "manuscrit_detecte": resultat.manuscrit_detecte, "confiance_ocr": resultat.confiance_ocr,
        "avertissements": resultat.avertissements,
        "avertissements_manuscrit": [
            {"zone": a.zone, "message": a.message, "confiance": a.confiance, "ligne": a.ligne_numero}
            for a in resultat.avertissements_manuscrit[:20]
        ],
    }


# ==============================
# API VERIFICATION DOCUMENTS OBLIGATOIRES
# ==============================

@app.get("/api/compliance/verifier/{operation}")
async def verifier_documents_obligatoires(
    operation: str,
    documents_fournis: str = Query("", description="Noms separes par virgules"),
):
    """Verifie les documents obligatoires pour une operation."""
    from urssaf_analyzer.compliance.document_checker import DocumentChecker, TypeOperation
    try:
        op = TypeOperation(operation)
    except ValueError:
        raise HTTPException(400, f"Operation inconnue. Valeurs: {[o.value for o in TypeOperation]}")
    docs = [d.strip() for d in documents_fournis.split(",") if d.strip()] if documents_fournis else []
    checker = DocumentChecker()
    resultat = checker.verifier_operation(op, docs)
    return {
        "operation": resultat.operation.value, "est_complet": resultat.est_complet,
        "taux_completude": resultat.taux_completude, "resume": resultat.resume,
        "documents_requis": [
            {"nom": d.nom, "description": d.description, "niveau": d.niveau.value,
             "statut": d.statut.value, "reference_legale": d.reference_legale}
            for d in resultat.documents_requis
        ],
        "alertes": [
            {"titre": a.titre, "description": a.description, "niveau": a.niveau.value,
             "reference_legale": a.reference_legale, "action_requise": a.action_requise}
            for a in resultat.alertes
        ],
    }


@app.get("/api/compliance/operations")
async def lister_operations():
    from urssaf_analyzer.compliance.document_checker import TypeOperation
    return [{"code": o.value, "libelle": o.value.replace("_", " ").capitalize()} for o in TypeOperation]


# ==============================
# API SUPABASE / PATCH MENSUEL
# ==============================

@app.get("/api/supabase/status")
async def supabase_status():
    from urssaf_analyzer.database.supabase_client import HAS_SUPABASE
    if not HAS_SUPABASE:
        return {"connected": False, "message": "Module supabase non installe"}
    from urssaf_analyzer.database.supabase_client import SupabaseClient
    client = SupabaseClient()
    return {"connected": client.is_connected, "url": client.url[:30] + "..." if client.url else ""}


@app.post("/api/supabase/patch-mensuel")
async def patch_mensuel(annee: int = Form(2026), mois: int = Form(1)):
    from urssaf_analyzer.database.supabase_client import SupabaseClient, generer_donnees_patch_mensuel
    client = SupabaseClient()
    if not client.is_connected:
        return {"status": "offline", "message": "Supabase non connecte. Configurez SUPABASE_URL et SUPABASE_KEY."}
    donnees = generer_donnees_patch_mensuel(annee, mois)
    return client.executer_patch_mensuel(annee, mois, donnees)


# ==============================
# LANDING PAGE (PAGE COMMERCIALE)
# ==============================

# ==============================
# LANDING PAGE (PAGE COMMERCIALE)
# ==============================

LANDING_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>URSSAF Analyzer - Conformite sociale et fiscale intelligente</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f7fafc;color:#333}
.top-bar{background:#1a365d;color:#fff;display:flex;justify-content:space-between;align-items:center;padding:12px 40px;position:sticky;top:0;z-index:100}
.top-bar .logo{font-size:1.4em;font-weight:800;letter-spacing:-0.5px}
.top-bar .links{display:flex;gap:20px;align-items:center}
.top-bar a{color:#fff;text-decoration:none;font-size:.9em;opacity:.85;transition:.2s}
.top-bar a:hover{opacity:1}
.btn-login{background:rgba(255,255,255,.15);padding:8px 22px;border-radius:8px;font-weight:600}
.hero{background:linear-gradient(135deg,#1a365d 0%,#2b6cb0 100%);color:#fff;text-align:center;padding:80px 20px 60px}
.hero h1{font-size:2.8em;font-weight:800;margin-bottom:15px;line-height:1.1}
.hero p{font-size:1.15em;opacity:.9;max-width:700px;margin:0 auto 30px}
.hero .price-box{display:inline-block;background:rgba(255,255,255,.15);border-radius:16px;padding:20px 40px;margin:20px 0}
.hero .price{font-size:2.5em;font-weight:800}
.hero .price-sub{font-size:.85em;opacity:.8}
.cta{display:inline-block;background:#fff;color:#1a365d;padding:14px 40px;border-radius:10px;font-size:1.1em;font-weight:700;text-decoration:none;margin-top:20px;transition:.2s;cursor:pointer;border:none}
.cta:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,0,0,.2)}
.features{max-width:1100px;margin:60px auto;padding:0 20px}
.features h2{text-align:center;font-size:1.8em;color:#1a365d;margin-bottom:40px}
.fg{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:25px}
.fc{background:#fff;border-radius:14px;padding:30px;box-shadow:0 4px 14px rgba(0,0,0,.06);transition:.2s}
.fc:hover{transform:translateY(-3px);box-shadow:0 8px 25px rgba(0,0,0,.1)}
.fc .ic{font-size:2em;margin-bottom:12px}
.fc h3{color:#1a365d;margin-bottom:8px}
.fc p{color:#718096;font-size:.9em;line-height:1.5}
.targets{background:#fff;padding:60px 20px;text-align:center}
.targets h2{font-size:1.8em;color:#1a365d;margin-bottom:30px}
.tg{display:flex;justify-content:center;gap:30px;flex-wrap:wrap;max-width:900px;margin:0 auto}
.ti{background:#ebf4ff;border-radius:12px;padding:25px;width:200px;text-align:center}
.ti .ic{font-size:2em}
.ti h4{color:#1a365d;margin:8px 0 4px}
.ti p{font-size:.8em;color:#718096}
.sa{max-width:440px;margin:60px auto;padding:0 20px}
.ac{background:#fff;border-radius:16px;padding:35px;box-shadow:0 4px 20px rgba(0,0,0,.08)}
.ac h2{text-align:center;color:#1a365d;margin-bottom:20px}
.at{display:flex;margin-bottom:20px;border-bottom:2px solid #e0e0e0}
.atb{flex:1;padding:10px;text-align:center;cursor:pointer;font-weight:600;color:#718096;border-bottom:3px solid transparent}
.atb.active{color:#1a365d;border-bottom-color:#1a365d}
.af{display:none}.af.active{display:block}
.af label{display:block;font-weight:600;font-size:.85em;color:#555;margin-bottom:4px}
.af input{width:100%;padding:10px 12px;border:2px solid #e0e0e0;border-radius:8px;font-size:.95em;margin-bottom:12px}
.af input:focus{border-color:#2b6cb0;outline:none}
.bs{width:100%;padding:12px;background:#1a365d;color:#fff;border:none;border-radius:10px;font-size:1em;font-weight:700;cursor:pointer}
.bs:hover{background:#2b6cb0}
.am{padding:10px;border-radius:8px;margin:10px 0;font-size:.9em;display:none}
.am.ok{display:block;background:#e8f5e9;color:#2e7d32}
.am.err{display:block;background:#fde8e8;color:#c53030}
footer{text-align:center;padding:40px 20px;color:#718096;font-size:.85em;background:#f0f4f8}
@media(max-width:600px){.hero h1{font-size:1.8em}.fg{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="top-bar">
<div class="logo">URSSAF Analyzer</div>
<div class="links">
<a href="#features">Fonctionnalites</a>
<a href="#pricing">Tarif</a>
<a href="#auth" class="btn-login">Se connecter</a>
</div>
</div>
<div class="hero" id="pricing">
<h1>La conformite sociale et fiscale<br>enfin simplifiee.</h1>
<p>Analyse automatique de vos documents sociaux, detection d'anomalies avec impact en euros, comptabilite integree, veille juridique temps reel. Pour entrepreneurs, comptables et experts.</p>
<div class="price-box"><div class="price">59,99 EUR</div><div class="price-sub">Licence complete &bull; Mises a jour mensuelles incluses</div></div>
<br><button class="cta" onclick="document.getElementById('auth').scrollIntoView({behavior:'smooth'})">Demarrer maintenant</button>
</div>
<div class="features" id="features">
<h2>Une plateforme complete et professionnelle</h2>
<div class="fg">
<div class="fc"><div class="ic">&#128269;</div><h3>Detection d'anomalies</h3><p>Ecarts d'assiette avec incidence en cotisations en EUR. Code couleur par impact et destinataire (URSSAF, Fiscal, France Travail, GUSO).</p></div>
<div class="fc"><div class="ic">&#128200;</div><h3>Dashboard dirigeant</h3><p>Vue synthetique : anomalies, charges vs brut, niveau de conformite, previsionnels, seuils sociaux depasses.</p></div>
<div class="fc"><div class="ic">&#128196;</div><h3>Comptabilite integree</h3><p>Plan comptable, ecritures automatiques, balance, grand livre, compte de resultat, TVA. Integration auto a l'import.</p></div>
<div class="fc"><div class="ic">&#128221;</div><h3>Multi-formats</h3><p>PDF, Excel, CSV, DSN, images (JPEG, PNG, TIFF). Detection d'ecriture manuscrite. OCR intelligent.</p></div>
<div class="fc"><div class="ic">&#9878;</div><h3>Veille juridique</h3><p>Baremes URSSAF et legislation Legifrance 2024-2026. Patch mensuel automatique. Historique conserve.</p></div>
<div class="fc"><div class="ic">&#128101;</div><h3>Tous profils</h3><p>Salaries, TNS, micro-entrepreneurs, GUSO spectacle, artistes-auteurs. Simulations et calculs complets.</p></div>
<div class="fc"><div class="ic">&#128203;</div><h3>Audit automatise</h3><p>Checklist automatique, rapports PDF exportables, historique des actions, recherche intelligente multi-fichiers.</p></div>
<div class="fc"><div class="ic">&#128274;</div><h3>Alertes justificatifs</h3><p>Alerte pour tout element sans justificatif. Code couleur rouge en comptabilite. Conformite garantie.</p></div>
</div></div>
<div class="targets">
<h2>Concu pour les professionnels</h2>
<div class="tg">
<div class="ti"><div class="ic">&#128188;</div><h4>Entrepreneurs</h4><p>Gerez votre conformite en autonomie</p></div>
<div class="ti"><div class="ic">&#128202;</div><h4>Comptables</h4><p>Automatisez vos controles et ecritures</p></div>
<div class="ti"><div class="ic">&#127891;</div><h4>Experts-comptables</h4><p>Portefeuille multi-entreprises complet</p></div>
<div class="ti"><div class="ic">&#128270;</div><h4>Inspecteurs URSSAF</h4><p>Verification rapide et exhaustive</p></div>
</div></div>
<div class="sa" id="auth">
<div class="ac">
<h2>Acces a la plateforme</h2>
<div class="at">
<div class="atb active" onclick="showAT('login')">Connexion</div>
<div class="atb" onclick="showAT('register')">Inscription</div>
</div>
<div id="amsg" class="am"></div>
<div class="af active" id="form-login">
<label>Identifiant / Email</label><input type="text" id="le" placeholder="admin">
<label>Mot de passe</label><input type="password" id="lp" placeholder="********">
<button class="bs" onclick="doLogin()">Se connecter</button>
</div>
<div class="af" id="form-register">
<label>Nom</label><input id="rn" placeholder="Dupont">
<label>Prenom</label><input id="rp" placeholder="Jean">
<label>Email</label><input type="email" id="re" placeholder="jean@exemple.fr">
<label>Mot de passe</label><input type="password" id="rpw" placeholder="Min. 6 caracteres">
<label>Confirmer</label><input type="password" id="rpw2" placeholder="Confirmez">
<div style="margin:12px 0;padding:12px;background:#f7fafc;border-radius:8px;font-size:.82em;color:#555">
<label style="display:flex;align-items:center;gap:8px;font-weight:400;margin:0"><input type="checkbox" id="cgv"> J'accepte les conditions generales de vente et d'utilisation.</label>
</div>
<button class="bs" onclick="doReg()">Creer mon compte - 59,99 EUR</button>
<div style="font-size:.8em;color:#718096;margin-top:8px;text-align:center">Paiement securise. Acces immediat.</div>
</div>
</div></div>
<footer>URSSAF Analyzer v3.0.0 &mdash; Plateforme professionnelle d'analyse sociale, fiscale et comptable<br>&copy; 2026</footer>
<script>
function showAT(t){document.querySelectorAll('.atb').forEach((b,i)=>{b.classList.toggle('active',i===(t==='login'?0:1))});document.getElementById('form-login').classList.toggle('active',t==='login');document.getElementById('form-register').classList.toggle('active',t==='register');document.getElementById('amsg').className='am';}
async function doLogin(){const fd=new FormData();fd.append('email',document.getElementById('le').value);fd.append('mot_de_passe',document.getElementById('lp').value);try{const r=await fetch('/api/auth/login',{method:'POST',body:fd});if(!r.ok){const e=await r.json();throw new Error(e.detail||'Erreur');}const m=document.getElementById('amsg');m.className='am ok';m.textContent='Connexion reussie...';setTimeout(()=>{window.location.href='/app'},600);}catch(e){const m=document.getElementById('amsg');m.className='am err';m.textContent=e.message;}}
async function doReg(){if(document.getElementById('rpw').value!==document.getElementById('rpw2').value){const m=document.getElementById('amsg');m.className='am err';m.textContent='Mots de passe differents.';return;}if(!document.getElementById('cgv').checked){const m=document.getElementById('amsg');m.className='am err';m.textContent='Veuillez accepter les CGV.';return;}const fd=new FormData();fd.append('nom',document.getElementById('rn').value);fd.append('prenom',document.getElementById('rp').value);fd.append('email',document.getElementById('re').value);fd.append('mot_de_passe',document.getElementById('rpw').value);try{const r=await fetch('/api/auth/register',{method:'POST',body:fd});if(!r.ok){const e=await r.json();throw new Error(e.detail||'Erreur');}const m=document.getElementById('amsg');m.className='am ok';m.textContent='Compte cree ! Redirection...';setTimeout(()=>{window.location.href='/app'},600);}catch(e){const m=document.getElementById('amsg');m.className='am err';m.textContent=e.message;}}
</script>
</body>
</html>"""


# ==============================
# APPLICATION (INTERFACE COMPLETE)
# ==============================

APP_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>URSSAF Analyzer - Application</title>
<style>
:root{--b:#1a365d;--b2:#2b6cb0;--bc:#ebf4ff;--v:#276749;--vc:#e8f5e9;--r:#c53030;--rc:#fde8e8;--o:#c05621;--oc:#fefcbf;--bg:#f7fafc;--g:#718096;--sh:0 4px 14px rgba(0,0,0,.08)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:#333}
nav{background:var(--b);color:#fff;padding:0 20px;display:flex;align-items:center;position:sticky;top:0;z-index:100}
nav .logo{font-size:1.3em;font-weight:700;padding:15px 0;margin-right:30px}
nav .nls{display:flex;gap:0;overflow-x:auto}
nav .nl{padding:15px 16px;cursor:pointer;opacity:.7;transition:.2s;border-bottom:3px solid transparent;font-size:.88em;white-space:nowrap}
nav .nl:hover,nav .nl.active{opacity:1;border-bottom-color:#fff;background:rgba(255,255,255,.1)}
nav .logout{margin-left:auto;padding:10px 18px;cursor:pointer;opacity:.7;font-size:.85em}
nav .logout:hover{opacity:1}
.main{max-width:1200px;margin:20px auto;padding:0 20px}
.sec{display:none}.sec.active{display:block}
.card{background:#fff;border-radius:12px;padding:25px;box-shadow:var(--sh);margin-bottom:20px}
.card h2{color:var(--b);margin-bottom:15px;font-size:1.2em}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}
.g4{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.uz{border:3px dashed #c5d3e8;border-radius:12px;padding:40px;text-align:center;cursor:pointer;transition:.3s;background:var(--bc);position:relative}
.uz:hover{border-color:var(--b);background:#d6e4f7}
.uz input[type="file"]{position:absolute;inset:0;opacity:0;cursor:pointer}
.uz h3{color:var(--b);margin:10px 0 5px}.uz p{color:var(--g);font-size:.85em}
input,select,textarea{width:100%;padding:10px 12px;border:2px solid #e0e0e0;border-radius:8px;font-size:.95em;transition:.2s;margin-bottom:12px}
input:focus,select:focus{border-color:var(--b);outline:none}
label{display:block;font-weight:600;margin-bottom:4px;font-size:.9em;color:#555}
.btn{display:inline-flex;align-items:center;gap:8px;padding:10px 24px;border:none;border-radius:8px;font-size:.95em;font-weight:600;cursor:pointer;transition:.2s}
.btn-p{background:var(--b);color:#fff}.btn-p:hover{background:var(--b2)}.btn-p:disabled{background:#a0b4cc;cursor:not-allowed}
.btn-s{background:var(--bc);color:var(--b)}
.btn-f{width:100%;justify-content:center}
.sc{background:var(--bc);border-radius:8px;padding:15px;text-align:center}
.sc .val{font-size:1.8em;font-weight:700}.sc .lab{font-size:.8em;color:var(--g);margin-top:4px}
table{width:100%;border-collapse:collapse}
th{background:var(--b);color:#fff;padding:10px 12px;text-align:left;font-size:.85em}
td{padding:8px 12px;border-bottom:1px solid #eee;font-size:.88em}
tr:hover{background:var(--bc)}
.num{text-align:right;font-family:'Consolas',monospace}
.badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:.75em;font-weight:700;color:#fff}
.badge-urssaf{background:#2b6cb0}.badge-fiscal{background:#805ad5}.badge-ft{background:#d69e2e;color:#333}.badge-guso{background:#319795}
.badge-pos{background:var(--v)}.badge-neg{background:var(--r)}
.fi{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--bc);border-radius:6px;margin:4px 0;font-size:.88em}
.fi .nm{font-weight:600;color:var(--b)}.fi .rm{background:none;border:none;color:var(--r);cursor:pointer;font-size:1.2em}
.prg{display:none;margin:15px 0}
.prg-bar{height:6px;background:#e0e0e0;border-radius:3px;overflow:hidden}
.prg-fill{height:100%;background:linear-gradient(90deg,var(--b),#005bb5);border-radius:3px;width:0%;transition:width .5s}
.prg-txt{text-align:center;margin-top:8px;color:var(--g);font-size:.85em}
.al{padding:12px 15px;border-radius:8px;margin:10px 0}
.al.info{background:#e3f2fd;color:#1565c0}.al.ok{background:#e8f5e9;color:#2e7d32}.al.err{background:#fde8e8;color:var(--r)}
.al.warn{background:#fff3e0;color:#e65100}
.al-just{background:#fde8e8;border-left:4px solid var(--r);padding:12px 15px;border-radius:0 8px 8px 0;margin:8px 0;font-size:.9em}
.tabs{display:flex;gap:0;border-bottom:2px solid #e0e0e0;margin-bottom:20px}
.tab{padding:10px 20px;cursor:pointer;border-bottom:3px solid transparent;color:var(--g);font-weight:600;font-size:.9em}
.tab:hover{color:var(--b)}.tab.active{color:var(--b);border-bottom-color:var(--b)}
.tc{display:none}.tc.active{display:block}
.anomalie{border:1px solid #e0e0e0;border-radius:10px;padding:15px;margin:10px 0;cursor:pointer;transition:.2s}
.anomalie:hover{box-shadow:0 4px 15px rgba(0,0,0,.1)}
.anomalie.neg{border-left:4px solid var(--r)}.anomalie.pos{border-left:4px solid var(--v)}
.anomalie .head{display:flex;justify-content:space-between;align-items:center}
.anomalie .montant{font-size:1.3em;font-weight:700;font-family:'Consolas',monospace}
.anomalie .montant.neg{color:var(--r)}.anomalie .montant.pos{color:var(--v)}
.anomalie .detail{display:none;margin-top:12px;padding-top:12px;border-top:1px solid #eee;font-size:.88em}
.anomalie.open .detail{display:block}
.anomalie .dest{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.72em;font-weight:700;color:#fff;margin-left:6px}
.gauge{width:120px;height:120px;border-radius:50%;background:conic-gradient(var(--v) 0%,var(--v) var(--pct),#e0e0e0 var(--pct));display:flex;align-items:center;justify-content:center;margin:0 auto}
.gauge-inner{width:90px;height:90px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;font-size:1.5em;font-weight:800;color:var(--b)}
.fmts{display:flex;gap:10px;margin-bottom:15px}
.fopt{flex:1;padding:12px;border:2px solid #e0e0e0;border-radius:8px;text-align:center;cursor:pointer;background:#fff}
.fopt:hover{border-color:var(--b)}.fopt.active{border-color:var(--b);background:var(--bc)}
@media(max-width:768px){.g2,.g3{grid-template-columns:1fr}nav .nls{overflow-x:auto}}
</style>
</head>
<body>
<nav>
<div class="logo">URSSAF Analyzer</div>
<div class="nls">
<div class="nl active" onclick="showS('dashboard',this)">Dashboard</div>
<div class="nl" onclick="showS('analyse',this)">Analyse</div>
<div class="nl" onclick="showS('factures',this)">Factures</div>
<div class="nl" onclick="showS('compta',this)">Comptabilite</div>
<div class="nl" onclick="showS('simulation',this)">Simulation</div>
<div class="nl" onclick="showS('veille',this)">Veille</div>
<div class="nl" onclick="showS('documents',this)">Documents</div>
<div class="nl" onclick="showS('portefeuille',this)">Portefeuille</div>
</div>
<div class="logout" onclick="window.location.href='/'">Deconnexion</div>
</nav>
<div class="main">

<!-- ===== DASHBOARD ===== -->
<div class="sec active" id="s-dashboard">
<div class="card"><h2>Tableau de bord dirigeant</h2>
<div class="g4" id="dash-stats">
<div class="sc"><div class="val" id="dash-anomalies">0</div><div class="lab">Anomalies detectees</div></div>
<div class="sc"><div class="val" id="dash-impact">0 EUR</div><div class="lab">Impact total cotisations</div></div>
<div class="sc" style="background:var(--vc)"><div class="val" id="dash-conf">-</div><div class="lab">Conformite</div></div>
<div class="sc"><div class="val" id="dash-docs">0</div><div class="lab">Documents analyses</div></div>
</div></div>
<div class="g2">
<div class="card"><h2>Niveau de conformite</h2>
<div class="gauge" id="gauge" style="--pct:0%"><div class="gauge-inner" id="gauge-val">-</div></div>
<div style="text-align:center;margin-top:10px;font-size:.85em;color:var(--g)">Basee sur les analyses realisees</div>
</div>
<div class="card"><h2>Alertes recentes</h2><div id="dash-alertes"><p style="color:var(--g)">Aucune alerte. Importez des documents pour commencer.</p></div></div>
</div>
<div class="card"><h2>Anomalies par destinataire</h2>
<div id="dash-by-dest" class="g4">
<div class="sc" style="border-left:4px solid #2b6cb0"><div class="val">-</div><div class="lab">URSSAF</div></div>
<div class="sc" style="border-left:4px solid #805ad5"><div class="val">-</div><div class="lab">Fiscal</div></div>
<div class="sc" style="border-left:4px solid #d69e2e"><div class="val">-</div><div class="lab">France Travail</div></div>
<div class="sc" style="border-left:4px solid #319795"><div class="val">-</div><div class="lab">GUSO</div></div>
</div></div>
<div class="card"><h2>Dernieres anomalies (ecarts en EUR)</h2><div id="dash-anomalies-list"><p style="color:var(--g)">Aucune anomalie. Lancez une analyse pour detecter les ecarts.</p></div></div>
</div>

<!-- ===== ANALYSE ===== -->
<div class="sec" id="s-analyse">
<div class="card">
<h2>Importer vos documents</h2>
<div class="uz" id="dz-analyse">
<input type="file" id="fi-analyse" multiple accept=".pdf,.csv,.xlsx,.xls,.xml,.dsn,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.gif,.webp,.txt">
<div style="font-size:2.5em">&#128196;</div>
<h3>Glissez vos fichiers ici</h3>
<p>PDF, Excel, CSV, DSN, XML, Images (JPEG, PNG, TIFF), TXT</p>
</div>
<div id="fl-analyse" style="margin:10px 0"></div>
<div class="al err" id="err-analyse" style="display:none"></div>
<h2 style="margin-top:20px">Format du rapport</h2>
<div class="fmts">
<div class="fopt active" data-fmt="json" onclick="selFmt(this)"><strong>JSON</strong><br><small>Structure</small></div>
<div class="fopt" data-fmt="html" onclick="selFmt(this)"><strong>HTML</strong><br><small>Visuel</small></div>
</div>
<button class="btn btn-p btn-f" id="btn-az" onclick="lancerAnalyse()" disabled>Lancer l'analyse</button>
<div class="prg" id="prg-az"><div class="prg-bar"><div class="prg-fill" id="pf-az"></div></div><div class="prg-txt" id="pt-az">Import...</div></div>
</div>
<div id="res-analyse" style="display:none">
<div class="card">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px">
<h2>Resultats de l'analyse</h2>
<button class="btn btn-s" onclick="resetAz()">Nouvelle analyse</button>
</div>
<div class="g4" id="az-dashboard"></div>
</div>
<div class="card"><h2>Anomalies detectees (ecarts en EUR)</h2><div id="az-findings"></div></div>
<div class="card"><h2>Recommandations de regularisation</h2><div id="az-reco"></div></div>
<div class="card" id="az-html-card" style="display:none"><h2>Rapport HTML</h2><iframe id="az-html-frame" style="width:100%;height:600px;border:1px solid #eee;border-radius:8px"></iframe></div>
</div>
</div>

<!-- ===== FACTURES ===== -->
<div class="sec" id="s-factures">
<div class="g2">
<div class="card">
<h2>Analyser une facture</h2>
<div class="uz" id="dz-fact">
<input type="file" id="fi-fact" accept=".pdf,.csv,.txt,.jpg,.jpeg,.png">
<div style="font-size:2.5em">&#128206;</div>
<h3>Deposer une facture</h3><p>PDF, CSV, TXT, Image</p>
</div>
<div id="fact-fn" style="margin:10px 0"></div>
<button class="btn btn-p btn-f" id="btn-fact" onclick="analyserFacture()" disabled>Analyser</button>
</div>
<div class="card">
<h2>Saisie manuelle</h2>
<label>Type</label>
<select id="f-type"><option value="facture_achat">Facture d'achat</option><option value="facture_vente">Facture de vente</option><option value="avoir_achat">Avoir d'achat</option><option value="avoir_vente">Avoir de vente</option></select>
<div class="g2">
<div><label>Date</label><input type="date" id="f-date"></div>
<div><label>N piece</label><input id="f-num" placeholder="FA-2026-001"></div>
</div>
<label>Tiers</label><input id="f-tiers" placeholder="Nom">
<div class="g3">
<div><label>HT</label><input type="number" step="0.01" id="f-ht" placeholder="0.00"></div>
<div><label>TVA</label><input type="number" step="0.01" id="f-tva" placeholder="0.00"></div>
<div><label>TTC</label><input type="number" step="0.01" id="f-ttc" placeholder="0.00"></div>
</div>
<button class="btn btn-p btn-f" onclick="comptabiliserFacture()">Comptabiliser</button>
<div class="al-just" id="alerte-justif" style="display:none"><strong>Alerte justificatif</strong> : Saisie manuelle sans document justificatif. Cette ecriture sera marquee en rouge dans la comptabilite.</div>
</div>
</div>
<div class="card" id="fact-res" style="display:none"><h2>Resultat</h2><div id="fact-det"></div></div>
</div>

<!-- ===== COMPTABILITE ===== -->
<div class="sec" id="s-compta">
<div class="tabs">
<div class="tab active" onclick="showCT('journal',this)">Journal</div>
<div class="tab" onclick="showCT('balance',this)">Balance</div>
<div class="tab" onclick="showCT('resultat',this)">Resultat</div>
<div class="tab" onclick="showCT('tva',this)">TVA</div>
<div class="tab" onclick="showCT('social',this)">Social</div>
<div class="tab" onclick="showCT('plan',this)">Plan comptable</div>
</div>
<div class="card">
<div style="display:flex;gap:10px;margin-bottom:15px">
<button class="btn btn-p" onclick="loadCompta()">Actualiser</button>
<button class="btn btn-s" onclick="validerEcr()">Valider ecritures</button>
</div>
<div class="tc active" id="ct-journal"><div id="ct-journal-c"></div></div>
<div class="tc" id="ct-balance"><div id="ct-balance-c"></div></div>
<div class="tc" id="ct-resultat"><div id="ct-resultat-c"></div></div>
<div class="tc" id="ct-tva"><div id="ct-tva-c"></div></div>
<div class="tc" id="ct-social"><div id="ct-social-c"></div></div>
<div class="tc" id="ct-plan"><div id="ct-plan-c"></div></div>
</div>
</div>

<!-- ===== SIMULATION ===== -->
<div class="sec" id="s-simulation">
<div class="tabs">
<div class="tab active" onclick="showSimTab('bulletin',this)">Bulletin paie</div>
<div class="tab" onclick="showSimTab('micro',this)">Micro-entrepreneur</div>
<div class="tab" onclick="showSimTab('tns',this)">TNS</div>
<div class="tab" onclick="showSimTab('guso',this)">GUSO</div>
<div class="tab" onclick="showSimTab('ir',this)">Impot revenu</div>
</div>
<div class="card">
<div class="tc active" id="sim-bulletin">
<h2>Simulation bulletin de paie</h2>
<div class="g3">
<div><label>Brut mensuel</label><input type="number" step="0.01" id="sim-brut" value="2500"></div>
<div><label>Effectif</label><input type="number" id="sim-eff" value="10"></div>
<div><label>Cadre</label><select id="sim-cadre"><option value="false">Non</option><option value="true">Oui</option></select></div>
</div>
<button class="btn btn-p" onclick="simBulletin()">Simuler</button>
<div id="sim-bull-res" style="margin-top:15px"></div>
</div>
<div class="tc" id="sim-micro">
<h2>Simulation micro-entrepreneur</h2>
<div class="g3">
<div><label>Chiffre d'affaires</label><input type="number" step="0.01" id="sim-ca" value="50000"></div>
<div><label>Activite</label><select id="sim-act"><option value="prestations_bnc">Prestations BNC</option><option value="prestations_bic">Prestations BIC</option><option value="vente_marchandises">Vente</option><option value="location_meublee">Location meublee</option></select></div>
<div><label>ACRE</label><select id="sim-acre"><option value="false">Non</option><option value="true">Oui</option></select></div>
</div>
<button class="btn btn-p" onclick="simMicro()">Simuler</button>
<div id="sim-micro-res" style="margin-top:15px"></div>
</div>
<div class="tc" id="sim-tns">
<h2>Simulation TNS</h2>
<div class="g3">
<div><label>Revenu net</label><input type="number" step="0.01" id="sim-rev" value="40000"></div>
<div><label>Statut</label><select id="sim-stat"><option value="gerant_majoritaire">Gerant majoritaire</option><option value="profession_liberale">Profession liberale</option><option value="artisan">Artisan</option><option value="commercant">Commercant</option></select></div>
<div><label>ACRE</label><select id="sim-tacre"><option value="false">Non</option><option value="true">Oui</option></select></div>
</div>
<button class="btn btn-p" onclick="simTNS()">Simuler</button>
<div id="sim-tns-res" style="margin-top:15px"></div>
</div>
<div class="tc" id="sim-guso">
<h2>Simulation GUSO</h2>
<div class="g2">
<div><label>Salaire brut</label><input type="number" step="0.01" id="sim-gbrut" value="500"></div>
<div><label>Nb heures</label><input type="number" step="0.5" id="sim-gh" value="8"></div>
</div>
<button class="btn btn-p" onclick="simGUSO()">Simuler</button>
<div id="sim-guso-res" style="margin-top:15px"></div>
</div>
<div class="tc" id="sim-ir">
<h2>Simulation impot sur le revenu</h2>
<div class="g3">
<div><label>Benefice</label><input type="number" step="0.01" id="sim-ben" value="40000"></div>
<div><label>Nb parts</label><input type="number" step="0.5" id="sim-parts" value="1"></div>
<div><label>Autres revenus</label><input type="number" step="0.01" id="sim-autres" value="0"></div>
</div>
<button class="btn btn-p" onclick="simIR()">Simuler</button>
<div id="sim-ir-res" style="margin-top:15px"></div>
</div>
</div>
</div>

<!-- ===== VEILLE ===== -->
<div class="sec" id="s-veille">
<div class="card">
<h2>Veille Juridique URSSAF / Legifrance</h2>
<div class="g3" style="margin-bottom:15px">
<div><label>Annee</label><select id="v-annee"><option value="2024">2024</option><option value="2025">2025</option><option value="2026" selected>2026</option></select></div>
<div><button class="btn btn-p btn-f" onclick="loadVeille()" style="margin-top:22px">Charger</button></div>
<div><button class="btn btn-s btn-f" onclick="compAnnees()" style="margin-top:22px">Comparer N-1</button></div>
</div>
</div>
<div id="v-res" style="display:none">
<div class="card"><h2>Baremes URSSAF</h2><div id="v-baremes"></div></div>
<div class="card"><h2>Legislation</h2><div id="v-legis"></div></div>
<div class="card" id="v-comp-card" style="display:none"><h2>Comparaison</h2><div id="v-comp"></div></div>
</div>
</div>

<!-- ===== DOCUMENTS ===== -->
<div class="sec" id="s-documents">
<div class="g2">
<div class="card">
<h2>Extraire informations juridiques</h2>
<div class="uz"><input type="file" id="fi-doc-jur" accept=".pdf,.jpg,.jpeg,.png,.txt"><div style="font-size:2.5em">&#128195;</div><h3>KBIS, Statuts, etc.</h3><p>PDF ou Image</p></div>
<button class="btn btn-p btn-f" onclick="extraireDoc()" style="margin-top:10px">Extraire</button>
</div>
<div class="card">
<h2>Lire tout document</h2>
<div class="uz"><input type="file" id="fi-doc-lire" accept="*/*"><div style="font-size:2.5em">&#128206;</div><h3>Tout format</h3><p>PDF, Images, Excel, CSV, TXT, DSN</p></div>
<button class="btn btn-p btn-f" onclick="lireDoc()" style="margin-top:10px">Lire</button>
</div>
</div>
<div class="card" id="doc-res" style="display:none"><h2>Resultat extraction</h2><div id="doc-det"></div></div>
</div>

<!-- ===== PORTEFEUILLE ===== -->
<div class="sec" id="s-portefeuille">
<div class="g2">
<div class="card">
<h2>Ajouter une entreprise</h2>
<label>SIRET</label><input id="ent-siret" placeholder="12345678901234" maxlength="14">
<label>Raison sociale</label><input id="ent-raison" placeholder="Nom">
<div class="g2">
<div><label>Forme juridique</label><input id="ent-forme" placeholder="SAS, SARL..."></div>
<div><label>Code NAF</label><input id="ent-naf" placeholder="6201Z"></div>
</div>
<div class="g2">
<div><label>Effectif</label><input type="number" id="ent-eff" value="0"></div>
<div><label>Ville</label><input id="ent-ville" placeholder="Paris"></div>
</div>
<button class="btn btn-p btn-f" onclick="ajouterEnt()">Ajouter</button>
</div>
<div class="card">
<h2>Rechercher</h2>
<input id="ent-search" placeholder="Rechercher..." oninput="rechEnt()">
<div id="ent-list"></div>
</div>
</div>
</div>

</div>
<footer style="text-align:center;padding:30px;color:var(--g);font-size:.85em">URSSAF Analyzer v3.0.0</footer>

<script>
/* === NAV === */
function showS(n,el){document.querySelectorAll('.sec').forEach(s=>s.classList.remove('active'));document.querySelectorAll('.nl').forEach(l=>l.classList.remove('active'));var sec=document.getElementById('s-'+n);if(sec)sec.classList.add('active');if(el)el.classList.add('active');if(n==='compta')loadCompta();if(n==='portefeuille')rechEnt();if(n==='dashboard')loadDash();}

document.addEventListener('click',function(e){var a=e.target.closest('.anomalie[data-toggle]');if(a)a.classList.toggle('open');});

/* === DASHBOARD === */
let analysisData=null;
function loadDash(){
if(!analysisData)return;
const d=analysisData,s=d.synthese||{};
const impact=s.impact_financier_total||0;
const constats=d.constats||[];
document.getElementById('dash-anomalies').textContent=constats.length;
document.getElementById('dash-impact').textContent=impact.toFixed(2)+' EUR';
const conf=Math.max(0,100-(s.score_risque_global||0));
document.getElementById('dash-conf').textContent=conf+'%';
document.getElementById('gauge').style.setProperty('--pct',conf+'%');
document.getElementById('gauge-val').textContent=conf+'%';
renderAnomalies('dash-anomalies-list',constats);
}

function renderAnomalies(id,constats){
const el=document.getElementById(id);
if(!constats.length){el.innerHTML='<p style="color:var(--g)">Aucune anomalie detectee.</p>';return;}
let h='';
constats.slice(0,30).forEach((c,i)=>{
const impact=c.montant_impact||0;
const neg=impact>0;
const dest=categToDest(c.categorie||'');
const destCls={'URSSAF':'badge-urssaf','Fiscal':'badge-fiscal','France Travail':'badge-ft','GUSO':'badge-guso'}[dest]||'badge-urssaf';
h+='<div class="anomalie '+(neg?'neg':'pos')+'" data-toggle="1">';
h+='<div class="head"><div><strong>'+(c.titre||'Ecart')+'</strong>';
h+='<span class="dest '+destCls+'">'+dest+'</span>';
h+=' <span class="badge '+(neg?'badge-neg':'badge-pos')+'">'+(neg?'Defavorable':'Favorable')+'</span></div>';
h+='<div class="montant '+(neg?'neg':'pos')+'">'+(neg?'+':'-')+Math.abs(impact).toFixed(2)+' EUR</div></div>';
h+='<div class="detail">';
h+='<p><strong>Nature :</strong> '+(c.description||'').substring(0,200)+'</p>';
h+='<p><strong>Categorie :</strong> '+(c.categorie||'-')+'</p>';
h+='<p><strong>Annee :</strong> '+(c.annee||c.periode||'-')+'</p>';
h+='<p><strong>Documents concernes :</strong> '+(c.source||c.document||'-')+'</p>';
h+='<p><strong>Lignes / Libelles :</strong> '+(c.rubrique||c.libelle||'-')+'</p>';
h+='<p><strong>Incidence en cotisations :</strong> '+Math.abs(impact).toFixed(2)+' EUR '+(neg?'(surcharge)':'(economie)')+'</p>';
if(c.recommandation)h+='<div class="al info" style="margin-top:8px"><strong>Regularisation suggeree :</strong> '+c.recommandation+'</div>';
h+='</div></div>';
});
el.innerHTML=h;
}

function categToDest(cat){
const c=cat.toLowerCase();
if(c.includes('fiscal')||c.includes('impot')||c.includes('ir')||c.includes('is'))return'Fiscal';
if(c.includes('france travail')||c.includes('chomage')||c.includes('pole'))return'France Travail';
if(c.includes('guso')||c.includes('spectacle'))return'GUSO';
return'URSSAF';
}

/* === ANALYSE === */
let fichiers=[],fmtR='json';
const dz=document.getElementById('dz-analyse'),fi=document.getElementById('fi-analyse');
['dragenter','dragover'].forEach(e=>dz.addEventListener(e,ev=>{ev.preventDefault();}));
dz.addEventListener('drop',ev=>{ev.preventDefault();addF(ev.dataTransfer.files);});
fi.addEventListener('change',ev=>{addF(ev.target.files);fi.value='';});
function addF(files){for(const f of files){if(!fichiers.find(x=>x.name===f.name))fichiers.push(f);}renderF();}
function renderF(){document.getElementById('fl-analyse').innerHTML=fichiers.map((f,i)=>'<div class="fi"><span class="nm">'+f.name+'</span><span>'+(f.size/1024).toFixed(1)+' Ko</span><button class="rm" onclick="rmF('+i+')">&times;</button></div>').join('');document.getElementById('btn-az').disabled=fichiers.length===0;}
function rmF(i){fichiers.splice(i,1);renderF();}
function selFmt(el){document.querySelectorAll('.fopt').forEach(o=>o.classList.remove('active'));el.classList.add('active');fmtR=el.dataset.fmt;}

async function lancerAnalyse(){
if(!fichiers.length)return;
const btn=document.getElementById('btn-az'),prg=document.getElementById('prg-az'),fill=document.getElementById('pf-az'),txt=document.getElementById('pt-az');
btn.disabled=true;prg.style.display='block';document.getElementById('res-analyse').style.display='none';
const steps=[[10,'Import...'],[30,'Integrite SHA-256...'],[50,'Parsing...'],[70,'Anomalies...'],[85,'Patterns...'],[95,'Rapport...']];
let si=0;const iv=setInterval(()=>{if(si<steps.length){fill.style.width=steps[si][0]+'%';txt.textContent=steps[si][1];si++;}},800);
const fd=new FormData();fichiers.forEach(f=>fd.append('fichiers',f));
try{
const resp=await fetch('/api/analyze?format_rapport='+fmtR,{method:'POST',body:fd});
clearInterval(iv);fill.style.width='100%';txt.textContent='Termine !';
if(!resp.ok){const e=await resp.json().catch(()=>({}));throw new Error(e.detail||'Erreur');}
if(fmtR==='html'){const html=await resp.text();document.getElementById('az-dashboard').innerHTML='';document.getElementById('az-findings').innerHTML='';document.getElementById('az-reco').innerHTML='';document.getElementById('az-html-card').style.display='block';document.getElementById('az-html-frame').srcdoc=html;}
else{const data=await resp.json();analysisData=data;showJsonResults(data);}
setTimeout(()=>{prg.style.display='none';},800);
document.getElementById('res-analyse').style.display='block';
}catch(e){clearInterval(iv);prg.style.display='none';alert(e.message);btn.disabled=false;}
}

function showJsonResults(data){
const s=data.synthese||{};const impact=s.impact_financier_total||0;
document.getElementById('az-dashboard').innerHTML=
'<div class="sc"><div class="val">'+((data.constats||[]).length)+'</div><div class="lab">Anomalies</div></div>'+
'<div class="sc"><div class="val">'+impact.toFixed(2)+' EUR</div><div class="lab">Impact cotisations</div></div>'+
'<div class="sc" style="background:'+(impact>1000?'var(--rc)':'var(--vc)')+'"><div class="val">'+Math.max(0,100-(s.score_risque_global||0))+'%</div><div class="lab">Conformite</div></div>'+
'<div class="sc"><div class="val">'+(s.nb_fichiers||0)+'</div><div class="lab">Fichiers</div></div>';
renderAnomalies('az-findings',data.constats||[]);
document.getElementById('az-reco').innerHTML=(data.recommandations||[]).map((r,i)=>'<div class="al info"><strong>#'+(i+1)+' '+(r.titre||'')+'</strong><br>'+(r.description||'')+'</div>').join('')||'<p>Aucune recommandation.</p>';
document.getElementById('az-html-card').style.display='none';
document.getElementById('dash-docs').textContent=(s.nb_fichiers||0);
loadDash();
}

function resetAz(){fichiers=[];renderF();document.getElementById('res-analyse').style.display='none';window.scrollTo({top:0,behavior:'smooth'});}

/* === FACTURES === */
let factFile=null;
document.getElementById('fi-fact').addEventListener('change',ev=>{factFile=ev.target.files[0];if(factFile){document.getElementById('fact-fn').innerHTML='<div class="fi"><span class="nm">'+factFile.name+'</span></div>';document.getElementById('btn-fact').disabled=false;}});
async function analyserFacture(){
if(!factFile)return;const fd=new FormData();fd.append('fichier',factFile);
try{const r=await fetch('/api/factures/analyser',{method:'POST',body:fd});if(!r.ok)throw new Error((await r.json()).detail||'Erreur');
const d=await r.json();document.getElementById('fact-res').style.display='block';
let h='<div class="g4">';
h+='<div class="sc"><div class="val">'+(d.type_document||'?')+'</div><div class="lab">Type</div></div>';
h+='<div class="sc"><div class="val">'+(d.montant_ttc||0).toFixed(2)+'</div><div class="lab">TTC (EUR)</div></div>';
h+='<div class="sc"><div class="val">'+((d.confiance||0)*100).toFixed(0)+'%</div><div class="lab">Confiance</div></div>';
h+='<div class="sc"><div class="val">'+(d.ecriture_manuscrite?'Oui':'Non')+'</div><div class="lab">Manuscrit</div></div></div>';
if(d.emetteur)h+='<p><strong>Emetteur:</strong> '+(d.emetteur.nom||'?')+' (SIRET: '+(d.emetteur.siret||'?')+')</p>';
if(d.lignes&&d.lignes.length){h+='<table style="margin-top:10px"><tr><th>Description</th><th>Qte</th><th>PU</th><th>HT</th></tr>';d.lignes.forEach(l=>{h+='<tr><td>'+l.description+'</td><td class="num">'+l.quantite+'</td><td class="num">'+l.prix_unitaire.toFixed(2)+'</td><td class="num">'+l.montant_ht.toFixed(2)+'</td></tr>';});h+='</table>';}
if(d.type_document)document.getElementById('f-type').value=d.type_document;
if(d.date_piece)document.getElementById('f-date').value=d.date_piece;
if(d.numero)document.getElementById('f-num').value=d.numero;
if(d.emetteur)document.getElementById('f-tiers').value=d.emetteur.nom||'';
document.getElementById('f-ht').value=d.montant_ht||0;document.getElementById('f-tva').value=d.montant_tva||0;document.getElementById('f-ttc').value=d.montant_ttc||0;
document.getElementById('fact-det').innerHTML=h;
document.getElementById('alerte-justif').style.display='none';
}catch(e){alert(e.message);}
}

async function comptabiliserFacture(){
const hasJustif=!!factFile;
if(!hasJustif)document.getElementById('alerte-justif').style.display='block';
const fd=new FormData();
fd.append('type_doc',document.getElementById('f-type').value);
fd.append('date_piece',document.getElementById('f-date').value);
fd.append('numero_piece',document.getElementById('f-num').value);
fd.append('montant_ht',document.getElementById('f-ht').value||'0');
fd.append('montant_tva',document.getElementById('f-tva').value||'0');
fd.append('montant_ttc',document.getElementById('f-ttc').value||'0');
fd.append('nom_tiers',document.getElementById('f-tiers').value);
try{const r=await fetch('/api/factures/comptabiliser',{method:'POST',body:fd});if(!r.ok)throw new Error((await r.json()).detail||'Erreur');
const d=await r.json();
let h='<div class="al '+(hasJustif?'ok':'err')+'"><strong>Ecriture '+(hasJustif?'generee':'generee SANS JUSTIFICATIF')+'</strong> ID: '+d.ecriture_id+'</div>';
h+='<table><tr><th>Compte</th><th>Libelle</th><th class="num">Debit</th><th class="num">Credit</th></tr>';
d.lignes.forEach(l=>{h+='<tr'+(hasJustif?'':' style="background:var(--rc)"')+'><td>'+l.compte+'</td><td>'+l.libelle+(hasJustif?'':' [SANS JUSTIFICATIF]')+'</td><td class="num">'+l.debit.toFixed(2)+'</td><td class="num">'+l.credit.toFixed(2)+'</td></tr>';});
h+='</table>';
document.getElementById('fact-res').style.display='block';document.getElementById('fact-det').innerHTML=h;
}catch(e){alert(e.message);}
}

/* === COMPTABILITE === */
function showCT(n,el){document.querySelectorAll('#s-compta .tab').forEach(t=>t.classList.remove('active'));document.querySelectorAll('#s-compta .tc').forEach(t=>t.classList.remove('active'));if(el)el.classList.add('active');document.getElementById('ct-'+n).classList.add('active');loadCompta();}
async function loadCompta(){
try{const j=await(await fetch('/api/comptabilite/journal')).json();let h=j.length?'':'<p>Aucune ecriture.</p>';j.forEach(e=>{h+='<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px;margin:8px 0"><strong>'+e.date+' | '+e.journal+' | '+e.piece+'</strong> - '+e.libelle+' <span class="badge '+(e.validee?'badge-pos':'badge-neg')+'">'+(e.validee?'Validee':'Brouillon')+'</span><table style="margin-top:8px"><tr><th>Compte</th><th>Libelle</th><th class="num">Debit</th><th class="num">Credit</th></tr>';e.lignes.forEach(l=>{h+='<tr><td>'+l.compte+'</td><td>'+l.libelle+'</td><td class="num">'+l.debit.toFixed(2)+'</td><td class="num">'+l.credit.toFixed(2)+'</td></tr>';});h+='</table></div>';});document.getElementById('ct-journal-c').innerHTML=h;}catch(e){}
try{const b=await(await fetch('/api/comptabilite/balance')).json();let h=b.length?'<table><tr><th>Compte</th><th>Libelle</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Solde D</th><th class="num">Solde C</th></tr>':'<p>Aucune donnee.</p>';b.forEach(r=>{h+='<tr><td>'+r.compte+'</td><td>'+r.libelle+'</td><td class="num">'+r.total_debit.toFixed(2)+'</td><td class="num">'+r.total_credit.toFixed(2)+'</td><td class="num">'+r.solde_debiteur.toFixed(2)+'</td><td class="num">'+r.solde_crediteur.toFixed(2)+'</td></tr>';});if(b.length)h+='</table>';document.getElementById('ct-balance-c').innerHTML=h;}catch(e){}
try{const cr=await(await fetch('/api/comptabilite/compte-resultat')).json();let h='<div class="g2"><div><h3>Charges: '+cr.charges.total.toFixed(2)+' EUR</h3></div><div><h3>Produits: '+cr.produits.total.toFixed(2)+' EUR</h3></div></div>';const clr=cr.resultat_net>=0?'var(--v)':'var(--r)';h+='<div class="sc" style="margin-top:15px;background:'+(cr.resultat_net>=0?'var(--vc)':'var(--rc)')+'"><div class="val" style="color:'+clr+'">'+cr.resultat_net.toFixed(2)+' EUR</div><div class="lab">Resultat net</div></div>';document.getElementById('ct-resultat-c').innerHTML=h;}catch(e){}
try{const now=new Date();const t=await(await fetch('/api/comptabilite/declaration-tva?mois='+now.getMonth()+'&annee='+now.getFullYear())).json();let h='<div class="g3"><div class="sc"><div class="val">'+t.chiffre_affaires_ht.toFixed(2)+'</div><div class="lab">CA HT</div></div><div class="sc"><div class="val">'+t.tva_collectee.toFixed(2)+'</div><div class="lab">TVA collectee</div></div><div class="sc"><div class="val">'+t.tva_deductible_totale.toFixed(2)+'</div><div class="lab">TVA deductible</div></div></div>';h+='<div class="sc" style="margin-top:15px"><div class="val">'+(t.tva_nette_a_payer>0?t.tva_nette_a_payer.toFixed(2)+' a payer':t.credit_tva.toFixed(2)+' credit')+'</div><div class="lab">TVA nette</div></div>';document.getElementById('ct-tva-c').innerHTML=h;}catch(e){}
try{const soc=await(await fetch('/api/comptabilite/charges-sociales')).json();let h='<table><tr><th>Poste</th><th class="num">Montant (EUR)</th></tr>';const lbl={'salaires_bruts':'Salaires bruts','cotisations_urssaf':'Cotisations URSSAF','cotisations_retraite':'Retraite','mutuelle_prevoyance':'Mutuelle','france_travail':'France Travail','total_charges_sociales':'TOTAL charges','cout_total_employeur':'Cout total'};for(const[k,l] of Object.entries(lbl)){h+='<tr'+(k.startsWith('total')||k.startsWith('cout')?' style="font-weight:bold;background:var(--bc)"':'')+'><td>'+l+'</td><td class="num">'+(soc[k]||0).toFixed(2)+'</td></tr>';}h+='</table>';document.getElementById('ct-social-c').innerHTML=h;}catch(e){}
try{const pc=await(await fetch('/api/comptabilite/plan-comptable')).json();let h='<input placeholder="Rechercher..." oninput="rechPC(this.value)" style="margin-bottom:10px"><table id="pc-t"><tr><th>N</th><th>Libelle</th><th>Classe</th></tr>';pc.forEach(c=>{h+='<tr><td>'+c.numero+'</td><td>'+c.libelle+'</td><td>'+c.classe+'</td></tr>';});h+='</table>';document.getElementById('ct-plan-c').innerHTML=h;}catch(e){}
}
async function rechPC(t){const url=t?'/api/comptabilite/plan-comptable?terme='+encodeURIComponent(t):'/api/comptabilite/plan-comptable';const pc=await(await fetch(url)).json();const tb=document.getElementById('pc-t');if(!tb)return;let h='<tr><th>N</th><th>Libelle</th><th>Classe</th></tr>';pc.forEach(c=>{h+='<tr><td>'+c.numero+'</td><td>'+c.libelle+'</td><td>'+c.classe+'</td></tr>';});tb.innerHTML=h;}
async function validerEcr(){try{const r=await fetch('/api/comptabilite/valider',{method:'POST'});const d=await r.json();alert('Validees: '+d.nb_validees+(d.erreurs.length?' | Erreurs: '+d.erreurs.join(', '):''));loadCompta();}catch(e){alert(e.message);}}

/* === SIMULATION === */
function showSimTab(n,el){document.querySelectorAll('#s-simulation .tab').forEach(t=>t.classList.remove('active'));document.querySelectorAll('#s-simulation .tc').forEach(t=>t.classList.remove('active'));if(el)el.classList.add('active');document.getElementById('sim-'+n).classList.add('active');}
async function simBulletin(){try{const r=await(await fetch('/api/simulation/bulletin?brut_mensuel='+document.getElementById('sim-brut').value+'&effectif='+document.getElementById('sim-eff').value+'&est_cadre='+document.getElementById('sim-cadre').value)).json();let h='<div class="g3"><div class="sc"><div class="val">'+r.brut_mensuel.toFixed(2)+'</div><div class="lab">Brut</div></div><div class="sc"><div class="val">'+r.net_a_payer.toFixed(2)+'</div><div class="lab">Net a payer</div></div><div class="sc"><div class="val">'+r.cout_total_employeur.toFixed(2)+'</div><div class="lab">Cout employeur</div></div></div>';h+='<table style="margin-top:15px"><tr><th>Rubrique</th><th class="num">Patronal</th><th class="num">Salarial</th></tr>';(r.lignes||[]).forEach(l=>{h+='<tr><td>'+l.libelle+'</td><td class="num">'+l.montant_patronal.toFixed(2)+'</td><td class="num">'+l.montant_salarial.toFixed(2)+'</td></tr>';});h+='</table>';document.getElementById('sim-bull-res').innerHTML=h;}catch(e){alert(e.message);}}
async function simMicro(){try{const r=await(await fetch('/api/simulation/micro-entrepreneur?chiffre_affaires='+document.getElementById('sim-ca').value+'&activite='+document.getElementById('sim-act').value+'&acre='+document.getElementById('sim-acre').value)).json();let h='<div class="g4">';for(const[k,v] of Object.entries(r)){if(typeof v==='number')h+='<div class="sc"><div class="val">'+v.toFixed(2)+'</div><div class="lab">'+k.replace(/_/g,' ')+'</div></div>';}h+='</div>';document.getElementById('sim-micro-res').innerHTML=h;}catch(e){alert(e.message);}}
async function simTNS(){try{const r=await(await fetch('/api/simulation/tns?revenu_net='+document.getElementById('sim-rev').value+'&type_statut='+document.getElementById('sim-stat').value+'&acre='+document.getElementById('sim-tacre').value)).json();let h='<div class="g4">';for(const[k,v] of Object.entries(r)){if(typeof v==='number')h+='<div class="sc"><div class="val">'+v.toFixed(2)+'</div><div class="lab">'+k.replace(/_/g,' ')+'</div></div>';}h+='</div>';document.getElementById('sim-tns-res').innerHTML=h;}catch(e){alert(e.message);}}
async function simGUSO(){try{const r=await(await fetch('/api/simulation/guso?salaire_brut='+document.getElementById('sim-gbrut').value+'&nb_heures='+document.getElementById('sim-gh').value)).json();let h='<div class="g4">';for(const[k,v] of Object.entries(r)){if(typeof v==='number')h+='<div class="sc"><div class="val">'+v.toFixed(2)+'</div><div class="lab">'+k.replace(/_/g,' ')+'</div></div>';}h+='</div>';document.getElementById('sim-guso-res').innerHTML=h;}catch(e){alert(e.message);}}
async function simIR(){try{const r=await(await fetch('/api/simulation/impot-independant?benefice='+document.getElementById('sim-ben').value+'&nb_parts='+document.getElementById('sim-parts').value+'&autres_revenus='+document.getElementById('sim-autres').value)).json();let h='<div class="g4">';for(const[k,v] of Object.entries(r)){if(typeof v==='number')h+='<div class="sc"><div class="val">'+v.toFixed(2)+'</div><div class="lab">'+k.replace(/_/g,' ')+'</div></div>';}h+='</div>';document.getElementById('sim-ir-res').innerHTML=h;}catch(e){alert(e.message);}}

/* === VEILLE === */
async function loadVeille(){const a=document.getElementById('v-annee').value;document.getElementById('v-res').style.display='block';try{const b=await(await fetch('/api/veille/baremes/'+a)).json();let h='<table><tr><th>Parametre</th><th class="num">Valeur</th></tr>';for(const[k,v] of Object.entries(b)){h+='<tr><td>'+k.replace(/_/g,' ')+'</td><td class="num">'+v+'</td></tr>';}h+='</table>';document.getElementById('v-baremes').innerHTML=h;}catch(e){}
try{const l=await(await fetch('/api/veille/legislation/'+a)).json();let h='<p><strong>'+l.description+'</strong></p>';(l.textes_cles||[]).forEach(t=>{h+='<div class="al info" style="margin:8px 0"><strong>'+t.reference+'</strong> - '+t.titre+'<br><small>'+t.resume+'</small></div>';});document.getElementById('v-legis').innerHTML=h;}catch(e){}}
async function compAnnees(){const a2=parseInt(document.getElementById('v-annee').value),a1=a2-1;try{const d=await(await fetch('/api/veille/baremes/comparer/'+a1+'/'+a2)).json();if(!d.length){alert('Pas de differences.');return;}let h='<table><tr><th>Parametre</th><th class="num">'+a1+'</th><th class="num">'+a2+'</th><th>Evolution</th></tr>';d.forEach(r=>{h+='<tr><td>'+r.parametre+'</td><td class="num">'+(r['valeur_'+a1]||'-')+'</td><td class="num">'+(r['valeur_'+a2]||'-')+'</td><td>'+r.evolution+'</td></tr>';});h+='</table>';document.getElementById('v-comp').innerHTML=h;document.getElementById('v-comp-card').style.display='block';}catch(e){alert(e.message);}}

/* === DOCUMENTS === */
async function extraireDoc(){const f=document.getElementById('fi-doc-jur').files[0];if(!f){alert('Selectionnez un fichier.');return;}const fd=new FormData();fd.append('fichier',f);try{const r=await fetch('/api/documents/extraire',{method:'POST',body:fd});if(!r.ok)throw new Error((await r.json()).detail||'Erreur');const d=await r.json();const i=d.info_entreprise||{};let h='<div class="g4">';for(const[k,v] of Object.entries(i)){if(v)h+='<div class="sc"><div class="val" style="font-size:1em">'+v+'</div><div class="lab">'+k.replace(/_/g,' ')+'</div></div>';}h+='</div>';if(d.avertissements&&d.avertissements.length)h+=d.avertissements.map(a=>'<div class="al warn">'+a+'</div>').join('');document.getElementById('doc-res').style.display='block';document.getElementById('doc-det').innerHTML=h;}catch(e){alert(e.message);}}
async function lireDoc(){const f=document.getElementById('fi-doc-lire').files[0];if(!f){alert('Selectionnez un fichier.');return;}const fd=new FormData();fd.append('fichier',f);try{const r=await fetch('/api/documents/lire',{method:'POST',body:fd});if(!r.ok)throw new Error((await r.json()).detail||'Erreur');const d=await r.json();let h='<div class="g4"><div class="sc"><div class="val">'+d.format+'</div><div class="lab">Format</div></div><div class="sc"><div class="val">'+(d.nb_pages||1)+'</div><div class="lab">Pages</div></div><div class="sc"><div class="val">'+(d.manuscrit_detecte?'Oui':'Non')+'</div><div class="lab">Manuscrit</div></div><div class="sc"><div class="val">'+(d.est_scan?'Oui':'Non')+'</div><div class="lab">Scan</div></div></div>';h+='<div style="margin-top:15px;background:#f7fafc;border-radius:8px;padding:15px;max-height:400px;overflow:auto;white-space:pre-wrap;font-size:.85em;font-family:monospace">'+d.texte+'</div>';if(d.avertissements&&d.avertissements.length)h+=d.avertissements.map(a=>'<div class="al warn">'+a+'</div>').join('');document.getElementById('doc-res').style.display='block';document.getElementById('doc-det').innerHTML=h;}catch(e){alert(e.message);}}

/* === PORTEFEUILLE === */
async function ajouterEnt(){const fd=new FormData();fd.append('siret',document.getElementById('ent-siret').value);fd.append('raison_sociale',document.getElementById('ent-raison').value);fd.append('forme_juridique',document.getElementById('ent-forme').value);fd.append('code_naf',document.getElementById('ent-naf').value);fd.append('effectif',document.getElementById('ent-eff').value||'0');fd.append('ville',document.getElementById('ent-ville').value);try{const r=await fetch('/api/entreprises',{method:'POST',body:fd});if(!r.ok)throw new Error((await r.json()).detail||'Erreur');alert('Entreprise ajoutee !');rechEnt();}catch(e){alert(e.message);}}
async function rechEnt(){const q=(document.getElementById('ent-search')||{}).value||'';try{const d=await(await fetch('/api/entreprises?q='+encodeURIComponent(q))).json();let h=d.length?'':'<p style="color:var(--g)">Aucune entreprise.</p>';d.forEach(e=>{h+='<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px;margin:8px 0"><strong>'+e.raison_sociale+'</strong><br><small>SIRET: '+e.siret+' | '+(e.ville||'')+(e.forme_juridique?' | '+e.forme_juridique:'')+'</small></div>';});document.getElementById('ent-list').innerHTML=h;}catch(e){}}
</script>
</body>
</html>"""
