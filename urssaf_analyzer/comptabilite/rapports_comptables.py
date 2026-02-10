"""Generateur de rapports comptables, fiscaux et sociaux.

Produit :
- Grand livre
- Balance generale
- Journal des ecritures
- Compte de resultat simplifie
- Bilan simplifie
- Declaration de TVA (CA3)
- Recapitulatif des charges sociales
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures, TypeJournal
from urssaf_analyzer.comptabilite.plan_comptable import PlanComptable, ClasseCompte


class GenerateurRapports:
    """Genere les rapports comptables a partir des ecritures."""

    def __init__(self, moteur: MoteurEcritures):
        self.moteur = moteur
        self.plan = moteur.plan

    # --- Rapports comptables ---

    def grand_livre_html(self, date_debut: date = None, date_fin: date = None) -> str:
        """Genere le grand livre en HTML."""
        gl = self.moteur.get_grand_livre()
        html = [self._header_html("Grand Livre")]

        total_general_debit = 0.0
        total_general_credit = 0.0

        for compte_num, mouvements in gl.items():
            mouvements_filtres = self._filtrer_par_date(mouvements, date_debut, date_fin)
            if not mouvements_filtres:
                continue

            cpt = self.plan.get_compte(compte_num)
            libelle_cpt = cpt.libelle if cpt else compte_num
            total_d = sum(m["debit"] for m in mouvements_filtres)
            total_c = sum(m["credit"] for m in mouvements_filtres)
            solde = total_d - total_c
            total_general_debit += total_d
            total_general_credit += total_c

            html.append(f'<div class="compte-section">')
            html.append(f'<h3>{compte_num} - {libelle_cpt}</h3>')
            html.append('<table><thead><tr>')
            html.append('<th>Date</th><th>Journal</th><th>Piece</th>')
            html.append('<th>Libelle</th><th class="num">Debit</th>')
            html.append('<th class="num">Credit</th></tr></thead><tbody>')

            for m in mouvements_filtres:
                html.append(f'<tr><td>{m["date"]}</td><td>{m["journal"]}</td>')
                html.append(f'<td>{m["piece"]}</td><td>{m["libelle"]}</td>')
                html.append(f'<td class="num">{m["debit"]:.2f}</td>')
                html.append(f'<td class="num">{m["credit"]:.2f}</td></tr>')

            html.append(f'<tr class="total"><td colspan="4">Total {compte_num}</td>')
            html.append(f'<td class="num">{total_d:.2f}</td>')
            html.append(f'<td class="num">{total_c:.2f}</td></tr>')
            html.append(f'<tr><td colspan="4">Solde</td>')
            html.append(f'<td class="num" colspan="2">{solde:+.2f}</td></tr>')
            html.append('</tbody></table></div>')

        html.append(f'<div class="total-general"><h3>Total General</h3>')
        html.append(f'<p>Debit: {total_general_debit:,.2f} EUR | '
                     f'Credit: {total_general_credit:,.2f} EUR</p></div>')
        html.append(self._footer_html())
        return "\n".join(html)

    def balance_html(self) -> str:
        """Genere la balance generale en HTML."""
        balance = self.moteur.get_balance()
        html = [self._header_html("Balance Generale")]

        html.append('<table><thead><tr>')
        html.append('<th>Compte</th><th>Libelle</th>')
        html.append('<th class="num">Total Debit</th><th class="num">Total Credit</th>')
        html.append('<th class="num">Solde Debiteur</th><th class="num">Solde Crediteur</th>')
        html.append('</tr></thead><tbody>')

        totaux = {"td": 0, "tc": 0, "sd": 0, "sc": 0}
        for b in balance:
            html.append(f'<tr><td>{b["compte"]}</td><td>{b["libelle"]}</td>')
            html.append(f'<td class="num">{b["total_debit"]:.2f}</td>')
            html.append(f'<td class="num">{b["total_credit"]:.2f}</td>')
            html.append(f'<td class="num">{b["solde_debiteur"]:.2f}</td>')
            html.append(f'<td class="num">{b["solde_crediteur"]:.2f}</td></tr>')
            totaux["td"] += b["total_debit"]
            totaux["tc"] += b["total_credit"]
            totaux["sd"] += b["solde_debiteur"]
            totaux["sc"] += b["solde_crediteur"]

        html.append(f'<tr class="total"><td colspan="2">TOTAUX</td>')
        html.append(f'<td class="num">{totaux["td"]:.2f}</td>')
        html.append(f'<td class="num">{totaux["tc"]:.2f}</td>')
        html.append(f'<td class="num">{totaux["sd"]:.2f}</td>')
        html.append(f'<td class="num">{totaux["sc"]:.2f}</td></tr>')
        html.append('</tbody></table>')
        html.append(self._footer_html())
        return "\n".join(html)

    def journal_html(self, type_journal: TypeJournal = None) -> str:
        """Genere le journal des ecritures en HTML."""
        ecritures = self.moteur.get_journal(type_journal)
        titre = f"Journal {type_journal.value}" if type_journal else "Journal General"
        html = [self._header_html(titre)]

        for e in ecritures:
            statut = "Validee" if e["validee"] else "Brouillon"
            equi = "Equilibree" if e["equilibree"] else "DESEQUILIBREE"
            html.append(f'<div class="ecriture">')
            html.append(f'<h4>{e["date"]} - {e["journal"]} - {e["piece"]} '
                         f'<span class="badge">{statut}</span> '
                         f'<span class="badge {"ok" if e["equilibree"] else "err"}">{equi}</span></h4>')
            html.append(f'<p>{e["libelle"]}</p>')
            html.append('<table><thead><tr><th>Compte</th><th>Libelle</th>')
            html.append('<th class="num">Debit</th><th class="num">Credit</th>')
            html.append('</tr></thead><tbody>')
            for l in e["lignes"]:
                html.append(f'<tr><td>{l["compte"]}</td><td>{l["libelle"]}</td>')
                html.append(f'<td class="num">{l["debit"]:.2f}</td>')
                html.append(f'<td class="num">{l["credit"]:.2f}</td></tr>')
            html.append(f'<tr class="total"><td colspan="2">Total</td>')
            html.append(f'<td class="num">{e["total_debit"]:.2f}</td>')
            html.append(f'<td class="num">{e["total_credit"]:.2f}</td></tr>')
            html.append('</tbody></table></div>')

        html.append(self._footer_html())
        return "\n".join(html)

    # --- Rapports de synthese ---

    def compte_resultat(self) -> dict:
        """Calcule le compte de resultat simplifie."""
        balance = self.moteur.get_balance()
        charges = {}
        produits = {}

        for b in balance:
            num = b["compte"]
            if num.startswith("6"):
                solde = b["total_debit"] - b["total_credit"]
                charges[num] = {"libelle": b["libelle"], "montant": solde}
            elif num.startswith("7"):
                solde = b["total_credit"] - b["total_debit"]
                produits[num] = {"libelle": b["libelle"], "montant": solde}

        total_charges = sum(c["montant"] for c in charges.values())
        total_produits = sum(p["montant"] for p in produits.values())
        resultat = total_produits - total_charges

        # Groupement par nature
        charges_exploitation = {k: v for k, v in charges.items() if k < "660000"}
        charges_financieres = {k: v for k, v in charges.items() if "660000" <= k < "670000"}
        charges_exceptionnelles = {k: v for k, v in charges.items() if k >= "670000"}

        produits_exploitation = {k: v for k, v in produits.items() if k < "760000"}
        produits_financiers = {k: v for k, v in produits.items() if "760000" <= k < "770000"}
        produits_exceptionnels = {k: v for k, v in produits.items() if k >= "770000"}

        return {
            "charges": {
                "exploitation": {k: {"libelle": v["libelle"], "montant": float(v["montant"])} for k, v in charges_exploitation.items()},
                "financieres": {k: {"libelle": v["libelle"], "montant": float(v["montant"])} for k, v in charges_financieres.items()},
                "exceptionnelles": {k: {"libelle": v["libelle"], "montant": float(v["montant"])} for k, v in charges_exceptionnelles.items()},
                "total": float(total_charges),
            },
            "produits": {
                "exploitation": {k: {"libelle": v["libelle"], "montant": float(v["montant"])} for k, v in produits_exploitation.items()},
                "financiers": {k: {"libelle": v["libelle"], "montant": float(v["montant"])} for k, v in produits_financiers.items()},
                "exceptionnels": {k: {"libelle": v["libelle"], "montant": float(v["montant"])} for k, v in produits_exceptionnels.items()},
                "total": float(total_produits),
            },
            "resultat_exploitation": float(
                sum(v["montant"] for v in produits_exploitation.values())
                - sum(v["montant"] for v in charges_exploitation.values())
            ),
            "resultat_financier": float(
                sum(v["montant"] for v in produits_financiers.values())
                - sum(v["montant"] for v in charges_financieres.values())
            ),
            "resultat_exceptionnel": float(
                sum(v["montant"] for v in produits_exceptionnels.values())
                - sum(v["montant"] for v in charges_exceptionnelles.values())
            ),
            "resultat_net": float(resultat),
        }

    def bilan_simplifie(self) -> dict:
        """Calcule le bilan simplifie."""
        balance = self.moteur.get_balance()

        actif = {"immobilisations": {}, "actif_circulant": {}, "tresorerie": {}}
        passif = {"capitaux_propres": {}, "dettes": {}}

        for b in balance:
            num = b["compte"]
            solde = b["total_debit"] - b["total_credit"]
            entry = {"libelle": b["libelle"], "montant": float(abs(solde))}

            if num.startswith("2"):
                actif["immobilisations"][num] = entry
            elif num.startswith("3"):
                actif["actif_circulant"][num] = entry
            elif num.startswith("41"):
                if solde > 0:
                    actif["actif_circulant"][num] = entry
            elif num.startswith("5"):
                if solde > 0:
                    actif["tresorerie"][num] = entry
                else:
                    passif["dettes"][num] = entry
            elif num.startswith("1"):
                passif["capitaux_propres"][num] = entry
            elif num.startswith("40") or num.startswith("43") or num.startswith("44"):
                if solde < 0:
                    passif["dettes"][num] = {"libelle": b["libelle"], "montant": float(abs(solde))}

        total_actif = (
            sum(v["montant"] for v in actif["immobilisations"].values())
            + sum(v["montant"] for v in actif["actif_circulant"].values())
            + sum(v["montant"] for v in actif["tresorerie"].values())
        )
        total_passif = (
            sum(v["montant"] for v in passif["capitaux_propres"].values())
            + sum(v["montant"] for v in passif["dettes"].values())
        )

        return {
            "actif": actif,
            "passif": passif,
            "total_actif": total_actif,
            "total_passif": total_passif,
        }

    def declaration_tva(self, mois: int, annee: int) -> dict:
        """Genere les elements pour la declaration de TVA (CA3)."""
        balance = self.moteur.get_balance()

        tva_collectee = 0.0
        tva_deductible_biens = 0.0
        tva_deductible_immo = 0.0

        for b in balance:
            num = b["compte"]
            if num == "445710":
                tva_collectee = b["total_credit"] - b["total_debit"]
            elif num == "445660":
                tva_deductible_biens = b["total_debit"] - b["total_credit"]
            elif num == "445620":
                tva_deductible_immo = b["total_debit"] - b["total_credit"]

        tva_deductible_total = tva_deductible_biens + tva_deductible_immo
        tva_nette = tva_collectee - tva_deductible_total

        # CA par taux
        ca_ht_20 = 0.0
        for b in balance:
            if b["compte"].startswith("70"):
                ca_ht_20 += b["total_credit"] - b["total_debit"]

        return {
            "periode": f"{mois:02d}/{annee}",
            "chiffre_affaires_ht": float(ca_ht_20),
            "tva_collectee": float(tva_collectee),
            "tva_deductible_biens_services": float(tva_deductible_biens),
            "tva_deductible_immobilisations": float(tva_deductible_immo),
            "tva_deductible_totale": float(tva_deductible_total),
            "tva_nette_a_payer": float(tva_nette) if tva_nette > 0 else 0.0,
            "credit_tva": float(abs(tva_nette)) if tva_nette < 0 else 0.0,
        }

    def recapitulatif_charges_sociales(self) -> dict:
        """Genere le recapitulatif des charges sociales."""
        balance = self.moteur.get_balance()

        charges = {
            "salaires_bruts": 0.0,
            "cotisations_urssaf": 0.0,
            "cotisations_retraite": 0.0,
            "mutuelle_prevoyance": 0.0,
            "france_travail": 0.0,
            "autres_charges_sociales": 0.0,
        }

        for b in balance:
            num = b["compte"]
            solde = b["total_debit"] - b["total_credit"]
            if num.startswith("6411"):
                charges["salaires_bruts"] += solde
            elif num == "645100":
                charges["cotisations_urssaf"] += solde
            elif num == "645300":
                charges["cotisations_retraite"] += solde
            elif num == "645200":
                charges["mutuelle_prevoyance"] += solde
            elif num == "645400":
                charges["france_travail"] += solde
            elif num.startswith("645") or num.startswith("646") or num.startswith("647"):
                charges["autres_charges_sociales"] += solde

        charges["total_charges_sociales"] = (
            charges["cotisations_urssaf"]
            + charges["cotisations_retraite"]
            + charges["mutuelle_prevoyance"]
            + charges["france_travail"]
            + charges["autres_charges_sociales"]
        )
        charges["cout_total_employeur"] = (
            charges["salaires_bruts"] + charges["total_charges_sociales"]
        )
        charges["taux_charges_global"] = (
            (charges["total_charges_sociales"] / charges["salaires_bruts"] * 100)
            if charges["salaires_bruts"] > 0 else 0.0
        )

        return {k: round(v, 2) for k, v in charges.items()}

    # --- Utilitaires HTML ---

    def _header_html(self, titre: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>{titre} - URSSAF Analyzer</title>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; color: #333; }}
h1 {{ color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: 10px; }}
h3 {{ color: #283593; margin-top: 30px; }}
h4 {{ color: #1565c0; }}
table {{ width: 100%; border-collapse: collapse; margin: 10px 0 25px 0; font-size: 0.9em; }}
th {{ background: #e8eaf6; color: #1a237e; padding: 8px; text-align: left; border-bottom: 2px solid #3f51b5; }}
td {{ padding: 6px 8px; border-bottom: 1px solid #e0e0e0; }}
tr:hover {{ background: #f5f5f5; }}
.num {{ text-align: right; font-family: 'Consolas', monospace; }}
.total {{ font-weight: bold; background: #e8eaf6; }}
.total-general {{ margin-top: 30px; padding: 15px; background: #1a237e; color: white; border-radius: 8px; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; }}
.badge.ok {{ background: #c8e6c9; color: #2e7d32; }}
.badge.err {{ background: #ffcdd2; color: #c62828; }}
.compte-section {{ margin-bottom: 20px; }}
.ecriture {{ border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; margin: 15px 0; }}
.date-generation {{ color: #757575; font-size: 0.85em; margin-top: 30px; }}
</style></head><body>
<h1>{titre}</h1>"""

    def _footer_html(self) -> str:
        return f"""<p class="date-generation">Document genere par URSSAF Analyzer le {date.today().isoformat()}</p>
</body></html>"""

    @staticmethod
    def _filtrer_par_date(
        mouvements: list[dict], date_debut: date = None, date_fin: date = None,
    ) -> list[dict]:
        if not date_debut and not date_fin:
            return mouvements
        result = []
        for m in mouvements:
            d = date.fromisoformat(m["date"])
            if date_debut and d < date_debut:
                continue
            if date_fin and d > date_fin:
                continue
            result.append(m)
        return result

    def compte_resultat_html(self) -> str:
        """Genere le compte de resultat en HTML."""
        cr = self.compte_resultat()
        html = [self._header_html("Compte de Resultat")]

        html.append('<div style="display:flex;gap:30px;">')

        # Charges
        html.append('<div style="flex:1;">')
        html.append('<h3>CHARGES</h3>')
        html.append('<table><thead><tr><th>Compte</th><th>Libelle</th><th class="num">Montant</th></tr></thead><tbody>')
        for section, label in [("exploitation", "Charges d'exploitation"), ("financieres", "Charges financieres"), ("exceptionnelles", "Charges exceptionnelles")]:
            items = cr["charges"][section]
            if items:
                html.append(f'<tr class="total"><td colspan="3">{label}</td></tr>')
                for k, v in items.items():
                    html.append(f'<tr><td>{k}</td><td>{v["libelle"]}</td><td class="num">{v["montant"]:.2f}</td></tr>')
        html.append(f'<tr class="total"><td colspan="2">TOTAL CHARGES</td><td class="num">{cr["charges"]["total"]:.2f}</td></tr>')
        html.append('</tbody></table></div>')

        # Produits
        html.append('<div style="flex:1;">')
        html.append('<h3>PRODUITS</h3>')
        html.append('<table><thead><tr><th>Compte</th><th>Libelle</th><th class="num">Montant</th></tr></thead><tbody>')
        for section, label in [("exploitation", "Produits d'exploitation"), ("financiers", "Produits financiers"), ("exceptionnels", "Produits exceptionnels")]:
            items = cr["produits"][section]
            if items:
                html.append(f'<tr class="total"><td colspan="3">{label}</td></tr>')
                for k, v in items.items():
                    html.append(f'<tr><td>{k}</td><td>{v["libelle"]}</td><td class="num">{v["montant"]:.2f}</td></tr>')
        html.append(f'<tr class="total"><td colspan="2">TOTAL PRODUITS</td><td class="num">{cr["produits"]["total"]:.2f}</td></tr>')
        html.append('</tbody></table></div>')

        html.append('</div>')

        # Resultat
        color = "#2e7d32" if cr["resultat_net"] >= 0 else "#c62828"
        html.append(f'<div class="total-general" style="background:{color};">')
        html.append(f'<h3>Resultat d\'exploitation: {cr["resultat_exploitation"]:,.2f} EUR</h3>')
        html.append(f'<h3>Resultat financier: {cr["resultat_financier"]:,.2f} EUR</h3>')
        html.append(f'<h3>Resultat exceptionnel: {cr["resultat_exceptionnel"]:,.2f} EUR</h3>')
        label = "BENEFICE" if cr["resultat_net"] >= 0 else "PERTE"
        html.append(f'<h2>RESULTAT NET ({label}): {cr["resultat_net"]:,.2f} EUR</h2>')
        html.append('</div>')

        html.append(self._footer_html())
        return "\n".join(html)

    def recapitulatif_social_html(self) -> str:
        """Genere le recapitulatif des charges sociales en HTML."""
        recap = self.recapitulatif_charges_sociales()
        html = [self._header_html("Recapitulatif des Charges Sociales")]

        html.append('<table>')
        html.append('<thead><tr><th>Poste</th><th class="num">Montant (EUR)</th></tr></thead>')
        html.append('<tbody>')

        postes = [
            ("Salaires bruts", recap["salaires_bruts"]),
            ("Cotisations URSSAF", recap["cotisations_urssaf"]),
            ("Cotisations retraite complementaire", recap["cotisations_retraite"]),
            ("Mutuelle / Prevoyance", recap["mutuelle_prevoyance"]),
            ("France Travail (chomage)", recap["france_travail"]),
            ("Autres charges sociales", recap["autres_charges_sociales"]),
        ]
        for label, montant in postes:
            html.append(f'<tr><td>{label}</td><td class="num">{montant:,.2f}</td></tr>')

        html.append(f'<tr class="total"><td>Total charges sociales</td>')
        html.append(f'<td class="num">{recap["total_charges_sociales"]:,.2f}</td></tr>')
        html.append(f'<tr class="total"><td>Cout total employeur</td>')
        html.append(f'<td class="num">{recap["cout_total_employeur"]:,.2f}</td></tr>')
        html.append(f'<tr class="total"><td>Taux de charges global</td>')
        html.append(f'<td class="num">{recap["taux_charges_global"]:.1f}%</td></tr>')
        html.append('</tbody></table>')

        html.append(self._footer_html())
        return "\n".join(html)
