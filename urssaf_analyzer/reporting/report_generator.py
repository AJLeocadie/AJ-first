"""Generateur de rapports d'analyse URSSAF.

Produit des rapports detailles en HTML et JSON contenant :
- Synthese / Dashboard
- Constats detailles par categorie et severite
- Impact financier chiffre
- Score de risque
- Recommandations priorisees
"""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from urssaf_analyzer.config.constants import Severity, FindingCategory
from urssaf_analyzer.models.documents import AnalysisResult, Finding
from urssaf_analyzer.utils.number_utils import formater_montant


class ReportGenerator:
    """Genere des rapports d'analyse complets."""

    def generer_html(self, result: AnalysisResult, chemin_sortie: Path) -> Path:
        """Genere un rapport HTML complet."""
        html = self._construire_html(result)
        chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
        with open(chemin_sortie, "w", encoding="utf-8") as f:
            f.write(html)
        return chemin_sortie

    def generer_json(self, result: AnalysisResult, chemin_sortie: Path) -> Path:
        """Genere un rapport JSON structure."""
        data = self._construire_json(result)
        chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
        with open(chemin_sortie, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        return chemin_sortie

    def _construire_json(self, result: AnalysisResult) -> dict:
        """Construit la structure JSON du rapport."""
        return {
            "metadata": {
                "session_id": result.session_id,
                "date_analyse": result.date_analyse.isoformat(),
                "duree_secondes": result.duree_analyse_secondes,
                "nb_documents": len(result.documents_analyses),
            },
            "synthese": {
                "nb_constats": len(result.findings),
                "nb_anomalies": result.nb_anomalies,
                "nb_incoherences": result.nb_incoherences,
                "nb_critiques": result.nb_critiques,
                "impact_financier_total": str(result.impact_total),
                "score_risque_global": result.score_risque_global,
                "par_severite": self._compter_par_severite(result.findings),
                "par_categorie": self._compter_par_categorie(result.findings),
            },
            "documents_analyses": [
                {
                    "id": d.id,
                    "nom": d.nom_fichier,
                    "type": d.type_fichier.value if d.type_fichier else "inconnu",
                    "hash": d.hash_sha256,
                }
                for d in result.documents_analyses
            ],
            "constats": [self._finding_to_dict(f) for f in result.findings],
            "recommandations": self._generer_recommandations(result.findings),
        }

    def _construire_html(self, result: AnalysisResult) -> str:
        """Construit le rapport HTML complet."""
        par_sev = self._compter_par_severite(result.findings)
        par_cat = self._compter_par_categorie(result.findings)

        findings_html = self._generer_findings_html(result.findings)
        recommandations = self._generer_recommandations(result.findings)
        reco_html = self._generer_recommandations_html(recommandations)
        docs_html = self._generer_documents_html(result)

        score = result.score_risque_global
        if score >= 70:
            score_class = "critique"
            score_label = "ELEVE"
        elif score >= 40:
            score_class = "haute"
            score_label = "MODERE"
        else:
            score_class = "faible"
            score_label = "FAIBLE"

        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rapport d'Analyse URSSAF - {result.date_analyse.strftime('%d/%m/%Y')}</title>
<style>
:root {{
    --bleu-urssaf: #003d7a;
    --bleu-clair: #e8f0fe;
    --rouge: #d32f2f;
    --orange: #f57c00;
    --jaune: #fbc02d;
    --vert: #388e3c;
    --gris: #757575;
    --bg: #f5f5f5;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: #333; line-height: 1.6; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
header {{ background: var(--bleu-urssaf); color: white; padding: 30px; border-radius: 8px 8px 0 0; }}
header h1 {{ font-size: 1.8em; margin-bottom: 5px; }}
header .meta {{ opacity: 0.8; font-size: 0.9em; }}
.dashboard {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
.card {{ background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
.card .value {{ font-size: 2em; font-weight: bold; }}
.card .label {{ color: var(--gris); font-size: 0.85em; margin-top: 5px; }}
.card.critique .value {{ color: var(--rouge); }}
.card.haute .value {{ color: var(--orange); }}
.card.moyenne .value {{ color: var(--jaune); }}
.card.faible .value {{ color: var(--vert); }}
section {{ background: white; border-radius: 8px; padding: 25px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
section h2 {{ color: var(--bleu-urssaf); border-bottom: 2px solid var(--bleu-clair); padding-bottom: 10px; margin-bottom: 15px; }}
table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
th {{ background: var(--bleu-urssaf); color: white; padding: 10px; text-align: left; font-size: 0.85em; }}
td {{ padding: 10px; border-bottom: 1px solid #eee; font-size: 0.9em; }}
tr:hover {{ background: var(--bleu-clair); }}
.badge {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.8em; font-weight: bold; color: white; }}
.badge.critique {{ background: var(--rouge); }}
.badge.haute {{ background: var(--orange); }}
.badge.moyenne {{ background: var(--jaune); color: #333; }}
.badge.faible {{ background: var(--vert); }}
.score-circle {{ width: 120px; height: 120px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-direction: column; margin: 10px auto; border: 6px solid; }}
.score-circle.critique {{ border-color: var(--rouge); color: var(--rouge); }}
.score-circle.haute {{ border-color: var(--orange); color: var(--orange); }}
.score-circle.faible {{ border-color: var(--vert); color: var(--vert); }}
.score-circle .score-value {{ font-size: 2em; font-weight: bold; }}
.score-circle .score-label {{ font-size: 0.7em; }}
.reco-item {{ border-left: 4px solid var(--bleu-urssaf); padding: 10px 15px; margin: 10px 0; background: var(--bleu-clair); border-radius: 0 4px 4px 0; }}
.reco-item .priority {{ font-weight: bold; color: var(--bleu-urssaf); }}
.finding-detail {{ margin: 10px 0; padding: 15px; border: 1px solid #eee; border-radius: 4px; }}
.finding-detail .title {{ font-weight: bold; margin-bottom: 5px; }}
.confidential {{ text-align: center; color: var(--rouge); font-weight: bold; padding: 10px; border: 2px solid var(--rouge); margin: 10px 0; }}
footer {{ text-align: center; color: var(--gris); padding: 20px; font-size: 0.85em; }}
</style>
</head>
<body>
<div class="container">

<header>
    <h1>Rapport d'Analyse de Conformite URSSAF</h1>
    <div class="meta">
        Session : {result.session_id}<br>
        Date d'analyse : {result.date_analyse.strftime('%d/%m/%Y a %H:%M')}<br>
        Duree : {result.duree_analyse_secondes:.1f} secondes<br>
        Documents analyses : {len(result.documents_analyses)}
    </div>
</header>

<div class="confidential">DOCUMENT CONFIDENTIEL - USAGE INTERNE UNIQUEMENT</div>

<!-- Dashboard -->
<div class="dashboard">
    <div class="card">
        <div class="value">{len(result.findings)}</div>
        <div class="label">Constats totaux</div>
    </div>
    <div class="card critique">
        <div class="value">{par_sev.get('critique', 0)}</div>
        <div class="label">Critiques</div>
    </div>
    <div class="card haute">
        <div class="value">{par_sev.get('haute', 0)}</div>
        <div class="label">Hauts</div>
    </div>
    <div class="card moyenne">
        <div class="value">{par_sev.get('moyenne', 0)}</div>
        <div class="label">Moyens</div>
    </div>
    <div class="card faible">
        <div class="value">{par_sev.get('faible', 0)}</div>
        <div class="label">Faibles</div>
    </div>
    <div class="card">
        <div class="value">{formater_montant(result.impact_total)}</div>
        <div class="label">Impact financier estime</div>
    </div>
</div>

<!-- Score de risque -->
<section>
    <h2>Score de Risque Global</h2>
    <div class="score-circle {score_class}">
        <div class="score-value">{score}/100</div>
        <div class="score-label">Risque {score_label}</div>
    </div>
    <table>
        <tr><th>Categorie</th><th>Nombre</th></tr>
        <tr><td>Anomalies</td><td>{par_cat.get('anomalie', 0)}</td></tr>
        <tr><td>Incoherences</td><td>{par_cat.get('incoherence', 0)}</td></tr>
        <tr><td>Donnees manquantes</td><td>{par_cat.get('donnee_manquante', 0)}</td></tr>
        <tr><td>Depassements de seuil</td><td>{par_cat.get('depassement_seuil', 0)}</td></tr>
        <tr><td>Patterns suspects</td><td>{par_cat.get('pattern_suspect', 0)}</td></tr>
    </table>
</section>

<!-- Documents analyses -->
{docs_html}

<!-- Constats detailles -->
<section>
    <h2>Constats Detailles</h2>
    {findings_html}
</section>

<!-- Recommandations -->
<section>
    <h2>Recommandations Priorisees</h2>
    {reco_html}
</section>

<footer>
    Rapport genere par URSSAF Analyzer v1.0.0 - {result.date_analyse.strftime('%d/%m/%Y %H:%M')}<br>
    Ce rapport est confidentiel et destine exclusivement aux personnes autorisees.
</footer>

</div>
</body>
</html>"""

    def _generer_findings_html(self, findings: list[Finding]) -> str:
        """Genere le HTML des constats detailles."""
        if not findings:
            return "<p>Aucun constat detecte.</p>"

        rows = []
        for f in findings:
            impact = formater_montant(f.montant_impact) if f.montant_impact else "N/A"
            rows.append(f"""
    <tr>
        <td><span class="badge {f.severite.value}">{f.severite.value.upper()}</span></td>
        <td><span class="badge">{f.categorie.value}</span></td>
        <td><strong>{f.titre}</strong><br><small>{f.description[:200]}{'...' if len(f.description) > 200 else ''}</small></td>
        <td>{impact}</td>
        <td>{f.score_risque}/100</td>
        <td><small>{f.recommandation[:100]}{'...' if len(f.recommandation) > 100 else ''}</small></td>
    </tr>""")

        return f"""
    <table>
        <tr>
            <th>Severite</th>
            <th>Categorie</th>
            <th>Constat</th>
            <th>Impact</th>
            <th>Risque</th>
            <th>Recommandation</th>
        </tr>
        {''.join(rows)}
    </table>"""

    def _generer_recommandations_html(self, recommandations: list[dict]) -> str:
        """Genere le HTML des recommandations."""
        if not recommandations:
            return "<p>Aucune recommandation.</p>"

        items = []
        for i, r in enumerate(recommandations, 1):
            items.append(f"""
    <div class="reco-item">
        <span class="priority">#{i} - {r['titre']}</span>
        <p>{r['description']}</p>
        <small>Impact estime : {r['impact']} | Nb constats lies : {r['nb_constats']}</small>
    </div>""")
        return "".join(items)

    def _generer_documents_html(self, result: AnalysisResult) -> str:
        """Genere le tableau des documents analyses."""
        if not result.documents_analyses:
            return ""

        rows = []
        for d in result.documents_analyses:
            rows.append(f"""
    <tr>
        <td>{d.nom_fichier}</td>
        <td>{d.type_fichier.value if d.type_fichier else 'N/A'}</td>
        <td><code>{d.hash_sha256[:16]}...</code></td>
        <td>{d.taille_octets:,} octets</td>
    </tr>""")

        return f"""
<section>
    <h2>Documents Analyses</h2>
    <table>
        <tr><th>Fichier</th><th>Type</th><th>Hash SHA-256</th><th>Taille</th></tr>
        {''.join(rows)}
    </table>
</section>"""

    def _generer_recommandations(self, findings: list[Finding]) -> list[dict]:
        """Genere des recommandations priorisees a partir des findings."""
        # Regrouper par recommandation
        par_reco: dict[str, list[Finding]] = {}
        for f in findings:
            if f.recommandation:
                key = f.recommandation[:80]
                if key not in par_reco:
                    par_reco[key] = []
                par_reco[key].append(f)

        recommandations = []
        for reco_text, fs in par_reco.items():
            impact = sum(f.montant_impact or Decimal("0") for f in fs)
            max_sev = max(fs, key=lambda f: f.score_risque)
            recommandations.append({
                "titre": max_sev.titre,
                "description": max_sev.recommandation,
                "impact": formater_montant(impact),
                "nb_constats": len(fs),
                "score": max_sev.score_risque,
            })

        recommandations.sort(key=lambda r: -r["score"])
        return recommandations[:15]  # Top 15

    @staticmethod
    def _compter_par_severite(findings: list[Finding]) -> dict[str, int]:
        result: dict[str, int] = {}
        for f in findings:
            result[f.severite.value] = result.get(f.severite.value, 0) + 1
        return result

    @staticmethod
    def _compter_par_categorie(findings: list[Finding]) -> dict[str, int]:
        result: dict[str, int] = {}
        for f in findings:
            result[f.categorie.value] = result.get(f.categorie.value, 0) + 1
        return result

    @staticmethod
    def _finding_to_dict(f: Finding) -> dict[str, Any]:
        return {
            "id": f.id,
            "categorie": f.categorie.value,
            "severite": f.severite.value,
            "titre": f.titre,
            "description": f.description,
            "valeur_attendue": f.valeur_attendue,
            "valeur_constatee": f.valeur_constatee,
            "montant_impact": str(f.montant_impact) if f.montant_impact else None,
            "score_risque": f.score_risque,
            "recommandation": f.recommandation,
            "detecte_par": f.detecte_par,
            "reference_legale": f.reference_legale,
            "documents_concernes": f.documents_concernes,
        }
