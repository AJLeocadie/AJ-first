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


def _taux(ct: ContributionType, cle: str, defaut: Decimal = None) -> Decimal:
    """Recupere un taux depuis TAUX_COTISATIONS_2026, source unique de verite.

    Leve KeyError si le taux n'existe pas et aucun defaut n'est fourni,
    evitant les fallbacks hardcodes desynchronises.
    """
    data = TAUX_COTISATIONS_2026.get(ct)
    if data is None:
        if defaut is not None:
            return defaut
        raise KeyError(f"Pas de taux defini pour {ct.value}")
    val = data.get(cle)
    if val is not None:
        return val
    if defaut is not None:
        return defaut
    raise KeyError(f"Cle '{cle}' absente pour {ct.value}")


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
        # Plafond mensuel effectif (proratable pour temps partiel)
        self._pass_mensuel = PASS_MENSUEL
        self._smic_mensuel = SMIC_MENSUEL_BRUT

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
            seuil = self._smic_mensuel * _taux(ContributionType.MALADIE, "seuil_reduction_smic")
            if Decimal("0") < salaire_brut <= seuil:
                return _taux(ContributionType.MALADIE, "patronal_reduit")
            return taux["patronal"]

        # Allocations familiales (reduction si <= 3.5 SMIC)
        if type_cotisation == ContributionType.ALLOCATIONS_FAMILIALES:
            seuil = self._smic_mensuel * _taux(ContributionType.ALLOCATIONS_FAMILIALES, "seuil_reduction_smic")
            if Decimal("0") < salaire_brut <= seuil:
                return _taux(ContributionType.ALLOCATIONS_FAMILIALES, "patronal_reduit")
            return taux["patronal"]

        # FNAL : plafonne < 50, deplafonne >= 50
        if type_cotisation == ContributionType.FNAL:
            if self.effectif >= SEUIL_EFFECTIF_50:
                return _taux(ContributionType.FNAL, "patronal_50_plus")
            return _taux(ContributionType.FNAL, "patronal_moins_50")

        # Formation professionnelle
        if type_cotisation == ContributionType.FORMATION_PROFESSIONNELLE:
            if self.effectif >= SEUIL_EFFECTIF_11:
                return _taux(ContributionType.FORMATION_PROFESSIONNELLE, "patronal_11_plus")
            return _taux(ContributionType.FORMATION_PROFESSIONNELLE, "patronal_moins_11")

        # AT/MP : taux propre a l'entreprise
        if type_cotisation == ContributionType.ACCIDENT_TRAVAIL:
            return self.taux_at

        # Versement mobilite : taux selon commune, >= 11 salaries
        if type_cotisation == ContributionType.VERSEMENT_MOBILITE:
            if self.effectif >= _taux(ContributionType.VERSEMENT_MOBILITE, "seuil_effectif", Decimal("11")):
                return self.taux_vm
            return Decimal("0")

        # PEEC : >= 20 salaries
        if type_cotisation == ContributionType.PEEC:
            if self.effectif >= SEUIL_EFFECTIF_20:
                return _taux(ContributionType.PEEC, "patronal")
            return Decimal("0")

        # Taxe apprentissage
        if type_cotisation == ContributionType.TAXE_APPRENTISSAGE:
            return _taux(ContributionType.TAXE_APPRENTISSAGE, "patronal")

        # CSA (Contribution Solidarite Autonomie)
        if type_cotisation == ContributionType.CONTRIBUTION_SOLIDARITE_AUTONOMIE:
            return _taux(ContributionType.CONTRIBUTION_SOLIDARITE_AUTONOMIE, "patronal")

        # Dialogue social
        if type_cotisation == ContributionType.CONTRIBUTION_DIALOGUE_SOCIAL:
            return _taux(ContributionType.CONTRIBUTION_DIALOGUE_SOCIAL, "patronal")

        # Prevoyance cadre (minimum)
        if type_cotisation == ContributionType.PREVOYANCE_CADRE:
            return _taux(ContributionType.PREVOYANCE_CADRE, "patronal_minimum")

        # Forfait social
        if type_cotisation == ContributionType.FORFAIT_SOCIAL:
            return _taux(ContributionType.FORFAIT_SOCIAL, "taux_droit_commun")

        # Contribution supplementaire apprentissage
        if type_cotisation == ContributionType.CONTRIBUTION_SUPPLEMENTAIRE_APPRENTISSAGE:
            if self.effectif >= SEUIL_EFFECTIF_250:
                return _taux(ContributionType.CONTRIBUTION_SUPPLEMENTAIRE_APPRENTISSAGE, "patronal_250_plus")
            return Decimal("0")

        # CPF-CDD
        if type_cotisation == ContributionType.CONTRIBUTION_CPF_CDD:
            return _taux(ContributionType.CONTRIBUTION_CPF_CDD, "patronal")

        # Taxe sur les salaires
        if type_cotisation == ContributionType.TAXE_SUR_SALAIRES:
            return _taux(ContributionType.TAXE_SUR_SALAIRES, "taux_normal")

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
                return _taux(ContributionType.MALADIE_ALSACE_MOSELLE, "salarial")
            return Decimal("0")

        return taux.get("salarial", taux.get("taux"))

    # =================================================================
    # ASSIETTES DE COTISATIONS
    # =================================================================

    def calculer_assiette(
        self, type_cotisation: ContributionType,
        brut_mensuel: Decimal,
        prevoyance_patronale: Decimal = Decimal("0"),
    ) -> Decimal:
        """Calcule l'assiette de cotisation apres plafonnement.

        Assiettes possibles :
        - Totalite du salaire brut (deplafonnee)
        - Plafonnee au PASS mensuel (Tranche 1)
        - Plafonnee a 4 PASS (chomage, AGS)
        - Tranche 2 : entre 1 et 8 PASS
        - 98.25% du brut + prevoyance patronale (CSG/CRDS)

        Pour CSG/CRDS, prevoyance_patronale correspond aux cotisations
        patronales prevoyance/mutuelle ajoutees sans abattement (art. L136-1-1 CSS).
        """
        taux = TAUX_COTISATIONS_2026.get(type_cotisation, {})

        # CSG/CRDS : assiette = 98.25% du brut + prevoyance/mutuelle patronale (sans abattement)
        if "assiette_pct" in taux:
            return (brut_mensuel * taux["assiette_pct"] + prevoyance_patronale).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )

        # Cotisations plafonnees au PASS (Tranche 1)
        if "plafond" in taux and "plancher" not in taux:
            # Utiliser le PASS effectif (proratise pour temps partiel)
            plafond = self._pass_mensuel
            return min(brut_mensuel, plafond)

        # Cotisations plafonnees a un multiple du PASS
        if "plafond_multiple_pass" in taux and "plancher" not in taux:
            plafond = self._pass_mensuel * taux["plafond_multiple_pass"]
            return min(brut_mensuel, plafond)

        # Tranche 2 : entre PASS et X * PASS
        if "plancher" in taux:
            plancher = self._pass_mensuel
            plafond = self._pass_mensuel * taux["plafond_multiple_pass"]
            if brut_mensuel <= plancher:
                return Decimal("0")
            return min(brut_mensuel, plafond) - plancher

        # FNAL < 50 : plafonnee au PASS
        if type_cotisation == ContributionType.FNAL:
            if self.effectif < SEUIL_EFFECTIF_50:
                return min(brut_mensuel, self._pass_mensuel)
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

        # --- Prevoyance cadre (calculee en amont pour CSG/CRDS) ---
        prevoyance_patronale = Decimal("0")
        if est_cadre:
            taux_prev = _taux(ContributionType.PREVOYANCE_CADRE, "patronal_minimum")
            assiette_prev = min(brut_mensuel, self._pass_mensuel)
            prevoyance_patronale = (assiette_prev * taux_prev).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )

        # --- CSG/CRDS (assiette inclut prevoyance/mutuelle patronale) ---
        for ct in [ContributionType.CSG_DEDUCTIBLE,
                    ContributionType.CSG_NON_DEDUCTIBLE,
                    ContributionType.CRDS]:
            ligne = self._calculer_ligne(ct, brut_mensuel, prevoyance_patronale)
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
        if brut_mensuel > self._pass_mensuel:
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
        prevoyance_patronale: Decimal = Decimal("0"),
    ) -> Optional[dict]:
        """Calcule une ligne de cotisation."""
        assiette = self.calculer_assiette(ct, brut_mensuel, prevoyance_patronale)
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
        """Verifie si un taux est conforme. Retourne (conforme, taux_attendu).

        Pour les cotisations a taux reduit conditionnel (maladie, AF),
        accepte a la fois le taux standard (affiche sur bulletin de paie)
        et le taux reduit (applique en DSN apres reduction generale).
        """
        if est_patronal:
            taux_attendu = self.get_taux_attendu_patronal(type_cotisation, salaire_brut)
        else:
            taux_attendu = self.get_taux_attendu_salarial(type_cotisation)

        if taux_attendu is None:
            return True, None

        ecart = abs(taux_constate - taux_attendu)
        if ecart <= TOLERANCE_TAUX:
            return True, taux_attendu

        # Pour maladie et AF patronal, accepter aussi le taux standard
        # (les bulletins de paie affichent le taux plein, la reduction
        # etant appliquee separement via la reduction generale / RGDU)
        if est_patronal and type_cotisation in (
            ContributionType.MALADIE,
            ContributionType.ALLOCATIONS_FAMILIALES,
        ):
            taux_data = TAUX_COTISATIONS_2026.get(type_cotisation, {})
            taux_standard = taux_data.get("patronal")
            taux_reduit = taux_data.get("patronal_reduit")
            if taux_standard is not None and abs(taux_constate - taux_standard) <= TOLERANCE_TAUX:
                return True, taux_standard
            if taux_reduit is not None and abs(taux_constate - taux_reduit) <= TOLERANCE_TAUX:
                return True, taux_reduit

        return False, taux_attendu

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

        Formule: C = (T / 2.0) * ((3 * SMIC_annuel / remuneration) - 1)
        Le diviseur 2.0 = seuil_multiple - 1 = 3.0 - 1.0
        Le coefficient C est plafonne a T.
        """
        seuil = SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
        if salaire_brut_annuel >= seuil or salaire_brut_annuel <= 0:
            return Decimal("0")

        # Taux maximal selon effectif
        t_max = RGDU_TAUX_MAX_50_PLUS if self.effectif >= SEUIL_EFFECTIF_50 else RGDU_TAUX_MAX_MOINS_50

        # Coefficient de reduction
        # Diviseur = seuil_multiple - 1 (pour RGDU 2026: 3.0 - 1.0 = 2.0)
        diviseur = RGDU_SEUIL_SMIC_MULTIPLE - 1
        coeff = (t_max / diviseur) * ((seuil / salaire_brut_annuel) - 1)
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
            diviseur = RGDU_SEUIL_SMIC_MULTIPLE - 1
            coeff = (t_max / diviseur) * ((seuil / salaire_brut_annuel) - 1)
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
        ct = ContributionType.TAXE_SUR_SALAIRES
        s1 = _taux(ct, "seuil_1")
        s2 = _taux(ct, "seuil_2")
        t1 = _taux(ct, "taux_normal")
        t2 = _taux(ct, "taux_majore_1")
        t3 = _taux(ct, "taux_majore_2")

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

    # =================================================================
    # TEMPS PARTIEL - PRORATISATION
    # Ref: CSS art. L241-13, Circ. DSS/5B n°2012/60
    # =================================================================

    def calculer_bulletin_temps_partiel(
        self, brut_mensuel: Decimal, heures_mensuelles: Decimal,
        est_cadre: bool = False,
    ) -> dict:
        """Calcule un bulletin avec proratisation temps partiel.

        Le PASS et les seuils SMIC sont proratas au rapport
        heures_mensuelles / 151.67h. Cela affecte :
        - Le plafonnement (PASS) pour vieillesse plafonnee, prevoyance
        - Les seuils de reduction (maladie, AF, RGDU)
        - Les tranches AGIRC-ARRCO
        """
        if heures_mensuelles <= 0 or heures_mensuelles >= HEURES_MENSUELLES_LEGALES:
            return self.calculer_bulletin_complet(brut_mensuel, est_cadre)

        ratio = heures_mensuelles / HEURES_MENSUELLES_LEGALES
        pass_proratise = (PASS_MENSUEL * ratio).quantize(Decimal("0.01"), ROUND_HALF_UP)
        smic_proratise = (SMIC_MENSUEL_BRUT * ratio).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # Appliquer les plafonds proratas pour le calcul
        saved_pass = self._pass_mensuel
        saved_smic = self._smic_mensuel
        try:
            self._pass_mensuel = pass_proratise
            self._smic_mensuel = smic_proratise
            bulletin = self.calculer_bulletin_complet(brut_mensuel, est_cadre)
        finally:
            self._pass_mensuel = saved_pass
            self._smic_mensuel = saved_smic

        bulletin["temps_partiel"] = {
            "heures_mensuelles": float(heures_mensuelles),
            "heures_legales": float(HEURES_MENSUELLES_LEGALES),
            "ratio": float(ratio),
            "pass_mensuel_proratise": float(pass_proratise),
            "smic_mensuel_proratise": float(smic_proratise),
        }
        return bulletin

    def calculer_rgdu_temps_partiel(
        self, salaire_brut_annuel: Decimal, heures_annuelles: Decimal,
    ) -> Decimal:
        """Calcule la RGDU pour un salarie a temps partiel.

        Le SMIC de reference est proratise :
        SMIC proratis = SMIC horaire * heures annuelles reelles.
        """
        if heures_annuelles <= 0 or salaire_brut_annuel <= 0:
            return Decimal("0")

        smic_horaire = SMIC_ANNUEL_BRUT / (HEURES_MENSUELLES_LEGALES * 12)
        smic_proratise = smic_horaire * heures_annuelles
        seuil = smic_proratise * RGDU_SEUIL_SMIC_MULTIPLE

        if salaire_brut_annuel >= seuil:
            return Decimal("0")

        t_max = RGDU_TAUX_MAX_50_PLUS if self.effectif >= SEUIL_EFFECTIF_50 else RGDU_TAUX_MAX_MOINS_50
        diviseur = RGDU_SEUIL_SMIC_MULTIPLE - 1
        coeff = (t_max / diviseur) * ((seuil / salaire_brut_annuel) - 1)
        coeff = min(coeff, t_max)
        coeff = max(coeff, Decimal("0"))

        return (salaire_brut_annuel * coeff).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # =================================================================
    # EXONERATIONS SPECIFIQUES
    # Ref: CSS art. L241-17 (ACRE), L6243-2 CT (apprentis)
    # =================================================================

    def calculer_exoneration_acre(
        self, brut_mensuel: Decimal,
    ) -> dict:
        """Calcule l'exoneration ACRE (Aide a la Creation/Reprise d'Entreprise).

        Depuis le Decret 2019-1215, l'ACRE pour salaries = exoneration de 50%
        des cotisations patronales SS pendant 12 mois, si remuneration < 75% PASS.
        Ref: CSS art. L131-6-4 / L241-17, Decret 2019-1215.
        """
        # Seuil d'eligibilite : 75% du PASS mensuel
        seuil_75_pass = self._pass_mensuel * Decimal("0.75")

        if brut_mensuel <= 0:
            return {"eligible": False, "exoneration_mensuelle": 0.0, "motif": "brut nul"}

        if brut_mensuel > seuil_75_pass:
            return {
                "eligible": False,
                "exoneration_mensuelle": 0.0,
                "motif": f"Salaire > 75% PASS ({float(seuil_75_pass):.2f} EUR)",
            }

        # Cotisations exonerables : maladie, vieillesse, AF, AT/MP, CSA
        cotisations_exonerables = [
            ContributionType.MALADIE,
            ContributionType.VIEILLESSE_PLAFONNEE,
            ContributionType.VIEILLESSE_DEPLAFONNEE,
            ContributionType.ALLOCATIONS_FAMILIALES,
            ContributionType.ACCIDENT_TRAVAIL,
            ContributionType.CONTRIBUTION_SOLIDARITE_AUTONOMIE,
        ]
        total_exonerable = Decimal("0")
        for ct in cotisations_exonerables:
            total_exonerable += self.calculer_montant_patronal(ct, brut_mensuel)

        # Exoneration = 50% des cotisations patronales eligibles
        taux_exo = Decimal("0.50")
        exoneration = (total_exonerable * taux_exo).quantize(Decimal("0.01"), ROUND_HALF_UP)

        return {
            "eligible": True,
            "exoneration_mensuelle": float(exoneration),
            "taux_exoneration": float(taux_exo),
            "seuil_75_pass": float(seuil_75_pass),
            "cotisations_exonerables": float(total_exonerable),
            "ref": "CSS art. L131-6-4 / L241-17, Decret 2019-1215",
        }

    def calculer_exoneration_apprenti(
        self, brut_mensuel: Decimal, annee_apprentissage: int = 1,
    ) -> dict:
        """Calcule les exonerations pour un contrat d'apprentissage.

        Depuis 2019, les apprentis beneficient de l'exoneration de
        cotisations salariales sur la part <= 79% du SMIC.
        Les cotisations patronales beneficient de la reduction
        generale (RGDU) de droit commun.
        """
        seuil_79_smic = self._smic_mensuel * Decimal("0.79")

        # Exoneration salariale : pas de cotisations salariales sur
        # la tranche <= 79% du SMIC
        assiette_exoneree = min(brut_mensuel, seuil_79_smic)

        # Cotisations salariales sur la tranche exoneree
        cotisations_salariales_ss = [
            ContributionType.VIEILLESSE_PLAFONNEE,
            ContributionType.VIEILLESSE_DEPLAFONNEE,
            ContributionType.RETRAITE_COMPLEMENTAIRE_T1,
            ContributionType.CEG_T1,
            ContributionType.CET,
        ]
        exo_salariale = Decimal("0")
        for ct in cotisations_salariales_ss:
            taux_s = self.get_taux_attendu_salarial(ct) or Decimal("0")
            exo_salariale += (assiette_exoneree * taux_s).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # Pas de CSG/CRDS sur la part <= 79% SMIC
        taux_csg_crds = Decimal("0.097")  # 6.8% + 2.4% + 0.5% CRDS = 9.70%
        exo_csg_crds = (assiette_exoneree * Decimal("0.9825") * taux_csg_crds).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        # RGDU patronale (reduction generale de droit commun)
        salaire_annuel = brut_mensuel * 12
        rgdu = self.calculer_rgdu(salaire_annuel)
        rgdu_mensuelle = (rgdu / 12).quantize(Decimal("0.01"), ROUND_HALF_UP)

        return {
            "eligible": True,
            "annee_apprentissage": annee_apprentissage,
            "seuil_79_smic": float(seuil_79_smic),
            "exoneration_salariale_mensuelle": float(exo_salariale + exo_csg_crds),
            "exoneration_salariale_detail": {
                "cotisations_ss": float(exo_salariale),
                "csg_crds": float(exo_csg_crds),
            },
            "rgdu_patronale_mensuelle": float(rgdu_mensuelle),
            "ref": "CT art. L6243-2, CSS art. L241-13",
        }

    # =================================================================
    # CONVENTIONS COLLECTIVES
    # Prevoyance et complementaire selon CCN
    # =================================================================

    # Table des principales CCN et leurs taux prevoyance/mutuelle
    CCN_PREVOYANCE = {
        "syntec": {
            "idcc": "1486",
            "nom": "SYNTEC (Bureaux etudes techniques)",
            "prevoyance_cadre_patronal": Decimal("0.015"),    # 1.50% T1
            "prevoyance_non_cadre_patronal": Decimal("0.006"),  # 0.60%
            "mutuelle_patronal_min": Decimal("0.50"),  # 50% minimum
        },
        "metallurgie": {
            "idcc": "3248",
            "nom": "Metallurgie",
            "prevoyance_cadre_patronal": Decimal("0.015"),
            "prevoyance_non_cadre_patronal": Decimal("0.010"),  # 1.00%
            "mutuelle_patronal_min": Decimal("0.50"),
        },
        "commerce": {
            "idcc": "2216",
            "nom": "Commerce de detail et de gros",
            "prevoyance_cadre_patronal": Decimal("0.015"),
            "prevoyance_non_cadre_patronal": Decimal("0.005"),  # 0.50%
            "mutuelle_patronal_min": Decimal("0.50"),
        },
        "batiment": {
            "idcc": "1597",
            "nom": "Batiment ouvriers (jusqu a 10 salaries)",
            "prevoyance_cadre_patronal": Decimal("0.015"),
            "prevoyance_non_cadre_patronal": Decimal("0.0175"),  # 1.75% (conge intemperies inclus)
            "mutuelle_patronal_min": Decimal("0.50"),
        },
        "restauration": {
            "idcc": "1979",
            "nom": "Hotels cafes restaurants (HCR)",
            "prevoyance_cadre_patronal": Decimal("0.015"),
            "prevoyance_non_cadre_patronal": Decimal("0.008"),  # 0.80%
            "mutuelle_patronal_min": Decimal("0.50"),
        },
        "transport": {
            "idcc": "0016",
            "nom": "Transports routiers",
            "prevoyance_cadre_patronal": Decimal("0.015"),
            "prevoyance_non_cadre_patronal": Decimal("0.012"),  # 1.20%
            "mutuelle_patronal_min": Decimal("0.50"),
        },
        "proprete": {
            "idcc": "3043",
            "nom": "Entreprises de proprete",
            "prevoyance_cadre_patronal": Decimal("0.015"),
            "prevoyance_non_cadre_patronal": Decimal("0.010"),
            "mutuelle_patronal_min": Decimal("0.50"),
        },
        "pharmacie": {
            "idcc": "1996",
            "nom": "Pharmacie d officine",
            "prevoyance_cadre_patronal": Decimal("0.015"),
            "prevoyance_non_cadre_patronal": Decimal("0.009"),  # 0.90%
            "mutuelle_patronal_min": Decimal("0.50"),
        },
    }

    def get_prevoyance_ccn(
        self, ccn_code: str, est_cadre: bool = False,
    ) -> dict:
        """Retourne les taux de prevoyance selon la convention collective.

        Si la CCN n est pas reconnue, retourne les minimums legaux
        (ANI 2013 / ANI 2016).
        """
        ccn = self.CCN_PREVOYANCE.get(ccn_code.lower())

        if ccn:
            taux_prev = ccn["prevoyance_cadre_patronal"] if est_cadre else ccn["prevoyance_non_cadre_patronal"]
            return {
                "ccn_connue": True,
                "idcc": ccn["idcc"],
                "nom_ccn": ccn["nom"],
                "taux_prevoyance_patronal": float(taux_prev),
                "mutuelle_part_employeur_min_pct": float(ccn["mutuelle_patronal_min"]) * 100,
                "est_cadre": est_cadre,
            }

        # Minimum legal : ANI 2013 (prevoyance cadre 1.50%) / ANI 2016 (mutuelle 50%)
        return {
            "ccn_connue": False,
            "idcc": None,
            "nom_ccn": "Convention non identifiee - minimums legaux appliques",
            "taux_prevoyance_patronal": float(Decimal("0.015") if est_cadre else Decimal("0")),
            "mutuelle_part_employeur_min_pct": 50.0,
            "est_cadre": est_cadre,
            "note": "Prevoyance non-cadre : pas de minimum legal general. Verifier la CCN applicable.",
        }

    def identifier_ccn(self, texte_ccn: str) -> Optional[str]:
        """Tente d identifier une CCN a partir d un texte (nom, IDCC, mots-cles).

        Retourne le code interne (syntec, metallurgie, etc.) ou None.
        """
        texte = texte_ccn.lower()

        ccn_keywords = {
            "syntec": ["syntec", "bureaux d etudes", "1486", "ingenierie", "conseil"],
            "metallurgie": ["metallurgie", "3248", "uimm", "forge", "fonderie"],
            "commerce": ["commerce de detail", "commerce de gros", "2216", "grande distribution"],
            "batiment": ["batiment", "btp", "1597", "travaux publics", "construction"],
            "restauration": ["hotel", "restaurant", "hcr", "1979", "cafe", "debit de boisson"],
            "transport": ["transport routier", "0016", "conducteur", "logistique"],
            "proprete": ["proprete", "nettoyage", "3043"],
            "pharmacie": ["pharmacie", "officine", "1996"],
        }

        best_match = None
        best_score = 0
        for code, keywords in ccn_keywords.items():
            score = sum(1 for kw in keywords if kw in texte)
            if score > best_score:
                best_score = score
                best_match = code

        return best_match if best_score >= 1 else None

    # =================================================================
    # REGIMES SPECIAUX - INTEGRATION AU MOTEUR DE CALCUL
    # Ref: CSS art. L711-1, L741-1
    # =================================================================

    def calculer_bulletin_regime_special(
        self, brut_mensuel: Decimal, regime: str,
        est_cadre: bool = False,
    ) -> dict:
        """Calcule un bulletin en appliquant les specificites d'un regime special.

        Regimes supportes : msa, alsace_moselle, crpcen.
        Pour les regimes en extinction (mines, sncf, ratp), retourne
        le bulletin regime general avec un avertissement.
        """
        from urssaf_analyzer.rules.regimes_speciaux import (
            get_regime, calculer_supplement_alsace_moselle,
            calculer_cotisations_msa,
        )

        regime_data = get_regime(regime)
        if not regime_data:
            bulletin = self.calculer_bulletin_complet(brut_mensuel, est_cadre)
            bulletin["regime_special"] = {
                "code": regime,
                "applique": False,
                "motif": f"Regime '{regime}' non reconnu, regime general applique.",
            }
            return bulletin

        regimes_en_extinction = {"mines", "sncf", "ratp", "ieg", "bdf"}
        if regime in regimes_en_extinction:
            bulletin = self.calculer_bulletin_complet(brut_mensuel, est_cadre)
            bulletin["regime_special"] = {
                "code": regime,
                "nom": regime_data["nom"],
                "applique": False,
                "motif": (
                    f"Regime '{regime_data['nom']}' en extinction - "
                    f"les nouveaux salaries relevent du regime general."
                ),
                "specificites": regime_data.get("specificites", []),
            }
            return bulletin

        # Alsace-Moselle : bulletin regime general + supplement maladie
        if regime == "alsace_moselle":
            saved = self.est_alsace_moselle
            try:
                self.est_alsace_moselle = True
                bulletin = self.calculer_bulletin_complet(brut_mensuel, est_cadre)
            finally:
                self.est_alsace_moselle = saved
            supplement = calculer_supplement_alsace_moselle(brut_mensuel)
            bulletin["regime_special"] = {
                "code": "alsace_moselle",
                "nom": regime_data["nom"],
                "applique": True,
                "supplement_maladie": supplement,
            }
            return bulletin

        # MSA : cotisations specifiques
        if regime == "msa":
            bulletin_rg = self.calculer_bulletin_complet(brut_mensuel, est_cadre)
            cotisations_msa = calculer_cotisations_msa(brut_mensuel, self.effectif)
            bulletin_rg["regime_special"] = {
                "code": "msa",
                "nom": regime_data["nom"],
                "applique": True,
                "cotisations_specifiques": cotisations_msa,
                "specificites": regime_data.get("specificites", []),
            }
            return bulletin_rg

        # CRPCEN : cotisations supplementaires
        if regime == "crpcen":
            bulletin = self.calculer_bulletin_complet(brut_mensuel, est_cadre)
            cots_crpcen = regime_data.get("cotisations", {})
            supplements = []
            for nom, params in cots_crpcen.items():
                pat = params.get("patronal", Decimal("0"))
                sal = params.get("salarial", Decimal("0"))
                montant_pat = (brut_mensuel * pat).quantize(Decimal("0.01"), ROUND_HALF_UP)
                montant_sal = (brut_mensuel * sal).quantize(Decimal("0.01"), ROUND_HALF_UP)
                supplements.append({
                    "cotisation": nom,
                    "taux_patronal": float(pat),
                    "taux_salarial": float(sal),
                    "montant_patronal": float(montant_pat),
                    "montant_salarial": float(montant_sal),
                })
            bulletin["regime_special"] = {
                "code": "crpcen",
                "nom": regime_data["nom"],
                "applique": True,
                "cotisations_supplementaires": supplements,
                "specificites": regime_data.get("specificites", []),
            }
            return bulletin

        # Fallback: regime general
        bulletin = self.calculer_bulletin_complet(brut_mensuel, est_cadre)
        bulletin["regime_special"] = {
            "code": regime,
            "nom": regime_data.get("nom", regime),
            "applique": False,
            "motif": "Regime non integre au moteur de calcul.",
        }
        return bulletin

    def detecter_et_appliquer_regime(
        self, brut_mensuel: Decimal,
        code_naf: str = "",
        departement: str = "",
        idcc: str = "",
        texte: str = "",
        est_cadre: bool = False,
    ) -> dict:
        """Detecte automatiquement les regimes applicables et calcule le bulletin."""
        from urssaf_analyzer.rules.regimes_speciaux import detecter_regime

        regimes = detecter_regime(code_naf, departement, idcc, texte)

        if not regimes:
            bulletin = self.calculer_bulletin_complet(brut_mensuel, est_cadre)
            bulletin["regimes_detectes"] = []
            return bulletin

        # Appliquer le regime principal (le premier detecte)
        regime_principal = regimes[0]
        bulletin = self.calculer_bulletin_regime_special(
            brut_mensuel, regime_principal, est_cadre
        )
        bulletin["regimes_detectes"] = regimes
        return bulletin
