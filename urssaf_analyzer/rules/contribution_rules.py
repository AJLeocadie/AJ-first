"""Regles metier de calcul et validation des cotisations sociales.

Couverture exhaustive de la reglementation URSSAF 2026 :
- RGDU (Reduction Generale Degressive Unique)
- Cotisations SS (maladie, vieillesse, AF, AT/MP)
- CSG/CRDS (assiette 98.25%)
- FNAL (plafonne/deplafonne selon effectif)
- Versement mobilite (VT) selon commune
- Contribution solidarite autonomie (CSA)
- Contribution dialogue social
- Chomage (bonus-malus), AGS
- Retraite complementaire AGIRC-ARRCO (T1, T2, CEG, CET)
- APEC (cadres)
- Prevoyance cadre obligatoire
- Formation professionnelle, taxe apprentissage
- PEEC (effort construction)
- Forfait social
- Taxe sur les salaires
- Assiettes fiscales (plafonnees, deplafonnees, 98.25%)
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from urssaf_analyzer.config.constants import (
    ContributionType,
    TAUX_COTISATIONS_2026,
    PASS_MENSUEL,
    PASS_ANNUEL,
    SMIC_MENSUEL_BRUT,
    SMIC_ANNUEL_BRUT,
    HEURES_MENSUELLES_LEGALES,
    RGDU_SEUIL_SMIC_MULTIPLE,
    RGDU_TAUX_MAX_MOINS_50,
    RGDU_TAUX_MAX_50_PLUS,
    SEUIL_EFFECTIF_11,
    SEUIL_EFFECTIF_20,
    SEUIL_EFFECTIF_50,
    SEUIL_EFFECTIF_250,
    TOLERANCE_TAUX,
    TOLERANCE_MONTANT,
)


class ContributionRules:
    """Regles de calcul et de validation des cotisations sociales 2026.

    Parametres:
        effectif_entreprise: effectif moyen annuel
        taux_at: taux AT/MP propre a l'entreprise
        taux_versement_mobilite: taux VM selon localisation (AOM)
        est_alsace_moselle: regime local Alsace-Moselle
        zone_geographique: pour le versement mobilite
    """

    def __init__(
        self,
        effectif_entreprise: int = 0,
        taux_at: Decimal = Decimal("0.0208"),
        taux_versement_mobilite: Decimal = Decimal("0"),
        est_alsace_moselle: bool = False,
    ):
        self.effectif = effectif_entreprise
        self.taux_at = taux_at
        self.taux_vm = taux_versement_mobilite
        self.est_alsace_moselle = est_alsace_moselle

    # =================================================================
    # TAUX PATRONAUX
    # =================================================================

    def get_taux_attendu_patronal(
        self, type_cotisation: ContributionType,
        salaire_brut: Decimal = Decimal("0"),
    ) -> Optional[Decimal]:
        """Retourne le taux patronal attendu pour un type de cotisation."""
        taux = TAUX_COTISATIONS_2026.get(type_cotisation)
        if not taux:
            return None

        # Maladie (reduction si <= 2.5 SMIC)
        if type_cotisation == ContributionType.MALADIE:
            seuil = SMIC_MENSUEL_BRUT * taux.get("seuil_reduction_smic", Decimal("2.5"))
            if Decimal("0") < salaire_brut <= seuil:
                return taux.get("patronal_reduit", taux["patronal"])
            return taux["patronal"]

        # Allocations familiales (reduction si <= 3.5 SMIC)
        if type_cotisation == ContributionType.ALLOCATIONS_FAMILIALES:
            seuil = SMIC_MENSUEL_BRUT * taux.get("seuil_reduction_smic", Decimal("3.5"))
            if Decimal("0") < salaire_brut <= seuil:
                return taux.get("patronal_reduit", taux["patronal"])
            return taux["patronal"]

        # FNAL : plafonne < 50, deplafonne >= 50
        if type_cotisation == ContributionType.FNAL:
            if self.effectif >= SEUIL_EFFECTIF_50:
                return taux.get("patronal_50_plus", Decimal("0.005"))
            return taux.get("patronal_moins_50", Decimal("0.001"))

        # Formation professionnelle
        if type_cotisation == ContributionType.FORMATION_PROFESSIONNELLE:
            if self.effectif >= SEUIL_EFFECTIF_11:
                return taux.get("patronal_11_plus", Decimal("0.01"))
            return taux.get("patronal_moins_11", Decimal("0.0055"))

        # AT/MP : taux propre a l'entreprise
        if type_cotisation == ContributionType.ACCIDENT_TRAVAIL:
            return self.taux_at

        # Versement mobilite : taux selon commune, >= 11 salaries
        if type_cotisation == ContributionType.VERSEMENT_MOBILITE:
            if self.effectif >= taux.get("seuil_effectif", 11):
                return self.taux_vm
            return Decimal("0")

        # PEEC : >= 20 salaries
        if type_cotisation == ContributionType.PEEC:
            if self.effectif >= SEUIL_EFFECTIF_20:
                return taux.get("patronal", Decimal("0.0045"))
            return Decimal("0")

        # Taxe apprentissage
        if type_cotisation == ContributionType.TAXE_APPRENTISSAGE:
            return taux.get("patronal", Decimal("0.0068"))

        # CSA (Contribution Solidarite Autonomie)
        if type_cotisation == ContributionType.CONTRIBUTION_SOLIDARITE_AUTONOMIE:
            return taux.get("patronal", Decimal("0.003"))

        # Dialogue social
        if type_cotisation == ContributionType.CONTRIBUTION_DIALOGUE_SOCIAL:
            return taux.get("patronal", Decimal("0.00016"))

        # Prevoyance cadre (minimum)
        if type_cotisation == ContributionType.PREVOYANCE_CADRE:
            return taux.get("patronal_minimum", Decimal("0.015"))

        # Forfait social
        if type_cotisation == ContributionType.FORFAIT_SOCIAL:
            return taux.get("taux_droit_commun", Decimal("0.20"))

        # Contribution supplementaire apprentissage
        if type_cotisation == ContributionType.CONTRIBUTION_SUPPLEMENTAIRE_APPRENTISSAGE:
            if self.effectif >= SEUIL_EFFECTIF_250:
                return taux.get("patronal_250_plus", Decimal("0.0005"))
            return Decimal("0")

        # CPF-CDD
        if type_cotisation == ContributionType.CONTRIBUTION_CPF_CDD:
            return taux.get("patronal", Decimal("0.01"))

        # Taxe sur les salaires
        if type_cotisation == ContributionType.TAXE_SUR_SALAIRES:
            return taux.get("taux_normal", Decimal("0.0420"))

        return taux.get("patronal", taux.get("taux"))

    # =================================================================
    # TAUX SALARIAUX
    # =================================================================

    def get_taux_attendu_salarial(
        self, type_cotisation: ContributionType,
    ) -> Optional[Decimal]:
        """Retourne le taux salarial attendu."""
        taux = TAUX_COTISATIONS_2026.get(type_cotisation)
        if not taux:
            return None

        # Alsace-Moselle : cotisation supplementaire maladie 1.30%
        if type_cotisation == ContributionType.MALADIE_ALSACE_MOSELLE:
            if self.est_alsace_moselle:
                return taux.get("salarial", Decimal("0.013"))
            return Decimal("0")

        return taux.get("salarial", taux.get("taux"))

    # =================================================================
    # ASSIETTES DE COTISATIONS
    # =================================================================

    def calculer_assiette(
        self, type_cotisation: ContributionType,
        brut_mensuel: Decimal,
    ) -> Decimal:
        """Calcule l'assiette de cotisation apres plafonnement.

        Assiettes possibles :
        - Totalite du salaire brut (deplafonnee)
        - Plafonnee au PASS mensuel (Tranche 1)
        - Plafonnee a 4 PASS (chomage, AGS)
        - Tranche 2 : entre 1 et 8 PASS
        - 98.25% du brut (CSG/CRDS)
        """
        taux = TAUX_COTISATIONS_2026.get(type_cotisation, {})

        # CSG/CRDS : assiette = 98.25% du brut
        if "assiette_pct" in taux:
            return (brut_mensuel * taux["assiette_pct"]).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )

        # Cotisations plafonnees au PASS (Tranche 1)
        if "plafond" in taux and "plancher" not in taux:
            plafond = taux["plafond"]
            return min(brut_mensuel, plafond)

        # Cotisations plafonnees a un multiple du PASS
        if "plafond_multiple_pass" in taux and "plancher" not in taux:
            plafond = PASS_MENSUEL * taux["plafond_multiple_pass"]
            return min(brut_mensuel, plafond)

        # Tranche 2 : entre PASS et X * PASS
        if "plancher" in taux:
            plancher = taux["plancher"]
            plafond = PASS_MENSUEL * taux.get("plafond_multiple_pass", Decimal("8"))
            if brut_mensuel <= plancher:
                return Decimal("0")
            return min(brut_mensuel, plafond) - plancher

        # FNAL < 50 : plafonnee au PASS
        if type_cotisation == ContributionType.FNAL:
            if self.effectif < SEUIL_EFFECTIF_50:
                return min(brut_mensuel, PASS_MENSUEL)
            return brut_mensuel

        # Pas de plafonnement (totalite)
        return brut_mensuel

    # =================================================================
    # CALCUL DES MONTANTS
    # =================================================================

    def calculer_montant_patronal(
        self, type_cotisation: ContributionType,
        brut_mensuel: Decimal,
    ) -> Decimal:
        """Calcule le montant de la cotisation patronale."""
        assiette = self.calculer_assiette(type_cotisation, brut_mensuel)
        taux = self.get_taux_attendu_patronal(type_cotisation, brut_mensuel)
        if taux is None or taux == 0:
            return Decimal("0")
        return (assiette * taux).quantize(Decimal("0.01"), ROUND_HALF_UP)

    def calculer_montant_salarial(
        self, type_cotisation: ContributionType,
        brut_mensuel: Decimal,
    ) -> Decimal:
        """Calcule le montant de la cotisation salariale."""
        assiette = self.calculer_assiette(type_cotisation, brut_mensuel)
        taux = self.get_taux_attendu_salarial(type_cotisation)
        if taux is None or taux == 0:
            return Decimal("0")
        return (assiette * taux).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # =================================================================
    # BULLETIN COMPLET
    # =================================================================

    def calculer_bulletin_complet(
        self, brut_mensuel: Decimal, est_cadre: bool = False,
    ) -> dict:
        """Calcule l'ensemble des cotisations pour un bulletin de paie.

        Retourne un dictionnaire avec le detail par cotisation
        et les totaux patronal/salarial/net.
        """
        lignes = []

        # --- Securite sociale ---
        cotisations_ss = [
            ContributionType.MALADIE,
            ContributionType.VIEILLESSE_PLAFONNEE,
            ContributionType.VIEILLESSE_DEPLAFONNEE,
            ContributionType.ALLOCATIONS_FAMILIALES,
            ContributionType.ACCIDENT_TRAVAIL,
        ]
        if self.est_alsace_moselle:
            cotisations_ss.append(ContributionType.MALADIE_ALSACE_MOSELLE)

        for ct in cotisations_ss:
            ligne = self._calculer_ligne(ct, brut_mensuel)
            if ligne:
                lignes.append(ligne)

        # --- CSG/CRDS ---
        for ct in [ContributionType.CSG_DEDUCTIBLE,
                    ContributionType.CSG_NON_DEDUCTIBLE,
                    ContributionType.CRDS]:
            ligne = self._calculer_ligne(ct, brut_mensuel)
            if ligne:
                lignes.append(ligne)

        # --- Contributions URSSAF ---
        contributions_urssaf = [
            ContributionType.CONTRIBUTION_SOLIDARITE_AUTONOMIE,
            ContributionType.FNAL,
            ContributionType.CONTRIBUTION_DIALOGUE_SOCIAL,
        ]
        if self.effectif >= SEUIL_EFFECTIF_11 and self.taux_vm > 0:
            contributions_urssaf.append(ContributionType.VERSEMENT_MOBILITE)

        for ct in contributions_urssaf:
            ligne = self._calculer_ligne(ct, brut_mensuel)
            if ligne:
                lignes.append(ligne)

        # --- Chomage ---
        for ct in [ContributionType.ASSURANCE_CHOMAGE, ContributionType.AGS]:
            ligne = self._calculer_ligne(ct, brut_mensuel)
            if ligne:
                lignes.append(ligne)

        # --- Retraite complementaire ---
        retraite = [
            ContributionType.RETRAITE_COMPLEMENTAIRE_T1,
            ContributionType.CEG_T1,
            ContributionType.CET,
        ]
        if brut_mensuel > PASS_MENSUEL:
            retraite.extend([
                ContributionType.RETRAITE_COMPLEMENTAIRE_T2,
                ContributionType.CEG_T2,
            ])
        if est_cadre:
            retraite.append(ContributionType.APEC)

        for ct in retraite:
            ligne = self._calculer_ligne(ct, brut_mensuel)
            if ligne:
                lignes.append(ligne)

        # --- Prevoyance cadre ---
        if est_cadre:
            ligne = self._calculer_ligne(ContributionType.PREVOYANCE_CADRE, brut_mensuel)
            if ligne:
                lignes.append(ligne)

        # --- Formation / apprentissage ---
        for ct in [ContributionType.FORMATION_PROFESSIONNELLE,
                    ContributionType.TAXE_APPRENTISSAGE]:
            ligne = self._calculer_ligne(ct, brut_mensuel)
            if ligne:
                lignes.append(ligne)

        # PEEC
        if self.effectif >= SEUIL_EFFECTIF_20:
            ligne = self._calculer_ligne(ContributionType.PEEC, brut_mensuel)
            if ligne:
                lignes.append(ligne)

        # --- Totaux ---
        total_patronal = sum(l["montant_patronal"] for l in lignes)
        total_salarial = sum(l["montant_salarial"] for l in lignes)
        net_avant_ir = brut_mensuel - total_salarial
        cout_total_employeur = brut_mensuel + total_patronal

        return {
            "brut_mensuel": float(brut_mensuel),
            "lignes": lignes,
            "total_patronal": float(total_patronal),
            "total_salarial": float(total_salarial),
            "net_avant_impot": float(net_avant_ir),
            "cout_total_employeur": float(cout_total_employeur),
            "taux_charges_patronales": float(
                (total_patronal / brut_mensuel * 100) if brut_mensuel > 0 else 0
            ),
            "taux_charges_salariales": float(
                (total_salarial / brut_mensuel * 100) if brut_mensuel > 0 else 0
            ),
        }

    def _calculer_ligne(
        self, ct: ContributionType, brut_mensuel: Decimal,
    ) -> Optional[dict]:
        """Calcule une ligne de cotisation."""
        assiette = self.calculer_assiette(ct, brut_mensuel)
        taux_p = self.get_taux_attendu_patronal(ct, brut_mensuel) or Decimal("0")
        taux_s = self.get_taux_attendu_salarial(ct) or Decimal("0")
        montant_p = (assiette * taux_p).quantize(Decimal("0.01"), ROUND_HALF_UP)
        montant_s = (assiette * taux_s).quantize(Decimal("0.01"), ROUND_HALF_UP)

        if montant_p == 0 and montant_s == 0:
            return None

        return {
            "type": ct.value,
            "libelle": ct.value.replace("_", " ").title(),
            "assiette": float(assiette),
            "taux_patronal": float(taux_p),
            "taux_salarial": float(taux_s),
            "montant_patronal": montant_p,
            "montant_salarial": montant_s,
        }

    # =================================================================
    # VERIFICATION DE CONFORMITE
    # =================================================================

    def verifier_taux(
        self, type_cotisation: ContributionType, taux_constate: Decimal,
        salaire_brut: Decimal = Decimal("0"), est_patronal: bool = True,
    ) -> tuple[bool, Optional[Decimal]]:
        """Verifie si un taux est conforme. Retourne (conforme, taux_attendu)."""
        if est_patronal:
            taux_attendu = self.get_taux_attendu_patronal(type_cotisation, salaire_brut)
        else:
            taux_attendu = self.get_taux_attendu_salarial(type_cotisation)

        if taux_attendu is None:
            return True, None

        ecart = abs(taux_constate - taux_attendu)
        conforme = ecart <= TOLERANCE_TAUX
        return conforme, taux_attendu

    def verifier_plafonnement(
        self, type_cotisation: ContributionType,
        assiette_constatee: Decimal, brut_mensuel: Decimal,
    ) -> tuple[bool, Decimal]:
        """Verifie si le plafonnement est correctement applique."""
        assiette_attendue = self.calculer_assiette(type_cotisation, brut_mensuel)
        ecart = abs(assiette_constatee - assiette_attendue)
        conforme = ecart <= TOLERANCE_MONTANT
        return conforme, assiette_attendue

    # =================================================================
    # RGDU - REDUCTION GENERALE DEGRESSIVE UNIQUE 2026
    # Ref: CSS art. L241-13, decret 2025-xxx
    # =================================================================

    def calculer_rgdu(self, salaire_brut_annuel: Decimal) -> Decimal:
        """Calcule la RGDU (Reduction Generale Degressive Unique) 2026.

        Fusion de l'ancienne reduction Fillon avec les reductions
        maladie et allocations familiales en une seule reduction
        degressive. Seuil porte a 3 SMIC.

        Formule: C = (T / 0.6) * ((3 * SMIC * 1820.04h / remuneration) - 1)
        Le coefficient C est plafonne a T.
        """
        seuil = SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
        if salaire_brut_annuel >= seuil or salaire_brut_annuel <= 0:
            return Decimal("0")

        # Taux maximal selon effectif
        t_max = RGDU_TAUX_MAX_50_PLUS if self.effectif >= SEUIL_EFFECTIF_50 else RGDU_TAUX_MAX_MOINS_50

        # Coefficient de reduction
        coeff = (t_max / Decimal("0.6")) * ((seuil / salaire_brut_annuel) - 1)
        coeff = min(coeff, t_max)
        coeff = max(coeff, Decimal("0"))

        reduction = (salaire_brut_annuel * coeff).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return reduction

    def est_eligible_rgdu(self, salaire_brut_annuel: Decimal) -> bool:
        """Verifie si un salaire est eligible a la RGDU."""
        seuil = SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
        return Decimal("0") < salaire_brut_annuel < seuil

    def detail_rgdu(self, salaire_brut_annuel: Decimal) -> dict:
        """Retourne le detail du calcul RGDU."""
        seuil = SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
        t_max = RGDU_TAUX_MAX_50_PLUS if self.effectif >= SEUIL_EFFECTIF_50 else RGDU_TAUX_MAX_MOINS_50

        eligible = self.est_eligible_rgdu(salaire_brut_annuel)
        reduction = self.calculer_rgdu(salaire_brut_annuel)

        coeff = Decimal("0")
        if eligible and salaire_brut_annuel > 0:
            coeff = (t_max / Decimal("0.6")) * ((seuil / salaire_brut_annuel) - 1)
            coeff = min(coeff, t_max)
            coeff = max(coeff, Decimal("0"))

        return {
            "eligible": eligible,
            "salaire_brut_annuel": float(salaire_brut_annuel),
            "seuil_3_smic": float(seuil),
            "taux_max": float(t_max),
            "coefficient": float(coeff),
            "reduction_annuelle": float(reduction),
            "reduction_mensuelle": float((reduction / 12).quantize(Decimal("0.01"))),
            "effectif": self.effectif,
        }

    # =================================================================
    # TAXE SUR LES SALAIRES (employeurs non assujettis TVA)
    # Ref: CGI art. 231
    # =================================================================

    def calculer_taxe_salaires(self, brut_annuel: Decimal) -> dict:
        """Calcule la taxe sur les salaires avec les 3 tranches."""
        taux = TAUX_COTISATIONS_2026.get(ContributionType.TAXE_SUR_SALAIRES, {})
        s1 = taux.get("seuil_1", Decimal("8573"))
        s2 = taux.get("seuil_2", Decimal("17114"))
        t1 = taux.get("taux_normal", Decimal("0.0420"))
        t2 = taux.get("taux_majore_1", Decimal("0.0850"))
        t3 = taux.get("taux_majore_2", Decimal("0.1360"))

        montant_t1 = (min(brut_annuel, s1) * t1).quantize(Decimal("0.01"))
        montant_t2 = Decimal("0")
        montant_t3 = Decimal("0")

        if brut_annuel > s1:
            tranche_2 = min(brut_annuel, s2) - s1
            montant_t2 = (tranche_2 * t2).quantize(Decimal("0.01"))

        if brut_annuel > s2:
            tranche_3 = brut_annuel - s2
            montant_t3 = (tranche_3 * t3).quantize(Decimal("0.01"))

        total = montant_t1 + montant_t2 + montant_t3

        return {
            "tranche_1": {"seuil": float(s1), "taux": float(t1), "montant": float(montant_t1)},
            "tranche_2": {"seuil": float(s2), "taux": float(t2), "montant": float(montant_t2)},
            "tranche_3": {"taux": float(t3), "montant": float(montant_t3)},
            "total": float(total),
        }

    # =================================================================
    # ASSIETTE FISCALE / REVENU IMPOSABLE
    # =================================================================

    def calculer_net_imposable(
        self, brut_mensuel: Decimal, est_cadre: bool = False,
    ) -> dict:
        """Calcule le net imposable (assiette fiscale) du salarie.

        Net imposable = Brut - cotisations salariales obligatoires
                        + CSG non deductible + CRDS
                        - part salariale mutuelle obligatoire (deductible)
        """
        bulletin = self.calculer_bulletin_complet(brut_mensuel, est_cadre)

        # Cotisations salariales deductibles (hors CSG non deductible et CRDS)
        cot_salariales_deductibles = Decimal("0")
        csg_non_deductible = Decimal("0")
        crds = Decimal("0")

        for ligne in bulletin["lignes"]:
            ms = ligne["montant_salarial"]
            if ms == 0:
                continue
            if ligne["type"] == "csg_non_deductible":
                csg_non_deductible = ms
            elif ligne["type"] == "crds":
                crds = ms
            else:
                cot_salariales_deductibles += ms

        # Net imposable = brut - cot deductibles
        # (la CSG non deductible et CRDS ne sont pas deduites du net imposable)
        net_imposable = brut_mensuel - cot_salariales_deductibles
        net_a_payer = brut_mensuel - Decimal(str(bulletin["total_salarial"]))

        return {
            "brut": float(brut_mensuel),
            "cotisations_salariales_deductibles": float(cot_salariales_deductibles),
            "csg_non_deductible": float(csg_non_deductible),
            "crds": float(crds),
            "net_imposable": float(net_imposable),
            "net_a_payer_avant_ir": float(net_a_payer),
            "assiette_pas": float(net_imposable),  # Assiette prelevement a la source
        }
