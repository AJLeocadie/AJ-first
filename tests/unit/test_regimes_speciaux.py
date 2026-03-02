"""Tests des regimes speciaux, travailleurs detaches et analyse multi-annuelle."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from decimal import Decimal

from urssaf_analyzer.rules.regimes_speciaux import (
    get_regime, lister_regimes, detecter_regime,
    calculer_supplement_alsace_moselle, calculer_cotisations_msa,
    REGIME_MSA, REGIME_ALSACE_MOSELLE,
)
from urssaf_analyzer.rules.travailleurs_detaches import (
    verifier_conformite_detachement, determiner_regime_applicable,
    DETACHEMENT_UE, TRAVAILLEURS_ETRANGERS,
)
from urssaf_analyzer.rules.analyse_multiannuelle import AnalyseMultiAnnuelle


# ==============================
# Regimes Speciaux
# ==============================

class TestGetRegime:
    """Tests de la recuperation des regimes."""

    def test_regime_msa(self):
        r = get_regime("msa")
        assert r is not None
        assert r["code"] == "msa"
        assert "cotisations" in r

    def test_regime_alsace_moselle(self):
        r = get_regime("alsace_moselle")
        assert r is not None
        assert "departements" in r
        assert "57" in r["departements"]

    def test_regime_inexistant(self):
        assert get_regime("inexistant") is None

    def test_regime_case_insensitive(self):
        r = get_regime("MSA")
        assert r is not None


class TestListerRegimes:
    """Tests du listing des regimes."""

    def test_liste_non_vide(self):
        regimes = lister_regimes()
        assert len(regimes) > 0

    def test_structure_element(self):
        regimes = lister_regimes()
        for r in regimes:
            assert "code" in r
            assert "nom" in r
            assert "description" in r

    def test_contient_principaux_regimes(self):
        regimes = lister_regimes()
        codes = [r["code"] for r in regimes]
        assert "msa" in codes
        assert "alsace_moselle" in codes


class TestDetecterRegime:
    """Tests de la detection automatique de regime."""

    def test_detection_alsace_par_departement(self):
        regimes = detecter_regime(departement="67")
        assert "alsace_moselle" in regimes

    def test_detection_moselle(self):
        regimes = detecter_regime(departement="57")
        assert "alsace_moselle" in regimes

    def test_detection_msa_par_naf(self):
        regimes = detecter_regime(code_naf="01.11")
        assert "msa" in regimes

    def test_detection_msa_par_texte(self):
        regimes = detecter_regime(texte="Mutualite Sociale Agricole")
        assert "msa" in regimes

    def test_detection_sncf_par_texte(self):
        regimes = detecter_regime(texte="salarie SNCF")
        assert "sncf" in regimes

    def test_detection_crpcen_par_idcc(self):
        regimes = detecter_regime(idcc="2205")
        assert "crpcen" in regimes

    def test_detection_aucun_regime(self):
        regimes = detecter_regime()
        assert len(regimes) == 0

    def test_detection_paris(self):
        """Paris n'a pas de regime special."""
        regimes = detecter_regime(departement="75")
        assert "alsace_moselle" not in regimes

    def test_detection_multiple(self):
        """Detection de plusieurs regimes simultanement."""
        regimes = detecter_regime(departement="67", texte="exploitant agricole MSA")
        assert "alsace_moselle" in regimes
        assert "msa" in regimes


class TestCalculerSupplementAlsaceMoselle:
    """Tests du calcul du supplement Alsace-Moselle."""

    def test_calcul_brut_3000(self):
        result = calculer_supplement_alsace_moselle(Decimal("3000"))
        assert result["taux_salarial"] == 0.013
        assert result["montant_salarial_mensuel"] == 39.0
        assert result["montant_salarial_annuel"] == 39.0 * 12

    def test_calcul_smic(self):
        from urssaf_analyzer.config.constants import SMIC_MENSUEL_BRUT
        result = calculer_supplement_alsace_moselle(SMIC_MENSUEL_BRUT)
        assert result["montant_salarial_mensuel"] > 0
        assert result["ref"] == "CSS art. L242-4-4"

    def test_calcul_brut_zero(self):
        result = calculer_supplement_alsace_moselle(Decimal("0"))
        assert result["montant_salarial_mensuel"] == 0


