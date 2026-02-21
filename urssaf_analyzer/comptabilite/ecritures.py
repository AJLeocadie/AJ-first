"""Moteur d'ecritures comptables.

Genere automatiquement les ecritures a partir des pieces comptables
detectees par le module OCR.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional

from urssaf_analyzer.comptabilite.plan_comptable import (
    PlanComptable, REGLES_AFFECTATION, determiner_compte_charge,
)


class TypeJournal(str, Enum):
    ACHATS = "AC"
    VENTES = "VE"
    BANQUE = "BQ"
    OPERATIONS_DIVERSES = "OD"
    PAIE = "PA"
    A_NOUVEAU = "AN"


@dataclass
class LigneEcriture:
    compte: str
    libelle: str
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")
    lettrage: str = ""
    piece_ref: str = ""

    @property
    def solde(self) -> Decimal:
        return self.debit - self.credit


@dataclass
class Ecriture:
    id: str = ""
    journal: TypeJournal = TypeJournal.OPERATIONS_DIVERSES
    date_ecriture: date = None
    date_piece: date = None
    numero_piece: str = ""
    libelle: str = ""
    lignes: list[LigneEcriture] = field(default_factory=list)
    validee: bool = False
    date_validation: Optional[datetime] = None

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.date_ecriture is None:
            self.date_ecriture = date.today()

    @property
    def est_equilibree(self) -> bool:
        total_debit = sum(l.debit for l in self.lignes)
        total_credit = sum(l.credit for l in self.lignes)
        return abs(total_debit - total_credit) < Decimal("0.01")

    @property
    def total_debit(self) -> Decimal:
        return sum(l.debit for l in self.lignes)

    @property
    def total_credit(self) -> Decimal:
        return sum(l.credit for l in self.lignes)


class MoteurEcritures:
    """Genere les ecritures comptables a partir des pieces detectees."""

    def __init__(self, plan_comptable: PlanComptable = None):
        self.plan = plan_comptable or PlanComptable()
        self.ecritures: list[Ecriture] = []

    def generer_ecriture_facture(
        self,
        type_doc: str,
        date_piece: date,
        numero_piece: str,
        montant_ht: Decimal,
        montant_tva: Decimal,
        montant_ttc: Decimal,
        nom_tiers: str = "",
        lignes_detail: list[dict] = None,
        libelle: str = "",
    ) -> Ecriture:
        """Genere l'ecriture pour une facture d'achat ou de vente."""
        regle = REGLES_AFFECTATION.get(type_doc, REGLES_AFFECTATION["facture_achat"])
        est_vente = type_doc in ("facture_vente", "avoir_vente")
        est_avoir = type_doc in ("avoir_achat", "avoir_vente")

        journal = TypeJournal.VENTES if est_vente else TypeJournal.ACHATS

        # Compte tiers (auxiliaire si nom connu)
        if nom_tiers:
            compte_tiers = self.plan.get_ou_creer_compte_tiers(nom_tiers, est_client=est_vente)
        else:
            compte_tiers = regle["compte_tiers"]

        ecriture = Ecriture(
            journal=journal,
            date_ecriture=date_piece,
            date_piece=date_piece,
            numero_piece=numero_piece,
            libelle=libelle or f"{'Avoir' if est_avoir else 'Facture'} {nom_tiers or numero_piece}",
        )

        ht = Decimal(str(montant_ht)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tva = Decimal(str(montant_tva)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ttc = Decimal(str(montant_ttc)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Assurer la coherence TTC = HT + TVA
        if ttc == Decimal("0.00") and ht > 0:
            ttc = ht + tva

        if est_vente and not est_avoir:
            # Facture de vente : debit client, credit produit + TVA collectee
            ecriture.lignes.append(LigneEcriture(
                compte=compte_tiers, libelle=ecriture.libelle,
                debit=ttc, piece_ref=numero_piece,
            ))
            self._ajouter_lignes_produits(ecriture, lignes_detail, type_doc, ht, numero_piece)
            if tva > 0:
                ecriture.lignes.append(LigneEcriture(
                    compte=regle["compte_tva"], libelle=f"TVA collectee {numero_piece}",
                    credit=tva, piece_ref=numero_piece,
                ))
        elif est_vente and est_avoir:
            # Avoir de vente : credit client, debit produit + TVA
            ecriture.lignes.append(LigneEcriture(
                compte=compte_tiers, libelle=ecriture.libelle,
                credit=ttc, piece_ref=numero_piece,
            ))
            self._ajouter_lignes_produits(ecriture, lignes_detail, type_doc, ht, numero_piece, sens_inverse=True)
            if tva > 0:
                ecriture.lignes.append(LigneEcriture(
                    compte=regle["compte_tva"], libelle=f"TVA collectee (avoir) {numero_piece}",
                    debit=tva, piece_ref=numero_piece,
                ))
        elif not est_vente and not est_avoir:
            # Facture d'achat : credit fournisseur, debit charge + TVA deductible
            ecriture.lignes.append(LigneEcriture(
                compte=compte_tiers, libelle=ecriture.libelle,
                credit=ttc, piece_ref=numero_piece,
            ))
            self._ajouter_lignes_charges(ecriture, lignes_detail, type_doc, ht, numero_piece)
            if tva > 0:
                ecriture.lignes.append(LigneEcriture(
                    compte=regle["compte_tva"], libelle=f"TVA deductible {numero_piece}",
                    debit=tva, piece_ref=numero_piece,
                ))
        else:
            # Avoir d'achat : debit fournisseur, credit charge + TVA
            ecriture.lignes.append(LigneEcriture(
                compte=compte_tiers, libelle=ecriture.libelle,
                debit=ttc, piece_ref=numero_piece,
            ))
            self._ajouter_lignes_charges(ecriture, lignes_detail, type_doc, ht, numero_piece, sens_inverse=True)
            if tva > 0:
                ecriture.lignes.append(LigneEcriture(
                    compte=regle["compte_tva"], libelle=f"TVA deductible (avoir) {numero_piece}",
                    credit=tva, piece_ref=numero_piece,
                ))

        self.ecritures.append(ecriture)
        return ecriture

    def _ajouter_lignes_charges(
        self, ecriture: Ecriture, lignes_detail: list[dict],
        type_doc: str, montant_ht_total: Decimal, numero_piece: str,
        sens_inverse: bool = False,
    ):
        if lignes_detail:
            total_lignes = Decimal("0.00")
            for i, ligne in enumerate(lignes_detail):
                montant = Decimal(str(ligne.get("montant_ht", 0))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if montant == 0:
                    continue
                compte = determiner_compte_charge(ligne.get("description", ""), type_doc)
                le = LigneEcriture(
                    compte=compte,
                    libelle=ligne.get("description", f"Ligne {i+1}"),
                    piece_ref=numero_piece,
                )
                if sens_inverse:
                    le.credit = montant
                else:
                    le.debit = montant
                ecriture.lignes.append(le)
                total_lignes += montant
            # Ecart d'arrondi
            ecart = montant_ht_total - total_lignes
            if abs(ecart) >= Decimal("0.01"):
                regle = REGLES_AFFECTATION.get(type_doc, {})
                le = LigneEcriture(
                    compte=regle.get("compte_defaut", "471000"),
                    libelle="Ecart d'arrondi",
                    piece_ref=numero_piece,
                )
                if sens_inverse:
                    le.credit = ecart
                else:
                    le.debit = ecart
                ecriture.lignes.append(le)
        else:
            regle = REGLES_AFFECTATION.get(type_doc, {})
            le = LigneEcriture(
                compte=regle.get("compte_defaut", "607000"),
                libelle=ecriture.libelle,
                piece_ref=numero_piece,
            )
            if sens_inverse:
                le.credit = montant_ht_total
            else:
                le.debit = montant_ht_total
            ecriture.lignes.append(le)

    def _ajouter_lignes_produits(
        self, ecriture: Ecriture, lignes_detail: list[dict],
        type_doc: str, montant_ht_total: Decimal, numero_piece: str,
        sens_inverse: bool = False,
    ):
        if lignes_detail:
            total_lignes = Decimal("0.00")
            for i, ligne in enumerate(lignes_detail):
                montant = Decimal(str(ligne.get("montant_ht", 0))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if montant == 0:
                    continue
                compte = determiner_compte_charge(ligne.get("description", ""), type_doc)
                le = LigneEcriture(
                    compte=compte,
                    libelle=ligne.get("description", f"Ligne {i+1}"),
                    piece_ref=numero_piece,
                )
                if sens_inverse:
                    le.debit = montant
                else:
                    le.credit = montant
                ecriture.lignes.append(le)
                total_lignes += montant
            ecart = montant_ht_total - total_lignes
            if abs(ecart) >= Decimal("0.01"):
                regle = REGLES_AFFECTATION.get(type_doc, {})
                le = LigneEcriture(
                    compte=regle.get("compte_defaut", "707000"),
                    libelle="Ecart d'arrondi",
                    piece_ref=numero_piece,
                )
                if sens_inverse:
                    le.debit = ecart
                else:
                    le.credit = ecart
                ecriture.lignes.append(le)
        else:
            regle = REGLES_AFFECTATION.get(type_doc, {})
            le = LigneEcriture(
                compte=regle.get("compte_defaut", "707000"),
                libelle=ecriture.libelle,
                piece_ref=numero_piece,
            )
            if sens_inverse:
                le.debit = montant_ht_total
            else:
                le.credit = montant_ht_total
            ecriture.lignes.append(le)

    def generer_ecriture_paie(
        self,
        date_piece: date,
        nom_salarie: str,
        salaire_brut: Decimal,
        cotisations_salariales: Decimal,
        cotisations_patronales_urssaf: Decimal,
        cotisations_patronales_retraite: Decimal = Decimal("0"),
        net_a_payer: Decimal = Decimal("0"),
        numero_piece: str = "",
    ) -> Ecriture:
        """Genere l'ecriture de paie."""
        brut = Decimal(str(salaire_brut)).quantize(Decimal("0.01"))
        cot_sal = Decimal(str(cotisations_salariales)).quantize(Decimal("0.01"))
        cot_urssaf = Decimal(str(cotisations_patronales_urssaf)).quantize(Decimal("0.01"))
        cot_retraite = Decimal(str(cotisations_patronales_retraite)).quantize(Decimal("0.01"))
        net = Decimal(str(net_a_payer)).quantize(Decimal("0.01"))

        if net == 0:
            net = brut - cot_sal

        ecriture = Ecriture(
            journal=TypeJournal.PAIE,
            date_ecriture=date_piece,
            date_piece=date_piece,
            numero_piece=numero_piece or f"PAIE-{date_piece.strftime('%Y%m')}",
            libelle=f"Paie {nom_salarie} {date_piece.strftime('%m/%Y')}",
        )

        # Debit salaire brut
        ecriture.lignes.append(LigneEcriture(
            compte="641100", libelle=f"Salaire brut {nom_salarie}",
            debit=brut, piece_ref=ecriture.numero_piece,
        ))
        # Debit charges patronales URSSAF
        if cot_urssaf > 0:
            ecriture.lignes.append(LigneEcriture(
                compte="645100", libelle=f"Cotisations URSSAF patronales {nom_salarie}",
                debit=cot_urssaf, piece_ref=ecriture.numero_piece,
            ))
        # Debit charges patronales retraite
        if cot_retraite > 0:
            ecriture.lignes.append(LigneEcriture(
                compte="645300", libelle=f"Cotisations retraite patronales {nom_salarie}",
                debit=cot_retraite, piece_ref=ecriture.numero_piece,
            ))
        # Credit net a payer (salarie)
        ecriture.lignes.append(LigneEcriture(
            compte="421000", libelle=f"Net a payer {nom_salarie}",
            credit=net, piece_ref=ecriture.numero_piece,
        ))
        # Credit URSSAF (cotisations salariales + patronales)
        ecriture.lignes.append(LigneEcriture(
            compte="431000", libelle=f"URSSAF {nom_salarie}",
            credit=cot_sal + cot_urssaf, piece_ref=ecriture.numero_piece,
        ))
        # Credit retraite
        if cot_retraite > 0:
            ecriture.lignes.append(LigneEcriture(
                compte="437100", libelle=f"Retraite {nom_salarie}",
                credit=cot_retraite, piece_ref=ecriture.numero_piece,
            ))

        self.ecritures.append(ecriture)
        return ecriture

    def generer_ecriture_reglement(
        self,
        date_reglement: date,
        montant: Decimal,
        compte_tiers: str,
        libelle: str = "",
        compte_banque: str = "512000",
        numero_piece: str = "",
    ) -> Ecriture:
        """Genere l'ecriture de reglement (paiement fournisseur ou encaissement client)."""
        mnt = Decimal(str(montant)).quantize(Decimal("0.01"))
        est_client = compte_tiers.startswith("411")

        ecriture = Ecriture(
            journal=TypeJournal.BANQUE,
            date_ecriture=date_reglement,
            date_piece=date_reglement,
            numero_piece=numero_piece,
            libelle=libelle or f"Reglement {compte_tiers}",
        )

        if est_client:
            # Encaissement : debit banque, credit client
            ecriture.lignes.append(LigneEcriture(
                compte=compte_banque, libelle=libelle, debit=mnt,
                piece_ref=numero_piece,
            ))
            ecriture.lignes.append(LigneEcriture(
                compte=compte_tiers, libelle=libelle, credit=mnt,
                piece_ref=numero_piece,
            ))
        else:
            # Paiement : credit banque, debit fournisseur
            ecriture.lignes.append(LigneEcriture(
                compte=compte_tiers, libelle=libelle, debit=mnt,
                piece_ref=numero_piece,
            ))
            ecriture.lignes.append(LigneEcriture(
                compte=compte_banque, libelle=libelle, credit=mnt,
                piece_ref=numero_piece,
            ))

        self.ecritures.append(ecriture)
        return ecriture

    def valider_ecritures(self) -> list[str]:
        """Valide toutes les ecritures non validees. Retourne les erreurs."""
        erreurs = []
        for e in self.ecritures:
            if e.validee:
                continue
            if not e.est_equilibree:
                erreurs.append(
                    f"Ecriture {e.id} ({e.libelle}) desequilibree: "
                    f"D={e.total_debit} C={e.total_credit}"
                )
                continue
            if not e.lignes:
                erreurs.append(f"Ecriture {e.id} sans lignes")
                continue
            e.validee = True
            e.date_validation = datetime.now()
        return erreurs

    def get_grand_livre(self, validees_seulement: bool = False) -> dict[str, list[dict]]:
        """Retourne le grand livre (mouvements par compte)."""
        grand_livre: dict[str, list[dict]] = {}
        for e in self.ecritures:
            if validees_seulement and not e.validee:
                continue
            for l in e.lignes:
                if l.compte not in grand_livre:
                    grand_livre[l.compte] = []
                grand_livre[l.compte].append({
                    "date": e.date_ecriture.isoformat(),
                    "journal": e.journal.value,
                    "piece": e.numero_piece,
                    "libelle": l.libelle,
                    "debit": float(l.debit),
                    "credit": float(l.credit),
                })
        return dict(sorted(grand_livre.items()))

    def get_balance(self, validees_seulement: bool = False) -> list[dict]:
        """Retourne la balance des comptes."""
        totaux: dict[str, dict] = {}
        for e in self.ecritures:
            if validees_seulement and not e.validee:
                continue
            for l in e.lignes:
                if l.compte not in totaux:
                    cpt = self.plan.get_compte(l.compte)
                    totaux[l.compte] = {
                        "compte": l.compte,
                        "libelle": cpt.libelle if cpt else l.libelle,
                        "total_debit": Decimal("0"),
                        "total_credit": Decimal("0"),
                    }
                totaux[l.compte]["total_debit"] += l.debit
                totaux[l.compte]["total_credit"] += l.credit

        balance = []
        for compte in sorted(totaux.keys()):
            t = totaux[compte]
            solde = t["total_debit"] - t["total_credit"]
            balance.append({
                "compte": t["compte"],
                "libelle": t["libelle"],
                "total_debit": float(t["total_debit"]),
                "total_credit": float(t["total_credit"]),
                "solde_debiteur": float(solde) if solde > 0 else 0.0,
                "solde_crediteur": float(abs(solde)) if solde < 0 else 0.0,
            })
        return balance

    def get_journal(self, type_journal: TypeJournal = None) -> list[dict]:
        """Retourne les ecritures d'un journal."""
        result = []
        for e in self.ecritures:
            if type_journal and e.journal != type_journal:
                continue
            result.append({
                "id": e.id,
                "journal": e.journal.value,
                "date": e.date_ecriture.isoformat(),
                "piece": e.numero_piece,
                "libelle": e.libelle,
                "validee": e.validee,
                "lignes": [
                    {
                        "compte": l.compte,
                        "libelle": l.libelle,
                        "debit": float(l.debit),
                        "credit": float(l.credit),
                    }
                    for l in e.lignes
                ],
                "total_debit": float(e.total_debit),
                "total_credit": float(e.total_credit),
                "equilibree": e.est_equilibree,
            })
        return result
