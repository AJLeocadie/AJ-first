"""URSSAF Analyzer - API FastAPI pour Vercel.

Point d'entree web : upload de documents, analyse automatisee,
generation et consultation de rapports.
"""

import io
import json
import tempfile
import time
import shutil
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from urssaf_analyzer.config.settings import AppConfig
from urssaf_analyzer.config.constants import SUPPORTED_EXTENSIONS
from urssaf_analyzer.core.orchestrator import Orchestrator
from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError

app = FastAPI(
    title="URSSAF Analyzer",
    description="Analyse securisee de documents sociaux et fiscaux URSSAF",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Page d'accueil ---

@app.get("/", response_class=HTMLResponse)
async def accueil():
    """Page d'accueil avec interface d'upload."""
    return FRONTEND_HTML


# --- API d'analyse ---

@app.post("/api/analyze")
async def analyser(
    fichiers: list[UploadFile] = File(...),
    format_rapport: str = "json",
):
    """Analyse les documents uploades et retourne le rapport."""
    if not fichiers:
        raise HTTPException(400, "Aucun fichier fourni.")

    # Valider les extensions
    for f in fichiers:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                400,
                f"Format non supporte : '{ext}' pour le fichier '{f.filename}'. "
                f"Formats acceptes : {', '.join(SUPPORTED_EXTENSIONS.keys())}",
            )

    # Creer un repertoire temporaire pour cette analyse
    with tempfile.TemporaryDirectory(prefix="urssaf_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        chemins_fichiers = []

        # Sauvegarder les fichiers uploades
        for f in fichiers:
            chemin = tmp_path / f.filename
            contenu = await f.read()
            chemin.write_bytes(contenu)
            chemins_fichiers.append(chemin)

        # Configurer et lancer l'analyse
        config = AppConfig(
            base_dir=tmp_path,
            data_dir=tmp_path / "data",
            reports_dir=tmp_path / "reports",
            temp_dir=tmp_path / "temp",
            audit_log_path=tmp_path / "audit.log",
        )

        orchestrator = Orchestrator(config)

        try:
            chemin_rapport = orchestrator.analyser_documents(
                chemins_fichiers,
                format_rapport=format_rapport,
            )

            result = orchestrator.result

            if format_rapport == "html":
                contenu_rapport = chemin_rapport.read_text(encoding="utf-8")
                return HTMLResponse(content=contenu_rapport)

            # JSON par defaut
            rapport_json = json.loads(chemin_rapport.read_text(encoding="utf-8"))
            return JSONResponse(content=rapport_json)

        except URSSAFAnalyzerError as e:
            raise HTTPException(422, str(e))
        except Exception as e:
            raise HTTPException(500, f"Erreur interne : {str(e)}")


@app.get("/api/health")
async def health():
    """Endpoint de sante."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "formats_supportes": list(SUPPORTED_EXTENSIONS.keys()),
    }


@app.get("/api/formats")
async def formats():
    """Liste les formats de fichiers supportes."""
    return {
        "formats": [
            {"extension": ext, "type": typ, "description": _desc(typ)}
            for ext, typ in SUPPORTED_EXTENSIONS.items()
        ]
    }


def _desc(typ: str) -> str:
    descs = {
        "pdf": "Documents PDF (bulletins de paie, attestations, bordereaux)",
        "csv": "Fichiers CSV (exports comptables, listes de salaries)",
        "excel": "Fichiers Excel (tableaux de bord, exports paie)",
        "xml": "Fichiers XML (bordereaux URSSAF, declarations)",
        "dsn": "Declaration Sociale Nominative (format structure)",
    }
    return descs.get(typ, typ)


# --- Frontend HTML embarque ---

FRONTEND_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>URSSAF Analyzer - Analyse de documents sociaux</title>
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
body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: #333;
    min-height: 100vh;
}

/* Header */
header {
    background: linear-gradient(135deg, var(--bleu) 0%, #005bb5 100%);
    color: white;
    padding: 40px 20px;
    text-align: center;
}
header h1 { font-size: 2.2em; margin-bottom: 8px; font-weight: 700; }
header p { opacity: 0.85; font-size: 1.1em; max-width: 600px; margin: 0 auto; }

/* Container */
.container {
    max-width: 900px;
    margin: -30px auto 40px;
    padding: 0 20px;
    position: relative;
    z-index: 1;
}

/* Card */
.card {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 30px;
    box-shadow: var(--shadow);
    margin-bottom: 20px;
}
.card h2 {
    color: var(--bleu);
    margin-bottom: 20px;
    font-size: 1.3em;
    display: flex;
    align-items: center;
    gap: 10px;
}

/* Upload zone */
.upload-zone {
    border: 3px dashed #c5d3e8;
    border-radius: 12px;
    padding: 50px 20px;
    text-align: center;
    cursor: pointer;
    transition: all 0.3s ease;
    background: var(--bleu-clair);
    position: relative;
}
.upload-zone:hover, .upload-zone.dragover {
    border-color: var(--bleu);
    background: #d6e4f7;
    transform: translateY(-2px);
}
.upload-zone .icon { font-size: 3em; margin-bottom: 15px; }
.upload-zone h3 { color: var(--bleu); margin-bottom: 8px; }
.upload-zone p { color: var(--gris); font-size: 0.9em; }
.upload-zone input[type="file"] {
    position: absolute; inset: 0; opacity: 0; cursor: pointer;
}

/* File list */
.file-list { margin: 15px 0; }
.file-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 15px;
    background: var(--bleu-clair);
    border-radius: 8px;
    margin: 6px 0;
    font-size: 0.9em;
}
.file-item .name { font-weight: 600; color: var(--bleu); }
.file-item .size { color: var(--gris); }
.file-item .remove {
    background: none;
    border: none;
    color: var(--rouge);
    cursor: pointer;
    font-size: 1.2em;
    padding: 0 5px;
}

/* Buttons */
.btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 14px 32px;
    border: none;
    border-radius: 8px;
    font-size: 1em;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
}
.btn-primary {
    background: var(--bleu);
    color: white;
    width: 100%;
    justify-content: center;
}
.btn-primary:hover:not(:disabled) { background: var(--bleu-hover); transform: translateY(-1px); }
.btn-primary:disabled { background: #a0b4cc; cursor: not-allowed; }

/* Format selector */
.format-selector {
    display: flex;
    gap: 10px;
    margin-bottom: 20px;
}
.format-option {
    flex: 1;
    padding: 12px;
    border: 2px solid #e0e0e0;
    border-radius: 8px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
    background: white;
}
.format-option:hover { border-color: var(--bleu); }
.format-option.active { border-color: var(--bleu); background: var(--bleu-clair); }
.format-option .label { font-weight: 600; display: block; }
.format-option .desc { font-size: 0.8em; color: var(--gris); }

/* Progress */
.progress-container { display: none; margin: 20px 0; }
.progress-bar {
    height: 6px;
    background: #e0e0e0;
    border-radius: 3px;
    overflow: hidden;
}
.progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--bleu), #005bb5);
    border-radius: 3px;
    width: 0%;
    transition: width 0.5s ease;
    animation: progress-pulse 1.5s infinite;
}
@keyframes progress-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}
.progress-text { text-align: center; margin-top: 10px; color: var(--gris); font-size: 0.9em; }

/* Results */
#results { display: none; }
.results-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}
.dashboard-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}
.stat-card {
    background: var(--bleu-clair);
    border-radius: 8px;
    padding: 15px;
    text-align: center;
}
.stat-card .value { font-size: 1.8em; font-weight: 700; }
.stat-card .label { font-size: 0.8em; color: var(--gris); margin-top: 4px; }
.stat-card.critique .value { color: var(--rouge); }
.stat-card.haute .value { color: var(--orange); }
.stat-card.vert .value { color: var(--vert); }

/* Findings table */
.findings-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
.findings-table th {
    background: var(--bleu);
    color: white;
    padding: 10px 12px;
    text-align: left;
    font-size: 0.85em;
}
.findings-table td { padding: 10px 12px; border-bottom: 1px solid #eee; font-size: 0.88em; }
.findings-table tr:hover { background: var(--bleu-clair); }
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.75em;
    font-weight: 700;
    color: white;
}
.badge.critique { background: var(--rouge); }
.badge.haute { background: var(--orange); }
.badge.moyenne { background: var(--jaune); color: #333; }
.badge.faible { background: var(--vert); }

/* Features */
.features {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 15px;
    margin-top: 15px;
}
.feature {
    padding: 15px;
    border-radius: 8px;
    background: var(--bleu-clair);
}
.feature h4 { color: var(--bleu); margin-bottom: 5px; font-size: 0.95em; }
.feature p { font-size: 0.82em; color: #555; }

/* Footer */
footer {
    text-align: center;
    padding: 30px;
    color: var(--gris);
    font-size: 0.85em;
}

/* Error */
.error-msg {
    background: #fde8e8;
    color: var(--rouge);
    padding: 15px;
    border-radius: 8px;
    margin: 15px 0;
    display: none;
}

/* Responsive */
@media (max-width: 600px) {
    header h1 { font-size: 1.5em; }
    .card { padding: 20px; }
    .upload-zone { padding: 30px 15px; }
    .format-selector { flex-direction: column; }
}
</style>
</head>
<body>

<header>
    <h1>URSSAF Analyzer</h1>
    <p>Analyse securisee de documents sociaux et fiscaux pour l'automatisation des controles URSSAF</p>
</header>

<div class="container">

    <!-- Upload Card -->
    <div class="card" id="upload-card">
        <h2>Importer vos documents</h2>

        <div class="upload-zone" id="dropzone">
            <input type="file" id="file-input" multiple
                   accept=".pdf,.csv,.xlsx,.xls,.xml,.dsn">
            <div class="icon">&#128196;</div>
            <h3>Glissez vos fichiers ici</h3>
            <p>ou cliquez pour selectionner<br>
            <strong>CSV, Excel, PDF, XML, DSN</strong></p>
        </div>

        <div class="file-list" id="file-list"></div>
        <div class="error-msg" id="error-msg"></div>

        <h2 style="margin-top: 25px;">Format du rapport</h2>
        <div class="format-selector">
            <div class="format-option active" data-format="json" onclick="selectFormat(this)">
                <span class="label">JSON</span>
                <span class="desc">Structure, exploitable</span>
            </div>
            <div class="format-option" data-format="html" onclick="selectFormat(this)">
                <span class="label">HTML</span>
                <span class="desc">Visuel, imprimable</span>
            </div>
        </div>

        <button class="btn btn-primary" id="btn-analyze" onclick="lancerAnalyse()" disabled>
            Lancer l'analyse
        </button>

        <div class="progress-container" id="progress">
            <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>
            <div class="progress-text" id="progress-text">Import des documents...</div>
        </div>
    </div>

    <!-- Results Card -->
    <div id="results">
        <div class="card">
            <div class="results-header">
                <h2>Resultats de l'analyse</h2>
                <button class="btn" style="background:var(--bleu-clair);color:var(--bleu);padding:8px 16px;" onclick="resetUI()">
                    Nouvelle analyse
                </button>
            </div>

            <div class="dashboard-grid" id="dashboard"></div>
        </div>

        <div class="card">
            <h2>Constats detailles</h2>
            <div id="findings-container"></div>
        </div>

        <div class="card">
            <h2>Recommandations</h2>
            <div id="reco-container"></div>
        </div>

        <div class="card" id="html-report-card" style="display:none;">
            <h2>Rapport HTML complet</h2>
            <iframe id="html-report-frame" style="width:100%;height:600px;border:1px solid #eee;border-radius:8px;"></iframe>
        </div>
    </div>

    <!-- Features Card -->
    <div class="card">
        <h2>Capacites d'analyse</h2>
        <div class="features">
            <div class="feature">
                <h4>Anomalies de taux</h4>
                <p>Verification des taux de cotisations vs bareme URSSAF 2026</p>
            </div>
            <div class="feature">
                <h4>Erreurs de calcul</h4>
                <p>Detection des ecarts base x taux vs montant declare</p>
            </div>
            <div class="feature">
                <h4>Plafonds PASS</h4>
                <p>Verification du plafonnement de securite sociale (4 005 EUR/mois)</p>
            </div>
            <div class="feature">
                <h4>Coherence inter-docs</h4>
                <p>Croisement des masses salariales et effectifs entre documents</p>
            </div>
            <div class="feature">
                <h4>Loi de Benford</h4>
                <p>Detection statistique de manipulation de donnees</p>
            </div>
            <div class="feature">
                <h4>Doublons & lacunes</h4>
                <p>Identification des declarations en double ou manquantes</p>
            </div>
        </div>
    </div>
</div>

<footer>
    URSSAF Analyzer v1.0.0 &mdash; Analyse securisee de documents sociaux et fiscaux<br>
    Les donnees importees sont traitees de maniere ephemere et ne sont pas conservees.
</footer>

<script>
let fichiers = [];
let formatRapport = 'json';

// Drag & Drop
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');

['dragenter','dragover'].forEach(e => {
    dropzone.addEventListener(e, ev => { ev.preventDefault(); dropzone.classList.add('dragover'); });
});
['dragleave','drop'].forEach(e => {
    dropzone.addEventListener(e, ev => { ev.preventDefault(); dropzone.classList.remove('dragover'); });
});
dropzone.addEventListener('drop', ev => {
    const files = ev.dataTransfer.files;
    ajouterFichiers(files);
});
fileInput.addEventListener('change', ev => {
    ajouterFichiers(ev.target.files);
    fileInput.value = '';
});

function ajouterFichiers(files) {
    const exts = ['.pdf','.csv','.xlsx','.xls','.xml','.dsn'];
    for (const f of files) {
        const ext = '.' + f.name.split('.').pop().toLowerCase();
        if (!exts.includes(ext)) {
            showError('Format non supporte : ' + ext);
            continue;
        }
        if (!fichiers.find(x => x.name === f.name)) {
            fichiers.push(f);
        }
    }
    renderFileList();
    hideError();
}

function renderFileList() {
    const list = document.getElementById('file-list');
    const btn = document.getElementById('btn-analyze');
    list.innerHTML = fichiers.map((f, i) => `
        <div class="file-item">
            <span class="name">${f.name}</span>
            <span class="size">${(f.size/1024).toFixed(1)} Ko</span>
            <button class="remove" onclick="supprimerFichier(${i})">&times;</button>
        </div>
    `).join('');
    btn.disabled = fichiers.length === 0;
}

function supprimerFichier(idx) {
    fichiers.splice(idx, 1);
    renderFileList();
}

function selectFormat(el) {
    document.querySelectorAll('.format-option').forEach(o => o.classList.remove('active'));
    el.classList.add('active');
    formatRapport = el.dataset.format;
}

function showError(msg) {
    const el = document.getElementById('error-msg');
    el.textContent = msg;
    el.style.display = 'block';
}
function hideError() { document.getElementById('error-msg').style.display = 'none'; }

async function lancerAnalyse() {
    if (fichiers.length === 0) return;

    const btn = document.getElementById('btn-analyze');
    const progress = document.getElementById('progress');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');
    const results = document.getElementById('results');

    btn.disabled = true;
    progress.style.display = 'block';
    results.style.display = 'none';
    hideError();

    // Etapes de progression
    const etapes = [
        [10, 'Import des documents...'],
        [30, 'Verification d\\'integrite (SHA-256)...'],
        [50, 'Parsing multi-format...'],
        [70, 'Analyse des anomalies...'],
        [85, 'Detection de patterns...'],
        [95, 'Generation du rapport...'],
    ];
    let etapeIdx = 0;
    const progressInterval = setInterval(() => {
        if (etapeIdx < etapes.length) {
            progressFill.style.width = etapes[etapeIdx][0] + '%';
            progressText.textContent = etapes[etapeIdx][1];
            etapeIdx++;
        }
    }, 800);

    const formData = new FormData();
    for (const f of fichiers) formData.append('fichiers', f);
    formData.append('format_rapport', formatRapport);

    try {
        const resp = await fetch('/api/analyze?format_rapport=' + formatRapport, {
            method: 'POST',
            body: formData,
        });

        clearInterval(progressInterval);
        progressFill.style.width = '100%';
        progressText.textContent = 'Analyse terminee !';

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({detail: 'Erreur inconnue'}));
            throw new Error(err.detail || `Erreur ${resp.status}`);
        }

        if (formatRapport === 'html') {
            const html = await resp.text();
            afficherRapportHTML(html);
        } else {
            const data = await resp.json();
            afficherResultatsJSON(data);
        }

        setTimeout(() => { progress.style.display = 'none'; }, 1000);
        results.style.display = 'block';
        results.scrollIntoView({behavior: 'smooth'});

    } catch(e) {
        clearInterval(progressInterval);
        progress.style.display = 'none';
        showError(e.message);
        btn.disabled = false;
    }
}

function afficherResultatsJSON(data) {
    const s = data.synthese || {};
    const dashboard = document.getElementById('dashboard');

    const score = s.score_risque_global || 0;
    const scoreClass = score >= 70 ? 'critique' : score >= 40 ? 'haute' : 'vert';

    dashboard.innerHTML = `
        <div class="stat-card ${scoreClass}">
            <div class="value">${score}/100</div>
            <div class="label">Score de risque</div>
        </div>
        <div class="stat-card">
            <div class="value">${s.nb_constats || 0}</div>
            <div class="label">Constats</div>
        </div>
        <div class="stat-card critique">
            <div class="value">${(s.par_severite || {}).critique || 0}</div>
            <div class="label">Critiques</div>
        </div>
        <div class="stat-card haute">
            <div class="value">${(s.par_severite || {}).haute || 0}</div>
            <div class="label">Hauts</div>
        </div>
        <div class="stat-card">
            <div class="value">${s.impact_financier_total || '0'} EUR</div>
            <div class="label">Impact financier</div>
        </div>
    `;

    // Constats
    const constats = data.constats || [];
    const fc = document.getElementById('findings-container');
    if (constats.length === 0) {
        fc.innerHTML = '<p style="color:var(--vert);font-weight:600;">Aucun constat detecte. Les documents semblent conformes.</p>';
    } else {
        fc.innerHTML = `<table class="findings-table">
            <tr><th>Severite</th><th>Categorie</th><th>Constat</th><th>Impact</th><th>Risque</th></tr>
            ${constats.slice(0, 50).map(f => `<tr>
                <td><span class="badge ${f.severite}">${(f.severite||'').toUpperCase()}</span></td>
                <td>${f.categorie || ''}</td>
                <td><strong>${f.titre || ''}</strong><br><small>${(f.description||'').substring(0,150)}</small></td>
                <td>${f.montant_impact ? f.montant_impact + ' EUR' : 'N/A'}</td>
                <td>${f.score_risque || 0}/100</td>
            </tr>`).join('')}
        </table>`;
    }

    // Recommandations
    const recos = data.recommandations || [];
    const rc = document.getElementById('reco-container');
    if (recos.length === 0) {
        rc.innerHTML = '<p>Aucune recommandation.</p>';
    } else {
        rc.innerHTML = recos.map((r, i) => `
            <div style="border-left:4px solid var(--bleu);padding:10px 15px;margin:8px 0;background:var(--bleu-clair);border-radius:0 6px 6px 0;">
                <strong>#${i+1} - ${r.titre || ''}</strong>
                <p style="font-size:0.9em;margin:5px 0;">${r.description || ''}</p>
                <small style="color:var(--gris);">Impact : ${r.impact || 'N/A'} | Constats lies : ${r.nb_constats || 0}</small>
            </div>
        `).join('');
    }

    document.getElementById('html-report-card').style.display = 'none';
}

function afficherRapportHTML(html) {
    document.getElementById('dashboard').innerHTML = '';
    document.getElementById('findings-container').innerHTML = '<p>Voir le rapport HTML ci-dessous.</p>';
    document.getElementById('reco-container').innerHTML = '';

    const card = document.getElementById('html-report-card');
    card.style.display = 'block';
    const frame = document.getElementById('html-report-frame');
    frame.srcdoc = html;
}

function resetUI() {
    fichiers = [];
    renderFileList();
    document.getElementById('results').style.display = 'none';
    document.getElementById('btn-analyze').disabled = true;
    hideError();
    window.scrollTo({top: 0, behavior: 'smooth'});
}
</script>

</body>
</html>"""