class TestCalculerCotisationsMSA:
    """Tests du calcul des cotisations MSA."""

    def test_calcul_basique(self):
        result = calculer_cotisations_msa(Decimal("2500"))
        assert result["regime"] == "msa"
        assert result["brut_mensuel"] == 2500.0
        assert len(result["lignes"]) > 0
        assert result["total_patronal"] > 0

    def test_cout_total(self):
        result = calculer_cotisations_msa(Decimal("3000"))
        assert result["cout_total"] > 3000.0

    def test_taux_reduit_maladie_bas_salaire(self):
        """Taux maladie reduit si <= 2.5 SMIC."""
        from urssaf_analyzer.config.constants import SMIC_MENSUEL_BRUT
        brut_bas = SMIC_MENSUEL_BRUT * Decimal("1.5")
        result = calculer_cotisations_msa(brut_bas)
        ligne_maladie = [l for l in result["lignes"] if l["cotisation"] == "maladie_maternite"]
        assert len(ligne_maladie) == 1
        assert ligne_maladie[0]["taux_patronal"] == 0.07  # Taux reduit

    def test_taux_normal_maladie_haut_salaire(self):
        """Taux maladie normal si > 2.5 SMIC."""
        from urssaf_analyzer.config.constants import SMIC_MENSUEL_BRUT
        brut_haut = SMIC_MENSUEL_BRUT * Decimal("3")
        result = calculer_cotisations_msa(brut_haut)
        ligne_maladie = [l for l in result["lignes"] if l["cotisation"] == "maladie_maternite"]
        assert len(ligne_maladie) == 1
        assert ligne_maladie[0]["taux_patronal"] == 0.13  # Taux normal


# ==============================
# Travailleurs Detaches
# ==============================

class TestVerifierConformiteDetachement:
    """Tests de la verification de conformite du detachement."""

    def test_detachement_conforme(self):
        result = verifier_conformite_detachement(
            nationalite="allemand",
            pays_employeur="allemagne",
            a1_present=True,
            sipsi_declare=True,
            duree_mois=6,
            remuneration_brute=Decimal("3000"),
        )
        assert result["conforme"] is True
        assert result["nb_anomalies"] == 0

    def test_detachement_sans_sipsi(self):
        result = verifier_conformite_detachement(
            sipsi_declare=False,
            a1_present=True,
            duree_mois=6,
            remuneration_brute=Decimal("3000"),
        )
        assert result["conforme"] is False
        assert any("SIPSI" in a["description"] for a in result["anomalies"])

    def test_detachement_sans_a1(self):
        result = verifier_conformite_detachement(
            sipsi_declare=True,
            a1_present=False,
            duree_mois=6,
            remuneration_brute=Decimal("3000"),
        )
        assert result["conforme"] is False
        assert any("A1" in a["description"] for a in result["anomalies"])

    def test_detachement_depassement_18_mois(self):
        result = verifier_conformite_detachement(
            sipsi_declare=True,
            a1_present=True,
            duree_mois=24,
            remuneration_brute=Decimal("3000"),
        )
        assert result["conforme"] is False
        assert any("depasse" in a["description"].lower() for a in result["anomalies"])

    def test_detachement_alerte_12_18_mois(self):
        result = verifier_conformite_detachement(
            sipsi_declare=True,
            a1_present=True,
            duree_mois=15,
            remuneration_brute=Decimal("3000"),
        )
        # Conforme mais alerte sur la duree
        assert result["nb_alertes"] > 0

    def test_detachement_remuneration_sous_smic(self):
        result = verifier_conformite_detachement(
            sipsi_declare=True,
            a1_present=True,
            duree_mois=6,
            remuneration_brute=Decimal("500"),
        )
        assert result["conforme"] is False
        assert any("remuneration" in a["description"].lower() for a in result["anomalies"])

    def test_detachement_btp_sans_carte(self):
        result = verifier_conformite_detachement(
            sipsi_declare=True,
            a1_present=True,
            duree_mois=6,
            remuneration_brute=Decimal("3000"),
            secteur_btp=True,
            carte_btp=False,
        )
        assert result["conforme"] is False
        assert any("BTP" in a["description"] for a in result["anomalies"])

    def test_detachement_btp_avec_carte(self):
        result = verifier_conformite_detachement(
            sipsi_declare=True,
            a1_present=True,
            duree_mois=6,
            remuneration_brute=Decimal("3000"),
            secteur_btp=True,
            carte_btp=True,
        )
        assert result["conforme"] is True


