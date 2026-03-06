"""Routes Comptabilite.

Journal, balance, grand livre, bilan, compte de resultat, TVA,
ecritures manuelles, FEC import/export/validation.
"""

import tempfile
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Form, Query, Request, File, UploadFile
from fastapi.responses import Response

from api.state import (
    log_action, safe_json, get_moteur, sous_comptes,
)
from urssaf_analyzer.comptabilite.plan_comptable import PlanComptable
from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures, TypeJournal, Ecriture, LigneEcriture
from urssaf_analyzer.comptabilite.rapports_comptables import GenerateurRapports

router = APIRouter(prefix="/api", tags=["Comptabilite"])

_sous_comptes = sous_comptes

# ==============================
# COMPTABILITE
# ==============================

@router.get("/api/comptabilite/journal")
async def journal_ecritures():
    moteur = get_moteur()
    return moteur.get_journal()


@router.get("/api/comptabilite/balance")
async def balance_comptable():
    moteur = get_moteur()
    bal = moteur.get_balance()
    # Serialize Decimal to float
    for item in bal:
        for k in ("total_debit", "total_credit", "solde_debiteur", "solde_crediteur"):
            if k in item and not isinstance(item[k], float):
                item[k] = float(item[k])
    return bal


@router.get("/api/comptabilite/grand-livre-detail")
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


@router.get("/api/comptabilite/compte-resultat")
async def compte_resultat():
    moteur = get_moteur()
    gen = GenerateurRapports(moteur)
    return gen.compte_resultat()


@router.get("/api/comptabilite/bilan")
async def bilan():
    moteur = get_moteur()
    gen = GenerateurRapports(moteur)
    raw = gen.bilan_simplifie()
    # Transformer en format attendu par le JS (nombres plats, pas dicts)
    a = raw.get("actif", {})
    p = raw.get("passif", {})
    immo = sum(v["montant"] for v in a.get("immobilisations", {}).values())
    stocks = sum(v["montant"] for v in a.get("actif_circulant", {}).values()
                 if v.get("libelle", "").lower().startswith("stock"))
    creances = sum(v["montant"] for v in a.get("actif_circulant", {}).values()
                   if not v.get("libelle", "").lower().startswith("stock"))
    treso = sum(v["montant"] for v in a.get("tresorerie", {}).values())
    cap_propres = sum(v["montant"] for v in p.get("capitaux_propres", {}).values())
    dettes_fin = sum(v["montant"] for k, v in p.get("dettes", {}).items() if k.startswith("5"))
    dettes_expl = sum(v["montant"] for k, v in p.get("dettes", {}).items() if not k.startswith("5"))
    total_a = immo + stocks + creances + treso
    total_p = cap_propres + dettes_fin + dettes_expl
    return {
        "actif": {
            "immobilisations": round(immo, 2),
            "stocks": round(stocks, 2),
            "creances": round(creances, 2),
            "tresorerie": round(treso, 2),
            "total": round(total_a, 2),
        },
        "passif": {
            "capitaux_propres": round(cap_propres, 2),
            "dettes_financieres": round(dettes_fin, 2),
            "dettes_exploitation": round(dettes_expl, 2),
            "total": round(total_p, 2),
        },
    }


@router.get("/api/comptabilite/declaration-tva")
async def declaration_tva(mois: int = Query(1), annee: int = Query(2026)):
    moteur = get_moteur()
    gen = GenerateurRapports(moteur)
    return gen.declaration_tva(mois=mois, annee=annee)


