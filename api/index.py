"""Clara - Plateforme professionnelle de conformite sociale et fiscale.

Point d'entree web : import/analyse de documents, gestion entreprise,
comptabilite, simulation, veille juridique, portefeuille.
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
    title="Clara",
    description="Plateforme professionnelle de conformite sociale et fiscale",
    version="3.2.0",
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
        pass


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
    return {"status": "ok", "version": "3.2.0", "nom": "Clara",
            "formats_supportes": list(SUPPORTED_EXTENSIONS.keys()),
            "limite_fichiers": 20, "limite_taille_mo": 50}


@app.get("/api/formats")
async def formats():
    return {"formats": [{"extension": ext, "type": typ} for ext, typ in SUPPORTED_EXTENSIONS.items()]}


# ==============================
# API VEILLE JURIDIQUE
# ==============================

@app.get("/api/veille/baremes/{annee}")
async def baremes_annee(annee: int):
    return get_baremes_annee(annee)


@app.get("/api/veille/baremes/comparer/{annee1}/{annee2}")
async def comparer_baremes_api(annee1: int, annee2: int):
    return comparer_baremes(annee1, annee2)


@app.get("/api/veille/legislation/{annee}")
async def legislation_annee(annee: int):
    return get_legislation_par_annee(annee)


@app.get("/api/veille/annees-disponibles")
async def annees_disponibles():
    return {
        "baremes": sorted(BAREMES_PAR_ANNEE.keys()),
        "legislation": sorted(ARTICLES_CSS_COTISATIONS.keys()),
    }


@app.get("/api/veille/alertes")
async def alertes_recentes(limit: int = Query(50, ge=1, le=200)):
    db = get_db()
    vm = VeilleManager(db)
    return vm.get_alertes_recentes(limit=limit)


@app.post("/api/veille/executer")
async def executer_veille(annee: int = Form(...), mois: int = Form(...)):
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
    db = get_db()
    pm = PortfolioManager(db)
    try:
        return pm.creer_profil(nom, prenom, email, mot_de_passe, role)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/profils/auth")
async def authentifier(email: str = Form(...), mot_de_passe: str = Form(...)):
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
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    rules = ContributionRules(
        effectif_entreprise=effectif,
        taux_at=Decimal(str(taux_at)),
        taux_versement_mobilite=Decimal(str(taux_vm)),
    )
    bulletin = rules.calculer_bulletin_complet(Decimal(str(brut_mensuel)), est_cadre)
    for l in bulletin["lignes"]:
        l["montant_patronal"] = float(l["montant_patronal"])
        l["montant_salarial"] = float(l["montant_salarial"])
    return bulletin


@app.get("/api/simulation/rgdu")
async def simulation_rgdu(
    brut_annuel: float = Query(...),
    effectif: int = Query(10),
):
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    rules = ContributionRules(effectif_entreprise=effectif)
    return rules.detail_rgdu(Decimal(str(brut_annuel)))


@app.get("/api/simulation/net-imposable")
async def simulation_net_imposable(
    brut_mensuel: float = Query(...),
    effectif: int = Query(10),
    est_cadre: bool = Query(False),
):
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    rules = ContributionRules(effectif_entreprise=effectif)
    result = rules.calculer_net_imposable(Decimal(str(brut_mensuel)), est_cadre)
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in result.items()}


@app.get("/api/simulation/taxe-salaires")
async def simulation_taxe_salaires(brut_annuel: float = Query(...)):
    from urssaf_analyzer.rules.contribution_rules import ContributionRules
    rules = ContributionRules()
    return rules.calculer_taxe_salaires(Decimal(str(brut_annuel)))


# ==============================
# API FACTURES / OCR
# ==============================

@app.post("/api/factures/analyser")
async def analyser_facture(fichier: UploadFile = File(...)):
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
    from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_guso
    return calculer_cotisations_guso(Decimal(str(salaire_brut)), Decimal(str(nb_heures)))


@app.get("/api/simulation/artistes-auteurs")
async def simulation_artistes_auteurs(
    revenus_bruts: float = Query(...),
    est_bda: bool = Query(True),
):
    from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_artistes_auteurs
    return calculer_cotisations_artistes_auteurs(Decimal(str(revenus_bruts)), est_bda=est_bda)


# ==============================
# API CONVENTIONS COLLECTIVES
# ==============================

@app.get("/api/conventions-collectives")
async def lister_conventions_api():
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
# API GRAND LIVRE / BILAN DETAILLE
# ==============================

@app.get("/api/comptabilite/grand-livre-detail")
async def grand_livre_detail(
    date_debut: str = Query("", description="YYYY-MM-DD"),
    date_fin: str = Query("", description="YYYY-MM-DD"),
):
    """Grand livre detaille avec selection de periode."""
    moteur = get_moteur()
    gl = moteur.get_grand_livre()
    if date_debut:
        try:
            dd = date.fromisoformat(date_debut)
            df = date.fromisoformat(date_fin) if date_fin else date.today()
            for compte in gl:
                if "mouvements" in compte:
                    compte["mouvements"] = [
                        m for m in compte["mouvements"]
                        if dd <= date.fromisoformat(m.get("date", "2099-01-01")) <= df
                    ]
        except ValueError:
            pass
    for compte in gl:
        for m in compte.get("mouvements", []):
            m["sans_justificatif"] = "[SANS JUSTIFICATIF]" in m.get("libelle", "")
    return gl


@app.get("/api/comptabilite/bilan")
async def bilan_api():
    """Genere un bilan simplifie."""
    moteur = get_moteur()
    balance = moteur.get_balance()
    actif = {"immobilisations": 0, "stocks": 0, "creances": 0, "tresorerie": 0, "total": 0}
    passif = {"capitaux_propres": 0, "dettes_financieres": 0, "dettes_exploitation": 0, "total": 0}
    for c in balance:
        num = c.get("compte", "")
        solde_d = c.get("solde_debiteur", 0)
        solde_c = c.get("solde_crediteur", 0)
        if num.startswith("2"):
            actif["immobilisations"] += solde_d - solde_c
        elif num.startswith("3"):
            actif["stocks"] += solde_d - solde_c
        elif num.startswith("4") and num < "45":
            actif["creances"] += solde_d
            passif["dettes_exploitation"] += solde_c
        elif num.startswith("5"):
            actif["tresorerie"] += solde_d - solde_c
        elif num.startswith("1"):
            passif["capitaux_propres"] += solde_c - solde_d
        elif num.startswith("16"):
            passif["dettes_financieres"] += solde_c - solde_d
        elif num >= "45":
            passif["dettes_exploitation"] += solde_c - solde_d
    actif["total"] = sum(v for k, v in actif.items() if k != "total")
    passif["total"] = sum(v for k, v in passif.items() if k != "total")
    return {"actif": actif, "passif": passif}


@app.post("/api/comptabilite/ecriture/manuelle")
async def ecriture_manuelle(
    date_piece: str = Form(...),
    libelle: str = Form(...),
    compte_debit: str = Form(...),
    compte_credit: str = Form(...),
    montant: float = Form(...),
    has_justificatif: bool = Form(False),
):
    """Enregistre une ecriture manuelle avec avertissement justificatif."""
    moteur = get_moteur()
    try:
        d = date.fromisoformat(date_piece)
    except ValueError:
        raise HTTPException(400, "Date invalide.")
    lib = libelle if has_justificatif else f"{libelle} [SANS JUSTIFICATIF]"
    from urssaf_analyzer.comptabilite.ecritures import LigneEcriture, Ecriture
    e = Ecriture(
        date_piece=d, journal=TypeJournal.OPERATIONS_DIVERSES,
        piece=f"MAN-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        libelle=lib,
    )
    e.lignes = [
        LigneEcriture(compte=compte_debit, libelle=lib, debit=Decimal(str(montant)), credit=Decimal("0")),
        LigneEcriture(compte=compte_credit, libelle=lib, debit=Decimal("0"), credit=Decimal(str(montant))),
    ]
    moteur.ecritures.append(e)
    return {
        "ecriture_id": e.id, "equilibree": e.est_equilibree,
        "sans_justificatif": not has_justificatif,
        "alerte": "ATTENTION: Ecriture enregistree sans justificatif. Un document justificatif est requis." if not has_justificatif else None,
        "lignes": [{"compte": l.compte, "libelle": l.libelle,
                     "debit": float(l.debit), "credit": float(l.credit)} for l in e.lignes],
    }


@app.get("/api/comptabilite/charges-sociales-detail")
async def charges_sociales_detail():
    """Detail des charges sociales par destinataire."""
    recap = GenerateurRapports(get_moteur()).recapitulatif_charges_sociales()
    return {
        "destinataires": [
            {"nom": "URSSAF", "postes": ["Maladie", "Vieillesse", "Allocations familiales", "CSG/CRDS", "FNAL", "Autonomie"],
             "montant": recap.get("cotisations_urssaf", 0)},
            {"nom": "France Travail", "postes": ["Chomage", "AGS"],
             "montant": recap.get("france_travail", 0)},
            {"nom": "Retraite complementaire", "postes": ["AGIRC-ARRCO", "CEG", "CET"],
             "montant": recap.get("cotisations_retraite", 0)},
            {"nom": "Prevoyance / Mutuelle", "postes": ["Prevoyance", "Complementaire sante"],
             "montant": recap.get("mutuelle_prevoyance", 0)},
        ],
        "total": recap.get("total_charges_sociales", 0),
        "taux_global": recap.get("taux_charges_global", 0),
        "brut": recap.get("salaires_bruts", 0),
        "cout_employeur": recap.get("cout_total_employeur", 0),
    }


# ==============================
# HTML TEMPLATES BELOW
# ==============================

LANDING_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Clara - Conformite sociale et fiscale intelligente</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',system-ui,sans-serif;background:#f8fafc;color:#1e293b;-webkit-font-smoothing:antialiased}
.nav{background:#0f172a;color:#fff;display:flex;justify-content:space-between;align-items:center;padding:14px 40px;position:sticky;top:0;z-index:100;backdrop-filter:blur(10px)}
.nav .logo{font-size:1.6em;font-weight:800;letter-spacing:-.5px}
.nav .logo em{font-style:normal;color:#60a5fa}
.nav .links{display:flex;gap:24px;align-items:center}
.nav a{color:#fff;text-decoration:none;font-size:.9em;opacity:.75;transition:.2s}
.nav a:hover{opacity:1}
.nav .bl{background:rgba(96,165,250,.2);padding:8px 22px;border-radius:8px;font-weight:600;opacity:1;border:1px solid rgba(96,165,250,.3)}
.nav .bl:hover{background:rgba(96,165,250,.35)}
.hero{background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 50%,#1e40af 100%);color:#fff;text-align:center;padding:90px 20px 70px;position:relative;overflow:hidden}
.hero::before{content:"";position:absolute;top:0;left:0;right:0;bottom:0;background:radial-gradient(circle at 30% 50%,rgba(96,165,250,.15) 0%,transparent 60%);pointer-events:none}
.hero h1{font-size:3em;font-weight:800;margin-bottom:18px;line-height:1.1;position:relative}
.hero h1 em{font-style:normal;color:#60a5fa}
.hero p{font-size:1.15em;opacity:.85;max-width:680px;margin:0 auto 35px;line-height:1.6}
.price-box{display:inline-block;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);border-radius:16px;padding:22px 44px;margin:20px 0;backdrop-filter:blur(10px)}
.price-box .price{font-size:2.6em;font-weight:800}.price-box .sub{font-size:.85em;opacity:.7;margin-top:4px}
.cta-btn{display:inline-block;background:#3b82f6;color:#fff;padding:15px 44px;border-radius:12px;font-size:1.1em;font-weight:700;text-decoration:none;margin-top:22px;transition:.3s;cursor:pointer;border:none;box-shadow:0 4px 20px rgba(59,130,246,.4)}
.cta-btn:hover{background:#2563eb;transform:translateY(-2px);box-shadow:0 8px 30px rgba(59,130,246,.5)}
.feat{max-width:1100px;margin:70px auto;padding:0 20px}
.feat h2{text-align:center;font-size:1.9em;font-weight:700;color:#0f172a;margin-bottom:12px}
.feat .sub{text-align:center;color:#64748b;margin-bottom:40px;font-size:1.05em}
.fg{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}
.fc{background:#fff;border-radius:16px;padding:28px;border:1px solid #e2e8f0;transition:.3s}
.fc:hover{transform:translateY(-4px);box-shadow:0 12px 30px rgba(0,0,0,.08);border-color:#cbd5e1}
.fc .ic{width:48px;height:48px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:1.4em;margin-bottom:14px}
.fc .ic.blue{background:#eff6ff;color:#3b82f6}.fc .ic.green{background:#f0fdf4;color:#22c55e}
.fc .ic.purple{background:#faf5ff;color:#a855f7}.fc .ic.amber{background:#fffbeb;color:#f59e0b}
.fc h3{color:#0f172a;margin-bottom:8px;font-size:1.05em}
.fc p{color:#64748b;font-size:.88em;line-height:1.6}
.tgt{background:#fff;padding:70px 20px;text-align:center;border-top:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0}
.tgt h2{font-size:1.8em;color:#0f172a;margin-bottom:35px;font-weight:700}
.tg{display:flex;justify-content:center;gap:24px;flex-wrap:wrap;max-width:900px;margin:0 auto}
.ti{background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;padding:28px 20px;width:200px;transition:.3s}
.ti:hover{border-color:#3b82f6;background:#eff6ff}
.ti .ic2{font-size:2em;margin-bottom:8px}.ti h4{color:#0f172a;margin-bottom:4px}.ti p{font-size:.82em;color:#64748b}
.auth-sec{max-width:420px;margin:70px auto;padding:0 20px}
.auth-card{background:#fff;border-radius:20px;padding:36px;box-shadow:0 8px 30px rgba(0,0,0,.06);border:1px solid #e2e8f0}
.auth-card h2{text-align:center;color:#0f172a;margin-bottom:24px;font-size:1.4em}
.auth-tabs{display:flex;margin-bottom:24px;background:#f1f5f9;border-radius:10px;padding:4px}
.auth-tab{flex:1;padding:10px;text-align:center;cursor:pointer;font-weight:600;color:#64748b;border-radius:8px;transition:.2s;font-size:.92em}
.auth-tab.active{color:#0f172a;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.auth-form{display:none}.auth-form.active{display:block}
.auth-form label{display:block;font-weight:600;font-size:.84em;color:#475569;margin-bottom:5px}
.auth-form input{width:100%;padding:11px 14px;border:1.5px solid #e2e8f0;border-radius:10px;font-size:.95em;margin-bottom:14px;transition:.2s;background:#f8fafc}
.auth-form input:focus{border-color:#3b82f6;outline:none;background:#fff;box-shadow:0 0 0 3px rgba(59,130,246,.1)}
.submit-btn{width:100%;padding:13px;background:#0f172a;color:#fff;border:none;border-radius:10px;font-size:1em;font-weight:700;cursor:pointer;transition:.2s}
.submit-btn:hover{background:#1e293b}
.msg{padding:10px 14px;border-radius:10px;margin:12px 0;font-size:.9em;display:none}
.msg.ok{display:block;background:#f0fdf4;color:#166534;border:1px solid #bbf7d0}
.msg.err{display:block;background:#fef2f2;color:#991b1b;border:1px solid #fecaca}
footer{text-align:center;padding:40px 20px;color:#94a3b8;font-size:.84em;background:#f8fafc}
@media(max-width:640px){.hero h1{font-size:2em}.hero{padding:60px 16px 50px}.fg{grid-template-columns:1fr}.nav{padding:12px 16px}}
</style>
</head>
<body>
<div class="nav">
<div class="logo"><em>Clara</em></div>
<div class="links">
<a href="#features">Fonctionnalites</a>
<a href="#pricing">Tarif</a>
<a href="#auth" class="bl">Se connecter</a>
</div>
</div>
<div class="hero" id="pricing">
<h1>La conformite sociale et fiscale<br>enfin <em>simplifiee</em>.</h1>
<p>Import et analyse automatique de vos documents sociaux et fiscaux. Detection d'anomalies en euros, comptabilite integree, simulations, veille juridique. Pour entrepreneurs, comptables et experts.</p>
<div class="price-box"><div class="price">59,99 EUR</div><div class="sub">Licence complete &bull; Mises a jour mensuelles</div></div>
<br><button class="cta-btn" onclick="document.getElementById('auth').scrollIntoView({behavior:'smooth'})">Commencer maintenant</button>
</div>
<div class="feat" id="features">
<h2>Tout-en-un, professionnel</h2>
<p class="sub">Une plateforme complete pour maitriser votre conformite</p>
<div class="fg">
<div class="fc"><div class="ic blue">&#128269;</div><h3>Analyse et detection</h3><p>Ecarts d'assiette avec incidence en cotisations. Rapprochement DSN / livre de paie. Score de risque par destinataire.</p></div>
<div class="fc"><div class="ic green">&#128200;</div><h3>Dashboard dirigeant</h3><p>Vision entreprise : anomalies, charges vs brut, conformite, previsionnels, seuils depasses, alertes.</p></div>
<div class="fc"><div class="ic purple">&#128196;</div><h3>Comptabilite integree</h3><p>Grand livre, balance, bilan, compte de resultat, TVA. Selection par periode. Alertes justificatifs manquants.</p></div>
<div class="fc"><div class="ic amber">&#128221;</div><h3>Multi-formats</h3><p>PDF, Excel, CSV, DSN, Images (JPEG, PNG, TIFF). Detection manuscrit. OCR. 20 fichiers / 50 Mo max.</p></div>
<div class="fc"><div class="ic blue">&#9878;</div><h3>Veille juridique</h3><p>Baremes et legislation 2020-2026. Patch mensuel automatique. Historique 6 ans pour analyse retroactive.</p></div>
<div class="fc"><div class="ic green">&#128101;</div><h3>Tous profils</h3><p>Salaries, TNS, micro-entrepreneurs, GUSO, artistes-auteurs. Simulations completes et recommandations.</p></div>
<div class="fc"><div class="ic purple">&#128203;</div><h3>Exports et rapports</h3><p>Grand livre, balance, livre de paie, planning, bilan : tout exportable. Rapports PDF et HTML professionnels.</p></div>
<div class="fc"><div class="ic amber">&#128274;</div><h3>Alertes conformite</h3><p>Justificatif manquant en rouge. Ecritures manuelles alertees. Detection avantages en nature, frais, seuils.</p></div>
</div>
</div>
<div class="tgt"><h2>Concu pour les professionnels</h2><div class="tg">
<div class="ti"><div class="ic2">&#128188;</div><h4>Entrepreneurs</h4><p>Autonomie totale</p></div>
<div class="ti"><div class="ic2">&#128202;</div><h4>Comptables</h4><p>Automatisation</p></div>
<div class="ti"><div class="ic2">&#127891;</div><h4>Experts-comptables</h4><p>Multi-entreprises</p></div>
<div class="ti"><div class="ic2">&#128270;</div><h4>Inspecteurs</h4><p>Verification rapide</p></div>
</div></div>
<div class="auth-sec" id="auth"><div class="auth-card">
<h2>Acces a Clara</h2>
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
<label style="display:flex;align-items:center;gap:8px;font-weight:400;margin:0;cursor:pointer"><input type="checkbox" id="cgv"> J'accepte les conditions generales.</label></div>
<button class="submit-btn" onclick="doReg()">Creer mon compte - 59,99 EUR</button>
<div style="font-size:.8em;color:#94a3b8;margin-top:10px;text-align:center">Paiement securise. Acces immediat.</div>
</div></div></div>
<footer>Clara v3.2.0 &mdash; Conformite sociale et fiscale &copy; 2026</footer>
<script>
function showAT(t){document.querySelectorAll('.auth-tab').forEach(function(b,i){b.classList.toggle('active',i===(t==='login'?0:1))});document.getElementById('form-login').classList.toggle('active',t==='login');document.getElementById('form-register').classList.toggle('active',t==='register');document.getElementById('amsg').className='msg';}
function doLogin(){var fd=new FormData();fd.append('email',document.getElementById('le').value);fd.append('mot_de_passe',document.getElementById('lp').value);fetch('/api/auth/login',{method:'POST',body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||'Erreur')});var m=document.getElementById('amsg');m.className='msg ok';m.textContent='Connexion reussie...';setTimeout(function(){window.location.href='/app'},600);}).catch(function(e){var m=document.getElementById('amsg');m.className='msg err';m.textContent=e.message;});}
function doReg(){if(document.getElementById('rpw').value!==document.getElementById('rpw2').value){var m=document.getElementById('amsg');m.className='msg err';m.textContent='Mots de passe differents.';return;}if(!document.getElementById('cgv').checked){var m2=document.getElementById('amsg');m2.className='msg err';m2.textContent='Veuillez accepter les CGV.';return;}var fd=new FormData();fd.append('nom',document.getElementById('rn').value);fd.append('prenom',document.getElementById('rp2').value);fd.append('email',document.getElementById('re').value);fd.append('mot_de_passe',document.getElementById('rpw').value);fetch('/api/auth/register',{method:'POST',body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||'Erreur')});var m=document.getElementById('amsg');m.className='msg ok';m.textContent='Compte cree ! Redirection...';setTimeout(function(){window.location.href='/app'},600);}).catch(function(e){var m=document.getElementById('amsg');m.className='msg err';m.textContent=e.message;});}
</script>
</body>
</html>"""