class TestDeterminerRegimeApplicable:
    """Tests de la determination du regime applicable."""

    def test_employeur_francais(self):
        result = determiner_regime_applicable(pays_employeur="france")
        assert result["regime"] == "regime_general_france"
        assert result["cotisations_en_france"] is True

    def test_detachement_ue_avec_a1(self):
        result = determiner_regime_applicable(
            pays_employeur="allemagne",
            certificat_a1=True,
        )
        assert result["cotisations_en_france"] is False

    def test_detachement_ue_sans_a1(self):
        result = determiner_regime_applicable(
            pays_employeur="espagne",
            certificat_a1=False,
        )
        assert result["cotisations_en_france"] is True

    def test_pays_tiers_sans_convention(self):
        result = determiner_regime_applicable(
            pays_employeur="chine",
            convention_bilaterale=False,
        )
        assert result["cotisations_en_france"] is True

    def test_employeur_vide(self):
        """Un employeur non renseigne = regime general."""
        result = determiner_regime_applicable(pays_employeur="")
        assert result["regime"] == "regime_general_france"


# ==============================
# Analyse Multi-Annuelle
# ==============================

class TestAnalyseMultiAnnuelle:
    """Tests de l'analyse multi-annuelle."""

    def setup_method(self):
        self.analyse = AnalyseMultiAnnuelle()

    def test_analyse_vide(self):
        result = self.analyse.analyser()
        assert result["couverture"]["annees"] == []
        assert result["couverture"]["complete"] is False
        assert len(result["recommandations"]) > 0

    def test_alimenter_annee(self):
        self.analyse.alimenter(2025, {"masse_salariale": 500000, "effectif_moyen": 20})
        assert 2025 in self.analyse.donnees_annuelles
        assert self.analyse.donnees_annuelles[2025]["masse_salariale"] == 500000

    def test_alimenter_cumul(self):
        """Alimenter deux fois la meme annee cumule les donnees."""
        self.analyse.alimenter(2025, {"masse_salariale": 500000})
        self.analyse.alimenter(2025, {"effectif_moyen": 20})
        d = self.analyse.donnees_annuelles[2025]
        assert d["masse_salariale"] == 500000
        assert d["effectif_moyen"] == 20

    def test_tendance_hausse_masse_salariale(self):
        self.analyse.alimenter(2022, {"masse_salariale": 400000, "effectif_moyen": 15})
        self.analyse.alimenter(2023, {"masse_salariale": 450000, "effectif_moyen": 16})
        self.analyse.alimenter(2024, {"masse_salariale": 500000, "effectif_moyen": 18})
        self.analyse.alimenter(2025, {"masse_salariale": 550000, "effectif_moyen": 20})
        result = self.analyse.analyser()
        tendances = result["tendances"]
        masse_tendance = [t for t in tendances if t["indicateur"] == "masse_salariale"]
        assert len(masse_tendance) == 1
        assert masse_tendance[0]["tendance"] in ("hausse", "stable")

    def test_anomalie_chute_masse_salariale(self):
        self.analyse.alimenter(2024, {"masse_salariale": 1000000, "effectif_moyen": 40})
        self.analyse.alimenter(2025, {"masse_salariale": 500000, "effectif_moyen": 40})
        result = self.analyse.analyser()
        anomalies = result["anomalies"]
        assert any(a["type"] == "chute_masse_salariale" for a in anomalies)

    def test_anomalie_chute_effectif(self):
        self.analyse.alimenter(2024, {"masse_salariale": 500000, "effectif_moyen": 50})
        self.analyse.alimenter(2025, {"masse_salariale": 500000, "effectif_moyen": 30})
        result = self.analyse.analyser()
        anomalies = result["anomalies"]
        assert any(a["type"] == "chute_effectif" for a in anomalies)

    def test_pas_anomalie_stable(self):
        self.analyse.alimenter(2024, {"masse_salariale": 500000, "effectif_moyen": 20})
        self.analyse.alimenter(2025, {"masse_salariale": 510000, "effectif_moyen": 21})
        result = self.analyse.analyser()
        anomalies = result["anomalies"]
        assert len(anomalies) == 0

    def test_couverture_temporelle(self):
        self.analyse.alimenter(2023, {"masse_salariale": 400000})
        self.analyse.alimenter(2024, {"masse_salariale": 450000})
        self.analyse.alimenter(2025, {"masse_salariale": 500000})
        result = self.analyse.analyser()
        couverture = result["couverture"]
        assert couverture["annee_min"] == 2023
        assert couverture["annee_max"] == 2025
        assert couverture["etendue"] == 3

    def test_recommandations_annees_manquantes(self):
        self.analyse.alimenter(2025, {"masse_salariale": 500000})
        result = self.analyse.analyser()
        reco = result["recommandations"]
        # Il devrait y avoir des recommandations car des annees manquent
        assert len(reco) > 0

    def test_ecart_dsn_bulletins(self):
        self.analyse.alimenter(2025, {
            "masse_salariale": 500000,
            "masse_salariale_dsn": 400000,  # 20% d'ecart
            "nb_bulletins": 12,
            "nb_dsn": 12,
            "effectif_moyen": 20,
        })
        # Il faut 2 annees pour comparer
        self.analyse.alimenter(2024, {"masse_salariale": 480000, "effectif_moyen": 20})
        result = self.analyse.analyser()
        anomalies = result["anomalies"]
        assert any(a["type"] == "ecart_dsn_bulletins" for a in anomalies)

    def test_alimenter_depuis_knowledge(self):
        knowledge = {
            "periodes_couvertes": ["2025-01", "2025-02"],
            "bulletins_paie": [
                {"periode": "2025-01", "masse_salariale": 50000, "nb_salaries": 20, "total_patronal": 15000},
            ],
            "declarations_dsn": [
                {"periode": "2025-01", "masse_salariale": 50000, "nb_salaries": 20},
            ],
            "effectifs": {"2025-01": 20},
        }
        self.analyse.alimenter_depuis_knowledge(knowledge)
        assert 2025 in self.analyse.donnees_annuelles

    def test_donnees_par_annee_dans_resultat(self):
        self.analyse.alimenter(2024, {"masse_salariale": 400000})
        self.analyse.alimenter(2025, {"masse_salariale": 500000})
        result = self.analyse.analyser()
        assert "donnees_par_annee" in result
        assert 2024 in result["donnees_par_annee"]
        assert 2025 in result["donnees_par_annee"]


class TestReferentielDetachement:
    """Tests du referentiel de donnees detachement."""

    def test_noyau_dur_complet(self):
        regles = DETACHEMENT_UE["noyau_dur"]["regles"]
        assert "remuneration_minimale" in regles
        assert "duree_travail" in regles
        assert "conges_payes" in regles
        assert "sante_securite" in regles

    def test_duree_maximale(self):
        duree = DETACHEMENT_UE["duree_maximale"]
        assert duree["standard"] == 12
        assert duree["total_max"] == 18

    def test_categories_travailleurs_etrangers(self):
        cats = TRAVAILLEURS_ETRANGERS["categories"]
        assert "ue_eee_suisse" in cats
        assert "hors_ue_titre_sejour" in cats
        assert "passeport_talent" in cats