@router.get("/api/comptabilite/charges-sociales-detail")
async def charges_sociales_detail():
    moteur = get_moteur()
    gen = GenerateurRapports(moteur)
    raw = gen.recapitulatif_charges_sociales()
    # Transformer en format attendu par le JS (destinataires, brut, total, cout_employeur)
    destinataires = []
    if raw.get("cotisations_urssaf", 0) > 0:
        destinataires.append({"nom": "URSSAF", "montant": raw["cotisations_urssaf"], "postes": ["Maladie", "Vieillesse", "Allocations familiales", "CSG/CRDS"]})
    if raw.get("cotisations_retraite", 0) > 0:
        destinataires.append({"nom": "Retraite compl.", "montant": raw["cotisations_retraite"], "postes": ["AGIRC-ARRCO"]})
    if raw.get("mutuelle_prevoyance", 0) > 0:
        destinataires.append({"nom": "Mutuelle/Prevoyance", "montant": raw["mutuelle_prevoyance"], "postes": ["Sante", "Prevoyance"]})
    if raw.get("france_travail", 0) > 0:
        destinataires.append({"nom": "France Travail", "montant": raw["france_travail"], "postes": ["Chomage"]})
    if raw.get("autres_charges_sociales", 0) > 0:
        destinataires.append({"nom": "Autres", "montant": raw["autres_charges_sociales"], "postes": ["Autres charges"]})
    return {
        "destinataires": destinataires,
        "brut": raw.get("salaires_bruts", 0),
        "total": raw.get("total_charges_sociales", 0),
        "cout_employeur": raw.get("cout_total_employeur", 0),
        "taux_charges": raw.get("taux_charges_global", 0),
    }


@router.get("/api/comptabilite/plan-comptable")
async def plan_comptable_api(terme: Optional[str] = None):
    pc = PlanComptable()
    comptes = pc.rechercher(terme) if terme else list(pc.comptes.values())
    return [{"numero": c.numero, "libelle": c.libelle, "classe": c.classe} for c in comptes]


@router.post("/api/comptabilite/ecriture/manuelle")
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


@router.post("/api/comptabilite/valider")
async def valider_ecritures():
    moteur = get_moteur()
    nb_avant = sum(1 for e in moteur.ecritures if not e.validee)
    erreurs = moteur.valider_ecritures()
    nb_validees = nb_avant - len(erreurs)
    log_action("utilisateur", "validation_ecritures", f"{nb_validees} ecritures validees")
    return {"nb_validees": nb_validees, "erreurs": erreurs}


@router.put("/api/comptabilite/ecriture/{ecriture_id}/libelle")
async def modifier_libelle_ecriture(ecriture_id: str, request: Request):
    """Modifie le libelle d'une ecriture et/ou de ses lignes."""
    moteur = get_moteur()
    body = await _safe_json(request)
    nouveau_libelle = body.get("libelle", "").strip()
    lignes_libelles = body.get("lignes", {})  # {index: nouveau_libelle}

    ecriture = None
    for e in moteur.ecritures:
        if e.id == ecriture_id:
            ecriture = e
            break

    if not ecriture:
        raise HTTPException(404, "Ecriture non trouvee")

    if ecriture.validee:
        raise HTTPException(400, "Impossible de modifier une ecriture validee")

    modifs = []
    if nouveau_libelle:
        ancien = ecriture.libelle
        ecriture.libelle = nouveau_libelle
        modifs.append(f"libelle: '{ancien}' -> '{nouveau_libelle}'")

    for idx_str, lib in lignes_libelles.items():
        idx = int(idx_str)
        if 0 <= idx < len(ecriture.lignes):
            lib = lib.strip()
            if lib:
                ancien_l = ecriture.lignes[idx].libelle
                ecriture.lignes[idx].libelle = lib
                modifs.append(f"ligne {idx}: '{ancien_l}' -> '{lib}'")

    log_action("utilisateur", "modification_libelle", f"Ecriture {ecriture_id}: {', '.join(modifs)}")
    return {"ok": True, "modifications": modifs}


@router.delete("/api/comptabilite/ecriture/{ecriture_id}")
async def supprimer_ecriture(ecriture_id: str):
    """Supprime une ecriture comptable non validee."""
    moteur = get_moteur()
    idx = None
    for i, e in enumerate(moteur.ecritures):
        if e.id == ecriture_id:
            if e.validee:
                raise HTTPException(400, "Impossible de supprimer une ecriture validee")
            idx = i
            break
    if idx is None:
        raise HTTPException(404, "Ecriture non trouvee")
    removed = moteur.ecritures.pop(idx)
    log_action("utilisateur", "suppression_ecriture", f"Ecriture {ecriture_id} supprimee: {removed.libelle}")
    return {"ok": True, "message": f"Ecriture {ecriture_id} supprimee"}


