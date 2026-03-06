"""Routes Ressources Humaines (RH).

Gestion des contrats, conges, arrets, sanctions, attestations,
entretiens, visites medicales, planning, alertes.
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Form, Query, Request

from api.state import (
    rh_contrats, rh_avenants, rh_conges, rh_arrets,
    rh_sanctions, rh_attestations, rh_entretiens, rh_visites_med,
    rh_echanges, rh_planning, alertes_config, alertes_libres,
    planning_creneau_defaut, entete_config,
    log_action, safe_json, paginate, get_moteur,
    DEFAULT_PAGE_LIMIT,
)

router = APIRouter(prefix="/api/rh", tags=["RH"])

# Alias pour compatibilite avec le code extrait
_rh_contrats = rh_contrats
_rh_avenants = rh_avenants
_rh_conges = rh_conges
_rh_arrets = rh_arrets
_rh_sanctions = rh_sanctions
_rh_attestations = rh_attestations
_rh_entretiens = rh_entretiens
_rh_visites_med = rh_visites_med
_rh_echanges = rh_echanges
_rh_planning = rh_planning
_alertes_config = alertes_config
_alertes_libres = alertes_libres
_planning_creneau_defaut = planning_creneau_defaut
_entete_config = entete_config
_DEFAULT_PAGE_LIMIT = DEFAULT_PAGE_LIMIT
_paginate = paginate

# ==============================
# RESSOURCES HUMAINES
# ==============================

@router.post("/contrats")
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
    nir: str = Form(""),
):
    """Cree un contrat de travail avec toutes les mentions legales obligatoires (Code du travail L.1221-1 et suivants)."""
    contrat_id = str(uuid.uuid4())[:8]
    salarie_id = str(uuid.uuid4())[:8]

    # Detection de doublons par Nom/Prenom et NIR
    nir_value = nir.strip() if nir else ""
    doublons_detectes = []
    nom_norm = nom_salarie.strip().lower()
    prenom_norm = prenom_salarie.strip().lower()

    for c in _rh_contrats:
        c_nom = c.get("nom_salarie", "").strip().lower()
        c_prenom = c.get("prenom_salarie", "").strip().lower()
        c_nir = c.get("nir", "")

        # Match par NIR (plus fiable)
        if nir_value and c_nir and nir_value.replace(" ", "") == c_nir.replace(" ", ""):
            doublons_detectes.append({
                "id": c["id"],
                "nom": c.get("nom_salarie", ""),
                "prenom": c.get("prenom_salarie", ""),
                "poste": c.get("poste", ""),
                "type_contrat": c.get("type_contrat", ""),
                "date_debut": c.get("date_debut", ""),
                "motif": "nir_identique",
                "nir": c_nir,
            })
            continue

        # Match par nom + prenom (insensible a la casse)
        if c_nom == nom_norm and c_prenom == prenom_norm:
            doublons_detectes.append({
                "id": c["id"],
                "nom": c.get("nom_salarie", ""),
                "prenom": c.get("prenom_salarie", ""),
                "poste": c.get("poste", ""),
                "type_contrat": c.get("type_contrat", ""),
                "date_debut": c.get("date_debut", ""),
                "motif": "nom_prenom_identique",
                "nir": c_nir,
            })

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
        "nir": nir_value,
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

    # 3. Planning : suggestion sans auto-creation
    # Le planning doit etre cree manuellement par l'utilisateur
    # en respectant le temps_travail et duree_hebdo du contrat
    cascading["planning_suggestion"] = {
        "temps_travail": temps_travail,
        "duree_hebdo": duree_hebdo,
        "message": f"Pensez a creer le planning de {prenom_salarie} {nom_salarie} ({temps_travail}, {duree_hebdo}h/sem) dans l onglet RH > Planning.",
    }

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

    # Ajouter l'alerte de doublons au retour
    if doublons_detectes:
        contrat["doublons_detectes"] = doublons_detectes
        contrat["alerte_doublon"] = (
            f"Attention : {len(doublons_detectes)} fiche(s) existante(s) trouvee(s) pour "
            f"{prenom_salarie} {nom_salarie}. Verifiez qu'il ne s'agit pas d'un doublon."
        )

    log_action("utilisateur", "creation_contrat", f"{type_contrat} {prenom_salarie} {nom_salarie} - {poste}")
    return contrat


@router.get("/doublons")
async def detecter_doublons_salaries():
    """Detecte les doublons potentiels parmi les salaries (par Nom/Prenom et NIR)."""
    doublons = []
    seen_noms = {}  # (nom_lower, prenom_lower) -> [contrats]
    seen_nirs = {}  # nir -> [contrats]

    for c in _rh_contrats:
        nom = c.get("nom_salarie", "").strip().lower()
        prenom = c.get("prenom_salarie", "").strip().lower()
        nir = c.get("nir", "").strip()

        # Detection par nom + prenom
        if nom and prenom:
            cle = (nom, prenom)
            if cle not in seen_noms:
                seen_noms[cle] = []
            seen_noms[cle].append(c)

        # Detection par NIR
        if nir and not nir.startswith("unknown_"):
            if nir not in seen_nirs:
                seen_nirs[nir] = []
            seen_nirs[nir].append(c)

    # Collecter les doublons par nom/prenom
    for cle, contrats in seen_noms.items():
        if len(contrats) > 1:
            doublons.append({
                "type": "nom_prenom",
                "valeur": f"{contrats[0].get('prenom_salarie', '')} {contrats[0].get('nom_salarie', '')}",
                "nb_occurrences": len(contrats),
                "fiches": [{
                    "id": c["id"],
                    "nom": c.get("nom_salarie", ""),
                    "prenom": c.get("prenom_salarie", ""),
                    "poste": c.get("poste", ""),
                    "type_contrat": c.get("type_contrat", ""),
                    "date_debut": c.get("date_debut", ""),
                    "nir": c.get("nir", ""),
                    "source": c.get("source", ""),
                    "salaire_brut": c.get("salaire_brut", "0"),
                } for c in contrats],
            })

    # Collecter les doublons par NIR
    for nir, contrats in seen_nirs.items():
        if len(contrats) > 1:
            # Verifier que ce n'est pas deja couvert par le doublon nom/prenom
            deja_couvert = False
            for d in doublons:
                ids_existants = {f["id"] for f in d["fiches"]}
                ids_nir = {c["id"] for c in contrats}
                if ids_nir.issubset(ids_existants):
                    deja_couvert = True
                    break
            if not deja_couvert:
                doublons.append({
                    "type": "nir",
                    "valeur": nir,
                    "nb_occurrences": len(contrats),
                    "fiches": [{
                        "id": c["id"],
                        "nom": c.get("nom_salarie", ""),
                        "prenom": c.get("prenom_salarie", ""),
                        "poste": c.get("poste", ""),
                        "type_contrat": c.get("type_contrat", ""),
                        "date_debut": c.get("date_debut", ""),
                        "nir": c.get("nir", ""),
                        "source": c.get("source", ""),
                        "salaire_brut": c.get("salaire_brut", "0"),
                    } for c in contrats],
                })

    return {
        "nb_doublons": len(doublons),
        "doublons": doublons,
    }


@router.post("/doublons/fusionner")
async def fusionner_doublons(request: Request):
    """Fusionne deux fiches salarie en une seule (garde la plus complete)."""
    body = await _safe_json(request)
    id_garder = body.get("id_garder", "")
    id_supprimer = body.get("id_supprimer", "")

    if not id_garder or not id_supprimer:
        raise HTTPException(400, "id_garder et id_supprimer sont requis")
    if id_garder == id_supprimer:
        raise HTTPException(400, "Les deux identifiants doivent etre differents")

    fiche_garder = None
    fiche_supprimer = None
    idx_supprimer = -1
    for i, c in enumerate(_rh_contrats):
        if c["id"] == id_garder:
            fiche_garder = c
        if c["id"] == id_supprimer:
            fiche_supprimer = c
            idx_supprimer = i

    if not fiche_garder:
        raise HTTPException(404, f"Fiche a garder ({id_garder}) non trouvee")
    if not fiche_supprimer:
        raise HTTPException(404, f"Fiche a supprimer ({id_supprimer}) non trouvee")

    # Fusionner: completer la fiche gardee avec les infos manquantes
    champs_a_fusionner = [
        "nir", "poste", "convention_collective", "salaire_brut",
        "date_debut", "date_fin", "duree_hebdo",
    ]
    for champ in champs_a_fusionner:
        val_garder = fiche_garder.get(champ, "")
        val_supprimer = fiche_supprimer.get(champ, "")
        if (not val_garder or val_garder == "0" or val_garder == "") and val_supprimer and val_supprimer != "0":
            fiche_garder[champ] = val_supprimer

    # Supprimer la fiche doublon
    if idx_supprimer >= 0:
        _rh_contrats.pop(idx_supprimer)

    log_action("utilisateur", "fusion_doublons", f"Garde {id_garder}, supprime {id_supprimer}")
    return {
        "status": "ok",
        "fiche_gardee": fiche_garder,
        "message": f"Fiche {id_supprimer} fusionnee dans {id_garder} et supprimee.",
    }


@router.get("/contrats")
async def liste_contrats(offset: int = Query(0, ge=0), limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1)):
    """Liste tous les contrats de travail."""
    return _paginate(_rh_contrats, offset, limit)


@router.get("/contrats/{contrat_id}")
async def detail_contrat(contrat_id: str):
    """Recupere un contrat par son identifiant."""
    for c in _rh_contrats:
        if c["id"] == contrat_id:
            return c
    raise HTTPException(404, "Contrat non trouve")


@router.post("/contrats/{contrat_id}/modifier")
async def modifier_contrat(contrat_id: str, request: Request):
    """Modifie un contrat/fiche salarie existant."""
    form = await request.form()
    contrat = None
    for c in _rh_contrats:
        if c["id"] == contrat_id:
            contrat = c
            break
    if not contrat:
        raise HTTPException(404, "Contrat non trouve")
    champs_modifiables = [
        "nom_salarie", "prenom_salarie", "poste", "type_contrat",
        "date_debut", "date_fin", "salaire_brut", "nir",
        "convention_collective", "temps_travail", "duree_hebdo",
        "periode_essai_jours", "motif_cdd", "statut",
    ]
    for champ in champs_modifiables:
        if champ in form:
            contrat[champ] = form[champ]
    if "verifie" in form:
        contrat["verifie"] = form["verifie"] in ("true", "True", "1")
    contrat["date_modification"] = datetime.now().isoformat()
    log_action("utilisateur", "modification_contrat", f"{contrat.get('prenom_salarie','')} {contrat.get('nom_salarie','')} ({contrat_id})")
    return contrat


@router.get("/contrats/{contrat_id}/document")
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
<p style="text-align:center;margin-top:30px;font-size:.8em;color:#94a3b8">Document genere par NormaCheck v3.9.0 - Ce document doit etre signe en deux exemplaires originaux</p>
</body></html>"""
    return HTMLResponse(html)


