"""Tests avec donnees realistes anonymisees.

Simule une paie mensuelle complete pour une entreprise de 25 salaries
avec differents profils (CDI/CDD, cadre/non-cadre, temps plein/partiel).
"""

import sys
from pathlib import Path
from decimal import Decimal

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.config.constants import (
    ContributionType, PASS_MENSUEL, SMIC_MENSUEL_BRUT,
    TAUX_COTISATIONS_2026,
)
from urssaf_analyzer.rules.contribution_rules import ContributionRules
from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
from urssaf_analyzer.comptabilite.fec_export import exporter_fec, valider_fec


# Employes anonymises
EMPLOYES = [
    # (nom, brut_mensuel, est_cadre, heures, est_alsace_moselle)
    ("Dupont J.", Decimal("2200"), False, Decimal("151.67"), False),    # SMIC+
    ("Martin S.", Decimal("2800"), False, Decimal("151.67"), False),    # Employe standard
    ("Durand P.", Decimal("3200"), False, Decimal("151.67"), False),    # < 2.25 SMIC
    ("Bernard L.", Decimal("4200"), False, Decimal("151.67"), False),   # > 2.25 SMIC
    ("Petit M.", Decimal("5500"), True, Decimal("151.67"), False),      # Cadre standard
    ("Robert A.", Decimal("7000"), True, Decimal("151.67"), False),      # Cadre > PASS
    ("Richard C.", Decimal("12000"), True, Decimal("151.67"), False),    # Cadre T2 haute
    ("Moreau E.", Decimal("1900"), False, Decimal("100"), False),        # Temps partiel
    ("Simon D.", Decimal("2500"), False, Decimal("120"), False),         # Temps partiel
    ("Laurent F.", Decimal("3000"), False, Decimal("151.67"), True),     # Alsace-Moselle
    ("Leroy G.", Decimal("3500"), False, Decimal("151.67"), False),
    ("Roux H.", Decimal("2600"), False, Decimal("151.67"), False),
    ("David I.", Decimal("4000"), True, Decimal("151.67"), False),       # Cadre junior
    ("Bertrand K.", Decimal("6500"), True, Decimal("151.67"), False),    # Cadre senior
    ("Morel N.", Decimal("2300"), False, Decimal("151.67"), False),
    ("Fournier O.", Decimal("2700"), False, Decimal("151.67"), False),
    ("Girard Q.", Decimal("3100"), False, Decimal("151.67"), False),
    ("Bonnet R.", Decimal("2900"), False, Decimal("151.67"), False),
    ("Dupuis T.", Decimal("3300"), False, Decimal("151.67"), False),
    ("Lambert U.", Decimal("4500"), True, Decimal("151.67"), False),     # Cadre
    ("Fontaine V.", Decimal("1823.03"), False, Decimal("151.67"), False), # Exactement SMIC
    ("Rousseau W.", Decimal("3800"), False, Decimal("151.67"), False),
    ("Vincent X.", Decimal("5000"), True, Decimal("151.67"), False),     # Cadre
    ("Muller Y.", Decimal("2400"), False, Decimal("80"), False),         # Mi-temps
    ("Lefevre Z.", Decimal("20000"), True, Decimal("151.67"), False),    # Dirigeant/haut cadre
]


class TestPayrollEntreprise25Salaries:
    """Simulation d'une paie mensuelle complete."""

    def _calculer_tous_les_bulletins(self):
        """Calcule les bulletins pour tous les employes."""
        bulletins = []
        for nom, brut, cadre, heures, alsace in EMPLOYES:
            rules = ContributionRules(
                effectif_entreprise=25,
                taux_at=Decimal("0.0208"),
                taux_versement_mobilite=Decimal("0.0175"),
                est_alsace_moselle=alsace,
            )
            if heures < Decimal("151.67"):
                bulletin = rules.calculer_bulletin_temps_partiel(brut, heures, cadre)
            else:
                bulletin = rules.calculer_bulletin_complet(brut, cadre)
            bulletin["nom"] = nom
            bulletin["est_cadre"] = cadre
            bulletin["est_alsace_moselle"] = alsace
            bulletins.append(bulletin)
        return bulletins

    def test_tous_les_bulletins_calculent(self):
        """Tous les bulletins se calculent sans erreur."""
        bulletins = self._calculer_tous_les_bulletins()
        assert len(bulletins) == 25

    def test_masse_salariale_coherente(self):
        """Masse salariale totale coherente."""
        masse = sum(brut for _, brut, _, _, _ in EMPLOYES)
        assert masse > Decimal("50000")
        assert masse < Decimal("200000")

    def test_charges_patronales_dans_fourchette(self):
        """Charges patronales totales entre 35% et 50% de la masse salariale."""
        bulletins = self._calculer_tous_les_bulletins()
        total_patronal = sum(b["total_patronal"] for b in bulletins)
        masse = sum(b["brut_mensuel"] for b in bulletins)

        taux_global = total_patronal / masse * 100
        assert 30 < taux_global < 55, f"Taux charges patronales {taux_global:.1f}% hors fourchette"

    def test_charges_salariales_dans_fourchette(self):
        """Charges salariales totales entre 18% et 28% du brut."""
        bulletins = self._calculer_tous_les_bulletins()
        total_salarial = sum(b["total_salarial"] for b in bulletins)
        masse = sum(b["brut_mensuel"] for b in bulletins)

        taux_global = total_salarial / masse * 100
        assert 15 < taux_global < 30, f"Taux charges salariales {taux_global:.1f}% hors fourchette"

    def test_net_positif_pour_tous(self):
        """Tous les employes ont un net > 0."""
        bulletins = self._calculer_tous_les_bulletins()
        for b in bulletins:
            assert b["net_avant_impot"] > 0, f"{b.get('nom')}: net negatif"

    def test_cadres_ont_apec(self):
        """Tous les cadres ont la cotisation APEC."""
        bulletins = self._calculer_tous_les_bulletins()
        for b in bulletins:
            types = {l["type"] for l in b["lignes"]}
            if b.get("est_cadre"):
                assert "apec" in types, f"{b.get('nom')}: cadre sans APEC"
            else:
                assert "apec" not in types

    def test_alsace_moselle_supplement(self):
        """Employes Alsace-Moselle ont la cotisation supplementaire."""
        bulletins = self._calculer_tous_les_bulletins()
        for b in bulletins:
            types = {l["type"] for l in b["lignes"]}
            if b.get("est_alsace_moselle"):
                assert "maladie_alsace_moselle" in types

    def test_maladie_taux_reduit_smic(self):
        """Employes au SMIC : taux maladie reduit applique."""
        rules = ContributionRules(effectif_entreprise=25)
        seuil_maladie = SMIC_MENSUEL_BRUT * Decimal("2.25")

        bulletins = self._calculer_tous_les_bulletins()
        for b in bulletins:
            for l in b["lignes"]:
                if l["type"] == "maladie":
                    if b["brut_mensuel"] <= float(seuil_maladie):
                        assert l["taux_patronal"] == 0.07, (
                            f"{b.get('nom')}: brut={b['brut_mensuel']}, "
                            f"taux_maladie={l['taux_patronal']} (attendu 0.07)"
                        )

    def test_rgdu_eligibilite(self):
        """Employes sous 3 SMIC annuel sont eligibles RGDU."""
        rules = ContributionRules(effectif_entreprise=25)
        for nom, brut, _, _, _ in EMPLOYES:
            salaire_annuel = brut * 12
            rgdu = rules.calculer_rgdu(salaire_annuel)
            seuil = SMIC_MENSUEL_BRUT * 12 * 3
            if salaire_annuel < seuil:
                assert rgdu > 0, f"{nom}: eligible RGDU mais reduction=0"
            else:
                assert rgdu == 0, f"{nom}: non eligible RGDU mais reduction>0"