@router.put("/api/comptabilite/ecriture/{ecriture_id}/montants")
async def modifier_montants_ecriture(ecriture_id: str, request: Request):
    """Modifie les montants d une ecriture comptable."""
    moteur = get_moteur()
    body = await _safe_json(request)

    ecriture = None
    for e in moteur.ecritures:
        if e.id == ecriture_id:
            ecriture = e
            break
    if not ecriture:
        raise HTTPException(404, "Ecriture non trouvee")
    if ecriture.validee:
        raise HTTPException(400, "Impossible de modifier une ecriture validee")

    modifs = []
    lignes_data = body.get("lignes", {})
    for idx_str, vals in lignes_data.items():
        idx = int(idx_str)
        if 0 <= idx < len(ecriture.lignes):
            ligne = ecriture.lignes[idx]
            if "debit" in vals:
                ancien = float(ligne.debit)
                ligne.debit = Decimal(str(vals["debit"]))
                modifs.append(f"ligne {idx} debit: {ancien} -> {vals['debit']}")
            if "credit" in vals:
                ancien = float(ligne.credit)
                ligne.credit = Decimal(str(vals["credit"]))
                modifs.append(f"ligne {idx} credit: {ancien} -> {vals['credit']}")
    log_action("utilisateur", "modification_montants", f"Ecriture {ecriture_id}: {', '.join(modifs)}")
    return {"ok": True, "modifications": modifs}


@router.delete("/api/comptabilite/ecritures/reset")
async def reset_ecritures():
    """Reinitialise toutes les ecritures comptables non validees."""
    moteur = get_moteur()
    nb_avant = len(moteur.ecritures)
    moteur.ecritures = [e for e in moteur.ecritures if e.validee]
    nb_supprimees = nb_avant - len(moteur.ecritures)
    log_action("utilisateur", "reset_ecritures", f"{nb_supprimees} ecritures supprimees")
    return {"ok": True, "nb_supprimees": nb_supprimees}

# ======================================================================
# COMPTABILITE - SUGGESTIONS ET SOUS-COMPTES
# ======================================================================

_sous_comptes: list[dict] = []