# ======================================================================
# RH - BULLETINS DE PAIE
# ======================================================================

_rh_bulletins: list[dict] = []
_epargne_contrats: list[dict] = []


@router.post("/bulletins/generer")
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
    heures_travaillees: str = Form("151.67"),
):
    """Genere un bulletin de salaire conforme R.3243-1 du Code du travail."""
    from urssaf_analyzer.rules.contribution_rules import ContributionRules

    alertes = []

    # Si contrat_id fourni, recuperer les infos (accepte ID ou nom salarie)
    contrat = None
    ccn_label = ""
    if contrat_id:
        cid_lower = contrat_id.strip().lower()
        for c in _rh_contrats:
            c_nom_complet = f"{c.get('prenom_salarie', '')} {c.get('nom_salarie', '')}".strip().lower()
            if c.get("id", "").lower() == cid_lower or c.get("salarie_id", "").lower() == cid_lower or c_nom_complet == cid_lower or cid_lower in c_nom_complet:
                contrat = c
                nom_salarie = nom_salarie or c.get("nom_salarie", "") or c.get("nom", "")
                prenom_salarie = prenom_salarie or c.get("prenom_salarie", "") or c.get("prenom", "")
                salaire_brut = salaire_brut if float(salaire_brut or 0) > 0 else str(c.get("salaire_brut", 0))
                est_cadre = "true" if c.get("convention_collective", "").lower().find("cadre") >= 0 else est_cadre
                ccn_label = c.get("convention_collective", "")
                if c.get("duree_hebdo") and float(c.get("duree_hebdo", 35)) != 35:
                    heures_travaillees = str(round(float(c["duree_hebdo"]) / 35 * 151.67, 2))
                break

    h_trav = float(heures_travaillees or "151.67")
    brut_base = Decimal(str(float(salaire_brut or "0")))
    hs = Decimal(str(float(heures_supplementaires or "0")))
    prime = Decimal(str(float(primes or "0")))
    an = Decimal(str(float(avantages_nature or "0")))
    abs_j = int(float(absences_jours or "0"))

    # Retenue absences (base 21.67 jours ouvrables/mois)
    retenue_abs = round(float(brut_base) / 21.67 * abs_j, 2) if abs_j > 0 else 0

    # Taux horaire (base heures travaillees)
    taux_horaire = round(float(brut_base) / h_trav, 2) if h_trav > 0 else 0

    # Majoration HS (25% pour les 8 premieres heures, 50% au-dela - art. L.3121-36 CT)
    if float(hs) > 0:
        hs_25 = min(float(hs), 8) * taux_horaire * 1.25
        hs_50 = max(0, float(hs) - 8) * taux_horaire * 1.50
        montant_hs = round(hs_25 + hs_50, 2)
    else:
        montant_hs = 0

    brut_total = float(brut_base) + montant_hs + float(prime) + float(an) - retenue_abs

    # --- Alertes SMIC et minimum conventionnel ---
    smic_horaire = round(float(_SMIC_MENSUEL) / 151.67, 2)  # ~12.04 EUR en 2026
    smic_mensuel = float(_SMIC_MENSUEL)

    if float(brut_base) > 0 and taux_horaire < smic_horaire:
        alertes.append({
            "niveau": "haute",
            "message": f"ALERTE SMIC : Le taux horaire ({taux_horaire:.2f} EUR/h) est inferieur au SMIC horaire ({smic_horaire:.2f} EUR/h). "
                       f"Le salaire brut minimum pour {h_trav}h est de {round(smic_horaire * h_trav, 2):.2f} EUR. "
                       f"Ref: Art. L.3231-2 du Code du travail.",
        })

    if float(brut_base) > 0 and float(brut_base) < smic_mensuel and h_trav >= 151.67:
        alertes.append({
            "niveau": "haute",
            "message": f"ALERTE SMIC MENSUEL : Le salaire brut ({float(brut_base):.2f} EUR) est inferieur au SMIC mensuel "
                       f"({smic_mensuel:.2f} EUR) pour un temps complet. Ref: Art. D.3231-6 CT.",
        })

    # Alerte minimum conventionnel (si convention renseignee)
    if ccn_label:
        # Tenter de verifier le minimum conventionnel via la base IDCC
        min_conv_rh = None
        try:
            from urssaf_analyzer.config.idcc_database import rechercher_idcc, get_ccn_par_idcc
            ccn_found_rh = get_ccn_par_idcc(ccn_label)
            if not ccn_found_rh:
                res_rh = rechercher_idcc(ccn_label)
                if res_rh:
                    ccn_found_rh = get_ccn_par_idcc(res_rh[0]["idcc"])
            if ccn_found_rh:
                is_cadre = est_cadre.lower() == "true"
                if is_cadre and ccn_found_rh.get("salaire_minimum_cadre"):
                    min_conv_rh = float(ccn_found_rh["salaire_minimum_cadre"])
                elif ccn_found_rh.get("salaire_minimum_conventionnel"):
                    min_conv_rh = float(ccn_found_rh["salaire_minimum_conventionnel"])
        except Exception:
            pass
        if min_conv_rh and float(brut_base) > 0 and float(brut_base) < min_conv_rh:
            alertes.append({
                "niveau": "haute",
                "message": f"ALERTE MINIMUM CONVENTIONNEL : Le salaire brut ({float(brut_base):.2f} EUR) est inferieur "
                           f"au minimum conventionnel ({min_conv_rh:.2f} EUR) de la CCN {ccn_label}. "
                           f"L employeur doit appliquer le montant le plus favorable (Art. L.2253-1 CT).",
            })
        elif min_conv_rh:
            alertes.append({
                "niveau": "info",
                "message": f"Convention collective : {ccn_label}. Minimum conventionnel : {min_conv_rh:.2f} EUR/mois. "
                           f"Salaire conforme (Art. L.2253-1 CT).",
            })
        else:
            alertes.append({
                "niveau": "info",
                "message": f"Convention collective : {ccn_label}. Verifiez que le salaire respecte le minimum conventionnel "
                           f"applicable a la classification du poste (Art. L.2253-1 CT).",
            })

    # Alerte heures sup au-dela du contingent annuel (220h/an - art. D.3121-24 CT)
    if float(hs) > 0:
        alertes.append({
            "niveau": "info",
            "message": f"Heures supplementaires : {float(hs):.1f}h ce mois. Contingent annuel : 220h (Art. D.3121-24 CT). "
                       f"Au-dela, repos compensateur obligatoire de 100% (Art. L.3121-30 CT). "
                       f"Exoneration TEPA applicable : reduction cotisations salariales sur les HS.",
        })

    calc = ContributionRules()
    bulletin_data = calc.calculer_bulletin_complet(Decimal(str(brut_total)), est_cadre=est_cadre.lower() == "true")

    # Exoneration TEPA sur HS (Art. 81 quater CGI / Art. L.241-17 CSS)
    exo_tepa_salariale = 0.0
    exo_tepa_patronale = 0.0
    if montant_hs > 0:
        # Reduction salariale : exoneration cotisations salariales d'assurance vieillesse sur HS (11.31%)
        exo_tepa_salariale = round(montant_hs * 0.1131, 2)
        # Deduction forfaitaire patronale : 1.50 EUR par heure (entreprises < 250 sal)
        exo_tepa_patronale = round(float(hs) * 1.50, 2)

    net_avant_impot = float(bulletin_data.get("net_avant_impot", brut_total * 0.78))
    cout_employeur = float(bulletin_data.get("cout_total_employeur", brut_total * 1.45))

    bulletin = {
        "id": str(uuid.uuid4())[:8],
        "contrat_id": contrat_id,
        "nom_salarie": nom_salarie,
        "prenom_salarie": prenom_salarie,
        "mois": mois or date.today().strftime("%Y%m"),
        "salaire_base": float(brut_base),
        "heures_travaillees": h_trav,
        "taux_horaire": taux_horaire,
        "heures_supplementaires": float(hs),
        "montant_hs": montant_hs,
        "primes": float(prime),
        "avantages_nature": float(an),
        "retenue_absences": retenue_abs,
        "brut_total": brut_total,
        "lignes": bulletin_data.get("lignes", []),
        "net_avant_impot": net_avant_impot,
        "total_patronal": float(bulletin_data.get("total_patronal", 0)),
        "total_salarial": float(bulletin_data.get("total_salarial", 0)),
        "net_a_payer": net_avant_impot + exo_tepa_salariale,
        "cout_total_employeur": cout_employeur - exo_tepa_patronale,
        "exoneration_tepa": {
            "reduction_salariale": exo_tepa_salariale,
            "deduction_patronale": exo_tepa_patronale,
            "reference": "Art. 81 quater CGI / Art. L.241-17 CSS",
        } if montant_hs > 0 else None,
        "alertes": alertes,
        "mentions_obligatoires": [
            "Mentions conformes a l'article R.3243-1 du Code du travail",
            "Convention collective applicable" + (f" : {ccn_label}" if ccn_label else ""),
            f"Nombre d'heures de travail : {h_trav}h",
            f"Taux horaire : {taux_horaire:.2f} EUR",
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


@router.get("/bulletins")
async def liste_bulletins(offset: int = Query(0, ge=0), limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1)):
    """Liste tous les bulletins de paie generes."""
    return _paginate(_rh_bulletins, offset, limit)


@router.get("/bulletins/{bulletin_id}/document")
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

    # Alertes HTML pour le bulletin imprimable
    alertes_html = ""
    for a in bulletin.get("alertes", []):
        color = "#991b1b" if a.get("niveau") == "haute" else "#92400e"
        bg = "#fef2f2" if a.get("niveau") == "haute" else "#fffbeb"
        alertes_html += f'<div style="padding:8px 12px;margin:4px 0;border-radius:6px;background:{bg};color:{color};font-size:.84em;border:1px solid {color}20">&#9888; {a["message"]}</div>'

    # TEPA HTML
    tepa_html = ""
    if bulletin.get("exoneration_tepa"):
        t = bulletin["exoneration_tepa"]
        tepa_html = f"""<tr style="background:#f0fdf4"><td>TEPA - Reduction salariale HS</td><td></td><td class="num" style="color:#166534">-{t["reduction_salariale"]:.2f}</td></tr>
<tr style="background:#f0fdf4"><td>TEPA - Deduction patronale HS</td><td class="num" style="color:#166534">-{t["deduction_patronale"]:.2f}</td><td></td></tr>"""

    html = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<title>Bulletin de paie - {bulletin["prenom_salarie"]} {bulletin["nom_salarie"]} - {bulletin["mois"]}</title>
<style>body{{font-family:'Segoe UI',sans-serif;max-width:800px;margin:0 auto;padding:30px;color:#1e293b}}
h1{{color:#1e40af;text-align:center;font-size:1.3em}}
table{{width:100%;border-collapse:collapse;margin:12px 0}}th{{background:#1e40af;color:#fff;padding:8px 12px;text-align:left;font-size:.85em}}
td{{padding:6px 12px;border-bottom:1px solid #e2e8f0;font-size:.88em}}.num{{text-align:right;font-family:monospace}}
.total{{font-weight:700;background:#eff6ff}}
.info-box{{display:flex;gap:20px;justify-content:center;margin:14px 0;flex-wrap:wrap}}
.info-item{{text-align:center;padding:8px 16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0}}
.info-item .val{{font-size:1.2em;font-weight:700;color:#1e40af}}
.info-item .lab{{font-size:.75em;color:#64748b}}
.print-btn{{position:fixed;top:20px;right:20px;padding:10px 20px;background:#1e40af;color:#fff;border:none;border-radius:8px;cursor:pointer}}
@media print{{.print-btn{{display:none}}}}</style></head><body>
<button class="print-btn" onclick="window.print()">Imprimer / PDF</button>
{header}
<h1>BULLETIN DE PAIE</h1>
<p style="text-align:center;color:#64748b">Periode: {bulletin["mois"]} | Salarie: {bulletin["prenom_salarie"]} {bulletin["nom_salarie"]}</p>
{alertes_html}
<div class="info-box">
<div class="info-item"><div class="val">{bulletin["heures_travaillees"]}h</div><div class="lab">Heures travaillees</div></div>
<div class="info-item"><div class="val">{bulletin["taux_horaire"]:.2f} EUR</div><div class="lab">Taux horaire</div></div>
<div class="info-item"><div class="val">{bulletin["heures_supplementaires"]:.1f}h</div><div class="lab">Heures sup.</div></div>
</div>
<table>
<tr><th>Rubrique</th><th class="num">Part patronale</th><th class="num">Part salariale</th></tr>
<tr><td><strong>Salaire de base ({bulletin["heures_travaillees"]}h x {bulletin["taux_horaire"]:.2f} EUR)</strong></td><td class="num">{bulletin["salaire_base"]:.2f}</td><td></td></tr>
{"<tr><td>Heures supplementaires (" + f"{bulletin['heures_supplementaires']:.1f}" + "h - maj. 25%/50%)</td><td class='num'>" + f"{bulletin['montant_hs']:.2f}" + "</td><td></td></tr>" if bulletin["montant_hs"] > 0 else ""}
{"<tr><td>Primes</td><td class='num'>" + f"{bulletin['primes']:.2f}" + "</td><td></td></tr>" if bulletin["primes"] > 0 else ""}
{"<tr><td>Avantages en nature</td><td class='num'>" + f"{bulletin['avantages_nature']:.2f}" + "</td><td></td></tr>" if bulletin["avantages_nature"] > 0 else ""}
{"<tr><td style='color:#ef4444'>Retenue absences (-" + str(bulletin['retenue_absences']) + "j)</td><td class='num' style='color:#ef4444'>-" + f"{bulletin['retenue_absences']:.2f}" + "</td><td></td></tr>" if bulletin["retenue_absences"] > 0 else ""}
<tr class="total"><td>BRUT TOTAL</td><td class="num">{bulletin["brut_total"]:.2f}</td><td></td></tr>
{lignes_html}
<tr class="total"><td>Total cotisations</td><td class="num">{bulletin["total_patronal"]:.2f}</td><td class="num">{bulletin["total_salarial"]:.2f}</td></tr>
{tepa_html}
<tr class="total" style="background:#f0fdf4"><td>NET A PAYER AVANT IMPOT</td><td></td><td class="num" style="font-size:1.1em">{bulletin["net_a_payer"]:.2f} EUR</td></tr>
<tr class="total" style="background:#eff6ff"><td>COUT TOTAL EMPLOYEUR</td><td class="num">{bulletin["cout_total_employeur"]:.2f} EUR</td><td></td></tr>
</table>
<p style="font-size:.78em;color:#94a3b8;margin-top:30px">Bulletin conforme aux mentions obligatoires de l'article R.3243-1 du Code du travail. Document genere par NormaCheck v3.8.</p>
</body></html>"""
    return HTMLResponse(html)


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


# ======================================================================
# RH - ALERTES PERSONNALISABLES
# ======================================================================

_alertes_config: list[dict] = []


@router.post("/alertes/personnaliser")
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


@router.get("/alertes/config")
async def liste_config_alertes():
    """Liste la configuration des alertes."""
    return _alertes_config


# ======================================================================
# RH - ALERTES LIBRES (PERSONNALISEES PAR L'UTILISATEUR)
# ======================================================================

_alertes_libres: list[dict] = []


@router.post("/alertes/libres")
async def creer_alerte_libre(
    titre: str = Form(...),
    description: str = Form(""),
    type_alerte: str = Form("personnalise"),
    urgence: str = Form("moyenne"),
    date_echeance: str = Form(""),
    recurrence: str = Form(""),
    destinataire: str = Form(""),
    action_requise: str = Form(""),
    reference_legale: str = Form(""),
    categorie: str = Form("autre"),
    actif: str = Form("true"),
    delai_rappel_jours: str = Form("7"),
    notes: str = Form(""),
):
    """Cree une alerte libre/personnalisee par l'utilisateur.

    Permet de configurer des rappels sur des echeances specifiques, des obligations
    ponctuelles ou recurrentes, avec notification avant echeance.
    """
    alerte = {
        "id": str(uuid.uuid4())[:8],
        "titre": titre,
        "description": description,
        "type_alerte": type_alerte,
        "urgence": urgence if urgence in ("haute", "moyenne", "info") else "moyenne",
        "date_echeance": date_echeance,
        "recurrence": recurrence if recurrence in ("", "quotidien", "hebdomadaire", "mensuel", "trimestriel", "semestriel", "annuel") else "",
        "destinataire": destinataire,
        "action_requise": action_requise,
        "reference_legale": reference_legale,
        "categorie": categorie,
        "actif": actif.lower() == "true",
        "delai_rappel_jours": int(delai_rappel_jours or "7"),
        "notes": notes,
        "date_creation": datetime.now().isoformat(),
        "date_modification": datetime.now().isoformat(),
        "statut": "active",
    }
    _alertes_libres.append(alerte)
    log_action("utilisateur", "creation_alerte_libre", f"{titre}")
    return alerte


@router.get("/alertes/libres")
async def liste_alertes_libres():
    """Liste toutes les alertes libres configurees."""
    return _alertes_libres


@router.put("/alertes/libres/{alerte_id}")
async def modifier_alerte_libre(
    alerte_id: str,
    titre: str = Form(""),
    description: str = Form(""),
    urgence: str = Form(""),
    date_echeance: str = Form(""),
    recurrence: str = Form(""),
    action_requise: str = Form(""),
    actif: str = Form(""),
    delai_rappel_jours: str = Form(""),
    statut: str = Form(""),
    notes: str = Form(""),
):
    """Modifie une alerte libre existante."""
    alerte = None
    for a in _alertes_libres:
        if a["id"] == alerte_id:
            alerte = a
            break
    if not alerte:
        raise HTTPException(404, "Alerte non trouvee")

    if titre:
        alerte["titre"] = titre
    if description:
        alerte["description"] = description
    if urgence and urgence in ("haute", "moyenne", "info"):
        alerte["urgence"] = urgence
    if date_echeance:
        alerte["date_echeance"] = date_echeance
    if recurrence is not None:
        alerte["recurrence"] = recurrence
    if action_requise:
        alerte["action_requise"] = action_requise
    if actif:
        alerte["actif"] = actif.lower() == "true"
    if delai_rappel_jours:
        alerte["delai_rappel_jours"] = int(delai_rappel_jours)
    if statut and statut in ("active", "traitee", "reportee", "archivee"):
        alerte["statut"] = statut
    if notes:
        alerte["notes"] = notes
    alerte["date_modification"] = datetime.now().isoformat()
    return alerte


@router.delete("/alertes/libres/{alerte_id}")
async def supprimer_alerte_libre(alerte_id: str):
    """Supprime une alerte libre."""
    before = len(_alertes_libres)
    _alertes_libres[:] = [a for a in _alertes_libres if a["id"] != alerte_id]
    if len(_alertes_libres) == before:
        raise HTTPException(404, "Alerte non trouvee")
    return {"status": "ok", "message": "Alerte supprimee"}


# ======================================================================
# RH - AVENANTS
# ======================================================================

@router.post("/avenants")
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


@router.get("/avenants")
async def liste_avenants(offset: int = Query(0, ge=0), limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1)):
    """Liste tous les avenants."""
    return _paginate(_rh_avenants, offset, limit)


# ======================================================================
# RH - CONGES
# ======================================================================

@router.post("/conges")
async def enregistrer_conge(
    nom_salarie: str = Form(""),
    salarie_id: str = Form(""),
    type_conge: str = Form(...),
    date_debut: str = Form(...),
    date_fin: str = Form(...),
    nb_jours: str = Form(...),
    statut: str = Form("demande"),
):
    """Enregistre une demande ou un conge (art. L.3141-1 et suivants CT)."""
    # Accept nom_salarie as an alias for salarie_id
    effective_salarie_id = salarie_id or nom_salarie

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
        "salarie_id": effective_salarie_id,
        "nom_salarie": nom_salarie,
        "type": type_conge,
        "type_conge": type_conge,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "nb_jours": float(nb_jours),
        "statut": statut,
        "date_creation": datetime.now().isoformat(),
        "info_legale": info_legale.get(type_conge, ""),
    }

    _rh_conges.append(conge)
    log_action("utilisateur", "enregistrement_conge", f"{type_conge} salarie {effective_salarie_id} du {date_debut} au {date_fin}")
    return conge


@router.get("/conges")
async def liste_conges(salarie_id: Optional[str] = Query(None), offset: int = Query(0, ge=0), limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1)):
    """Liste les conges, avec filtre optionnel par salarie."""
    data = [c for c in _rh_conges if c["salarie_id"] == salarie_id] if salarie_id else _rh_conges
    return _paginate(data, offset, limit)


# ======================================================================
# RH - ARRETS DE TRAVAIL
# ======================================================================

@router.post("/arrets")
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


@router.get("/arrets")
async def liste_arrets(offset: int = Query(0, ge=0), limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1)):
    """Liste tous les arrets de travail."""
    return _paginate(_rh_arrets, offset, limit)


# ======================================================================
# RH - SANCTIONS DISCIPLINAIRES
# ======================================================================

@router.post("/sanctions")
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


@router.get("/sanctions")
async def liste_sanctions(offset: int = Query(0, ge=0), limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1)):
    """Liste toutes les sanctions disciplinaires."""
    return _paginate(_rh_sanctions, offset, limit)


# ======================================================================
# RH - ATTESTATIONS
# ======================================================================

@router.post("/attestations/generer")
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
    # Accepte un UUID (salarie_id), un nom complet, ou un nom partiel
    contrat_salarie = None
    sid_lower = salarie_id.strip().lower()
    for c in _rh_contrats:
        c_sid = (c.get("salarie_id") or "").lower()
        c_id = (c.get("id") or "").lower()
        c_nom_complet = f"{c.get('prenom_salarie', '')} {c.get('nom_salarie', '')}".strip().lower()
        c_nom = (c.get("nom_salarie") or "").lower()
        c_prenom = (c.get("prenom_salarie") or "").lower()
        if (c_sid == sid_lower or c_id == sid_lower or c_nom_complet == sid_lower
                or c_nom == sid_lower or sid_lower in c_nom_complet):
            contrat_salarie = c
            break

    nom_salarie = ""
    prenom_salarie = ""
    poste = ""
    date_debut = ""
    salaire_brut = 0
    if contrat_salarie:
        nom_salarie = contrat_salarie.get("nom_salarie", "")
        prenom_salarie = contrat_salarie.get("prenom_salarie", "")
        poste = contrat_salarie.get("poste", "")
        date_debut = contrat_salarie.get("date_debut", "")
        salaire_brut = contrat_salarie.get("salaire_brut", 0)
    else:
        # Fallback: utiliser le texte saisi comme nom
        parts = salarie_id.strip().split(" ", 1)
        prenom_salarie = parts[0] if parts else salarie_id
        nom_salarie = parts[1] if len(parts) > 1 else ""

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


@router.get("/attestations")
async def liste_attestations(offset: int = Query(0, ge=0), limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1)):
    """Liste toutes les attestations generees."""
    return _paginate(_rh_attestations, offset, limit)


# ======================================================================
# RH - ENTRETIENS PROFESSIONNELS
# ======================================================================

@router.post("/entretiens")
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


@router.get("/entretiens")
async def liste_entretiens(offset: int = Query(0, ge=0), limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1)):
    """Liste tous les entretiens professionnels."""
    return _paginate(_rh_entretiens, offset, limit)


# ======================================================================
# RH - VISITES MEDICALES
# ======================================================================

@router.post("/visites-medicales")
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


@router.get("/visites-medicales")
async def liste_visites_medicales(offset: int = Query(0, ge=0), limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1)):
    """Liste toutes les visites medicales."""
    return _paginate(_rh_visites_med, offset, limit)


# ======================================================================
# RH - ALERTES (calcul dynamique)
# ======================================================================

@router.get("/alertes")
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

    # 4k. DAS-2 (honoraires > 2400 EUR/beneficiaire/an)
    kb = _biblio_knowledge
    docs_compta = kb.get("documents_comptables", [])
    factures_importees = [d for d in _doc_library if d.get("nature") in ("facture_achat", "facture_vente", "note_frais")]
    if factures_importees or docs_compta:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "das2_honoraires",
            "urgence": "moyenne",
            "titre": "DAS-2 : declaration des honoraires",
            "description": (
                "Tout versement d'honoraires, commissions, courtages, ristournes "
                "superieurs a 2400 EUR par beneficiaire et par an doit etre declare "
                "via la DAS-2 avant le 28 fevrier de l'annee suivante."
            ),
            "reference": "CGI art. 241 a 243-bis - CSS art. L.133-5-3",
            "action_requise": "Verifier le montant cumule des honoraires verses par beneficiaire et deposer la DAS-2",
            "echeance": f"{aujourdhui.year + 1}-02-28",
            "incidence_legale": "Amende de 50% des sommes non declarees (art. 1736 CGI). Majoration 50% si retard > 1 mois.",
        })

    # 4l. Heures supplementaires - contingent annuel 220h
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "heures_supplementaires",
            "urgence": "info",
            "titre": "Contingent annuel d'heures supplementaires (220h)",
            "description": (
                "Le contingent annuel d'heures supplementaires est fixe a 220 heures par salarie. "
                "Au-dela, chaque heure supplementaire ouvre droit a une contrepartie obligatoire en repos (COR). "
                "Majorations: +25% pour les 8 premieres heures/semaine, +50% au-dela."
            ),
            "reference": "Art. L.3121-30 a L.3121-33 CT - Art. D.3121-24 CT",
            "action_requise": "Verifier le decompte individuel des heures supplementaires et les majorations appliquees",
            "incidence_legale": "Rappel de salaire sur 3 ans + dommages et interets pour non-respect du repos compensateur.",
        })

    # 4m. Conges payes - accumulation et prise
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "conges_payes",
            "urgence": "info",
            "titre": "Conges payes : droits et prise effective",
            "description": (
                "Chaque salarie acquiert 2,5 jours ouvrables de conges par mois (30 jours/an). "
                "L'employeur doit permettre la prise des conges et verifier leur effectivite. "
                "Le calcul de l'indemnite se fait au maintien de salaire ou au 1/10eme (le plus favorable)."
            ),
            "reference": "Art. L.3141-1 a L.3141-31 CT",
            "action_requise": "Verifier le solde de conges de chaque salarie et planifier les periodes de prise",
            "incidence_legale": "Indemnite compensatrice de conges non pris due au depart du salarie.",
        })

    # 4n. Affichages obligatoires
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "affichages_obligatoires",
            "urgence": "info",
            "titre": "Affichages obligatoires dans les locaux",
            "description": (
                "L'employeur doit afficher: horaires de travail, convention collective applicable, "
                "coordonnees inspection du travail, consignes de securite, interdiction de fumer, "
                "lutte contre le harcelement moral et sexuel, egalite de remuneration H/F."
            ),
            "reference": "Art. L.1321-1 et suivants CT - Art. R.4227-34 CT",
            "action_requise": "Verifier la presence des affichages obligatoires dans tous les locaux",
            "incidence_legale": "Contravention de 3e a 5e classe selon l'affichage manquant (750 a 1500 EUR).",
        })

    # 4o. Entretien professionnel bisannuel
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "entretien_professionnel",
            "urgence": "moyenne",
            "titre": "Entretien professionnel bisannuel",
            "description": (
                "L'entretien professionnel est obligatoire tous les 2 ans pour chaque salarie. "
                "Un bilan recapitulatif doit etre fait tous les 6 ans. "
                "Il porte sur les perspectives d'evolution professionnelle et les actions de formation."
            ),
            "reference": "Art. L.6315-1 CT",
            "action_requise": "Verifier la planification des entretiens professionnels pour chaque salarie",
            "incidence_legale": "Abondement correctif CPF de 3000 EUR par salarie si non-realise dans les 6 ans (entreprises >= 50 sal.).",
        })

    # --- 5. ECHEANCES LEGALES CALENDAIRES ---
    mois = aujourdhui.month
    annee = aujourdhui.year

    # 5a. Taxe sur les salaires (entreprises non assujetties TVA)
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "taxe_salaires",
            "urgence": "info",
            "titre": "Taxe sur les salaires (si non assujetti TVA)",
            "description": (
                "Les employeurs non soumis a la TVA ou partiellement doivent declarer et payer "
                "la taxe sur les salaires. Baremes progressifs : 4.25%, 8.50%, 13.60%. "
                "Paiement mensuel (>10 000 EUR/an), trimestriel (4 000-10 000 EUR) ou annuel."
            ),
            "reference": "CGI art. 231 a 231 bis V",
            "action_requise": "Verifier l'assujettissement TVA et le cas echeant declarer la taxe sur les salaires",
            "echeance": f"15 janvier {annee + 1}",
            "incidence_legale": "Majoration de 10% pour defaut de declaration, 5% pour retard de paiement.",
        })

    # 5b. Contribution formation professionnelle et taxe apprentissage (via DSN depuis 2022)
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "contribution_formation",
            "urgence": "moyenne",
            "titre": "Contribution formation professionnelle et taxe d'apprentissage",
            "description": (
                f"Depuis 2022, la contribution a la formation professionnelle (0.55% si <11 sal., 1% au-dela) "
                f"et la taxe d'apprentissage (0.68%) sont collectees mensuellement via la DSN par l'URSSAF. "
                f"Le solde de la taxe d'apprentissage (0.09%) est verse directement aux etablissements eligibles."
            ),
            "reference": "Art. L.6131-1 et L.6241-1 CT - Loi Avenir professionnel du 05/09/2018",
            "action_requise": "Verifier le paiement via DSN et le versement du solde de la TA aux organismes eligibles",
            "echeance": "Mensuel (DSN) + solde TA avant le 31 mai",
            "incidence_legale": "Majoration de 100% de l'insuffisance constatee (art. L.6252-4 CT).",
        })

    # 5c. Participation construction (effort construction) >= 50 salaries
    if nb_actifs >= 50:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "participation_construction",
            "urgence": "moyenne",
            "titre": "Participation a l'effort de construction (PEEC)",
            "description": (
                f"Les entreprises >= 50 salaries doivent investir 0.45% de la masse salariale N-1 dans "
                f"le logement des salaries via un organisme collecteur (Action Logement). Effectif: {nb_actifs}."
            ),
            "reference": "Art. L.313-1 CCH",
            "action_requise": "Verifier le versement a Action Logement avant le 31 decembre",
            "echeance": f"{annee}-12-31",
            "incidence_legale": "Cotisation de 2% de la masse salariale en cas de non-versement (art. L.313-4 CCH).",
        })

    # 5d. AGEFIPH - Obligation emploi travailleurs handicapes >= 20 salaries
    if nb_actifs >= 20:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "oeth_handicap",
            "urgence": "moyenne",
            "titre": "Obligation d'emploi de travailleurs handicapes (OETH)",
            "description": (
                f"Les entreprises >= 20 salaries doivent employer au moins 6% de travailleurs handicapes. "
                f"Effectif actif: {nb_actifs}, objectif: {max(1, round(nb_actifs * 0.06))} TH. "
                f"Declaration annuelle via la DSN."
            ),
            "reference": "Art. L.5212-1 et suivants CT",
            "action_requise": "Verifier le taux d'emploi de TH et la declaration OETH via DSN",
            "echeance": "Declaration annuelle via DSN de mars",
            "incidence_legale": f"Contribution AGEFIPH : environ {max(1, round(nb_actifs * 0.06))} x 400 a 600 SMIC horaire/an selon effort.",
        })

    # 5e. Versement mobilite (transport) >= 11 salaries
    if nb_actifs >= 11:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "versement_mobilite",
            "urgence": "info",
            "titre": "Versement mobilite (ex-versement transport)",
            "description": (
                f"Le versement mobilite est du par les entreprises >= 11 salaries. "
                f"Taux variable selon la zone (0.55% a 2.95% en IDF). Effectif: {nb_actifs}."
            ),
            "reference": "Art. L.2333-64 CGCT",
            "action_requise": "Verifier le taux applicable selon la zone et le paiement via DSN",
        })

    # 5f. Forfait social sur epargne salariale
    if nb_actifs >= 50:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "forfait_social",
            "urgence": "info",
            "titre": "Forfait social sur epargne salariale",
            "description": (
                "Le forfait social de 20% s'applique sur l'interessement, la participation, "
                "l'abondement PEE pour les entreprises >= 50 salaries. "
                "Exoneration pour les entreprises < 50 salaries."
            ),
            "reference": "Art. L.137-15 et L.137-16 CSS",
            "action_requise": "Verifier le calcul et le paiement du forfait social sur les sommes versees",
        })

    # 5g. Contribution patronale prevoyance - Declaration DAS2
    # deja gere en 4k

    # 5h. Declaration des effectifs (DADS/DSN annuelle)
    if nb_actifs >= 1 and mois in (1, 2):
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "dsn_annuelle",
            "urgence": "haute",
            "titre": "DSN evenementielle annuelle (bilan)",
            "description": (
                "La DSN de janvier doit inclure les donnees de bilan annuel : effectifs, "
                "masse salariale annuelle, base OETH, base formation. A transmettre avant le 31 janvier."
            ),
            "reference": "Art. R.133-14 CSS",
            "action_requise": "Verifier et transmettre la DSN annuelle (bilan) avant le 31 janvier",
            "echeance": f"{annee}-01-31",
        })

    # 5i. Cotisations retraite complementaire AGIRC-ARRCO
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "agirc_arrco",
            "urgence": "info",
            "titre": "Cotisations retraite complementaire AGIRC-ARRCO",
            "description": (
                "Cotisations obligatoires : Tranche 1 (jusqu'a 1 PASS) 7.87% dont 3.15% salarial. "
                "Tranche 2 (1 a 8 PASS) 21.59% dont 8.64% salarial. "
                "Paiement mensuel ou trimestriel (< 10 salaries)."
            ),
            "reference": "ANI du 17/11/2017 - Accord AGIRC-ARRCO",
            "action_requise": "Verifier les declarations et paiements AGIRC-ARRCO",
        })

    # 5j. Remboursement des frais de transport (50% abonnement)
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "remboursement_transport",
            "urgence": "info",
            "titre": "Prise en charge obligatoire des frais de transport",
            "description": (
                "L'employeur doit prendre en charge 50% du prix des abonnements de transports "
                "publics (metro, bus, train, velo). Egalement le forfait mobilites durables "
                "(velo, covoiturage) jusqu'a 800 EUR/an net d'impot."
            ),
            "reference": "Art. L.3261-2 CT et Art. L.3261-3-1 CT",
            "action_requise": "Verifier la prise en charge des abonnements transport et le forfait mobilites durables",
            "incidence_legale": "Amende de 3750 EUR par salarie concerne (art. R.3261-1 CT).",
        })

    # 5k. NAO (Negociation Annuelle Obligatoire) >= 50 salaries
    if nb_actifs >= 50:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "nao",
            "urgence": "moyenne",
            "titre": "Negociation Annuelle Obligatoire (NAO)",
            "description": (
                f"L'employeur doit engager chaque annee une negociation sur la remuneration, "
                f"le temps de travail, le partage de la valeur ajoutee et l'egalite professionnelle. "
                f"Effectif: {nb_actifs}."
            ),
            "reference": "Art. L.2242-1 et suivants CT",
            "action_requise": "Convoquer les delegues syndicaux pour l'ouverture de la NAO",
            "echeance": "Annuelle",
            "incidence_legale": "Delit d'entrave : 1 an d'emprisonnement et 3750 EUR d'amende (art. L.2243-1 CT).",
        })

    # 5l. BDESE (Base de Donnees Economiques, Sociales et Environnementales) >= 50 sal
    if nb_actifs >= 50:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "bdese",
            "urgence": "moyenne",
            "titre": "BDESE (Base de Donnees Economiques, Sociales et Environnementales)",
            "description": (
                f"La BDESE doit etre mise a disposition du CSE et mise a jour annuellement. "
                f"Contient les informations sur 6 ans (investissements, egalite, flux financiers, "
                f"remuneration, fonds propres, consequences environnementales). Effectif: {nb_actifs}."
            ),
            "reference": "Art. L.2312-18 et R.2312-7 CT - Loi Climat et Resilience 2021",
            "action_requise": "Verifier la mise a jour annuelle de la BDESE",
            "incidence_legale": "Delit d'entrave (7500 EUR d'amende).",
        })

    # 5m. Plan de mobilite >= 50 salaries sur un meme site
    if nb_actifs >= 50:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "plan_mobilite",
            "urgence": "info",
            "titre": "Plan de mobilite employeur",
            "description": (
                f"Les entreprises regroupant >= 50 salaries sur un meme site doivent elaborer "
                f"un plan de mobilite employeur. Effectif: {nb_actifs}."
            ),
            "reference": "Art. L.1214-8-2 Code des transports - Loi LOM du 24/12/2019",
            "action_requise": "Elaborer ou mettre a jour le plan de mobilite",
        })

    # 5n. Referent harcelement CSE + employeur
    if nb_actifs >= 11:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "referent_harcelement",
            "urgence": "info",
            "titre": "Designation d'un referent harcelement sexuel",
            "description": (
                "Le CSE doit designer un referent harcelement sexuel parmi ses membres. "
                "Dans les entreprises >= 250 salaries, l'employeur doit aussi designer un referent charge "
                "d'orienter, informer et accompagner les salaries."
            ),
            "reference": "Art. L.1153-5-1 CT et Art. L.2314-1 CT",
            "action_requise": "Verifier la designation du/des referent(s) harcelement",
        })

    # 5o. Referent securite (personne competente prevention risques)
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "referent_securite",
            "urgence": "info",
            "titre": "Designation d'un referent securite / prevention",
            "description": (
                "L'employeur doit designer un ou plusieurs salaries competents pour s'occuper "
                "des activites de protection et de prevention des risques professionnels. "
                "A defaut, il peut faire appel a des intervenants exterieurs (IPRP)."
            ),
            "reference": "Art. L.4644-1 CT",
            "action_requise": "Verifier la designation du salarie competent en prevention",
        })

    # 5p. Entretien de retour (apres absence longue)
    for contrat in _rh_contrats:
        if contrat.get("statut") != "actif":
            continue
        # Verifier arrets > 30 jours
        for arret in _rh_arrets:
            if arret.get("salarie_id") == contrat.get("salarie_id") and arret.get("date_fin"):
                try:
                    fin_arret = date.fromisoformat(arret["date_fin"])
                    debut_arret = date.fromisoformat(arret.get("date_debut", arret["date_fin"]))
                    duree = (fin_arret - debut_arret).days
                    retour_recent = 0 <= (aujourdhui - fin_arret).days <= 14
                    if duree >= 30 and retour_recent:
                        alertes.append({
                            "id": str(uuid.uuid4())[:8],
                            "type": "entretien_retour_absence",
                            "urgence": "haute",
                            "titre": f"Entretien de retour : {contrat['prenom_salarie']} {contrat['nom_salarie']}",
                            "description": (
                                f"Entretien de reprise obligatoire apres une absence de {duree} jours "
                                f"(retour le {arret['date_fin']}). Un entretien professionnel doit etre propose "
                                f"au salarie de retour d'un arret de travail d'au moins 30 jours."
                            ),
                            "reference": "Art. L.6315-1 CT - Art. R.4624-31 CT",
                            "action_requise": "Organiser l'entretien professionnel de reprise et la visite medicale de reprise",
                            "salarie_id": contrat.get("salarie_id"),
                        })
                except (ValueError, TypeError):
                    pass

    # 5q. Visite d'information et de prevention (VIP) embauche
    for contrat in _rh_contrats:
        if contrat.get("statut") != "actif":
            continue
        try:
            dd = date.fromisoformat(contrat["date_debut"])
            anciennete = (aujourdhui - dd).days
            if anciennete <= 90:  # < 3 mois
                sid = contrat.get("salarie_id", "")
                # Verifier si visite deja planifiee
                a_visite = any(v.get("salarie_id") == sid for v in _rh_visites_med)
                if not a_visite:
                    alertes.append({
                        "id": str(uuid.uuid4())[:8],
                        "type": "vip_embauche",
                        "urgence": "haute" if anciennete > 60 else "moyenne",
                        "titre": f"VIP embauche : {contrat['prenom_salarie']} {contrat['nom_salarie']}",
                        "description": (
                            f"La visite d'information et de prevention (VIP) doit avoir lieu dans les 3 mois "
                            f"suivant la prise de poste. Embauche le {contrat['date_debut']} ({anciennete} jours). "
                            f"Suivi renforce si poste a risque."
                        ),
                        "reference": "Art. R.4624-10 CT",
                        "action_requise": "Prendre rendez-vous avec le service de prevention et sante au travail",
                        "salarie_id": sid,
                        "contrat_id": contrat["id"],
                    })
        except (ValueError, TypeError):
            pass

    # 5r. Arrets de travail en cours - suivi
    for arret in _rh_arrets:
        if arret.get("date_fin") and arret.get("date_debut"):
            try:
                debut = date.fromisoformat(arret["date_debut"])
                fin = date.fromisoformat(arret["date_fin"])
                if debut <= aujourdhui <= fin:
                    duree = (fin - debut).days
                    jours_restants = (fin - aujourdhui).days
                    nom_complet = arret.get("salarie_id", "")
                    for c in _rh_contrats:
                        if c.get("salarie_id") == arret.get("salarie_id"):
                            nom_complet = f"{c['prenom_salarie']} {c['nom_salarie']}"
                            break
                    if jours_restants <= 7:
                        alertes.append({
                            "id": str(uuid.uuid4())[:8],
                            "type": "retour_arret_imminent",
                            "urgence": "moyenne",
                            "titre": f"Retour d'arret imminent : {nom_complet}",
                            "description": (
                                f"Fin de l'arret prevue le {arret['date_fin']} (dans {jours_restants} jour(s)). "
                                f"Duree totale: {duree} jours. "
                                + ("Visite de reprise obligatoire (arret > 30 jours)." if duree >= 30 else "")
                            ),
                            "reference": "Art. R.4624-31 CT" if duree >= 30 else "",
                            "action_requise": "Preparer la reprise" + (" et planifier la visite medicale de reprise" if duree >= 30 else ""),
                            "salarie_id": arret.get("salarie_id"),
                        })
            except (ValueError, TypeError):
                pass

    # 5s. Conges payes en cours - solde et planification
    for conge in _rh_conges:
        if conge.get("date_fin") and conge.get("statut") in ("valide", "accepte", "en_cours"):
            try:
                fin_conge = date.fromisoformat(conge["date_fin"])
                jours_avant_retour = (fin_conge - aujourdhui).days
                if 0 <= jours_avant_retour <= 3:
                    sid = conge.get("salarie_id", "")
                    nom_complet = sid
                    for c in _rh_contrats:
                        if c.get("salarie_id") == sid:
                            nom_complet = f"{c['prenom_salarie']} {c['nom_salarie']}"
                            break
                    alertes.append({
                        "id": str(uuid.uuid4())[:8],
                        "type": "retour_conge",
                        "urgence": "info",
                        "titre": f"Retour de conge : {nom_complet}",
                        "description": f"Retour prevu le {conge['date_fin']} (dans {jours_avant_retour} jour(s)).",
                        "salarie_id": sid,
                    })
            except (ValueError, TypeError):
                pass

    # 5t. Sanctions disciplinaires - purge du dossier
    for sanction in _rh_sanctions:
        if sanction.get("date_notification"):
            try:
                date_sanction = date.fromisoformat(sanction["date_notification"])
                anciennete_sanction = (aujourdhui - date_sanction).days
                if 1060 <= anciennete_sanction <= 1100:  # Proche des 3 ans
                    alertes.append({
                        "id": str(uuid.uuid4())[:8],
                        "type": "purge_sanction",
                        "urgence": "info",
                        "titre": f"Sanction a purger : {sanction.get('nom_salarie', '')}",
                        "description": (
                            f"La sanction du {sanction['date_notification']} ne peut plus etre invoquee "
                            f"(prescription de 3 ans - art. L.1332-5 CT). Elle doit etre retiree du dossier."
                        ),
                        "reference": "Art. L.1332-5 CT",
                        "action_requise": "Retirer la sanction du dossier disciplinaire du salarie",
                    })
            except (ValueError, TypeError):
                pass

    # 5u. Echeances fiscales calendaires
    echeances_fiscales = [
        (1, 15, "TVA mensuelle", "Declarer et payer la TVA du mois precedent (regime mensuel)", "CGI art. 287"),
        (1, 15, "Acompte IS 1er trimestre", "Verser le 1er acompte d'IS (15% ou 25% de l'IS N-1)", "CGI art. 1668"),
        (2, 28, "DAS-2 Honoraires", "Declarer les honoraires verses > 2400 EUR/beneficiaire/an", "CGI art. 240"),
        (3, 1, "Index egalite pro", "Publier l'index d'egalite professionnelle F/H", "Art. L.1142-8 CT"),
        (3, 31, "Contribution AGEFIPH", "Declaration OETH via DSN de mars", "Art. L.5212-5 CT"),
        (4, 15, "Acompte IS 2eme trimestre", "Verser le 2e acompte d'IS", "CGI art. 1668"),
        (5, 31, "Solde taxe apprentissage", "Verser le solde de la taxe d'apprentissage (0.09%)", "Art. L.6241-2 CT"),
        (5, 15, "Liasse fiscale / IS", "Deposer la liasse fiscale et payer le solde d'IS", "CGI art. 223"),
        (6, 15, "Acompte IS 3eme trimestre", "Verser le 3e acompte d'IS", "CGI art. 1668"),
        (12, 15, "Acompte IS 4eme trimestre", "Verser le 4e acompte d'IS", "CGI art. 1668"),
        (12, 31, "PEEC (Action Logement)", "Verser la participation construction 0.45%", "Art. L.313-1 CCH"),
    ]

    for m_ech, j_ech, titre_ech, desc_ech, ref_ech in echeances_fiscales:
        try:
            date_ech = date(annee, m_ech, j_ech)
            jours_avant = (date_ech - aujourdhui).days
            if -7 <= jours_avant <= 30:
                urg = "haute" if jours_avant <= 3 else ("moyenne" if jours_avant <= 14 else "info")
                alertes.append({
                    "id": str(uuid.uuid4())[:8],
                    "type": "echeance_fiscale",
                    "urgence": urg,
                    "titre": titre_ech,
                    "description": f"{desc_ech}. Echeance: {date_ech.isoformat()} ({jours_avant} jour(s)).",
                    "reference": ref_ech,
                    "action_requise": desc_ech,
                    "echeance": date_ech.isoformat(),
                })
        except (ValueError, TypeError):
            pass

    # 5v. Elections CSE - renouvellement tous les 4 ans
    if nb_actifs >= 11:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "elections_cse_renouvellement",
            "urgence": "info",
            "titre": "Renouvellement du CSE (tous les 4 ans)",
            "description": (
                "Le mandat des elus du CSE est de 4 ans. L'employeur doit organiser les elections "
                "de renouvellement et informer les organisations syndicales au moins 2 mois avant l'expiration."
            ),
            "reference": "Art. L.2314-33 et L.2314-4 CT",
            "action_requise": "Verifier la date de fin des mandats CSE et anticiper l'organisation des elections",
        })

    # 5w. Protection des donnees (RGPD / DPO)
    if nb_actifs >= 1:
        alertes.append({
            "id": str(uuid.uuid4())[:8],
            "type": "rgpd_conformite",
            "urgence": "info",
            "titre": "Conformite RGPD - Protection des donnees personnelles",
            "description": (
                "L'employeur traite des donnees personnelles de ses salaries (paie, sante, evaluations). "
                "Registre des traitements obligatoire. DPO obligatoire si plus de 250 salaries ou "
                "traitement de donnees sensibles a grande echelle."
            ),
            "reference": "RGPD art. 30, 37 - Loi Informatique et Libertes (CNIL)",
            "action_requise": "Verifier le registre des traitements, les clauses contractuelles et la designation DPO si necessaire",
        })

    # 5x. Medaille du travail (20, 30, 35, 40 ans)
    for contrat in _rh_contrats:
        if contrat.get("statut") != "actif" or not contrat.get("date_debut"):
            continue
        try:
            dd = date.fromisoformat(contrat["date_debut"])
            anciennete_ans = (aujourdhui - dd).days / 365.25
            for seuil in (20, 30, 35, 40):
                if seuil - 0.5 <= anciennete_ans <= seuil + 0.5:
                    alertes.append({
                        "id": str(uuid.uuid4())[:8],
                        "type": "medaille_travail",
                        "urgence": "info",
                        "titre": f"Medaille du travail : {contrat['prenom_salarie']} {contrat['nom_salarie']} ({seuil} ans)",
                        "description": (
                            f"Eligible a la medaille du travail ({seuil} ans de service). "
                            f"Gratification facultative exoneree dans la limite d'un mois de salaire."
                        ),
                        "reference": "Decret n2000-1015 du 17/10/2000",
                        "salarie_id": contrat.get("salarie_id"),
                    })
                    break
        except (ValueError, TypeError):
            pass

    # --- 5bis. Alertes libres de l'utilisateur ---
    for al in _alertes_libres:
        if not al.get("actif", True) or al.get("statut") == "archivee":
            continue
        urgence_libre = al.get("urgence", "moyenne")
        # Ajuster urgence si echeance proche
        if al.get("date_echeance"):
            try:
                ech = date.fromisoformat(al["date_echeance"])
                jours_avant = (ech - aujourdhui).days
                if jours_avant < 0:
                    urgence_libre = "haute"
                elif jours_avant <= al.get("delai_rappel_jours", 7):
                    urgence_libre = "haute" if jours_avant <= 3 else "moyenne"
            except (ValueError, TypeError):
                pass
        alertes.append({
            "id": al["id"],
            "type": al.get("type_alerte", "personnalise"),
            "urgence": urgence_libre,
            "titre": al.get("titre", "Alerte personnalisee"),
            "description": al.get("description", ""),
            "reference": al.get("reference_legale", ""),
            "action_requise": al.get("action_requise", ""),
            "echeance": al.get("date_echeance", ""),
            "recurrence": al.get("recurrence", ""),
            "categorie": al.get("categorie", "autre"),
            "notes": al.get("notes", ""),
            "est_libre": True,
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

    # Include contextual alerts from analysis (DPAE/contrat/registre/DUERP absence)
    kb_ctx_alerts = _biblio_knowledge.get("alertes_contextuelles", [])
    for ctx_al in kb_ctx_alerts:
        # Avoid duplicates by title
        if not any(a.get("titre") == ctx_al.get("titre") for a in alertes):
            alertes.append({
                "id": str(uuid.uuid4())[:8],
                "type": ctx_al.get("type", "analyse_contextuelle"),
                "urgence": ctx_al.get("severite", "moyenne"),
                "titre": ctx_al.get("titre", ""),
                "description": ctx_al.get("description", ""),
                "reference": ctx_al.get("reference_legale", ""),
                "action_requise": "Importer le document manquant ou verifier sa conformite",
                "incidence_legale": ctx_al.get("incidence_legale", ""),
            })

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

@router.post("/echanges")
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


@router.get("/echanges")
async def liste_echanges(offset: int = Query(0, ge=0), limit: int = Query(_DEFAULT_PAGE_LIMIT, ge=1)):
    """Liste tous les echanges enregistres."""
    return _paginate(_rh_echanges, offset, limit)


# ======================================================================
# RH - PLANNING (vues jour/hebdo/mensuelle/annuelle, filtrage, integration salaries)
# ======================================================================

# Creneau par defaut applique a l'integration automatique (modifiable)
_planning_creneau_defaut = {
    "heure_debut": "09:00",
    "heure_fin": "17:00",
    "type_poste": "normal",
}


def _resoudre_salarie(salarie_id: str) -> dict:
    """Resout les infos d'un salarie depuis contrats RH et base de connaissances."""
    # 1. Chercher dans les contrats RH
    for c in _rh_contrats:
        if c.get("id") == salarie_id or c.get("salarie_id") == salarie_id:
            return {
                "id": c.get("id", salarie_id),
                "nom": c.get("nom", ""),
                "prenom": c.get("prenom", ""),
                "nom_complet": f"{c.get('prenom', '')} {c.get('nom', '')}".strip(),
                "statut": c.get("categorie", c.get("statut", "")),
                "type_contrat": c.get("type_contrat", ""),
                "source": "contrat_rh",
            }
    # 2. Chercher dans la base de connaissances (salaries detectes)
    kb = _biblio_knowledge
    for nir, sal in kb.get("salaries", {}).items():
        if nir == salarie_id or sal.get("nom", "") == salarie_id:
            return {
                "id": nir,
                "nom": sal.get("nom", ""),
                "prenom": sal.get("prenom", ""),
                "nom_complet": f"{sal.get('prenom', '')} {sal.get('nom', '')}".strip(),
                "statut": sal.get("statut", ""),
                "type_contrat": "",
                "source": "analyse_documents",
            }
    return {
        "id": salarie_id,
        "nom": salarie_id,
        "prenom": "",
        "nom_complet": salarie_id,
        "statut": "",
        "type_contrat": "",
        "source": "manuel",
    }


def _get_statut_jour(salarie_id: str, date_str: str) -> str:
    """Determine le statut d'un salarie pour un jour donne (present, conge, absence, arret)."""
    # Verifier conges
    for c in _rh_conges:
        if c.get("salarie_id") == salarie_id or c.get("nom_salarie") == salarie_id:
            if c.get("statut") != "refuse":
                deb = c.get("date_debut", "")
                fin = c.get("date_fin", "")
                if deb <= date_str <= fin:
                    return f"conge_{c.get('type_conge', c.get('type', 'cp'))}"
    # Verifier arrets
    for a in _rh_arrets:
        if a.get("salarie_id") == salarie_id:
            deb = a.get("date_debut", "")
            fin = a.get("date_fin", "")
            if deb <= date_str <= fin:
                return f"arret_{a.get('type_arret', a.get('type', 'maladie'))}"
    return "present"


def _calculer_majorations(type_poste: str) -> list[dict]:
    """Calcule les majorations applicables selon le type de poste."""
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
    return majorations


def _semaine_iso_vers_dates(semaine: str):
    """Convertit une semaine ISO (YYYY-Www) en tuple (lundi, dimanche)."""
    from datetime import timedelta
    parts = semaine.split("-W")
    if len(parts) != 2:
        raise ValueError("Format semaine invalide. Utiliser YYYY-Www (ex: 2026-W10)")
    annee = int(parts[0])
    num_semaine = int(parts[1])
    jan4 = date(annee, 1, 4)
    lundi_s1 = jan4 - timedelta(days=jan4.weekday())
    lundi = lundi_s1 + timedelta(weeks=num_semaine - 1)
    dimanche = lundi + timedelta(days=6)
    return lundi, dimanche


@router.get("/salaries")
async def liste_salaries():
    """Liste tous les salaries connus (detectes par analyse + contrats RH + manuels).

    Alimente la liste deroulante du planning.
    Fusionne les sources : base de connaissances (OCR/DSN) et contrats RH.
    """
    salaries = {}

    # 1. Salaries detectes lors de l'analyse documentaire
    kb = _biblio_knowledge
    for nir, sal in kb.get("salaries", {}).items():
        nom_complet = f"{sal.get('prenom', '')} {sal.get('nom', '')}".strip()
        salaries[nir] = {
            "id": nir,
            "nir": nir if not nir.startswith("unknown_") else "",
            "nom": sal.get("nom", ""),
            "prenom": sal.get("prenom", ""),
            "nom_complet": nom_complet or nir,
            "statut": sal.get("statut", ""),
            "dernier_brut": sal.get("dernier_brut", 0),
            "type_contrat": "",
            "source": "analyse_documents",
            "date_embauche": "",
            "actif": True,
        }

    # 2. Salaries issus des contrats RH (enrichir ou ajouter)
    for c in _rh_contrats:
        cid = c.get("salarie_id", "") or c.get("id", "")
        c_nom = c.get("nom_salarie", "") or c.get("nom", "")
        c_prenom = c.get("prenom_salarie", "") or c.get("prenom", "")
        nom_complet = f"{c_prenom} {c_nom}".strip()
        # Chercher si deja present par NIR dans les salaries detectes
        matched = False
        for nir, sal in list(salaries.items()):
            if sal["nom"] == c_nom and sal["prenom"] == c_prenom:
                # Enrichir le salarie existant
                salaries[nir]["type_contrat"] = c.get("type_contrat", "")
                salaries[nir]["date_embauche"] = c.get("date_debut", "")
                salaries[nir]["source"] = "contrat_rh+analyse"
                salaries[nir]["actif"] = c.get("statut", "") != "termine"
                matched = True
                break
        if not matched:
            salaries[cid] = {
                "id": cid,
                "nir": c.get("nir", ""),
                "nom": c_nom,
                "prenom": c_prenom,
                "nom_complet": nom_complet or cid,
                "statut": c.get("categorie", c.get("statut", "")),
                "dernier_brut": float(c.get("salaire_brut", 0) or c.get("remuneration", 0) or 0),
                "type_contrat": c.get("type_contrat", ""),
                "source": "contrat_rh",
                "date_embauche": c.get("date_debut", ""),
                "actif": c.get("statut", "") != "termine",
            }

    # 3. Salaries presents uniquement dans le planning (ajouts manuels)
    for p in _rh_planning:
        sid = p.get("salarie_id", "")
        if sid and sid not in salaries:
            salaries[sid] = {
                "id": sid,
                "nir": "",
                "nom": p.get("salarie_nom", sid),
                "prenom": "",
                "nom_complet": p.get("salarie_nom", sid),
                "statut": "",
                "dernier_brut": 0,
                "type_contrat": "",
                "source": "planning_manuel",
                "date_embauche": "",
                "actif": True,
            }

    result = sorted(salaries.values(), key=lambda s: s.get("nom_complet", ""))
    return {"total": len(result), "salaries": result}


@router.post("/planning")
async def ajouter_planning(
    salarie_id: str = Form(...),
    date: str = Form(...),
    date_fin: str = Form(""),
    heure_debut: str = Form(""),
    heure_fin: str = Form(""),
    type_poste: str = Form(""),
    statut: str = Form(""),
    jours_semaine: str = Form("1,2,3,4,5"),
):
    """Ajoute ou modifie une entree de planning pour un salarie.

    Si date_fin est fourni, cree des entrees pour chaque jour de la periode.
    Si heure_debut/heure_fin ne sont pas fournis, utilise le creneau par defaut.
    Le statut peut etre force (conge_cp, arret_maladie...) ou determine automatiquement.
    """
    # Appliquer le creneau par defaut si non specifie
    if not heure_debut:
        heure_debut = _planning_creneau_defaut["heure_debut"]
    if not heure_fin:
        heure_fin = _planning_creneau_defaut["heure_fin"]
    if not type_poste:
        type_poste = _planning_creneau_defaut["type_poste"]

    types_valides = ("normal", "astreinte", "nuit", "dimanche", "ferie")
    if type_poste not in types_valides:
        raise HTTPException(400, f"Type de poste invalide. Valeurs acceptees: {', '.join(types_valides)}")

    # Calcul de la duree
    try:
        h_deb = datetime.strptime(heure_debut, "%H:%M")
        h_fin = datetime.strptime(heure_fin, "%H:%M")
        duree_minutes = (h_fin - h_deb).seconds // 60
        duree_heures = round(duree_minutes / 60, 2)
    except (ValueError, TypeError):
        duree_heures = 0

    majorations = _calculer_majorations(type_poste)
    sal_info = _resoudre_salarie(salarie_id)

    # Determiner les jours de la semaine a planifier
    try:
        jours_valides = [int(j) for j in jours_semaine.split(",") if j.strip()]
    except ValueError:
        jours_valides = [1, 2, 3, 4, 5]

    # Generer la liste de dates (mono ou periode)
    dates_a_planifier = []
    if date_fin and date_fin >= date:
        from datetime import timedelta as _td
        d_start = datetime.strptime(date, "%Y-%m-%d")
        d_end = datetime.strptime(date_fin, "%Y-%m-%d")
        current = d_start
        while current <= d_end:
            # isoweekday: 1=lundi, 7=dimanche
            if current.isoweekday() in jours_valides:
                dates_a_planifier.append(current.strftime("%Y-%m-%d"))
            current += _td(days=1)
    else:
        dates_a_planifier = [date]

    nb_creees = 0
    derniere_entree = None
    for d in dates_a_planifier:
        planning_id = str(uuid.uuid4())[:8]

        # Determiner le statut automatiquement si non force
        st = statut if statut else _get_statut_jour(salarie_id, d)

        entree = {
            "id": planning_id,
            "salarie_id": salarie_id,
            "salarie_nom": sal_info["nom_complet"],
            "salarie_statut": sal_info["statut"],
            "date": d,
            "heure_debut": heure_debut,
            "heure_fin": heure_fin,
            "duree_heures": duree_heures,
            "type_poste": type_poste,
            "statut": st,
            "majorations": majorations,
            "date_creation": datetime.now().isoformat(),
        }

        # Verifier s'il existe deja une entree pour ce salarie a cette date/heure
        index_existant = None
        for i, p in enumerate(_rh_planning):
            if p["salarie_id"] == salarie_id and p["date"] == d and p["heure_debut"] == heure_debut:
                index_existant = i
                break

        if index_existant is not None:
            entree["id"] = _rh_planning[index_existant]["id"]
            _rh_planning[index_existant] = entree
        else:
            _rh_planning.append(entree)
            nb_creees += 1
        derniere_entree = entree

    log_action("utilisateur", "ajout_planning", f"salarie {salarie_id} {date}-{date_fin or date} {heure_debut}-{heure_fin} ({type_poste}) - {nb_creees} creneaux")

    if len(dates_a_planifier) > 1:
        return {"ok": True, "nb_creneaux_crees": nb_creees, "periode": f"{date} - {date_fin}", "derniere_entree": derniere_entree}
    return derniere_entree


@router.get("/planning")
async def liste_planning(
    semaine: Optional[str] = Query(None, description="Semaine ISO: YYYY-Www (ex: 2026-W10)"),
    salarie_id: Optional[str] = Query(None, description="Filtrer par salarie"),
    statut: Optional[str] = Query(None, description="Filtrer par statut (present, conge_cp, arret_maladie...)"),
):
    """Liste le planning hebdomadaire avec filtres optionnels.

    Filtres disponibles :
    - semaine : format ISO 8601 YYYY-Www (ex: 2026-W10)
    - salarie_id : identifiant du salarie
    - statut : present, conge_cp, conge_maladie, arret_maladie, arret_accident_travail...
    """
    data = list(_rh_planning)

    # Filtre par salarie
    if salarie_id:
        data = [p for p in data if p.get("salarie_id") == salarie_id or p.get("salarie_nom", "").lower() == salarie_id.lower()]

    # Filtre par statut
    if statut:
        data = [p for p in data if p.get("statut", "present") == statut]

    if not semaine:
        return _paginate(data, 0, _DEFAULT_PAGE_LIMIT)

    # Parser la semaine ISO
    try:
        lundi, dimanche = _semaine_iso_vers_dates(semaine)
        resultats = []
        for p in data:
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


@router.get("/planning/jour")
async def planning_jour(
    date_jour: str = Query(..., description="Date au format YYYY-MM-DD"),
    salarie_id: Optional[str] = Query(None),
    statut: Optional[str] = Query(None),
):
    """Vue journaliere du planning.

    Retourne tous les creneaux planifies pour une date donnee,
    enrichis du statut reel de chaque salarie (present, conge, arret...).
    """
    try:
        d = date.fromisoformat(date_jour)
    except ValueError:
        raise HTTPException(400, "Format de date invalide (attendu: YYYY-MM-DD)")

    entrees = []
    for p in _rh_planning:
        if p.get("date") != date_jour:
            continue
        if salarie_id and p.get("salarie_id") != salarie_id:
            continue
        # Enrichir avec le statut reel
        st = _get_statut_jour(p["salarie_id"], date_jour)
        entry = dict(p)
        entry["statut_reel"] = st
        if statut and st != statut:
            continue
        entrees.append(entry)

    # Ajouter les salaries qui n'ont pas de creneau mais ont un statut specifique ce jour
    ids_planifies = {p["salarie_id"] for p in entrees}
    tous_salaries = set()
    for c in _rh_contrats:
        if c.get("statut") != "termine":
            tous_salaries.add(c.get("id", ""))
    for nir in _biblio_knowledge.get("salaries", {}):
        tous_salaries.add(nir)

    for sid in tous_salaries:
        if sid in ids_planifies:
            continue
        st = _get_statut_jour(sid, date_jour)
        if st != "present":
            sal = _resoudre_salarie(sid)
            entrees.append({
                "id": "",
                "salarie_id": sid,
                "salarie_nom": sal["nom_complet"],
                "salarie_statut": sal["statut"],
                "date": date_jour,
                "heure_debut": "",
                "heure_fin": "",
                "duree_heures": 0,
                "type_poste": "",
                "statut": st,
                "statut_reel": st,
                "majorations": [],
            })

    jour_semaine = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    return {
        "date": date_jour,
        "jour": jour_semaine[d.weekday()],
        "entrees": entrees,
        "nb_entrees": len(entrees),
        "nb_presents": sum(1 for e in entrees if e.get("statut_reel", e.get("statut")) == "present"),
        "nb_absents": sum(1 for e in entrees if e.get("statut_reel", e.get("statut")) != "present"),
    }


@router.get("/planning/mois")
async def planning_mois(
    annee: int = Query(..., description="Annee"),
    mois: int = Query(..., ge=1, le=12, description="Mois (1-12)"),
    salarie_id: Optional[str] = Query(None),
    statut: Optional[str] = Query(None),
):
    """Vue mensuelle du planning.

    Retourne un calendrier mensuel avec pour chaque jour le nombre de
    salaries presents/absents et le detail des creneaux.
    """
    import calendar
    nb_jours = calendar.monthrange(annee, mois)[1]

    jours = []
    jour_semaine = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    total_heures = 0

    for j in range(1, nb_jours + 1):
        d = date(annee, mois, j)
        date_str = d.isoformat()

        entrees_jour = []
        for p in _rh_planning:
            if p.get("date") != date_str:
                continue
            if salarie_id and p.get("salarie_id") != salarie_id:
                continue
            st = _get_statut_jour(p["salarie_id"], date_str)
            entry = {
                "salarie_id": p["salarie_id"],
                "salarie_nom": p.get("salarie_nom", ""),
                "heure_debut": p.get("heure_debut", ""),
                "heure_fin": p.get("heure_fin", ""),
                "type_poste": p.get("type_poste", "normal"),
                "statut": st,
                "duree_heures": p.get("duree_heures", 0),
            }
            if statut and st != statut:
                continue
            entrees_jour.append(entry)
            total_heures += p.get("duree_heures", 0)

        jours.append({
            "date": date_str,
            "jour_semaine": jour_semaine[d.weekday()],
            "nb_salaries": len(entrees_jour),
            "nb_presents": sum(1 for e in entrees_jour if e["statut"] == "present"),
            "nb_absents": sum(1 for e in entrees_jour if e["statut"] != "present"),
            "entrees": entrees_jour,
        })

    return {
        "annee": annee,
        "mois": mois,
        "nb_jours": nb_jours,
        "jours": jours,
        "total_heures_planifiees": round(total_heures, 2),
    }


@router.get("/planning/annee")
async def planning_annee(
    annee: int = Query(..., description="Annee"),
    salarie_id: Optional[str] = Query(None),
):
    """Vue annuelle du planning.

    Retourne un resume par mois : jours travailles, heures, absences.
    """
    import calendar

    mois_resume = []
    total_heures_annee = 0
    total_jours_travailles = 0
    total_absences = 0

    for m in range(1, 13):
        nb_jours = calendar.monthrange(annee, m)[1]
        heures_mois = 0
        jours_travailles = 0
        jours_absence = 0

        for j in range(1, nb_jours + 1):
            date_str = date(annee, m, j).isoformat()
            entrees_jour = [p for p in _rh_planning if p.get("date") == date_str]
            if salarie_id:
                entrees_jour = [p for p in entrees_jour if p.get("salarie_id") == salarie_id]

            if entrees_jour:
                jours_travailles += 1
                heures_mois += sum(p.get("duree_heures", 0) for p in entrees_jour)

            # Compter les absences
            if salarie_id:
                st = _get_statut_jour(salarie_id, date_str)
                if st != "present":
                    jours_absence += 1

        mois_noms = ["", "Janvier", "Fevrier", "Mars", "Avril", "Mai", "Juin",
                      "Juillet", "Aout", "Septembre", "Octobre", "Novembre", "Decembre"]
        mois_resume.append({
            "mois": m,
            "nom_mois": mois_noms[m],
            "jours_travailles": jours_travailles,
            "heures_planifiees": round(heures_mois, 2),
            "jours_absence": jours_absence,
        })
        total_heures_annee += heures_mois
        total_jours_travailles += jours_travailles
        total_absences += jours_absence

    return {
        "annee": annee,
        "salarie_id": salarie_id,
        "mois": mois_resume,
        "total_heures": round(total_heures_annee, 2),
        "total_jours_travailles": total_jours_travailles,
        "total_jours_absence": total_absences,
    }


@router.post("/planning/integrer-salaries")
async def integrer_salaries_planning(
    date_debut: str = Form(..., description="Date de debut (YYYY-MM-DD)"),
    date_fin: str = Form(..., description="Date de fin (YYYY-MM-DD)"),
    heure_debut: str = Form(""),
    heure_fin: str = Form(""),
    type_poste: str = Form(""),
    jours_semaine: str = Form("1,2,3,4,5"),
):
    """Integre automatiquement tous les salaries detectes et contractuels au planning.

    Cree des creneaux par defaut pour chaque salarie actif sur la periode demandee.
    Par defaut : lundi-vendredi, creneau par defaut (modifiable).
    jours_semaine : liste des jours (1=lundi...7=dimanche), ex: "1,2,3,4,5"
    """
    from datetime import timedelta

    if not heure_debut:
        heure_debut = _planning_creneau_defaut["heure_debut"]
    if not heure_fin:
        heure_fin = _planning_creneau_defaut["heure_fin"]
    if not type_poste:
        type_poste = _planning_creneau_defaut["type_poste"]

    try:
        d_debut = date.fromisoformat(date_debut)
        d_fin = date.fromisoformat(date_fin)
    except ValueError:
        raise HTTPException(400, "Format de date invalide (attendu: YYYY-MM-DD)")

    if d_fin < d_debut:
        raise HTTPException(400, "date_fin doit etre >= date_debut")
    if (d_fin - d_debut).days > 366:
        raise HTTPException(400, "Periode maximale: 366 jours")

    try:
        jours = [int(j.strip()) for j in jours_semaine.split(",")]
    except ValueError:
        raise HTTPException(400, "jours_semaine invalide (ex: 1,2,3,4,5)")

    # Collecter tous les salaries actifs
    salaries_actifs = {}
    # Depuis les contrats RH
    for c in _rh_contrats:
        if c.get("statut") != "termine":
            cid = c.get("id", "")
            salaries_actifs[cid] = f"{c.get('prenom', '')} {c.get('nom', '')}".strip() or cid
    # Depuis la base de connaissances
    for nir, sal in _biblio_knowledge.get("salaries", {}).items():
        if nir not in salaries_actifs:
            nom = f"{sal.get('prenom', '')} {sal.get('nom', '')}".strip() or nir
            salaries_actifs[nir] = nom

    if not salaries_actifs:
        return {"ok": True, "nb_entrees_creees": 0, "message": "Aucun salarie connu a integrer"}

    # Calcul duree
    try:
        h_deb = datetime.strptime(heure_debut, "%H:%M")
        h_fin_dt = datetime.strptime(heure_fin, "%H:%M")
        duree_heures = round((h_fin_dt - h_deb).seconds / 3600, 2)
    except (ValueError, TypeError):
        duree_heures = 0

    majorations = _calculer_majorations(type_poste)

    # Generer les creneaux
    nb_creees = 0
    current = d_debut
    while current <= d_fin:
        # weekday(): 0=lundi, 6=dimanche => ISO: 1=lundi, 7=dimanche
        jour_iso = current.weekday() + 1
        if jour_iso in jours:
            date_str = current.isoformat()
            for sid, nom in salaries_actifs.items():
                # Verifier si deja present dans le planning
                deja = any(
                    p["salarie_id"] == sid and p["date"] == date_str and p["heure_debut"] == heure_debut
                    for p in _rh_planning
                )
                if deja:
                    continue

                st = _get_statut_jour(sid, date_str)
                _rh_planning.append({
                    "id": str(uuid.uuid4())[:8],
                    "salarie_id": sid,
                    "salarie_nom": nom,
                    "salarie_statut": "",
                    "date": date_str,
                    "heure_debut": heure_debut,
                    "heure_fin": heure_fin,
                    "duree_heures": duree_heures,
                    "type_poste": type_poste,
                    "statut": st,
                    "majorations": majorations,
                    "date_creation": datetime.now().isoformat(),
                })
                nb_creees += 1
        current += timedelta(days=1)

    log_action("utilisateur", "integration_planning",
               f"{nb_creees} creneaux crees pour {len(salaries_actifs)} salaries du {date_debut} au {date_fin}")
    return {
        "ok": True,
        "nb_salaries": len(salaries_actifs),
        "nb_entrees_creees": nb_creees,
        "periode": {"debut": date_debut, "fin": date_fin},
        "creneau": {"heure_debut": heure_debut, "heure_fin": heure_fin, "type_poste": type_poste},
        "salaries_integres": [{"id": k, "nom": v} for k, v in salaries_actifs.items()],
    }


@router.put("/planning/creneau-defaut")
async def modifier_creneau_defaut(request: Request):
    """Modifie le creneau par defaut applique lors de l'integration automatique."""
    global _planning_creneau_defaut
    body = await _safe_json(request)
    if "heure_debut" in body:
        _planning_creneau_defaut["heure_debut"] = body["heure_debut"]
    if "heure_fin" in body:
        _planning_creneau_defaut["heure_fin"] = body["heure_fin"]
    if "type_poste" in body:
        if body["type_poste"] in ("normal", "astreinte", "nuit", "dimanche", "ferie"):
            _planning_creneau_defaut["type_poste"] = body["type_poste"]
    log_action("utilisateur", "modification_creneau_defaut", str(_planning_creneau_defaut))
    return {"ok": True, "creneau_defaut": _planning_creneau_defaut}


@router.delete("/planning/{planning_id}")
async def supprimer_planning(planning_id: str):
    """Supprime une entree de planning."""
    for i, p in enumerate(_rh_planning):
        if p.get("id") == planning_id:
            removed = _rh_planning.pop(i)
            log_action("utilisateur", "suppression_planning", f"Planning {planning_id} supprime")
            return {"ok": True, "supprime": removed}
    raise HTTPException(404, "Entree de planning non trouvee")