APP_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Clara - Application</title>
<style>
:root{--p:#0f172a;--p2:#1e40af;--p3:#3b82f6;--pl:#eff6ff;--g:#22c55e;--gl:#f0fdf4;--r:#ef4444;--rl:#fef2f2;--o:#f59e0b;--ol:#fffbeb;--pu:#a855f7;--pul:#faf5ff;--bg:#f8fafc;--tx:#1e293b;--tx2:#64748b;--brd:#e2e8f0;--sh:0 1px 3px rgba(0,0,0,.06)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--tx);-webkit-font-smoothing:antialiased}

/* === SIDEBAR NAV === */
.layout{display:flex;min-height:100vh}
.sidebar{width:240px;background:var(--p);color:#fff;display:flex;flex-direction:column;position:fixed;top:0;bottom:0;left:0;z-index:100;transition:.3s}
.sidebar .logo{padding:20px 22px;font-size:1.4em;font-weight:800;border-bottom:1px solid rgba(255,255,255,.08)}
.sidebar .logo em{font-style:normal;color:#60a5fa}
.sidebar .nav-group{padding:12px 10px 6px;font-size:.7em;text-transform:uppercase;letter-spacing:1.5px;color:#64748b;font-weight:600}
.sidebar .nl{display:flex;align-items:center;gap:10px;padding:10px 18px;cursor:pointer;color:rgba(255,255,255,.65);transition:.2s;border-radius:8px;margin:2px 8px;font-size:.9em}
.sidebar .nl:hover{background:rgba(255,255,255,.08);color:#fff}
.sidebar .nl.active{background:rgba(96,165,250,.15);color:#60a5fa;font-weight:600}
.sidebar .nl .ico{width:20px;text-align:center;font-size:1.1em}
.sidebar .spacer{flex:1}
.sidebar .logout{padding:14px 18px;cursor:pointer;color:rgba(255,255,255,.5);font-size:.85em;border-top:1px solid rgba(255,255,255,.08);transition:.2s;display:flex;align-items:center;gap:8px}
.sidebar .logout:hover{color:#fff;background:rgba(239,68,68,.15)}

/* === MAIN CONTENT === */
.content{margin-left:240px;flex:1;min-height:100vh}
.topbar{background:#fff;border-bottom:1px solid var(--brd);padding:14px 28px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:50}
.topbar h1{font-size:1.15em;font-weight:700;color:var(--p)}
.topbar .info{font-size:.85em;color:var(--tx2)}
.page{padding:24px 28px;max-width:1200px}

/* === SECTIONS === */
.sec{display:none}.sec.active{display:block}

/* === CARDS === */
.card{background:#fff;border-radius:14px;padding:24px;border:1px solid var(--brd);margin-bottom:18px;transition:.2s}
.card:hover{box-shadow:0 4px 16px rgba(0,0,0,.05)}
.card h2{color:var(--p);margin-bottom:14px;font-size:1.1em;font-weight:700;display:flex;align-items:center;gap:8px}
.card h2 .badge-count{background:var(--pl);color:var(--p3);padding:2px 10px;border-radius:20px;font-size:.75em}

/* === GRIDS === */
.g2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.g4{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}

/* === STAT CARDS === */
.sc{border-radius:12px;padding:18px;text-align:center;border:1px solid var(--brd);background:#fff;transition:.2s}
.sc:hover{border-color:var(--p3);box-shadow:0 2px 12px rgba(59,130,246,.08)}
.sc .val{font-size:1.7em;font-weight:800;color:var(--p)}.sc .lab{font-size:.78em;color:var(--tx2);margin-top:4px}
.sc.blue{background:var(--pl);border-color:#bfdbfe}.sc.green{background:var(--gl);border-color:#bbf7d0}
.sc.red{background:var(--rl);border-color:#fecaca}.sc.amber{background:var(--ol);border-color:#fde68a}

/* === UPLOAD ZONE === */
.uz{border:2px dashed var(--brd);border-radius:14px;padding:36px;text-align:center;cursor:pointer;transition:.3s;background:#fff;position:relative}
.uz:hover{border-color:var(--p3);background:var(--pl)}
.uz input[type="file"]{position:absolute;inset:0;opacity:0;cursor:pointer}
.uz .uz-icon{font-size:2.2em;margin-bottom:8px;opacity:.6}
.uz h3{color:var(--p);font-size:.95em;margin-bottom:4px}.uz p{color:var(--tx2);font-size:.82em}

/* === FORMS === */
input,select,textarea{width:100%;padding:10px 14px;border:1.5px solid var(--brd);border-radius:10px;font-size:.92em;transition:.2s;margin-bottom:12px;background:#fff;font-family:inherit}
input:focus,select:focus,textarea:focus{border-color:var(--p3);outline:none;box-shadow:0 0 0 3px rgba(59,130,246,.1)}
label{display:block;font-weight:600;margin-bottom:5px;font-size:.84em;color:#475569}

/* === BUTTONS === */
.btn{display:inline-flex;align-items:center;gap:8px;padding:10px 22px;border:none;border-radius:10px;font-size:.9em;font-weight:600;cursor:pointer;transition:.2s;font-family:inherit}
.btn-p{background:var(--p);color:#fff}.btn-p:hover{background:#1e293b}
.btn-p:disabled{background:#94a3b8;cursor:not-allowed}
.btn-blue{background:var(--p3);color:#fff}.btn-blue:hover{background:var(--p2)}
.btn-s{background:var(--pl);color:var(--p3);border:1px solid #bfdbfe}.btn-s:hover{background:#dbeafe}
.btn-danger{background:var(--rl);color:var(--r);border:1px solid #fecaca}.btn-danger:hover{background:#fee2e2}
.btn-f{width:100%;justify-content:center}
.btn-sm{padding:6px 14px;font-size:.82em;border-radius:8px}
.btn-group{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}

/* === TABLE === */
table{width:100%;border-collapse:collapse}
th{background:var(--p);color:#fff;padding:10px 14px;text-align:left;font-size:.82em;font-weight:600}
th:first-child{border-radius:8px 0 0 0}th:last-child{border-radius:0 8px 0 0}
td{padding:9px 14px;border-bottom:1px solid var(--brd);font-size:.88em}
tr:hover{background:var(--pl)}
.num{text-align:right;font-family:'SF Mono','Consolas',monospace;font-size:.85em}
.sans-just{background:var(--rl) !important}
.sans-just td{color:var(--r)}

/* === BADGES === */
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.72em;font-weight:700}
.badge-blue{background:var(--pl);color:var(--p2)}.badge-green{background:var(--gl);color:#16a34a}
.badge-red{background:var(--rl);color:var(--r)}.badge-amber{background:var(--ol);color:#d97706}
.badge-purple{background:var(--pul);color:var(--pu)}.badge-teal{background:#f0fdfa;color:#0d9488}

/* === TABS === */
.tabs{display:flex;gap:2px;background:#f1f5f9;border-radius:10px;padding:4px;margin-bottom:18px}
.tab{padding:8px 18px;cursor:pointer;border-radius:8px;color:var(--tx2);font-weight:600;font-size:.85em;transition:.2s;text-align:center}
.tab:hover{color:var(--tx)}.tab.active{color:var(--p);background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.tc{display:none}.tc.active{display:block}

/* === ANOMALIES === */
.anomalie{border:1px solid var(--brd);border-radius:12px;padding:16px;margin:10px 0;cursor:pointer;transition:.2s;background:#fff}
.anomalie:hover{box-shadow:0 4px 16px rgba(0,0,0,.06)}
.anomalie.sev-high{border-left:4px solid var(--r)}.anomalie.sev-med{border-left:4px solid var(--o)}.anomalie.sev-low{border-left:4px solid var(--p3)}
.anomalie .head{display:flex;justify-content:space-between;align-items:center}
.anomalie .head .title{font-weight:600;font-size:.92em}
.anomalie .montant{font-size:1.2em;font-weight:700;font-family:'SF Mono','Consolas',monospace}
.anomalie .montant.neg{color:var(--r)}.anomalie .montant.pos{color:var(--g)}
.anomalie .detail{display:none;margin-top:14px;padding-top:14px;border-top:1px solid var(--brd);font-size:.86em;line-height:1.6}
.anomalie.open .detail{display:block}
.anomalie .dest{padding:2px 10px;border-radius:20px;font-size:.72em;font-weight:700;display:inline-block;margin-left:6px}

/* === ALERTS === */
.al{padding:12px 16px;border-radius:10px;margin:8px 0;font-size:.88em;display:flex;align-items:flex-start;gap:10px;line-height:1.5}
.al .al-icon{font-size:1.1em;margin-top:1px}
.al.info{background:var(--pl);color:var(--p2);border:1px solid #bfdbfe}
.al.ok{background:var(--gl);color:#166534;border:1px solid #bbf7d0}
.al.err{background:var(--rl);color:#991b1b;border:1px solid #fecaca}
.al.warn{background:var(--ol);color:#92400e;border:1px solid #fde68a}
.al-just{background:var(--rl);border-left:4px solid var(--r);padding:12px 16px;border-radius:0 10px 10px 0;margin:10px 0;font-size:.88em}

/* === GAUGE === */
.gauge{width:130px;height:130px;border-radius:50%;background:conic-gradient(var(--g) 0%,var(--g) var(--pct),#e2e8f0 var(--pct));display:flex;align-items:center;justify-content:center;margin:0 auto;transition:.5s}
.gauge-inner{width:98px;height:98px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;font-size:1.6em;font-weight:800;color:var(--p)}

/* === PROGRESS === */
.prg{display:none;margin:16px 0}
.prg-bar{height:6px;background:#e2e8f0;border-radius:3px;overflow:hidden}
.prg-fill{height:100%;background:linear-gradient(90deg,var(--p3),var(--p2));border-radius:3px;width:0%;transition:width .5s}
.prg-txt{text-align:center;margin-top:8px;color:var(--tx2);font-size:.84em}

/* === FILE ITEM === */
.fi{display:flex;align-items:center;justify-content:space-between;padding:8px 14px;background:var(--pl);border-radius:8px;margin:4px 0;font-size:.86em;border:1px solid #bfdbfe}
.fi .nm{font-weight:600;color:var(--p)}.fi .sz{color:var(--tx2);font-size:.82em}
.fi .rm{background:none;border:none;color:var(--r);cursor:pointer;font-size:1.3em;padding:2px 6px;border-radius:4px}
.fi .rm:hover{background:var(--rl)}

/* === FORMAT SELECTOR === */
.fmts{display:flex;gap:8px;margin-bottom:16px}
.fopt{flex:1;padding:12px;border:1.5px solid var(--brd);border-radius:10px;text-align:center;cursor:pointer;background:#fff;transition:.2s}
.fopt:hover{border-color:var(--p3)}.fopt.active{border-color:var(--p3);background:var(--pl)}
.fopt strong{color:var(--p);font-size:.92em}.fopt small{color:var(--tx2);font-size:.78em}

/* === EXPORT BAR === */
.export-bar{display:flex;gap:8px;justify-content:flex-end;margin-bottom:14px}

/* === RESPONSIVE === */
@media(max-width:768px){
.sidebar{width:56px;overflow:hidden}
.sidebar .logo span,.sidebar .nav-group,.sidebar .nl span,.sidebar .logout span{display:none}
.sidebar .nl{padding:12px;justify-content:center}.sidebar .nl .ico{width:auto}
.content{margin-left:56px}
.g2,.g3{grid-template-columns:1fr}
.topbar h1{font-size:1em}
.page{padding:16px}
}
</style>
</head>
<body>
<div class="layout">
<div class="sidebar">
<div class="logo"><em>Clara</em> <span>v3.2</span></div>
<div class="nav-group">Analyse</div>
<div class="nl active" onclick="showS('dashboard',this)"><span class="ico">&#9632;</span><span>Dashboard</span></div>
<div class="nl" onclick="showS('analyse',this)"><span class="ico">&#128269;</span><span>Import / Analyse</span></div>
<div class="nl" onclick="showS('documents',this)"><span class="ico">&#128196;</span><span>Documents</span></div>
<div class="nav-group">Gestion</div>
<div class="nl" onclick="showS('compta',this)"><span class="ico">&#128203;</span><span>Comptabilite</span></div>
<div class="nl" onclick="showS('factures',this)"><span class="ico">&#128206;</span><span>Factures</span></div>
<div class="nl" onclick="showS('simulation',this)"><span class="ico">&#128200;</span><span>Simulation</span></div>
<div class="nav-group">Outils</div>
<div class="nl" onclick="showS('veille',this)"><span class="ico">&#9878;</span><span>Veille juridique</span></div>
<div class="nl" onclick="showS('portefeuille',this)"><span class="ico">&#128101;</span><span>Portefeuille</span></div>
<div class="spacer"></div>
<div class="logout" onclick="window.location.href='/'"><span class="ico">&#10132;</span><span>Deconnexion</span></div>
</div>
<div class="content">
<div class="topbar"><h1 id="page-title">Dashboard</h1><div class="info">Clara v3.2.0 &bull; <span id="topbar-date"></span></div></div>
<div class="page">

"""

APP_HTML += """
<!-- ===== DASHBOARD ===== -->
<div class="sec active" id="s-dashboard">
<div class="g4" id="dash-stats">
<div class="sc blue"><div class="val" id="dash-anomalies">0</div><div class="lab">Anomalies detectees</div></div>
<div class="sc amber"><div class="val" id="dash-impact">0 EUR</div><div class="lab">Impact cotisations</div></div>
<div class="sc green"><div class="val" id="dash-conf">-</div><div class="lab">Conformite globale</div></div>
<div class="sc"><div class="val" id="dash-docs">0</div><div class="lab">Documents analyses</div></div>
</div>
<div class="g2">
<div class="card"><h2>Niveau de conformite</h2>
<div class="gauge" id="gauge" style="--pct:0%"><div class="gauge-inner" id="gauge-val">-</div></div>
<div style="text-align:center;margin-top:12px;font-size:.84em;color:var(--tx2)">Score base sur les analyses realisees</div>
</div>
<div class="card"><h2>Alertes recentes</h2><div id="dash-alertes"><div class="al info"><span class="al-icon">&#128161;</span><span>Importez des documents pour commencer l'analyse.</span></div></div></div>
</div>
<div class="card"><h2>Risques par destinataire</h2>
<div class="g4" id="dash-by-dest">
<div class="sc" style="border-left:4px solid var(--p3)"><div class="val" id="dd-urssaf">-</div><div class="lab">URSSAF</div></div>
<div class="sc" style="border-left:4px solid var(--pu)"><div class="val" id="dd-fiscal">-</div><div class="lab">Fiscal</div></div>
<div class="sc" style="border-left:4px solid var(--o)"><div class="val" id="dd-ft">-</div><div class="lab">France Travail</div></div>
<div class="sc" style="border-left:4px solid #0d9488"><div class="val" id="dd-guso">-</div><div class="lab">GUSO</div></div>
</div></div>
<div class="card"><h2>Dernieres anomalies <span class="badge-count" id="dash-anom-count">0</span></h2><div id="dash-anomalies-list"><p style="color:var(--tx2)">Aucune anomalie. Lancez une analyse pour detecter les ecarts.</p></div></div>
</div>

<!-- ===== IMPORT / ANALYSE ===== -->
<div class="sec" id="s-analyse">
<div class="card">
<h2>Importer et analyser vos documents</h2>
<p style="color:var(--tx2);font-size:.88em;margin-bottom:16px">Deposez vos fichiers (DSN, livre de paie, bulletins, factures...). Max 20 fichiers, 50 Mo au total.</p>
<div class="uz" id="dz-analyse">
<input type="file" id="fi-analyse" multiple accept=".pdf,.csv,.xlsx,.xls,.xml,.dsn,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.gif,.webp,.txt">
<div class="uz-icon">&#128196;</div>
<h3>Glissez vos fichiers ici ou cliquez pour parcourir</h3>
<p>PDF, Excel, CSV, DSN, XML, Images (JPEG, PNG, TIFF), TXT</p>
</div>
<div id="fl-analyse" style="margin:12px 0"></div>
<div id="err-analyse" class="al err" style="display:none"></div>
<div style="margin-top:18px"><h2 style="margin-bottom:10px">Format du rapport</h2>
<div class="fmts">
<div class="fopt active" data-fmt="json" onclick="selFmt(this)"><strong>JSON</strong><br><small>Donnees structurees</small></div>
<div class="fopt" data-fmt="html" onclick="selFmt(this)"><strong>HTML</strong><br><small>Rapport visuel</small></div>
</div></div>
<div style="display:flex;align-items:center;gap:12px;margin:16px 0;padding:14px;background:var(--pl);border-radius:10px;border:1px solid #bfdbfe">
<input type="checkbox" id="chk-integrer" checked style="width:auto;margin:0">
<label for="chk-integrer" style="margin:0;font-weight:500;color:var(--p);font-size:.88em;cursor:pointer">Integrer les documents dans le dossier (decocher pour simple analyse sans integration)</label>
</div>
<button class="btn btn-blue btn-f" id="btn-az" onclick="lancerAnalyse()" disabled style="padding:14px">&#128269; Lancer l'analyse</button>
<div class="prg" id="prg-az"><div class="prg-bar"><div class="prg-fill" id="pf-az"></div></div><div class="prg-txt" id="pt-az">Import...</div></div>
</div>
<div id="res-analyse" style="display:none">
<div class="card">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
<h2>Resultats de l'analyse</h2>
<div class="btn-group"><button class="btn btn-s btn-sm" onclick="exportSection('az')">&#128190; Exporter</button><button class="btn btn-s btn-sm" onclick="resetAz()">&#10227; Nouvelle analyse</button></div>
</div>
<div class="g4" id="az-dashboard"></div>
</div>
<div class="card"><h2>Anomalies detectees</h2><div id="az-findings"></div></div>
<div class="card"><h2>Recommandations</h2><div id="az-reco"></div></div>
<div class="card" id="az-html-card" style="display:none"><h2>Rapport HTML</h2><iframe id="az-html-frame" style="width:100%;height:600px;border:1px solid var(--brd);border-radius:10px"></iframe></div>
</div>
</div>

<!-- ===== FACTURES ===== -->
<div class="sec" id="s-factures">
<div class="g2">
<div class="card">
<h2>Analyser une facture</h2>
<div class="uz" id="dz-fact">
<input type="file" id="fi-fact" accept=".pdf,.csv,.txt,.jpg,.jpeg,.png">
<div class="uz-icon">&#128206;</div>
<h3>Deposer une facture</h3><p>PDF, CSV, TXT, Image</p>
</div>
<div id="fact-fn" style="margin:10px 0"></div>
<button class="btn btn-blue btn-f" id="btn-fact" onclick="analyserFacture()" disabled>Analyser la facture</button>
</div>
<div class="card">
<h2>Saisie manuelle / Comptabilisation</h2>
<label>Type de piece</label>
<select id="f-type"><option value="facture_achat">Facture d'achat</option><option value="facture_vente">Facture de vente</option><option value="avoir_achat">Avoir d'achat</option><option value="avoir_vente">Avoir de vente</option></select>
<div class="g2">
<div><label>Date piece</label><input type="date" id="f-date"></div>
<div><label>N piece</label><input id="f-num" placeholder="FA-2026-001"></div>
</div>
<label>Tiers</label><input id="f-tiers" placeholder="Nom du tiers">
<div class="g3">
<div><label>Montant HT</label><input type="number" step="0.01" id="f-ht" placeholder="0.00"></div>
<div><label>TVA</label><input type="number" step="0.01" id="f-tva" placeholder="0.00"></div>
<div><label>TTC</label><input type="number" step="0.01" id="f-ttc" placeholder="0.00"></div>
</div>
<button class="btn btn-p btn-f" onclick="comptabiliserFacture()">Comptabiliser</button>
<div class="al-just" id="alerte-justif" style="display:none"><strong>&#9888; Alerte justificatif</strong> : Saisie manuelle sans document joint. L'ecriture sera marquee en rouge dans la comptabilite.</div>
</div>
</div>
<div class="card" id="fact-res" style="display:none"><h2>Resultat</h2><div id="fact-det"></div></div>
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
<button class="btn btn-s btn-sm" onclick="validerEcr()">&#9989; Valider ecritures</button>
<button class="btn btn-s btn-sm" onclick="exportSection('compta')">&#128190; Exporter</button>
</div>

<!-- Period selector for GL, balance, bilan -->
<div id="period-sel" style="display:none;margin-bottom:14px;padding:14px;background:var(--pl);border-radius:10px;border:1px solid #bfdbfe">
<div class="g3">
<div><label>Date debut</label><input type="date" id="gl-dd"></div>
<div><label>Date fin</label><input type="date" id="gl-df"></div>
<div><button class="btn btn-blue btn-f" onclick="loadCompta()" style="margin-top:22px">Appliquer</button></div>
</div>
</div>

<div class="tc active" id="ct-journal"><div id="ct-journal-c"></div></div>
<div class="tc" id="ct-balance"><div id="ct-balance-c"></div></div>
<div class="tc" id="ct-grandlivre"><div id="ct-grandlivre-c"></div></div>
<div class="tc" id="ct-resultat"><div id="ct-resultat-c"></div></div>
<div class="tc" id="ct-bilan"><div id="ct-bilan-c"></div></div>
<div class="tc" id="ct-tva"><div id="ct-tva-c"></div></div>
<div class="tc" id="ct-social"><div id="ct-social-c"></div></div>
<div class="tc" id="ct-ecritures">
<h2 style="margin-bottom:14px">Ecriture manuelle</h2>
<div class="g2">
<div>
<label>Date</label><input type="date" id="em-date">
<label>Libelle</label><input id="em-lib" placeholder="Description de l'ecriture">
</div>
<div>
<label>Compte debit</label><input id="em-deb" placeholder="Ex: 601000">
<label>Compte credit</label><input id="em-cre" placeholder="Ex: 401000">
</div>
</div>
<div class="g3">
<div><label>Montant</label><input type="number" step="0.01" id="em-mt" placeholder="0.00"></div>
<div><label>Justificatif</label><select id="em-just"><option value="false">Non (sans justificatif)</option><option value="true">Oui (justificatif present)</option></select></div>
<div><button class="btn btn-p btn-f" onclick="saisirEcriture()" style="margin-top:22px">Enregistrer</button></div>
</div>
<div id="em-res" style="margin-top:12px"></div>
</div>
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
<div><label>Brut mensuel (EUR)</label><input type="number" step="0.01" id="sim-brut" value="2500"></div>
<div><label>Effectif entreprise</label><input type="number" id="sim-eff" value="10"></div>
<div><label>Statut cadre</label><select id="sim-cadre"><option value="false">Non cadre</option><option value="true">Cadre</option></select></div>
</div>
<div class="btn-group"><button class="btn btn-blue" onclick="simBulletin()">Simuler</button><button class="btn btn-s btn-sm" onclick="exportSection('sim')">&#128190; Exporter</button></div>
<div id="sim-bull-res" style="margin-top:14px"></div>
</div>
<div class="tc" id="sim-micro">
<h2>Simulation micro-entrepreneur</h2>
<div class="g3">
<div><label>Chiffre d'affaires (EUR)</label><input type="number" step="0.01" id="sim-ca" value="50000"></div>
<div><label>Activite</label><select id="sim-act"><option value="prestations_bnc">Prestations BNC</option><option value="prestations_bic">Prestations BIC</option><option value="vente_marchandises">Vente marchandises</option><option value="location_meublee">Location meublee</option></select></div>
<div><label>ACRE</label><select id="sim-acre"><option value="false">Non</option><option value="true">Oui</option></select></div>
</div>
<button class="btn btn-blue" onclick="simMicro()">Simuler</button>
<div id="sim-micro-res" style="margin-top:14px"></div>
</div>
<div class="tc" id="sim-tns">
<h2>Simulation TNS</h2>
<div class="g3">
<div><label>Revenu net (EUR)</label><input type="number" step="0.01" id="sim-rev" value="40000"></div>
<div><label>Statut</label><select id="sim-stat"><option value="gerant_majoritaire">Gerant majoritaire</option><option value="profession_liberale">Profession liberale</option><option value="artisan">Artisan</option><option value="commercant">Commercant</option></select></div>
<div><label>ACRE</label><select id="sim-tacre"><option value="false">Non</option><option value="true">Oui</option></select></div>
</div>
<button class="btn btn-blue" onclick="simTNS()">Simuler</button>
<div id="sim-tns-res" style="margin-top:14px"></div>
</div>
<div class="tc" id="sim-guso">
<h2>Simulation GUSO</h2>
<div class="g2">
<div><label>Salaire brut (EUR)</label><input type="number" step="0.01" id="sim-gbrut" value="500"></div>
<div><label>Nombre d'heures</label><input type="number" step="0.5" id="sim-gh" value="8"></div>
</div>
<button class="btn btn-blue" onclick="simGUSO()">Simuler</button>
<div id="sim-guso-res" style="margin-top:14px"></div>
</div>
<div class="tc" id="sim-ir">
<h2>Simulation impot sur le revenu</h2>
<div class="g3">
<div><label>Benefice (EUR)</label><input type="number" step="0.01" id="sim-ben" value="40000"></div>
<div><label>Nombre de parts</label><input type="number" step="0.5" id="sim-parts" value="1"></div>
<div><label>Autres revenus foyer</label><input type="number" step="0.01" id="sim-autres" value="0"></div>
</div>
<button class="btn btn-blue" onclick="simIR()">Simuler</button>
<div id="sim-ir-res" style="margin-top:14px"></div>
</div>
</div>
</div>

<!-- ===== VEILLE JURIDIQUE ===== -->
<div class="sec" id="s-veille">
<div class="card">
<h2>Veille juridique - Baremes et legislation</h2>
<p style="color:var(--tx2);font-size:.88em;margin-bottom:16px">Consultez les baremes URSSAF et la legislation applicable. Historique 2020-2026 disponible.</p>
<div class="g3" style="margin-bottom:0">
<div><label>Annee</label><select id="v-annee"><option value="2020">2020</option><option value="2021">2021</option><option value="2022">2022</option><option value="2023">2023</option><option value="2024">2024</option><option value="2025">2025</option><option value="2026" selected>2026</option></select></div>
<div><button class="btn btn-blue btn-f" onclick="loadVeille()" style="margin-top:22px">Charger</button></div>
<div><button class="btn btn-s btn-f" onclick="compAnnees()" style="margin-top:22px">Comparer N / N-1</button></div>
</div>
</div>
<div id="v-res" style="display:none">
<div class="card"><h2>Baremes URSSAF</h2><div class="export-bar"><button class="btn btn-s btn-sm" onclick="exportSection('veille')">&#128190; Exporter</button></div><div id="v-baremes"></div></div>
<div class="card"><h2>Legislation applicable</h2><div id="v-legis"></div></div>
<div class="card" id="v-comp-card" style="display:none"><h2>Comparaison interannuelle</h2><div id="v-comp"></div></div>
</div>
</div>

<!-- ===== DOCUMENTS ===== -->
<div class="sec" id="s-documents">
<div class="g2">
<div class="card">
<h2>Extraire informations juridiques</h2>
<p style="color:var(--tx2);font-size:.85em;margin-bottom:12px">KBIS, statuts, contrats, etc.</p>
<div class="uz"><input type="file" id="fi-doc-jur" accept=".pdf,.jpg,.jpeg,.png,.txt"><div class="uz-icon">&#128195;</div><h3>KBIS, Statuts, contrats</h3><p>PDF ou Image</p></div>
<button class="btn btn-blue btn-f" onclick="extraireDoc()" style="margin-top:12px">Extraire</button>
</div>
<div class="card">
<h2>Lire tout document</h2>
<p style="color:var(--tx2);font-size:.85em;margin-bottom:12px">Lecture universelle avec OCR</p>
<div class="uz"><input type="file" id="fi-doc-lire" accept="*/*"><div class="uz-icon">&#128206;</div><h3>Tout format</h3><p>PDF, Images, Excel, CSV, TXT, DSN</p></div>
<button class="btn btn-blue btn-f" onclick="lireDoc()" style="margin-top:12px">Lire le document</button>
</div>
</div>
<div class="card" id="doc-res" style="display:none"><h2>Resultat</h2><div class="export-bar"><button class="btn btn-s btn-sm" onclick="exportSection('doc')">&#128190; Exporter</button></div><div id="doc-det"></div></div>
</div>

<!-- ===== PORTEFEUILLE ===== -->
<div class="sec" id="s-portefeuille">
<div class="g2">
<div class="card">
<h2>Ajouter une entreprise</h2>
<label>SIRET</label><input id="ent-siret" placeholder="12345678901234" maxlength="14">
<label>Raison sociale</label><input id="ent-raison" placeholder="Nom de l'entreprise">
<div class="g2">
<div><label>Forme juridique</label><select id="ent-forme"><option value="">-- Choisir --</option><option>SAS</option><option>SARL</option><option>SA</option><option>EURL</option><option>EI</option><option>SASU</option><option>SCI</option><option>SNC</option><option>Association</option></select></div>
<div><label>Code NAF</label><input id="ent-naf" placeholder="6201Z"></div>
</div>
<div class="g2">
<div><label>Effectif</label><input type="number" id="ent-eff" value="0"></div>
<div><label>Ville</label><input id="ent-ville" placeholder="Paris"></div>
</div>
<button class="btn btn-p btn-f" onclick="ajouterEnt()">Ajouter au portefeuille</button>
</div>
<div class="card">
<h2>Mon portefeuille</h2>
<input id="ent-search" placeholder="Rechercher par nom, SIRET, ville..." oninput="rechEnt()">
<div id="ent-list"></div>
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
var titles={"dashboard":"Dashboard","analyse":"Import / Analyse","factures":"Factures","compta":"Comptabilite","simulation":"Simulation","veille":"Veille juridique","documents":"Documents","portefeuille":"Portefeuille"};
document.getElementById("topbar-date").textContent=new Date().toLocaleDateString("fr-FR",{day:"numeric",month:"long",year:"numeric"});

/* === NAV === */
function showS(n,el){
document.querySelectorAll(".sec").forEach(function(s){s.classList.remove("active")});
document.querySelectorAll(".sidebar .nl").forEach(function(l){l.classList.remove("active")});
var sec=document.getElementById("s-"+n);
if(sec)sec.classList.add("active");
if(el)el.classList.add("active");
document.getElementById("page-title").textContent=titles[n]||n;
if(n==="compta")loadCompta();
if(n==="portefeuille")rechEnt();
if(n==="dashboard")loadDash();
}

/* === TOGGLE ANOMALIES === */
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
var el=document.getElementById(id);
if(!constats.length){el.innerHTML="<p style='color:var(--tx2)'>Aucune anomalie detectee.</p>";return;}
var h="";
constats.slice(0,30).forEach(function(c){
var impact=c.montant_impact||0;
var neg=impact>0;
var sev=Math.abs(impact)>5000?"high":(Math.abs(impact)>1000?"med":"low");
var dest=categToDest(c.categorie||"");
var destCls={"URSSAF":"badge-blue","Fiscal":"badge-purple","France Travail":"badge-amber","GUSO":"badge-teal"}[dest]||"badge-blue";
h+="<div class='anomalie sev-"+sev+"' data-toggle='1'>";
h+="<div class='head'><div><span class='title'>"+(c.titre||"Ecart detecte")+"</span>";
h+="<span class='dest "+destCls+"'>"+dest+"</span>";
h+=" <span class='badge "+(neg?"badge-red":"badge-green")+"'>"+(neg?"Risque":"Favorable")+"</span></div>";
h+="<div class='montant "+(neg?"neg":"pos")+"'>"+(neg?"+":"-")+Math.abs(impact).toFixed(2)+" EUR</div></div>";
h+="<div class='detail'>";
h+="<p><strong>Nature de l'ecart :</strong> "+(c.description||"").substring(0,300)+"</p>";
h+="<p><strong>Categorie :</strong> "+(c.categorie||"-")+"</p>";
h+="<p><strong>Annee / Periode :</strong> "+(c.annee||c.periode||"-")+"</p>";
h+="<p><strong>Documents concernes :</strong> "+(c.source||c.document||"-")+"</p>";
h+="<p><strong>Lignes / Rubriques :</strong> "+(c.rubrique||c.libelle||"-")+"</p>";
h+="<p><strong>Incidence cotisations :</strong> "+Math.abs(impact).toFixed(2)+" EUR "+(neg?"(surcharge potentielle)":"(economie)")+"</p>";
if(c.recommandation)h+="<div class='al info' style='margin-top:10px'><span class='al-icon'>&#128161;</span><span><strong>Regularisation suggeree :</strong> "+c.recommandation+"</span></div>";
h+="</div></div>";
});
el.innerHTML=h;
}

function categToDest(cat){
var c=cat.toLowerCase();
if(c.indexOf("fiscal")>=0||c.indexOf("impot")>=0||c.indexOf("ir ")>=0||c.indexOf("is ")>=0)return"Fiscal";
if(c.indexOf("france travail")>=0||c.indexOf("chomage")>=0||c.indexOf("pole")>=0)return"France Travail";
if(c.indexOf("guso")>=0||c.indexOf("spectacle")>=0)return"GUSO";
return"URSSAF";
}

/* === ANALYSE === */
var fichiers=[],fmtR="json";
var dz=document.getElementById("dz-analyse"),fi=document.getElementById("fi-analyse");
["dragenter","dragover"].forEach(function(ev){dz.addEventListener(ev,function(e){e.preventDefault();});});
dz.addEventListener("drop",function(e){e.preventDefault();addF(e.dataTransfer.files);});
fi.addEventListener("change",function(e){addF(e.target.files);fi.value="";});
function addF(files){for(var i=0;i<files.length;i++){var f=files[i];var dup=false;for(var j=0;j<fichiers.length;j++){if(fichiers[j].name===f.name){dup=true;break;}}if(!dup)fichiers.push(f);}renderF();}
function renderF(){var el=document.getElementById("fl-analyse");var h="";for(var i=0;i<fichiers.length;i++){h+="<div class='fi'><span class='nm'>"+fichiers[i].name+"</span><span class='sz'>"+(fichiers[i].size/1024).toFixed(1)+" Ko</span><button class='rm' onclick='rmF("+i+")'>&times;</button></div>";}el.innerHTML=h;document.getElementById("btn-az").disabled=fichiers.length===0;}
function rmF(i){fichiers.splice(i,1);renderF();}
function selFmt(el){document.querySelectorAll(".fopt").forEach(function(o){o.classList.remove("active")});el.classList.add("active");fmtR=el.getAttribute("data-fmt");}

function lancerAnalyse(){
if(!fichiers.length)return;
var btn=document.getElementById("btn-az"),prg=document.getElementById("prg-az"),fill=document.getElementById("pf-az"),txt=document.getElementById("pt-az");
btn.disabled=true;prg.style.display="block";document.getElementById("res-analyse").style.display="none";
var steps=[[10,"Import des fichiers..."],[25,"Verification integrite SHA-256..."],[40,"Parsing des documents..."],[55,"Analyse de coherence..."],[70,"Detection d'anomalies..."],[85,"Analyse de patterns..."],[95,"Generation du rapport..."]];
var si=0;var iv=setInterval(function(){if(si<steps.length){fill.style.width=steps[si][0]+"%";txt.textContent=steps[si][1];si++;}},900);
var fd=new FormData();for(var i=0;i<fichiers.length;i++){fd.append("fichiers",fichiers[i]);}
fetch("/api/analyze?format_rapport="+fmtR,{method:"POST",body:fd}).then(function(resp){
clearInterval(iv);fill.style.width="100%";txt.textContent="Analyse terminee !";
if(!resp.ok)return resp.json().then(function(e){throw new Error(e.detail||"Erreur serveur")});
if(fmtR==="html")return resp.text().then(function(html){document.getElementById("az-dashboard").innerHTML="";document.getElementById("az-findings").innerHTML="";document.getElementById("az-reco").innerHTML="";document.getElementById("az-html-card").style.display="block";document.getElementById("az-html-frame").srcdoc=html;});
return resp.json().then(function(data){analysisData=data;showJsonResults(data);});
}).then(function(){setTimeout(function(){prg.style.display="none";},800);document.getElementById("res-analyse").style.display="block";}).catch(function(e){clearInterval(iv);prg.style.display="none";showAlert(e.message);btn.disabled=false;});
}

function showJsonResults(data){
var s=data.synthese||{};var impact=s.impact_financier_total||0;
document.getElementById("az-dashboard").innerHTML=
"<div class='sc blue'><div class='val'>"+((data.constats||[]).length)+"</div><div class='lab'>Anomalies</div></div>"+
"<div class='sc "+(impact>1000?"red":"green")+"'><div class='val'>"+impact.toFixed(2)+" EUR</div><div class='lab'>Impact cotisations</div></div>"+
"<div class='sc green'><div class='val'>"+Math.max(0,100-(s.score_risque_global||0))+"%</div><div class='lab'>Conformite</div></div>"+
"<div class='sc'><div class='val'>"+(s.nb_fichiers||0)+"</div><div class='lab'>Fichiers analyses</div></div>";
renderAnomalies("az-findings",data.constats||[]);
var recos=data.recommandations||[];
var rh="";for(var i=0;i<recos.length;i++){rh+="<div class='al info'><span class='al-icon'>&#128161;</span><span><strong>#"+(i+1)+" "+(recos[i].titre||"")+"</strong><br>"+(recos[i].description||"")+"</span></div>";}
document.getElementById("az-reco").innerHTML=rh||"<p style='color:var(--tx2)'>Aucune recommandation.</p>";
document.getElementById("az-html-card").style.display="none";
document.getElementById("dash-docs").textContent=(s.nb_fichiers||0);
loadDash();
}

function resetAz(){fichiers=[];renderF();document.getElementById("res-analyse").style.display="none";window.scrollTo({top:0,behavior:"smooth"});}

/* === FACTURES === */
var factFile=null;
document.getElementById("fi-fact").addEventListener("change",function(e){factFile=e.target.files[0];if(factFile){document.getElementById("fact-fn").innerHTML="<div class='fi'><span class='nm'>"+factFile.name+"</span></div>";document.getElementById("btn-fact").disabled=false;}});
function analyserFacture(){
if(!factFile)return;var fd=new FormData();fd.append("fichier",factFile);
fetch("/api/factures/analyser",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){
document.getElementById("fact-res").style.display="block";
var h="<div class='g4'>";
h+="<div class='sc blue'><div class='val'>"+(d.type_document||"?")+"</div><div class='lab'>Type</div></div>";
h+="<div class='sc'><div class='val'>"+(d.montant_ttc||0).toFixed(2)+"</div><div class='lab'>TTC (EUR)</div></div>";
h+="<div class='sc'><div class='val'>"+((d.confiance||0)*100).toFixed(0)+"%</div><div class='lab'>Confiance</div></div>";
h+="<div class='sc "+(d.ecriture_manuscrite?"amber":"green")+"'><div class='val'>"+(d.ecriture_manuscrite?"Oui":"Non")+"</div><div class='lab'>Manuscrit</div></div></div>";
if(d.emetteur)h+="<p style='margin:12px 0'><strong>Emetteur :</strong> "+(d.emetteur.nom||"?")+" (SIRET: "+(d.emetteur.siret||"?")+")</p>";
if(d.lignes&&d.lignes.length){h+="<table style='margin-top:10px'><tr><th>Description</th><th>Qte</th><th>PU</th><th>HT</th></tr>";for(var i=0;i<d.lignes.length;i++){var l=d.lignes[i];h+="<tr><td>"+l.description+"</td><td class='num'>"+l.quantite+"</td><td class='num'>"+l.prix_unitaire.toFixed(2)+"</td><td class='num'>"+l.montant_ht.toFixed(2)+"</td></tr>";}h+="</table>";}
if(d.type_document)document.getElementById("f-type").value=d.type_document;
if(d.date_piece)document.getElementById("f-date").value=d.date_piece;
if(d.numero)document.getElementById("f-num").value=d.numero;
if(d.emetteur)document.getElementById("f-tiers").value=d.emetteur.nom||"";
document.getElementById("f-ht").value=d.montant_ht||0;document.getElementById("f-tva").value=d.montant_tva||0;document.getElementById("f-ttc").value=d.montant_ttc||0;
document.getElementById("fact-det").innerHTML=h;
document.getElementById("alerte-justif").style.display="none";
}).catch(function(e){showAlert(e.message);});
}

function comptabiliserFacture(){
var hasJustif=!!factFile;
if(!hasJustif)document.getElementById("alerte-justif").style.display="block";
var fd=new FormData();
fd.append("type_doc",document.getElementById("f-type").value);
fd.append("date_piece",document.getElementById("f-date").value);
fd.append("numero_piece",document.getElementById("f-num").value);
fd.append("montant_ht",document.getElementById("f-ht").value||"0");
fd.append("montant_tva",document.getElementById("f-tva").value||"0");
fd.append("montant_ttc",document.getElementById("f-ttc").value||"0");
fd.append("nom_tiers",document.getElementById("f-tiers").value);
fetch("/api/factures/comptabiliser",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){
var h="<div class='al "+(hasJustif?"ok":"err")+"'><span class='al-icon'>"+(hasJustif?"&#9989;":"&#9888;")+"</span><span><strong>Ecriture "+(hasJustif?"generee":"generee SANS JUSTIFICATIF")+"</strong> - ID: "+d.ecriture_id+"</span></div>";
h+="<table><tr><th>Compte</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th></tr>";
for(var i=0;i<d.lignes.length;i++){var l=d.lignes[i];h+="<tr"+(hasJustif?"":" class='sans-just'")+"><td>"+l.compte+"</td><td>"+l.libelle+"</td><td class='num'>"+l.debit.toFixed(2)+"</td><td class='num'>"+l.credit.toFixed(2)+"</td></tr>";}
h+="</table>";
document.getElementById("fact-res").style.display="block";document.getElementById("fact-det").innerHTML=h;
}).catch(function(e){showAlert(e.message);});
}

/* === COMPTABILITE === */
function showCT(n,el){
document.querySelectorAll("#compta-tabs .tab").forEach(function(t){t.classList.remove("active")});
document.querySelectorAll("#s-compta .tc").forEach(function(t){t.classList.remove("active")});
if(el)el.classList.add("active");
var tc=document.getElementById("ct-"+n);if(tc)tc.classList.add("active");
var ps=document.getElementById("period-sel");
ps.style.display=(n==="grandlivre"||n==="balance"||n==="bilan")?"block":"none";
loadCompta();
}

function loadCompta(){
var dd=document.getElementById("gl-dd").value;
var df=document.getElementById("gl-df").value;

fetch("/api/comptabilite/journal").then(function(r){return r.json();}).then(function(j){
var h="";if(!j.length){h="<p style='color:var(--tx2)'>Aucune ecriture enregistree.</p>";}
for(var i=0;i<j.length;i++){var e=j[i];
h+="<div style='border:1px solid var(--brd);border-radius:10px;padding:14px;margin:8px 0'>";
h+="<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px'>";
h+="<strong>"+e.date+" | "+e.journal+" | "+e.piece+"</strong>";
h+="<span class='badge "+(e.validee?"badge-green":"badge-amber")+"'>"+(e.validee?"Validee":"Brouillon")+"</span></div>";
h+="<div style='color:var(--tx2);font-size:.88em;margin-bottom:8px'>"+e.libelle+"</div>";
h+="<table><tr><th>Compte</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th></tr>";
for(var k=0;k<e.lignes.length;k++){var l=e.lignes[k];var sj=l.libelle.indexOf("[SANS JUSTIFICATIF]")>=0;
h+="<tr"+(sj?" class='sans-just'":"")+">";
h+="<td>"+l.compte+"</td><td>"+l.libelle+"</td><td class='num'>"+l.debit.toFixed(2)+"</td><td class='num'>"+l.credit.toFixed(2)+"</td></tr>";}
h+="</table></div>";}
document.getElementById("ct-journal-c").innerHTML=h;
}).catch(function(){});

fetch("/api/comptabilite/balance").then(function(r){return r.json();}).then(function(b){
var h="";if(!b.length){h="<p style='color:var(--tx2)'>Aucune donnee.</p>";}else{
h="<table><tr><th>Compte</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th><th class='num'>Solde D</th><th class='num'>Solde C</th></tr>";
for(var i=0;i<b.length;i++){var r2=b[i];h+="<tr><td>"+r2.compte+"</td><td>"+r2.libelle+"</td><td class='num'>"+r2.total_debit.toFixed(2)+"</td><td class='num'>"+r2.total_credit.toFixed(2)+"</td><td class='num'>"+r2.solde_debiteur.toFixed(2)+"</td><td class='num'>"+r2.solde_crediteur.toFixed(2)+"</td></tr>";}
h+="</table>";}
document.getElementById("ct-balance-c").innerHTML=h;
}).catch(function(){});

var glUrl="/api/comptabilite/grand-livre-detail";
if(dd)glUrl+="?date_debut="+dd+(df?"&date_fin="+df:"");
fetch(glUrl).then(function(r){return r.json();}).then(function(gl){
var h="";if(!gl.length){h="<p style='color:var(--tx2)'>Aucune donnee dans le grand livre.</p>";}
for(var i=0;i<gl.length;i++){var c=gl[i];
h+="<div style='border:1px solid var(--brd);border-radius:10px;padding:14px;margin:8px 0'>";
h+="<strong>"+c.compte+" - "+(c.libelle||"")+"</strong>";
var mvts=c.mouvements||[];
if(mvts.length){h+="<table style='margin-top:8px'><tr><th>Date</th><th>Libelle</th><th class='num'>Debit</th><th class='num'>Credit</th></tr>";
for(var k=0;k<mvts.length;k++){var m=mvts[k];var sj=m.sans_justificatif;
h+="<tr"+(sj?" class='sans-just'":"")+">";
h+="<td>"+(m.date||"")+"</td><td>"+(m.libelle||"")+(sj?" <span class='badge badge-red'>Sans justif.</span>":"")+"</td>";
h+="<td class='num'>"+(m.debit||0).toFixed(2)+"</td><td class='num'>"+(m.credit||0).toFixed(2)+"</td></tr>";}
h+="</table>";}else{h+="<p style='color:var(--tx2);font-size:.85em;margin-top:6px'>Aucun mouvement.</p>";}
h+="</div>";}
document.getElementById("ct-grandlivre-c").innerHTML=h;
}).catch(function(){});

fetch("/api/comptabilite/compte-resultat").then(function(r){return r.json();}).then(function(cr){
var clr=cr.resultat_net>=0?"var(--g)":"var(--r)";
var bg=cr.resultat_net>=0?"var(--gl)":"var(--rl)";
var h="<div class='g2'><div class='card' style='text-align:center'><h2>Charges</h2><div class='val' style='font-size:1.4em;color:var(--r)'>"+cr.charges.total.toFixed(2)+" EUR</div></div>";
h+="<div class='card' style='text-align:center'><h2>Produits</h2><div class='val' style='font-size:1.4em;color:var(--g)'>"+cr.produits.total.toFixed(2)+" EUR</div></div></div>";
h+="<div class='sc' style='margin-top:14px;background:"+bg+"'><div class='val' style='color:"+clr+"'>"+cr.resultat_net.toFixed(2)+" EUR</div><div class='lab'>Resultat net</div></div>";
document.getElementById("ct-resultat-c").innerHTML=h;
}).catch(function(){});

fetch("/api/comptabilite/bilan").then(function(r){return r.json();}).then(function(bi){
var a=bi.actif,p=bi.passif;
var h="<div class='g2'>";
h+="<div><h3 style='margin-bottom:10px;color:var(--p)'>Actif</h3><table><tr><th>Poste</th><th class='num'>Montant</th></tr>";
h+="<tr><td>Immobilisations</td><td class='num'>"+a.immobilisations.toFixed(2)+"</td></tr>";
h+="<tr><td>Stocks</td><td class='num'>"+a.stocks.toFixed(2)+"</td></tr>";
h+="<tr><td>Creances</td><td class='num'>"+a.creances.toFixed(2)+"</td></tr>";
h+="<tr><td>Tresorerie</td><td class='num'>"+a.tresorerie.toFixed(2)+"</td></tr>";
h+="<tr style='font-weight:bold;background:var(--pl)'><td>TOTAL ACTIF</td><td class='num'>"+a.total.toFixed(2)+"</td></tr></table></div>";
h+="<div><h3 style='margin-bottom:10px;color:var(--p)'>Passif</h3><table><tr><th>Poste</th><th class='num'>Montant</th></tr>";
h+="<tr><td>Capitaux propres</td><td class='num'>"+p.capitaux_propres.toFixed(2)+"</td></tr>";
h+="<tr><td>Dettes financieres</td><td class='num'>"+p.dettes_financieres.toFixed(2)+"</td></tr>";
h+="<tr><td>Dettes exploitation</td><td class='num'>"+p.dettes_exploitation.toFixed(2)+"</td></tr>";
h+="<tr style='font-weight:bold;background:var(--pl)'><td>TOTAL PASSIF</td><td class='num'>"+p.total.toFixed(2)+"</td></tr></table></div>";
h+="</div>";
document.getElementById("ct-bilan-c").innerHTML=h;
}).catch(function(){});

(function(){var now=new Date();fetch("/api/comptabilite/declaration-tva?mois="+(now.getMonth()+1)+"&annee="+now.getFullYear()).then(function(r){return r.json();}).then(function(t){
var h="<div class='g3'><div class='sc'><div class='val'>"+t.chiffre_affaires_ht.toFixed(2)+"</div><div class='lab'>CA HT</div></div>";
h+="<div class='sc'><div class='val'>"+t.tva_collectee.toFixed(2)+"</div><div class='lab'>TVA collectee</div></div>";
h+="<div class='sc'><div class='val'>"+t.tva_deductible_totale.toFixed(2)+"</div><div class='lab'>TVA deductible</div></div></div>";
var net=t.tva_nette_a_payer>0?t.tva_nette_a_payer.toFixed(2)+" EUR a payer":t.credit_tva.toFixed(2)+" EUR credit";
h+="<div class='sc' style='margin-top:14px'><div class='val'>"+net+"</div><div class='lab'>TVA nette</div></div>";
document.getElementById("ct-tva-c").innerHTML=h;}).catch(function(){});})();

fetch("/api/comptabilite/charges-sociales-detail").then(function(r){return r.json();}).then(function(soc){
var h="<div class='g4'>";
var ds=soc.destinataires||[];
for(var i=0;i<ds.length;i++){var d=ds[i];
var cls=["blue","amber","green","sc"][i%4];
h+="<div class='sc "+cls+"'><div class='val'>"+(d.montant||0).toFixed(2)+"</div><div class='lab'>"+d.nom+"</div><div style='font-size:.72em;color:var(--tx2);margin-top:4px'>"+d.postes.join(", ")+"</div></div>";}
h+="</div>";
h+="<div class='g3' style='margin-top:14px'>";
h+="<div class='sc'><div class='val'>"+(soc.brut||0).toFixed(2)+"</div><div class='lab'>Salaires bruts</div></div>";
h+="<div class='sc amber'><div class='val'>"+(soc.total||0).toFixed(2)+"</div><div class='lab'>Total charges</div></div>";
h+="<div class='sc blue'><div class='val'>"+(soc.cout_employeur||0).toFixed(2)+"</div><div class='lab'>Cout employeur</div></div></div>";
document.getElementById("ct-social-c").innerHTML=h;
}).catch(function(){});

fetch("/api/comptabilite/plan-comptable").then(function(r){return r.json();}).then(function(pc){
var h="<input placeholder='Rechercher un compte...' oninput='rechPC(this.value)' style='margin-bottom:12px'>";
h+="<table id='pc-t'><tr><th>N</th><th>Libelle</th><th>Classe</th></tr>";
for(var i=0;i<pc.length;i++){h+="<tr><td>"+pc[i].numero+"</td><td>"+pc[i].libelle+"</td><td>"+pc[i].classe+"</td></tr>";}
h+="</table>";document.getElementById("ct-plan-c").innerHTML=h;}).catch(function(){});
}

function rechPC(t){var url=t?"/api/comptabilite/plan-comptable?terme="+encodeURIComponent(t):"/api/comptabilite/plan-comptable";fetch(url).then(function(r){return r.json();}).then(function(pc){var tb=document.getElementById("pc-t");if(!tb)return;var h="<tr><th>N</th><th>Libelle</th><th>Classe</th></tr>";for(var i=0;i<pc.length;i++){h+="<tr><td>"+pc[i].numero+"</td><td>"+pc[i].libelle+"</td><td>"+pc[i].classe+"</td></tr>";}tb.innerHTML=h;}).catch(function(){});}

function validerEcr(){fetch("/api/comptabilite/valider",{method:"POST"}).then(function(r){return r.json();}).then(function(d){showAlert("Ecritures validees: "+d.nb_validees+(d.erreurs.length?" | Erreurs: "+d.erreurs.join(", "):""),"ok");loadCompta();}).catch(function(e){showAlert(e.message);});}

function saisirEcriture(){
var fd=new FormData();
fd.append("date_piece",document.getElementById("em-date").value);
fd.append("libelle",document.getElementById("em-lib").value);
fd.append("compte_debit",document.getElementById("em-deb").value);
fd.append("compte_credit",document.getElementById("em-cre").value);
fd.append("montant",document.getElementById("em-mt").value||"0");
fd.append("has_justificatif",document.getElementById("em-just").value);
fetch("/api/comptabilite/ecriture/manuelle",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){
var h="<div class='al "+(d.sans_justificatif?"err":"ok")+"'><span class='al-icon'>"+(d.sans_justificatif?"&#9888;":"&#9989;")+"</span><span>"+(d.alerte||"Ecriture enregistree avec succes.")+"</span></div>";
document.getElementById("em-res").innerHTML=h;
loadCompta();
}).catch(function(e){document.getElementById("em-res").innerHTML="<div class='al err'><span class='al-icon'>&#10060;</span><span>"+e.message+"</span></div>";});
}

/* === SIMULATION === */
function showSimTab(n,el){document.querySelectorAll("#s-simulation .tab").forEach(function(t){t.classList.remove("active")});document.querySelectorAll("#s-simulation .tc").forEach(function(t){t.classList.remove("active")});if(el)el.classList.add("active");var tc=document.getElementById("sim-"+n);if(tc)tc.classList.add("active");}

function simBulletin(){fetch("/api/simulation/bulletin?brut_mensuel="+document.getElementById("sim-brut").value+"&effectif="+document.getElementById("sim-eff").value+"&est_cadre="+document.getElementById("sim-cadre").value).then(function(r){return r.json();}).then(function(r){
var h="<div class='g3'><div class='sc blue'><div class='val'>"+r.brut_mensuel.toFixed(2)+"</div><div class='lab'>Brut mensuel</div></div>";
h+="<div class='sc green'><div class='val'>"+r.net_a_payer.toFixed(2)+"</div><div class='lab'>Net a payer</div></div>";
h+="<div class='sc amber'><div class='val'>"+r.cout_total_employeur.toFixed(2)+"</div><div class='lab'>Cout employeur</div></div></div>";
h+="<table style='margin-top:14px'><tr><th>Rubrique</th><th class='num'>Patronal</th><th class='num'>Salarial</th></tr>";
var ls=r.lignes||[];for(var i=0;i<ls.length;i++){h+="<tr><td>"+ls[i].libelle+"</td><td class='num'>"+ls[i].montant_patronal.toFixed(2)+"</td><td class='num'>"+ls[i].montant_salarial.toFixed(2)+"</td></tr>";}
h+="</table>";document.getElementById("sim-bull-res").innerHTML=h;}).catch(function(e){showAlert(e.message);});}

function simMicro(){fetch("/api/simulation/micro-entrepreneur?chiffre_affaires="+document.getElementById("sim-ca").value+"&activite="+document.getElementById("sim-act").value+"&acre="+document.getElementById("sim-acre").value).then(function(r){return r.json();}).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-micro-res").innerHTML=h;}).catch(function(e){showAlert(e.message);});}

function simTNS(){fetch("/api/simulation/tns?revenu_net="+document.getElementById("sim-rev").value+"&type_statut="+document.getElementById("sim-stat").value+"&acre="+document.getElementById("sim-tacre").value).then(function(r){return r.json();}).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-tns-res").innerHTML=h;}).catch(function(e){showAlert(e.message);});}

function simGUSO(){fetch("/api/simulation/guso?salaire_brut="+document.getElementById("sim-gbrut").value+"&nb_heures="+document.getElementById("sim-gh").value).then(function(r){return r.json();}).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-guso-res").innerHTML=h;}).catch(function(e){showAlert(e.message);});}

function simIR(){fetch("/api/simulation/impot-independant?benefice="+document.getElementById("sim-ben").value+"&nb_parts="+document.getElementById("sim-parts").value+"&autres_revenus="+document.getElementById("sim-autres").value).then(function(r){return r.json();}).then(function(r){var h="<div class='g4'>";for(var k in r){if(typeof r[k]==="number")h+="<div class='sc'><div class='val'>"+r[k].toFixed(2)+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";document.getElementById("sim-ir-res").innerHTML=h;}).catch(function(e){showAlert(e.message);});}

/* === VEILLE === */
function loadVeille(){var a=document.getElementById("v-annee").value;document.getElementById("v-res").style.display="block";
fetch("/api/veille/baremes/"+a).then(function(r){return r.json();}).then(function(b){var h="<table><tr><th>Parametre</th><th class='num'>Valeur</th></tr>";for(var k in b){h+="<tr><td>"+k.replace(/_/g," ")+"</td><td class='num'>"+b[k]+"</td></tr>";}h+="</table>";document.getElementById("v-baremes").innerHTML=h;}).catch(function(){});
fetch("/api/veille/legislation/"+a).then(function(r){return r.json();}).then(function(l){var h="<p style='margin-bottom:12px'><strong>"+l.description+"</strong></p>";var tx=l.textes_cles||[];for(var i=0;i<tx.length;i++){h+="<div class='al info' style='margin:6px 0'><span class='al-icon'>&#9878;</span><span><strong>"+tx[i].reference+"</strong> - "+tx[i].titre+"<br><small>"+tx[i].resume+"</small></span></div>";}document.getElementById("v-legis").innerHTML=h;}).catch(function(){});
}

function compAnnees(){var a2=parseInt(document.getElementById("v-annee").value),a1=a2-1;
fetch("/api/veille/baremes/comparer/"+a1+"/"+a2).then(function(r){return r.json();}).then(function(d){
if(!d.length){showAlert("Pas de differences entre "+a1+" et "+a2+".","info");return;}
var h="<table><tr><th>Parametre</th><th class='num'>"+a1+"</th><th class='num'>"+a2+"</th><th>Evolution</th></tr>";
for(var i=0;i<d.length;i++){h+="<tr><td>"+d[i].parametre+"</td><td class='num'>"+(d[i]["valeur_"+a1]||"-")+"</td><td class='num'>"+(d[i]["valeur_"+a2]||"-")+"</td><td>"+d[i].evolution+"</td></tr>";}
h+="</table>";document.getElementById("v-comp").innerHTML=h;document.getElementById("v-comp-card").style.display="block";
}).catch(function(e){showAlert(e.message);});}

/* === DOCUMENTS === */
function extraireDoc(){var f=document.getElementById("fi-doc-jur").files[0];if(!f){showAlert("Selectionnez un fichier.","warn");return;}
var fd=new FormData();fd.append("fichier",f);
fetch("/api/documents/extraire",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){
var info=d.info_entreprise||{};var h="<div class='g4'>";for(var k in info){if(info[k])h+="<div class='sc'><div class='val' style='font-size:1em'>"+info[k]+"</div><div class='lab'>"+k.replace(/_/g," ")+"</div></div>";}h+="</div>";
var aws=d.avertissements||[];for(var i=0;i<aws.length;i++){h+="<div class='al warn'><span class='al-icon'>&#9888;</span><span>"+aws[i]+"</span></div>";}
document.getElementById("doc-res").style.display="block";document.getElementById("doc-det").innerHTML=h;
}).catch(function(e){showAlert(e.message);});}

function lireDoc(){var f=document.getElementById("fi-doc-lire").files[0];if(!f){showAlert("Selectionnez un fichier.","warn");return;}
var fd=new FormData();fd.append("fichier",f);
fetch("/api/documents/lire",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(d){
var h="<div class='g4'><div class='sc blue'><div class='val'>"+d.format+"</div><div class='lab'>Format</div></div>";
h+="<div class='sc'><div class='val'>"+(d.nb_pages||1)+"</div><div class='lab'>Pages</div></div>";
h+="<div class='sc "+(d.manuscrit_detecte?"amber":"green")+"'><div class='val'>"+(d.manuscrit_detecte?"Oui":"Non")+"</div><div class='lab'>Manuscrit</div></div>";
h+="<div class='sc'><div class='val'>"+(d.est_scan?"Scan":"Natif")+"</div><div class='lab'>Type</div></div></div>";
h+="<div style='margin-top:14px;background:#f1f5f9;border-radius:10px;padding:16px;max-height:400px;overflow:auto;white-space:pre-wrap;font-size:.84em;font-family:monospace;border:1px solid var(--brd)'>"+d.texte+"</div>";
var aws=d.avertissements||[];for(var i=0;i<aws.length;i++){h+="<div class='al warn' style='margin-top:8px'><span class='al-icon'>&#9888;</span><span>"+aws[i]+"</span></div>";}
document.getElementById("doc-res").style.display="block";document.getElementById("doc-det").innerHTML=h;
}).catch(function(e){showAlert(e.message);});}

/* === PORTEFEUILLE === */
function ajouterEnt(){var fd=new FormData();
fd.append("siret",document.getElementById("ent-siret").value);
fd.append("raison_sociale",document.getElementById("ent-raison").value);
fd.append("forme_juridique",document.getElementById("ent-forme").value);
fd.append("code_naf",document.getElementById("ent-naf").value);
fd.append("effectif",document.getElementById("ent-eff").value||"0");
fd.append("ville",document.getElementById("ent-ville").value);
fetch("/api/entreprises",{method:"POST",body:fd}).then(function(r){if(!r.ok)return r.json().then(function(e){throw new Error(e.detail||"Erreur")});return r.json();}).then(function(){showAlert("Entreprise ajoutee au portefeuille !","ok");rechEnt();}).catch(function(e){showAlert(e.message);});}

function rechEnt(){var q=(document.getElementById("ent-search")||{}).value||"";
fetch("/api/entreprises?q="+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(d){
var h="";if(!d.length){h="<p style='color:var(--tx2);padding:20px 0'>Aucune entreprise dans le portefeuille.</p>";}
for(var i=0;i<d.length;i++){var e=d[i];
h+="<div style='border:1px solid var(--brd);border-radius:10px;padding:14px;margin:8px 0;transition:.2s;cursor:pointer' onmouseover='this.style.borderColor=\"var(--p3)\"' onmouseout='this.style.borderColor=\"var(--brd)\"'>";
h+="<div style='display:flex;justify-content:space-between;align-items:center'>";
h+="<strong>"+e.raison_sociale+"</strong>";
if(e.forme_juridique)h+="<span class='badge badge-blue'>"+e.forme_juridique+"</span>";
h+="</div>";
h+="<div style='font-size:.85em;color:var(--tx2);margin-top:6px'>SIRET: "+e.siret;
if(e.ville)h+=" &bull; "+e.ville;
if(e.code_naf)h+=" &bull; NAF: "+e.code_naf;
if(e.effectif)h+=" &bull; "+e.effectif+" salaries";
h+="</div></div>";}
document.getElementById("ent-list").innerHTML=h;
}).catch(function(){});}

/* === EXPORT === */
function exportSection(name){
var el=document.querySelector("#s-"+name+" .card")||document.querySelector("#s-"+name);
if(!el){showAlert("Rien a exporter.","warn");return;}
var tables=el.querySelectorAll("table");
if(tables.length===0){showAlert("Aucune donnee tabulaire a exporter.","warn");return;}
var csv="";
for(var t=0;t<tables.length;t++){
var rows=tables[t].querySelectorAll("tr");
for(var i=0;i<rows.length;i++){
var cells=rows[i].querySelectorAll("th,td");
var line=[];for(var j=0;j<cells.length;j++){var txt=cells[j].textContent.replace(/"/g,'""');line.push('"'+txt+'"');}
csv+=line.join(";")+"\n";}
csv+="\n";}
var blob=new Blob([csv],{type:"text/csv;charset=utf-8"});
var a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="clara_export_"+name+".csv";a.click();
showAlert("Export CSV telecharge avec succes.","ok");
}

/* === ALERT TOAST === */
function showAlert(msg,type){
type=type||"err";
var d=document.createElement("div");
d.style.cssText="position:fixed;top:20px;right:20px;z-index:9999;padding:14px 20px;border-radius:12px;font-size:.9em;max-width:400px;box-shadow:0 8px 30px rgba(0,0,0,.15);animation:slideIn .3s;font-family:inherit";
if(type==="ok"){d.style.background="#f0fdf4";d.style.color="#166534";d.style.border="1px solid #bbf7d0";}
else if(type==="warn"||type==="info"){d.style.background="#eff6ff";d.style.color="#1e40af";d.style.border="1px solid #bfdbfe";}
else{d.style.background="#fef2f2";d.style.color="#991b1b";d.style.border="1px solid #fecaca";}
d.textContent=msg;document.body.appendChild(d);
setTimeout(function(){d.style.opacity="0";d.style.transition="opacity .3s";setTimeout(function(){d.remove();},300);},4000);
}
</script>
<style>@keyframes slideIn{from{transform:translateX(100px);opacity:0}to{transform:translateX(0);opacity:1}}</style>
</body>
</html>"""