@router.get("/api/comptabilite/suggestions")
async def suggestions_comptes(compte: str = Query(""), description: str = Query("")):
    """Suggestions de comptes pour l'assistance a la saisie d'ecritures.

    Supporte la recherche par numero, libelle, OU par description en langage naturel
    (ex: 'loyer', 'achat fournitures', 'salaire') pour guider les utilisateurs
    ne connaissant pas le plan comptable.
    """
    pc = PlanComptable()
    suggestions = []
    contreparties = []

    # Guide par mots-cles en langage naturel (pour les non-comptables)
    _GUIDE_COMPTES = {
        "loyer": [("613000", "Locations", "Loyers et charges locatives de vos locaux professionnels")],
        "location": [("613000", "Locations", "Loyers de bureaux, ateliers, entrepots"), ("612000", "Redevances de credit-bail", "Leasing de materiel ou vehicules")],
        "electricite": [("606100", "Fournitures non stockables (eau, energie)", "Factures EDF, eau, gaz pour vos locaux")],
        "eau": [("606100", "Fournitures non stockables (eau, energie)", "Factures d'eau et d'energie")],
        "gaz": [("606100", "Fournitures non stockables (eau, energie)", "Factures de gaz et d'energie")],
        "energie": [("606100", "Fournitures non stockables (eau, energie)", "Toutes les factures d'energie (EDF, gaz, eau)")],
        "telephone": [("626000", "Frais postaux et de telecommunications", "Factures de telephone, internet, abonnements telecom")],
        "internet": [("626000", "Frais postaux et de telecommunications", "Abonnement internet, fibre, services cloud")],
        "assurance": [("616000", "Primes d'assurances", "Assurance RC pro, locaux, vehicules, multirisque")],
        "salaire": [("641100", "Salaires, appointements", "Salaires bruts verses aux employes")],
        "paie": [("641100", "Salaires, appointements", "Salaires bruts mensuels des salaries")],
        "remuneration": [("641100", "Salaires, appointements", "Remunerations brutes du personnel")],
        "cotisation": [("645100", "Cotisations URSSAF", "Cotisations sociales URSSAF patronales"), ("645300", "Cotisations retraite complementaire", "Cotisations AGIRC-ARRCO")],
        "urssaf": [("645100", "Cotisations URSSAF", "Charges patronales URSSAF"), ("431000", "Securite sociale (URSSAF)", "Dette URSSAF a payer")],
        "banque": [("512000", "Banque", "Compte bancaire principal de l'entreprise"), ("627000", "Services bancaires et assimiles", "Frais et commissions bancaires")],
        "frais bancaire": [("627000", "Services bancaires et assimiles", "Commissions, frais de tenue de compte, agios")],
        "achat": [("607000", "Achats de marchandises", "Marchandises achetees pour revente"), ("601000", "Achats de matieres premieres", "Matieres premieres pour la production"), ("606000", "Achats non stockes de matieres et fournitures", "Fournitures consommables")],
        "marchandise": [("607000", "Achats de marchandises", "Marchandises destinees a la revente")],
        "fourniture": [("606000", "Achats non stockes de matieres et fournitures", "Fournitures de bureau, consommables"), ("606400", "Fournitures administratives", "Papeterie, cartouches, petit materiel de bureau")],
        "materiel": [("218100", "Materiel de bureau et informatique", "Ordinateurs, imprimantes, mobilier (immobilisations > 500 EUR)"), ("606300", "Fournitures d'entretien et petit equipement", "Petit materiel < 500 EUR (charge directe)")],
        "informatique": [("218100", "Materiel de bureau et informatique", "Ordinateurs, serveurs, logiciels (immobilisations)"), ("606400", "Fournitures administratives", "Petit materiel informatique < 500 EUR")],
        "vehicule": [("218200", "Materiel de transport", "Achat de vehicule (immobilisation)"), ("625000", "Deplacements, missions et receptions", "Frais de deplacement, carburant, peages")],
        "voiture": [("218200", "Materiel de transport", "Achat de vehicule professionnel"), ("625000", "Deplacements, missions et receptions", "Frais de route, carburant")],
        "carburant": [("625000", "Deplacements, missions et receptions", "Carburant, peages, parking professionnel")],
        "deplacement": [("625000", "Deplacements, missions et receptions", "Frais de transport, hotel, repas en deplacement")],
        "restaurant": [("625000", "Deplacements, missions et receptions", "Repas d'affaires, frais de reception")],
        "hotel": [("625000", "Deplacements, missions et receptions", "Frais d'hebergement en deplacement professionnel")],
        "vente": [("707000", "Ventes de marchandises", "Ventes de biens et marchandises"), ("706000", "Prestations de services", "Ventes de services et prestations")],
        "prestation": [("706000", "Prestations de services", "Facturation de services rendus aux clients")],
        "service": [("706000", "Prestations de services", "Prestations de services facturees"), ("604000", "Achats d'etudes et prestations de services", "Prestations de services achetees a des tiers")],
        "client": [("411000", "Clients", "Creances dues par vos clients"), ("707000", "Ventes de marchandises", "Chiffre d'affaires ventes")],
        "fournisseur": [("401000", "Fournisseurs", "Dettes envers vos fournisseurs")],
        "honoraire": [("622000", "Remunerations d'intermediaires et honoraires", "Honoraires d'avocat, comptable, consultant")],
        "comptable": [("622600", "Honoraires comptables", "Honoraires de l'expert-comptable")],
        "avocat": [("622700", "Frais d'actes et de contentieux", "Honoraires d'avocats et frais juridiques")],
        "publicite": [("623000", "Publicite, publications, relations publiques", "Frais de publicite, communication, marketing")],
        "marketing": [("623000", "Publicite, publications, relations publiques", "Campagnes marketing, reseaux sociaux, flyers")],
        "entretien": [("615000", "Entretien et reparations", "Travaux d'entretien et de reparation des locaux/materiel")],
        "reparation": [("615000", "Entretien et reparations", "Reparations de materiel, locaux, equipements")],
        "tva": [("445660", "TVA deductible sur autres biens et services", "TVA recuperable sur vos achats"), ("445710", "TVA collectee", "TVA facturee a vos clients")],
        "impot": [("695000", "Impots sur les benefices", "IS ou IR sur les benefices de l'entreprise"), ("635100", "Contribution economique territoriale (CET)", "CFE + CVAE")],
        "sous-traitance": [("611000", "Sous-traitance generale", "Travaux sous-traites a d'autres entreprises")],
        "formation": [("618000", "Divers (documentation, colloques...)", "Frais de formation professionnelle, conferences"), ("631300", "Participation formation continue", "Contribution formation professionnelle obligatoire")],
        "mutuelle": [("645200", "Cotisations aux mutuelles", "Part patronale de la mutuelle obligatoire"), ("437220", "Mutuelle obligatoire", "Dette mutuelle a payer")],
        "prevoyance": [("645200", "Cotisations aux mutuelles", "Cotisations de prevoyance complementaire"), ("437210", "Prevoyance complementaire", "Dette prevoyance a payer")],
        "retraite": [("645300", "Cotisations retraite complementaire", "Cotisations AGIRC-ARRCO patronales"), ("437100", "Retraite complementaire (AGIRC-ARRCO)", "Dette retraite complementaire")],
        "amortissement": [("681000", "Dotations aux amortissements et provisions - Exploitation", "Amortissement annuel des immobilisations")],
        "capital": [("101000", "Capital social", "Capital social de la societe")],
        "emprunt": [("661000", "Charges d'interets", "Interets d'emprunts bancaires")],
        "dividende": [("455000", "Associes - Comptes courants", "Distribution de dividendes aux associes")],
        "caisse": [("530000", "Caisse", "Paiements et encaissements en especes")],
        "espece": [("530000", "Caisse", "Mouvements de caisse en especes")],
        "attente": [("471000", "Compte d'attente", "Ecriture temporaire en attente de justificatif ou d'affectation definitive")],
        "provision": [("681000", "Dotations aux amortissements et provisions - Exploitation", "Constitution de provisions pour risques et charges")],
    }

    terme = (description or compte or "").lower().strip()

    if terme:
        # 1. Recherche dans le guide en langage naturel
        guide_matches = []
        for mot_cle, comptes_guide in _GUIDE_COMPTES.items():
            if mot_cle in terme or terme in mot_cle:
                for num, lib, explication in comptes_guide:
                    if not any(s["numero"] == num for s in guide_matches):
                        guide_matches.append({"numero": num, "libelle": lib, "explication": explication})

        # 2. Recherche classique par numero ou libelle
        try:
            resultats = pc.rechercher(terme)
            for r in resultats[:15]:
                if not any(s["numero"] == r.numero for s in suggestions):
                    suggestions.append({"numero": r.numero, "libelle": r.libelle, "explication": ""})
        except Exception:
            pass

        # Aussi chercher dans les sous-comptes manuels
        for sc in _sous_comptes:
            if terme in sc["numero"] or terme in sc["libelle"].lower():
                if not any(s["numero"] == sc["numero"] for s in suggestions):
                    suggestions.append({"numero": sc["numero"], "libelle": sc["libelle"], "explication": ""})

        # Mettre les resultats du guide en premier (plus pertinents pour les non-comptables)
        suggestions = guide_matches + suggestions

        # Si pas de resultat et le terme est un mot courant, suggerer le compte d'attente
        if not suggestions:
            suggestions.append({
                "numero": "471000",
                "libelle": "Compte d'attente",
                "explication": "Utilisez ce compte temporaire si vous ne savez pas ou affecter l'ecriture. Vous pourrez reclasser plus tard."
            })

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
        prefix = terme[:3] if len(terme) >= 3 else terme
        for p, cps in contreparties_map.items():
            if prefix.startswith(p) or p.startswith(prefix):
                for num, lib in cps:
                    contreparties.append({"numero": num + "000", "libelle": lib})

    # Convertir en dict {numero_suggestion: numero_contrepartie} pour le JS
    cp_dict = {}
    for s in suggestions[:15]:
        snum = s["numero"]
        sprefix = snum[:3] if len(snum) >= 3 else snum
        for cp in contreparties:
            if cp["numero"][:3] != sprefix:
                cp_dict[snum] = cp["numero"]
                break
    return {"suggestions": suggestions[:15], "contreparties": cp_dict}