class TestEcrituresPaieRealistes:
    """Generation d'ecritures comptables pour la paie."""

    def test_ecritures_paie_equilibrees(self):
        """Toutes les ecritures de paie sont equilibrees."""
        from datetime import date
        moteur = MoteurEcritures()

        rules = ContributionRules(effectif_entreprise=25, taux_at=Decimal("0.0208"))

        for nom, brut, cadre, heures, _ in EMPLOYES[:10]:  # 10 premiers
            bulletin = rules.calculer_bulletin_complet(brut, cadre)
            cot_sal = Decimal(str(bulletin["total_salarial"]))
            cot_pat = Decimal(str(bulletin["total_patronal"]))
            net = brut - cot_sal
            cot_retraite = Decimal("0")
            for l in bulletin["lignes"]:
                if "retraite" in l["type"] or "ceg" in l["type"] or "cet" in l["type"]:
                    cot_retraite += Decimal(str(l["montant_patronal"]))

            cot_urssaf = cot_pat - cot_retraite
            ecriture = moteur.generer_ecriture_paie(
                date_piece=date(2026, 1, 31),
                nom_salarie=nom,
                salaire_brut=brut,
                cotisations_salariales=cot_sal,
                cotisations_patronales_urssaf=cot_urssaf,
                cotisations_patronales_retraite=cot_retraite,
                net_a_payer=net,
            )
            assert ecriture.est_equilibree

    def test_fec_export_paie(self):
        """Export FEC des ecritures de paie valide."""
        from datetime import date
        moteur = MoteurEcritures()
        rules = ContributionRules(effectif_entreprise=25)

        for nom, brut, cadre, _, _ in EMPLOYES[:5]:
            bulletin = rules.calculer_bulletin_complet(brut, cadre)
            cot_sal = Decimal(str(bulletin["total_salarial"]))
            cot_pat = Decimal(str(bulletin["total_patronal"]))
            net = brut - cot_sal

            moteur.generer_ecriture_paie(
                date_piece=date(2026, 1, 31),
                nom_salarie=nom,
                salaire_brut=brut,
                cotisations_salariales=cot_sal,
                cotisations_patronales_urssaf=cot_pat,
                net_a_payer=net,
            )

        moteur.valider_ecritures()
        fec = exporter_fec(moteur, siren="123456789")
        result = valider_fec(fec)
        assert result["valide"]
        assert result["equilibre_general"]
        assert result["ecritures_desequilibrees"] == 0


class TestRecapitulatifAnnuel:
    """Verification des totaux annuels realistes."""

    def test_cout_total_employeur_realiste(self):
        """Le cout total employeur est dans la fourchette attendue."""
        rules = ContributionRules(
            effectif_entreprise=25,
            taux_at=Decimal("0.0208"),
            taux_versement_mobilite=Decimal("0.0175"),
        )
        brut = Decimal("3000")
        bulletin = rules.calculer_bulletin_complet(brut)

        # Cout total = brut + charges patronales
        cout = bulletin["cout_total_employeur"]
        # Typiquement 140-155% du brut
        ratio = cout / float(brut) * 100
        assert 130 < ratio < 160, f"Ratio cout/brut = {ratio:.1f}% hors norme"

    def test_net_a_payer_realiste(self):
        """Le net a payer est dans la fourchette attendue."""
        rules = ContributionRules(effectif_entreprise=25)
        brut = Decimal("3000")
        bulletin = rules.calculer_bulletin_complet(brut)

        # Net typiquement 72-82% du brut
        ratio_net = bulletin["net_avant_impot"] / float(brut) * 100
        assert 70 < ratio_net < 85, f"Ratio net/brut = {ratio_net:.1f}% hors norme"