@router.post("/api/comptabilite/sous-compte")
async def creer_sous_compte(
    compte_parent: str = Form(...),
    libelle: str = Form(...),
):
    """Cree un sous-compte du plan comptable (ex: 401001 pour fournisseur specifique)."""
    pc = PlanComptable()

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
# FEC - IMPORT / EXPORT / VALIDATION
# ======================================================================

@router.post("/api/fec/importer")
async def importer_fec(file: UploadFile = File(...)):
    """Importe et analyse un fichier FEC (Art. L.47 A-I LPF).

    Accepte les formats : .fec, .txt, .csv avec separateur tabulation ou pipe.
    Retourne l'analyse complete : conformite, equilibre, ecritures.
    """
    from urssaf_analyzer.parsers.fec_parser import FECParser, detecter_fec
    from urssaf_analyzer.models.documents import Document

    contenu = await file.read()
    ext = Path(file.filename).suffix.lower() if file.filename else ".fec"

    # Sauvegarder temporairement
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False, mode="wb") as tmp:
        tmp.write(contenu)
        tmp_path = Path(tmp.name)

    try:
        parser = FECParser()
        if not parser.peut_traiter(tmp_path):
            raise HTTPException(
                400,
                "Le fichier ne semble pas etre un FEC valide. "
                "Verifiez que les 18 colonnes obligatoires sont presentes."
            )

        doc = Document(
            nom_fichier=file.filename or "fec_import.fec",
            chemin=str(tmp_path),
            taille=len(contenu),
        )

        declarations = parser.parser(tmp_path, doc)
        metadata = parser.extraire_metadata(tmp_path)

        # Importer les ecritures FEC dans le moteur comptable
        moteur = get_moteur()
        ecritures_importees = 0
        if declarations and declarations[0].metadata.get("ecritures_fec"):
            from urssaf_analyzer.comptabilite.ecritures import Ecriture, LigneEcriture
            ecritures_fec = declarations[0].metadata["ecritures_fec"]

            # Regrouper par ecriture_num
            par_num = {}
            for ec in ecritures_fec:
                num = ec.get("ecriture_num", "")
                if num not in par_num:
                    par_num[num] = []
                par_num[num].append(ec)

            for num, lignes_ec in par_num.items():
                if not lignes_ec:
                    continue
                premiere = lignes_ec[0]
                journal_code = premiere.get("journal_code", "OD")

                # Mapper vers TypeJournal
                tj = TypeJournal.OPERATIONS_DIVERSES
                for t in TypeJournal:
                    if t.value == journal_code:
                        tj = t
                        break

                ecriture_date = None
                if premiere.get("ecriture_date"):
                    try:
                        ecriture_date = date.fromisoformat(premiere["ecriture_date"])
                    except (ValueError, TypeError):
                        ecriture_date = date.today()

                piece_date = None
                if premiere.get("piece_date"):
                    try:
                        piece_date = date.fromisoformat(premiere["piece_date"])
                    except (ValueError, TypeError):
                        pass

                ecriture = Ecriture(
                    journal=tj,
                    date_ecriture=ecriture_date or date.today(),
                    date_piece=piece_date or ecriture_date or date.today(),
                    numero_piece=premiere.get("piece_ref", num),
                    libelle=premiere.get("ecriture_lib", ""),
                )

                for l in lignes_ec:
                    ecriture.lignes.append(LigneEcriture(
                        compte=l.get("compte_num", ""),
                        libelle=l.get("ecriture_lib", ""),
                        debit=Decimal(str(l.get("debit", 0))),
                        credit=Decimal(str(l.get("credit", 0))),
                        lettrage=l.get("ecrture_let", ""),
                        piece_ref=l.get("piece_ref", ""),
                    ))

                moteur.ecritures.append(ecriture)
                ecritures_importees += 1

        # Retirer les ecritures brutes de la reponse (trop volumineux)
        result_meta = {k: v for k, v in (declarations[0].metadata or {}).items()
                       if k != "ecritures_fec"}

        log_action("utilisateur", "import_fec", f"{file.filename}: {ecritures_importees} ecritures importees")
        return {
            "ok": True,
            "fichier": file.filename,
            "ecritures_importees": ecritures_importees,
            "metadata": metadata,
            "analyse": result_meta,
        }
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/api/fec/exporter")
async def exporter_fec_endpoint(
    siren: str = Query("", description="SIREN de l'entreprise (9 chiffres)"),
    date_cloture: Optional[str] = Query(None, description="Date de cloture (YYYY-MM-DD)"),
    validees_seulement: bool = Query(True, description="N'exporter que les ecritures validees"),
):
    """Exporte les ecritures comptables au format FEC reglementaire.

    Genere un fichier conforme a l'art. L.47 A-I LPF, telechargeable directement.
    Nom de fichier : {SIREN}FEC{YYYYMMDD}.txt
    """
    from urssaf_analyzer.comptabilite.fec_export import exporter_fec, nom_fichier_fec
    from fastapi.responses import Response

    moteur = get_moteur()
    if not moteur.ecritures:
        raise HTTPException(404, "Aucune ecriture comptable a exporter")

    dt_cloture = None
    if date_cloture:
        try:
            dt_cloture = date.fromisoformat(date_cloture)
        except ValueError:
            raise HTTPException(400, "Format de date invalide (attendu: YYYY-MM-DD)")

    contenu = exporter_fec(moteur, siren=siren, date_cloture=dt_cloture,
                            validees_seulement=validees_seulement)
    filename = nom_fichier_fec(siren, dt_cloture)

    log_action("utilisateur", "export_fec", f"Export FEC: {filename}")
    return Response(
        content=contenu.encode("utf-8-sig"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-FEC-Siren": siren or "000000000",
        },
    )


@router.post("/api/fec/valider")
async def valider_fec_endpoint(file: UploadFile = File(...)):
    """Valide la conformite d'un fichier FEC (controles DGFIP).

    Controles effectues :
    - Presence des 18 colonnes obligatoires (art. A.47 A-1 LPF)
    - Format des dates (YYYYMMDD)
    - Equilibre debit/credit par ecriture
    - Equilibre general du fichier
    """
    from urssaf_analyzer.comptabilite.fec_export import valider_fec as _valider_fec

    contenu_bytes = await file.read()
    try:
        contenu = contenu_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        contenu = contenu_bytes.decode("latin-1")

    # Detecter le separateur
    premiere_ligne = contenu.split("\n", 1)[0]
    sep = "\t"
    for s in ("\t", "|", ";"):
        if s in premiere_ligne:
            sep = s
            break

    rapport = _valider_fec(contenu, separateur=sep)
    rapport["fichier"] = file.filename
    log_action("utilisateur", "validation_fec", f"{file.filename}: {'conforme' if rapport['valide'] else 'non conforme'}")
    return rapport
