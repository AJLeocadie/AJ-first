"""Tests exhaustifs couvrant les lignes manquantes de:
- urssaf_analyzer/database/supabase_client.py (toutes les methodes avec client mocke)
- persistence.py (PersistentList.__bool__, __iter__, save_uploaded_file, save_report, log_action, get_data_stats)
- auth.py (get_current_user, get_optional_user, require_role, set_auth_cookie, clear_auth_cookie, etc.)
"""

import sys
import os
import json
import time
from decimal import Decimal
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ================================================================
# PART 1: SUPABASE CLIENT - ALL METHODS WITH MOCKED CLIENT
# ================================================================

class TestSupabaseClientConnected:
    """Test all SupabaseClient methods with a mocked supabase client."""

    def _make_client_with_mock(self):
        """Create a SupabaseClient with a mocked internal client.

        We bypass the client property by directly setting _client AND
        patching HAS_SUPABASE so the property doesn't short-circuit.
        """
        import urssaf_analyzer.database.supabase_client as sc_mod
        self._orig_has = sc_mod.HAS_SUPABASE
        sc_mod.HAS_SUPABASE = True
        sc = sc_mod.SupabaseClient(url="https://fake.supabase.co", key="fake-key", service_key="fake-svc")
        mock_client = MagicMock()
        sc._client = mock_client
        return sc, mock_client

    def teardown_method(self):
        import urssaf_analyzer.database.supabase_client as sc_mod
        if hasattr(self, '_orig_has'):
            sc_mod.HAS_SUPABASE = self._orig_has

    def _mock_execute(self, data):
        """Create a mock result.execute() that returns data."""
        result = MagicMock()
        result.data = data
        return result

    # --- Profils ---

    def test_creer_profil_success(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "uuid-1", "nom": "Dupont", "email": "d@t.fr"}
        mock.table.return_value.insert.return_value.execute.return_value = self._mock_execute([row])
        result = sc.creer_profil({"nom": "Dupont", "email": "d@t.fr"})
        assert result == row
        mock.table.assert_called_with("ua_profils")

    def test_creer_profil_empty_result(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.insert.return_value.execute.return_value = self._mock_execute([])
        result = sc.creer_profil({"nom": "Test"})
        assert result == {}

    def test_get_profil_found(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "uuid-1", "nom": "Dupont"}
        mock.table.return_value.select.return_value.eq.return_value.execute.return_value = self._mock_execute([row])
        result = sc.get_profil("uuid-1")
        assert result == row

    def test_get_profil_not_found(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.select.return_value.eq.return_value.execute.return_value = self._mock_execute([])
        result = sc.get_profil("uuid-missing")
        assert result is None

    def test_get_profil_par_email_found(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "uuid-1", "email": "d@t.fr"}
        mock.table.return_value.select.return_value.eq.return_value.execute.return_value = self._mock_execute([row])
        result = sc.get_profil_par_email("d@t.fr")
        assert result == row

    def test_get_profil_par_email_not_found(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.select.return_value.eq.return_value.execute.return_value = self._mock_execute([])
        result = sc.get_profil_par_email("missing@t.fr")
        assert result is None

    def test_lister_profils(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"id": "1", "nom": "A"}, {"id": "2", "nom": "B"}]
        mock.table.return_value.select.return_value.order.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.lister_profils()
        assert result == rows

    def test_lister_profils_empty(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.select.return_value.order.return_value.execute.return_value = self._mock_execute(None)
        result = sc.lister_profils()
        assert result == []

    def test_maj_profil_success(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "uuid-1", "nom": "Updated"}
        mock.table.return_value.update.return_value.eq.return_value.execute.return_value = self._mock_execute([row])
        result = sc.maj_profil("uuid-1", {"nom": "Updated"})
        assert result == row

    def test_maj_profil_empty(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.update.return_value.eq.return_value.execute.return_value = self._mock_execute([])
        result = sc.maj_profil("uuid-1", {"nom": "Updated"})
        assert result == {}

    # --- Entreprises ---

    def test_creer_entreprise_success(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "e1", "siret": "12345678901234"}
        mock.table.return_value.insert.return_value.execute.return_value = self._mock_execute([row])
        result = sc.creer_entreprise({"siret": "12345678901234"})
        assert result == row

    def test_creer_entreprise_empty(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.insert.return_value.execute.return_value = self._mock_execute([])
        result = sc.creer_entreprise({"siret": "12345678901234"})
        assert result == {}

    def test_get_entreprise_found(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "e1", "siret": "12345678901234"}
        mock.table.return_value.select.return_value.eq.return_value.execute.return_value = self._mock_execute([row])
        result = sc.get_entreprise("e1")
        assert result == row

    def test_get_entreprise_not_found(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.select.return_value.eq.return_value.execute.return_value = self._mock_execute([])
        result = sc.get_entreprise("e-missing")
        assert result is None

    def test_get_entreprise_par_siret_found(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "e1", "siret": "12345678901234"}
        mock.table.return_value.select.return_value.eq.return_value.execute.return_value = self._mock_execute([row])
        result = sc.get_entreprise_par_siret("12345678901234")
        assert result == row

    def test_get_entreprise_par_siret_not_found(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.select.return_value.eq.return_value.execute.return_value = self._mock_execute([])
        result = sc.get_entreprise_par_siret("00000000000000")
        assert result is None

    def test_rechercher_entreprises_success(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"id": "e1", "raison_sociale": "ACME"}]
        chain = mock.table.return_value.select.return_value
        chain.or_.return_value.order.return_value.limit.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.rechercher_entreprises("ACME")
        assert result == rows

    def test_rechercher_entreprises_empty_term(self):
        sc, mock = self._make_client_with_mock()
        result = sc.rechercher_entreprises("")
        assert result == []

    def test_rechercher_entreprises_special_chars_only(self):
        sc, mock = self._make_client_with_mock()
        result = sc.rechercher_entreprises("%()")
        assert result == []

    def test_rechercher_entreprises_sanitizes_input(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"id": "e1"}]
        chain = mock.table.return_value.select.return_value
        chain.or_.return_value.order.return_value.limit.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.rechercher_entreprises("test%injection")
        assert result == rows

    def test_rechercher_entreprises_none_data(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.select.return_value
        chain.or_.return_value.order.return_value.limit.return_value.execute.return_value = self._mock_execute(None)
        result = sc.rechercher_entreprises("test")
        assert result == []

    def test_lister_entreprises(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"id": "e1", "actif": True}]
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.lister_entreprises()
        assert result == rows

    def test_lister_entreprises_none(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = self._mock_execute(None)
        result = sc.lister_entreprises()
        assert result == []

    def test_maj_entreprise_success(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "e1", "raison_sociale": "Updated"}
        mock.table.return_value.update.return_value.eq.return_value.execute.return_value = self._mock_execute([row])
        result = sc.maj_entreprise("e1", {"raison_sociale": "Updated"})
        assert result == row

    def test_maj_entreprise_empty(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.update.return_value.eq.return_value.execute.return_value = self._mock_execute([])
        result = sc.maj_entreprise("e1", {"raison_sociale": "Updated"})
        assert result == {}

    # --- Profils independants ---

    def test_creer_profil_independant_success(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "pi1", "type_statut": "micro_entrepreneur"}
        mock.table.return_value.insert.return_value.execute.return_value = self._mock_execute([row])
        result = sc.creer_profil_independant({"type_statut": "micro_entrepreneur"})
        assert result == row

    def test_creer_profil_independant_empty(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.insert.return_value.execute.return_value = self._mock_execute([])
        result = sc.creer_profil_independant({"type_statut": "micro_entrepreneur"})
        assert result == {}

    def test_get_profils_independants_success(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"id": "pi1"}, {"id": "pi2"}]
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_profils_independants("user-1")
        assert result == rows

    def test_get_profils_independants_none(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = self._mock_execute(None)
        result = sc.get_profils_independants("user-1")
        assert result == []

    def test_maj_profil_independant_success(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "pi1", "activite": "updated"}
        chain = mock.table.return_value.update.return_value
        chain.eq.return_value.execute.return_value = self._mock_execute([row])
        result = sc.maj_profil_independant("pi1", {"activite": "updated"})
        assert result == row

    def test_maj_profil_independant_empty(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.update.return_value
        chain.eq.return_value.execute.return_value = self._mock_execute([])
        result = sc.maj_profil_independant("pi1", {"activite": "updated"})
        assert result == {}

    # --- Portefeuille ---

    def test_assigner_entreprise_success(self):
        sc, mock = self._make_client_with_mock()
        row = {"profil_id": "u1", "entreprise_id": "e1", "role_sur_entreprise": "gestionnaire"}
        mock.table.return_value.upsert.return_value.execute.return_value = self._mock_execute([row])
        result = sc.assigner_entreprise("u1", "e1")
        assert result == row

    def test_assigner_entreprise_custom_role(self):
        sc, mock = self._make_client_with_mock()
        row = {"profil_id": "u1", "entreprise_id": "e1", "role_sur_entreprise": "admin"}
        mock.table.return_value.upsert.return_value.execute.return_value = self._mock_execute([row])
        result = sc.assigner_entreprise("u1", "e1", role="admin")
        assert result == row

    def test_assigner_entreprise_empty(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.upsert.return_value.execute.return_value = self._mock_execute([])
        result = sc.assigner_entreprise("u1", "e1")
        assert result == {}

    def test_get_portefeuille_success(self):
        sc, mock = self._make_client_with_mock()
        ent_rows = [{"entreprise_id": "e1", "ua_entreprises": {"raison_sociale": "ACME"}}]
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.execute.return_value = self._mock_execute(ent_rows)

        # Also mock get_profils_independants via the table chain
        ind_rows = [{"id": "pi1"}]
        # We need to set up the second call to table for independants
        # get_portefeuille calls self.get_profils_independants which uses self.client.table(...)
        call_count = [0]
        original_table = mock.table

        def table_side_effect(name):
            call_count[0] += 1
            result_mock = MagicMock()
            if name == "ua_portefeuille":
                result_mock.select.return_value.eq.return_value.execute.return_value = self._mock_execute(ent_rows)
            elif name == "ua_profils_independants":
                result_mock.select.return_value.eq.return_value.order.return_value.execute.return_value = self._mock_execute(ind_rows)
            return result_mock

        mock.table = MagicMock(side_effect=table_side_effect)
        result = sc.get_portefeuille("u1")
        assert "entreprises" in result
        assert "profils_independants" in result
        assert result["entreprises"] == ent_rows
        assert result["profils_independants"] == ind_rows

    # --- Baremes et reglementation ---

    def test_get_baremes(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"type_cotisation": "maladie", "taux_patronal": 0.07}]
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_baremes(2026)
        assert result == rows

    def test_get_baremes_none(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = self._mock_execute(None)
        result = sc.get_baremes(2026)
        assert result == []

    def test_get_plafonds(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"type_plafond": "PASS", "valeur_annuelle": 46368}]
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_plafonds(2026)
        assert result == rows

    def test_get_plafonds_none(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.execute.return_value = self._mock_execute(None)
        result = sc.get_plafonds(2026)
        assert result == []

    def test_get_annees_disponibles(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"annee": 2025}, {"annee": 2026}, {"annee": 2025}]  # duplicates
        chain = mock.table.return_value.select.return_value
        chain.order.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_annees_disponibles()
        assert result == [2025, 2026]

    def test_get_annees_disponibles_none(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.select.return_value
        chain.order.return_value.execute.return_value = self._mock_execute(None)
        result = sc.get_annees_disponibles()
        assert result == []

    def test_get_reglementation_with_domaine(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"reference": "CSS art. L241-1"}]
        chain = mock.table.return_value.select.return_value
        eq_chain = chain.eq.return_value
        eq_chain.eq.return_value.order.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_reglementation(2026, domaine="cotisations")
        assert result == rows

    def test_get_reglementation_no_domaine(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"reference": "R1"}, {"reference": "R2"}]
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_reglementation(2026)
        assert result == rows

    def test_get_reglementation_none(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = self._mock_execute(None)
        result = sc.get_reglementation(2026)
        assert result == []

    # --- Analyses ---

    def test_enregistrer_analyse_success(self):
        sc, mock = self._make_client_with_mock()
        row = {"id": "a1", "nb_constats": 5}
        mock.table.return_value.insert.return_value.execute.return_value = self._mock_execute([row])
        result = sc.enregistrer_analyse({"nb_constats": 5, "montant": Decimal("1234.56")})
        assert result == row

    def test_enregistrer_analyse_empty(self):
        sc, mock = self._make_client_with_mock()
        mock.table.return_value.insert.return_value.execute.return_value = self._mock_execute([])
        result = sc.enregistrer_analyse({"nb_constats": 0})
        assert result == {}

    def test_get_historique_analyses_with_entreprise(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"id": "a1"}]
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.limit.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_historique_analyses(entreprise_id="e1")
        assert result == rows

    def test_get_historique_analyses_with_profil(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"id": "a1"}]
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.limit.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_historique_analyses(profil_id="p1")
        assert result == rows

    def test_get_historique_analyses_both_filters(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"id": "a1"}]
        chain = mock.table.return_value.select.return_value
        chain.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_historique_analyses(entreprise_id="e1", profil_id="p1")
        assert result == rows

    def test_get_historique_analyses_no_filter(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"id": "a1"}, {"id": "a2"}]
        chain = mock.table.return_value.select.return_value
        chain.order.return_value.limit.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_historique_analyses()
        assert result == rows

    def test_get_historique_analyses_none(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.select.return_value
        chain.order.return_value.limit.return_value.execute.return_value = self._mock_execute(None)
        result = sc.get_historique_analyses()
        assert result == []

    # --- Patches ---

    def test_get_historique_patches(self):
        sc, mock = self._make_client_with_mock()
        rows = [{"annee": 2026, "mois": 3}]
        chain = mock.table.return_value.select.return_value
        chain.order.return_value.limit.return_value.execute.return_value = self._mock_execute(rows)
        result = sc.get_historique_patches()
        assert result == rows

    def test_get_historique_patches_none(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.select.return_value
        chain.order.return_value.limit.return_value.execute.return_value = self._mock_execute(None)
        result = sc.get_historique_patches()
        assert result == []

    def test_get_historique_patches_custom_limit(self):
        sc, mock = self._make_client_with_mock()
        chain = mock.table.return_value.select.return_value
        chain.order.return_value.limit.return_value.execute.return_value = self._mock_execute([])
        sc.get_historique_patches(limit=5)
        # Verify limit was called
        chain.order.return_value.limit.assert_called_with(5)


class TestExecuterPatchMensuel:
    """Test executer_patch_mensuel with full data pipeline."""

    def _make_client_with_admin(self):
        import urssaf_analyzer.database.supabase_client as sc_mod
        self._orig_has = sc_mod.HAS_SUPABASE
        sc_mod.HAS_SUPABASE = True
        sc = sc_mod.SupabaseClient(url="https://fake.supabase.co", key="fk", service_key="fsk")
        mock_admin = MagicMock()
        sc._admin_client = mock_admin
        return sc, mock_admin

    def teardown_method(self):
        import urssaf_analyzer.database.supabase_client as sc_mod
        if hasattr(self, '_orig_has'):
            sc_mod.HAS_SUPABASE = self._orig_has

    def test_executer_patch_no_admin(self):
        from urssaf_analyzer.database.supabase_client import SupabaseClient
        sc = SupabaseClient(url="", key="", service_key="")
        result = sc.executer_patch_mensuel(2026, 3, {})
        assert result["status"] == "failed"
        assert "admin" in result["error"].lower()

    def test_executer_patch_empty_data(self):
        sc, admin = self._make_client_with_admin()
        admin.table.return_value.insert.return_value.execute.return_value = MagicMock()
        result = sc.executer_patch_mensuel(2026, 3, {"source": "test"})
        assert result["status"] == "success"
        assert result["baremes_maj"] == 0
        assert result["plafonds_maj"] == 0
        assert result["reglements_maj"] == 0
        assert "2026-03" in result["message"]

    def test_executer_patch_with_baremes(self):
        sc, admin = self._make_client_with_admin()
        admin.table.return_value.upsert.return_value.execute.return_value = MagicMock()
        admin.table.return_value.insert.return_value.execute.return_value = MagicMock()

        data = {
            "baremes": [
                {"type_cotisation": "maladie", "taux_patronal": 0.07, "code_ctp": "100"},
                {"type_cotisation": "vieillesse", "taux_patronal": 0.0855, "code_ctp": "200"},
            ],
            "plafonds": [],
            "reglementation": [],
            "source": "test",
        }
        result = sc.executer_patch_mensuel(2026, 3, data)
        assert result["baremes_maj"] == 2
        assert result["status"] == "success"

    def test_executer_patch_with_plafonds(self):
        sc, admin = self._make_client_with_admin()
        admin.table.return_value.upsert.return_value.execute.return_value = MagicMock()
        admin.table.return_value.insert.return_value.execute.return_value = MagicMock()

        data = {
            "baremes": [],
            "plafonds": [
                {"type_plafond": "PASS", "valeur_annuelle": 46368},
                {"type_plafond": "SMIC", "valeur_annuelle": 21203},
            ],
            "reglementation": [],
            "source": "test",
        }
        result = sc.executer_patch_mensuel(2026, 3, data)
        assert result["plafonds_maj"] == 2

    def test_executer_patch_with_reglementation(self):
        sc, admin = self._make_client_with_admin()
        admin.table.return_value.upsert.return_value.execute.return_value = MagicMock()
        admin.table.return_value.insert.return_value.execute.return_value = MagicMock()

        data = {
            "baremes": [],
            "plafonds": [],
            "reglementation": [
                {"reference": "CSS art. L241-1", "titre": "Maladie", "domaine": "cotisations"},
            ],
            "source": "legifrance",
        }
        result = sc.executer_patch_mensuel(2026, 3, data)
        assert result["reglements_maj"] == 1

    def test_executer_patch_full(self):
        sc, admin = self._make_client_with_admin()
        admin.table.return_value.upsert.return_value.execute.return_value = MagicMock()
        admin.table.return_value.insert.return_value.execute.return_value = MagicMock()

        data = {
            "baremes": [{"type_cotisation": "maladie", "code_ctp": "100"}],
            "plafonds": [{"type_plafond": "PASS"}],
            "reglementation": [{"reference": "R1", "titre": "T1"}],
            "source": "full test",
        }
        result = sc.executer_patch_mensuel(2026, 1, data)
        assert result["baremes_maj"] == 1
        assert result["plafonds_maj"] == 1
        assert result["reglements_maj"] == 1
        assert result["status"] == "success"
        # Verify the log was inserted
        admin.table.assert_any_call("ua_patches_log")

    def test_executer_patch_sets_annee_on_baremes(self):
        sc, admin = self._make_client_with_admin()
        admin.table.return_value.upsert.return_value.execute.return_value = MagicMock()
        admin.table.return_value.insert.return_value.execute.return_value = MagicMock()

        bareme = {"type_cotisation": "test", "code_ctp": ""}
        sc.executer_patch_mensuel(2026, 6, {"baremes": [bareme]})
        assert bareme["annee"] == 2026
        assert bareme["mois_maj"] == 6
        assert "date_maj" in bareme


class TestSupabaseClientProperties:
    """Test client and admin properties with mocked create_client."""

    def _patch_module(self):
        """Patch module to simulate supabase being available."""
        import urssaf_analyzer.database.supabase_client as sc_mod
        self._orig_has = sc_mod.HAS_SUPABASE
        sc_mod.HAS_SUPABASE = True
        self._mock_create = MagicMock(return_value=MagicMock())
        if not hasattr(sc_mod, 'create_client'):
            self._had_create_client = False
        else:
            self._had_create_client = True
            self._orig_create = sc_mod.create_client
        sc_mod.create_client = self._mock_create
        return sc_mod

    def _unpatch_module(self):
        import urssaf_analyzer.database.supabase_client as sc_mod
        sc_mod.HAS_SUPABASE = self._orig_has
        if self._had_create_client:
            sc_mod.create_client = self._orig_create
        elif hasattr(sc_mod, 'create_client'):
            delattr(sc_mod, 'create_client')

    def test_client_property_creates_client(self):
        sc_mod = self._patch_module()
        try:
            sc = sc_mod.SupabaseClient(url="https://x.supabase.co", key="key123")
            client = sc.client
            assert client is not None
            self._mock_create.assert_called_once_with("https://x.supabase.co", "key123")
        finally:
            self._unpatch_module()

    def test_client_property_cached(self):
        sc_mod = self._patch_module()
        try:
            sc = sc_mod.SupabaseClient(url="https://x.supabase.co", key="key123")
            c1 = sc.client
            c2 = sc.client
            assert c1 is c2
            assert self._mock_create.call_count == 1
        finally:
            self._unpatch_module()

    def test_admin_property_creates_client(self):
        sc_mod = self._patch_module()
        try:
            sc = sc_mod.SupabaseClient(url="https://x.supabase.co", key="k", service_key="svc123")
            admin = sc.admin
            assert admin is not None
            self._mock_create.assert_called_with("https://x.supabase.co", "svc123")
        finally:
            self._unpatch_module()

    def test_admin_property_cached(self):
        sc_mod = self._patch_module()
        try:
            sc = sc_mod.SupabaseClient(url="https://x.supabase.co", key="k", service_key="svc123")
            a1 = sc.admin
            a2 = sc.admin
            assert a1 is a2
        finally:
            self._unpatch_module()

    def test_is_connected_false(self):
        from urssaf_analyzer.database.supabase_client import SupabaseClient
        sc = SupabaseClient(url="", key="")
        assert sc.is_connected is False

    def test_is_connected_true(self):
        sc_mod = self._patch_module()
        try:
            sc = sc_mod.SupabaseClient(url="https://x.supabase.co", key="key123")
            assert sc.is_connected is True
        finally:
            self._unpatch_module()


class TestDecimalEncoderAndSerialize:
    """Additional coverage for DecimalEncoder and _serialize."""

    def test_serialize_with_decimal_and_date(self):
        from urssaf_analyzer.database.supabase_client import _serialize
        data = {
            "amount": Decimal("1234.56"),
            "date": date(2026, 3, 15),
            "dt": datetime(2026, 3, 15, 10, 30),
            "name": "test",
            "count": 42,
        }
        result = _serialize(data)
        assert result["amount"] == 1234.56
        assert result["date"] == "2026-03-15"
        assert "2026-03-15" in result["dt"]
        assert result["name"] == "test"
        assert result["count"] == 42


class TestGenererDonneesPatchMensuel:
    """Test generer_donnees_patch_mensuel."""

    def test_generer_donnees_patch_returns_structure(self):
        from urssaf_analyzer.database.supabase_client import generer_donnees_patch_mensuel
        result = generer_donnees_patch_mensuel(2026, 3)
        assert "baremes" in result
        assert "plafonds" in result
        assert "reglementation" in result
        assert "source" in result
        assert isinstance(result["baremes"], list)
        assert isinstance(result["plafonds"], list)
        assert len(result["plafonds"]) >= 2  # PASS and SMIC at minimum

    def test_generer_donnees_patch_plafonds_values(self):
        from urssaf_analyzer.database.supabase_client import generer_donnees_patch_mensuel
        result = generer_donnees_patch_mensuel(2026, 1)
        plafonds = {p["type_plafond"]: p for p in result["plafonds"]}
        assert "PASS" in plafonds
        assert "SMIC" in plafonds
        assert plafonds["PASS"]["valeur_annuelle"] > 0
        assert plafonds["SMIC"]["valeur_annuelle"] > 0

    def test_generer_donnees_patch_baremes_present(self):
        from urssaf_analyzer.database.supabase_client import generer_donnees_patch_mensuel
        result = generer_donnees_patch_mensuel(2026, 6)
        assert len(result["baremes"]) > 0
        for b in result["baremes"]:
            assert "type_cotisation" in b

    def test_generer_donnees_patch_source_format(self):
        from urssaf_analyzer.database.supabase_client import generer_donnees_patch_mensuel
        result = generer_donnees_patch_mensuel(2026, 3)
        assert "2026-03" in result["source"]

    def test_generer_donnees_patch_different_year(self):
        """Test with a different year to exercise the annees anterieures branch."""
        from urssaf_analyzer.database.supabase_client import generer_donnees_patch_mensuel
        # Using 2025 means current year baremes will be added, and
        # BAREMES_PAR_ANNEE entries != 2025 will also be added
        result = generer_donnees_patch_mensuel(2025, 1)
        assert len(result["baremes"]) > 0
        assert "2025-01" in result["source"]


# ================================================================
# PART 2: PERSISTENCE - UNCOVERED LINES
# ================================================================

class TestPersistentListBoolAndIter:
    """Test PersistentList.__bool__ and __iter__ (lines 114-118)."""

    def test_bool_empty_list(self, tmp_path, monkeypatch):
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        plist = PersistentList("test_bool_empty")
        assert bool(plist) is False

    def test_bool_nonempty_list(self, tmp_path, monkeypatch):
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        plist = PersistentList("test_bool_nonempty")
        plist.append({"x": 1})
        assert bool(plist) is True

    def test_iter_empty(self, tmp_path, monkeypatch):
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        plist = PersistentList("test_iter_empty")
        items = list(plist)
        assert items == []

    def test_iter_with_items(self, tmp_path, monkeypatch):
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        plist = PersistentList("test_iter_items")
        plist.append("a")
        plist.append("b")
        plist.append("c")
        items = list(plist)
        assert items == ["a", "b", "c"]

    def test_iter_in_for_loop(self, tmp_path, monkeypatch):
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        plist = PersistentList("test_iter_for")
        plist.append({"n": 1})
        plist.append({"n": 2})
        total = 0
        for item in plist:
            total += item["n"]
        assert total == 3


from persistence import PersistentList


class TestSaveUploadedFile:
    """Test save_uploaded_file (lines 182-201)."""

    def test_save_no_encryption(self, tmp_path, monkeypatch):
        import persistence
        monkeypatch.setattr(persistence, "UPLOADS_DIR", tmp_path / "uploads")
        (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
        monkeypatch.delenv("NORMACHECK_ENCRYPTION_KEY", raising=False)

        dest = persistence.save_uploaded_file("test.pdf", b"hello world")
        assert dest.exists()
        assert dest.read_bytes() == b"hello world"
        assert dest.name == "test.pdf"

    def test_save_with_analysis_id(self, tmp_path, monkeypatch):
        import persistence
        monkeypatch.setattr(persistence, "UPLOADS_DIR", tmp_path / "uploads")
        (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
        monkeypatch.delenv("NORMACHECK_ENCRYPTION_KEY", raising=False)

        dest = persistence.save_uploaded_file("doc.csv", b"data", analysis_id="analysis-123")
        assert dest.exists()
        assert "analysis-123" in str(dest)

    def test_save_with_encryption_key_but_no_module(self, tmp_path, monkeypatch):
        """If encryption key is set but module fails to import, falls back to unencrypted."""
        import persistence
        monkeypatch.setattr(persistence, "UPLOADS_DIR", tmp_path / "uploads")
        (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("NORMACHECK_ENCRYPTION_KEY", "some-secret-key")

        dest = persistence.save_uploaded_file("test.pdf", b"content here")
        assert dest.exists()
        # Should fall back to unencrypted since the encryption module may not be importable
        # or may raise; either way file should be saved
        content = dest.read_bytes()
        assert len(content) > 0

    def test_save_with_encryption_success(self, tmp_path, monkeypatch):
        """Test encryption path when chiffrer_donnees is available."""
        import persistence
        monkeypatch.setattr(persistence, "UPLOADS_DIR", tmp_path / "uploads")
        (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("NORMACHECK_ENCRYPTION_KEY", "test-key-256bit")

        # Mock the encryption function
        def fake_chiffrer(content, key, contexte=""):
            return b"ENCRYPTED:" + content

        with patch("persistence.chiffrer_donnees", fake_chiffrer, create=True):
            # Patch the import inside save_uploaded_file
            with patch.dict("sys.modules", {
                "urssaf_analyzer.security.encryption": MagicMock(chiffrer_donnees=fake_chiffrer)
            }):
                dest = persistence.save_uploaded_file("secret.pdf", b"sensitive data")
                assert dest.exists()
                assert dest.name == "secret.pdf.enc"
                assert dest.read_bytes() == b"ENCRYPTED:sensitive data"


class TestSaveReport:
    """Test save_report (lines 206-208)."""

    def test_save_report_html(self, tmp_path, monkeypatch):
        import persistence
        monkeypatch.setattr(persistence, "REPORTS_DIR", tmp_path / "reports")
        (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

        dest = persistence.save_report("report-001", "<h1>Analysis</h1>", fmt="html")
        assert dest.exists()
        assert dest.name == "report-001.html"
        assert dest.read_text(encoding="utf-8") == "<h1>Analysis</h1>"

    def test_save_report_json(self, tmp_path, monkeypatch):
        import persistence
        monkeypatch.setattr(persistence, "REPORTS_DIR", tmp_path / "reports")
        (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

        dest = persistence.save_report("report-002", '{"result": "ok"}', fmt="json")
        assert dest.exists()
        assert dest.name == "report-002.json"

    def test_save_report_default_format(self, tmp_path, monkeypatch):
        import persistence
        monkeypatch.setattr(persistence, "REPORTS_DIR", tmp_path / "reports")
        (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

        dest = persistence.save_report("report-003", "<p>test</p>")
        assert dest.name == "report-003.html"


class TestLogAction:
    """Test log_action (lines 213, 224-225)."""

    def test_log_action_creates_entry(self, tmp_path, monkeypatch):
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        audit_store = PersistentList("test_audit_log")
        monkeypatch.setattr(persistence, "audit_log_store", audit_store)

        persistence.log_action("admin@test.fr", "connexion", "IP: 127.0.0.1")
        logs = audit_store.load()
        assert len(logs) == 1
        assert logs[0]["profil"] == "admin@test.fr"
        assert logs[0]["action"] == "connexion"
        assert logs[0]["details"] == "IP: 127.0.0.1"
        assert "date" in logs[0]
        assert "id" in logs[0]

    def test_log_action_no_details(self, tmp_path, monkeypatch):
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        audit_store = PersistentList("test_audit_no_details")
        monkeypatch.setattr(persistence, "audit_log_store", audit_store)

        persistence.log_action("user@test.fr", "upload")
        logs = audit_store.load()
        assert logs[0]["details"] == ""

    def test_log_action_multiple(self, tmp_path, monkeypatch):
        import persistence
        db_dir = tmp_path / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)

        audit_store = PersistentList("test_audit_multi")
        monkeypatch.setattr(persistence, "audit_log_store", audit_store)

        persistence.log_action("u1", "action1")
        persistence.log_action("u2", "action2")
        persistence.log_action("u1", "action3")
        logs = audit_store.load()
        assert len(logs) == 3


class TestGetDataStats:
    """Test get_data_stats (lines 224-234)."""

    def test_get_data_stats_empty(self, tmp_path, monkeypatch):
        import persistence
        db_dir = tmp_path / "db"
        uploads_dir = tmp_path / "uploads"
        reports_dir = tmp_path / "reports"
        for d in [db_dir, uploads_dir, reports_dir]:
            d.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)
        monkeypatch.setattr(persistence, "UPLOADS_DIR", uploads_dir)
        monkeypatch.setattr(persistence, "REPORTS_DIR", reports_dir)

        # Create fresh stores for this test
        kb_store = persistence.PersistentStore.__new__(persistence.PersistentStore)
        kb_store.path = db_dir / "test_kb.json"
        kb_store.lock_path = db_dir / "test_kb.lock"
        kb_store.name = "test_kb"
        kb_store._default = {
            "salaries": {}, "derniere_maj": None,
        }
        kb_store._write(kb_store._default)
        monkeypatch.setattr(persistence, "knowledge_store", kb_store)

        doc_store = PersistentList("test_doc_lib")
        monkeypatch.setattr(persistence, "doc_library_store", doc_store)

        rh_store = PersistentList("test_rh_contrats")
        monkeypatch.setattr(persistence, "rh_contrats_store", rh_store)

        stats = persistence.get_data_stats()
        assert "db_size_mb" in stats
        assert "uploads_count" in stats
        assert "uploads_size_mb" in stats
        assert "reports_count" in stats
        assert "salaries_count" in stats
        assert "documents_count" in stats
        assert "contrats_rh_count" in stats
        assert "derniere_maj" in stats
        assert stats["salaries_count"] == 0
        assert stats["documents_count"] == 0

    def test_get_data_stats_with_data(self, tmp_path, monkeypatch):
        import persistence
        db_dir = tmp_path / "db"
        uploads_dir = tmp_path / "uploads"
        reports_dir = tmp_path / "reports"
        for d in [db_dir, uploads_dir, reports_dir]:
            d.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(persistence, "DB_DIR", db_dir)
        monkeypatch.setattr(persistence, "UPLOADS_DIR", uploads_dir)
        monkeypatch.setattr(persistence, "REPORTS_DIR", reports_dir)

        # Create files in uploads and reports (large enough to register in MB)
        (uploads_dir / "file1.pdf").write_bytes(b"x" * (1024 * 1024 + 100))
        (reports_dir / "report1.html").write_text("<p>test</p>")

        kb_store = persistence.PersistentStore.__new__(persistence.PersistentStore)
        kb_store.path = db_dir / "test_kb2.json"
        kb_store.lock_path = db_dir / "test_kb2.lock"
        kb_store.name = "test_kb2"
        kb_store._default = {"salaries": {"s1": {"nom": "Dupont"}}, "derniere_maj": "2026-03-01"}
        kb_store._write(kb_store._default)
        monkeypatch.setattr(persistence, "knowledge_store", kb_store)

        # These stores write into db_dir since we patched DB_DIR before creating them
        doc_store_inner = persistence.PersistentStore("test_doc_lib2", default=[])
        doc_store_inner.path = db_dir / "test_doc_lib2.json"
        doc_store_inner.lock_path = db_dir / "test_doc_lib2.lock"
        doc_store_inner._write([])
        doc_plist = PersistentList.__new__(PersistentList)
        doc_plist._store = doc_store_inner
        doc_plist._store._write([{"name": "doc1"}])
        monkeypatch.setattr(persistence, "doc_library_store", doc_plist)

        rh_store_inner = persistence.PersistentStore("test_rh2", default=[])
        rh_store_inner.path = db_dir / "test_rh2.json"
        rh_store_inner.lock_path = db_dir / "test_rh2.lock"
        rh_store_inner._write([{"id": "c1"}, {"id": "c2"}])
        rh_plist = PersistentList.__new__(PersistentList)
        rh_plist._store = rh_store_inner
        monkeypatch.setattr(persistence, "rh_contrats_store", rh_plist)

        stats = persistence.get_data_stats()
        assert stats["db_size_mb"] >= 0  # May be very small but computed
        assert stats["uploads_count"] == 1
        assert stats["uploads_size_mb"] > 0
        assert stats["reports_count"] == 1
        assert stats["salaries_count"] == 1
        assert stats["documents_count"] == 1
        assert stats["contrats_rh_count"] == 2
        assert stats["derniere_maj"] == "2026-03-01"


# ================================================================
# PART 3: AUTH - UNCOVERED LINES
# ================================================================

class TestGetCurrentUser:
    """Test get_current_user from cookie and header."""

    def setup_method(self):
        import auth
        self._orig_users = auth._users.copy()
        self._orig_blacklist = auth._token_blacklist.copy()
        auth._users = {}
        auth._token_blacklist = {}

    def teardown_method(self):
        import auth
        auth._users = self._orig_users
        auth._token_blacklist = self._orig_blacklist

    def _create_user_and_token(self):
        import auth
        user = auth.create_user("current@test.fr", "SecurePass123!", "Current", "User")
        token = auth.generate_token(user)
        return user, token

    def _make_request(self, cookie_token=None, bearer_token=None):
        """Create a mock Request with proper .get() on cookies/headers."""
        request = MagicMock()
        cookies = MagicMock()
        cookies.get = MagicMock(side_effect=lambda key, default=None: cookie_token if key == "nc_token" and cookie_token else default)
        request.cookies = cookies

        headers = MagicMock()
        auth_val = f"Bearer {bearer_token}" if bearer_token else ""
        headers.get = MagicMock(side_effect=lambda key, default="": auth_val if key == "Authorization" else default)
        request.headers = headers
        return request

    def test_get_current_user_from_cookie(self):
        import auth
        user, token = self._create_user_and_token()
        request = self._make_request(cookie_token=token)
        result = auth.get_current_user(request)
        assert result["email"] == "current@test.fr"
        assert "password_hash" not in result

    def test_get_current_user_from_header(self):
        import auth
        user, token = self._create_user_and_token()
        request = self._make_request(bearer_token=token)
        result = auth.get_current_user(request)
        assert result["email"] == "current@test.fr"

    def test_get_current_user_no_token(self):
        import auth
        from fastapi import HTTPException
        request = self._make_request()
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(request)
        assert exc_info.value.status_code == 401
        assert "authentifie" in str(exc_info.value.detail).lower()

    def test_get_current_user_expired_token(self):
        import auth
        from fastapi import HTTPException
        user = auth.create_user("expired@test.fr", "SecurePass123!", "Exp", "User")
        payload = {
            "sub": user["email"], "exp": int(time.time()) - 100,
            "jti": "test-jti-expired",
        }
        token = auth.jwt_encode(payload)
        request = self._make_request(cookie_token=token)
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(request)
        assert exc_info.value.status_code == 401

    def test_get_current_user_unknown_user(self):
        import auth
        from fastapi import HTTPException
        payload = {
            "sub": "ghost@test.fr",
            "exp": int(time.time()) + 3600,
            "jti": "test-jti-ghost",
        }
        token = auth.jwt_encode(payload)
        request = self._make_request(cookie_token=token)
        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(request)
        assert exc_info.value.status_code == 401
        assert "inconnu" in str(exc_info.value.detail).lower()


class TestGetOptionalUser:
    """Test get_optional_user."""

    def setup_method(self):
        import auth
        self._orig_users = auth._users.copy()
        self._orig_blacklist = auth._token_blacklist.copy()
        auth._users = {}
        auth._token_blacklist = {}

    def teardown_method(self):
        import auth
        auth._users = self._orig_users
        auth._token_blacklist = self._orig_blacklist

    def _make_request(self, cookie_token=None):
        request = MagicMock()
        cookies = MagicMock()
        cookies.get = MagicMock(side_effect=lambda key, default=None: cookie_token if key == "nc_token" and cookie_token else default)
        request.cookies = cookies
        headers = MagicMock()
        headers.get = MagicMock(side_effect=lambda key, default="": default)
        request.headers = headers
        return request

    def test_optional_user_valid(self):
        import auth
        user = auth.create_user("opt@test.fr", "SecurePass123!", "Opt", "User")
        token = auth.generate_token(user)
        request = self._make_request(cookie_token=token)
        result = auth.get_optional_user(request)
        assert result is not None
        assert result["email"] == "opt@test.fr"

    def test_optional_user_no_token(self):
        import auth
        request = self._make_request()
        result = auth.get_optional_user(request)
        assert result is None

    def test_optional_user_invalid_token(self):
        import auth
        request = self._make_request(cookie_token="invalid.token.here")
        result = auth.get_optional_user(request)
        assert result is None


class TestRequireRole:
    """Test require_role dependency factory."""

    def setup_method(self):
        import auth
        self._orig_users = auth._users.copy()
        self._orig_blacklist = auth._token_blacklist.copy()
        auth._users = {}
        auth._token_blacklist = {}

    def teardown_method(self):
        import auth
        auth._users = self._orig_users
        auth._token_blacklist = self._orig_blacklist

    def _make_request_for_user(self, email, password, role):
        import auth
        user = auth.create_user(email, password, "Test", "User", role=role)
        token = auth.generate_token(user)
        request = MagicMock()
        cookies = MagicMock()
        cookies.get = MagicMock(side_effect=lambda key, default=None: token if key == "nc_token" else default)
        request.cookies = cookies
        headers = MagicMock()
        headers.get = MagicMock(side_effect=lambda key, default="": default)
        request.headers = headers
        return request

    def test_require_role_allowed(self):
        import auth
        request = self._make_request_for_user("admin@r.fr", "SecurePass123!", "admin")
        checker = auth.require_role("admin", "expert_comptable")
        result = checker(request)
        assert result["role"] == "admin"

    def test_require_role_denied(self):
        import auth
        from fastapi import HTTPException
        request = self._make_request_for_user("collab@r.fr", "SecurePass123!", "collaborateur")
        checker = auth.require_role("admin", "expert_comptable")
        with pytest.raises(HTTPException) as exc_info:
            checker(request)
        assert exc_info.value.status_code == 403
        assert "Role requis" in str(exc_info.value.detail)

    def test_require_role_single(self):
        import auth
        request = self._make_request_for_user("ec@r.fr", "SecurePass123!", "expert_comptable")
        checker = auth.require_role("expert_comptable")
        result = checker(request)
        assert result["email"] == "ec@r.fr"


class TestSetAndClearAuthCookie:
    """Test set_auth_cookie and clear_auth_cookie."""

    def test_set_auth_cookie_no_https(self, monkeypatch):
        import auth
        monkeypatch.setenv("NORMACHECK_HTTPS", "0")
        response = MagicMock()
        auth.set_auth_cookie(response, "test-token-123")
        response.set_cookie.assert_called_once()
        call_kwargs = response.set_cookie.call_args
        assert call_kwargs.kwargs.get("key") or call_kwargs[1].get("key") == "nc_token"
        # Check secure is False
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        assert kwargs.get("secure") is False

    def test_set_auth_cookie_with_https(self, monkeypatch):
        import auth
        monkeypatch.setenv("NORMACHECK_HTTPS", "1")
        response = MagicMock()
        auth.set_auth_cookie(response, "test-token-456")
        response.set_cookie.assert_called_once()
        call_kwargs = response.set_cookie.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        assert kwargs.get("secure") is True

    def test_set_auth_cookie_params(self, monkeypatch):
        import auth
        monkeypatch.setenv("NORMACHECK_HTTPS", "0")
        response = MagicMock()
        auth.set_auth_cookie(response, "tok")
        call_kwargs = response.set_cookie.call_args.kwargs
        assert call_kwargs["key"] == "nc_token"
        assert call_kwargs["value"] == "tok"
        assert call_kwargs["httponly"] is True
        assert call_kwargs["samesite"] == "lax"
        assert call_kwargs["path"] == "/"

    def test_clear_auth_cookie(self):
        import auth
        response = MagicMock()
        auth.clear_auth_cookie(response)
        response.delete_cookie.assert_called_once_with(key="nc_token", path="/")


class TestRevokeTokenAndCleanup:
    """Test revoke_token and _cleanup_blacklist edge cases."""

    def setup_method(self):
        import auth
        self._orig_users = auth._users.copy()
        self._orig_blacklist = auth._token_blacklist.copy()
        auth._users = {}
        auth._token_blacklist = {}

    def teardown_method(self):
        import auth
        auth._users = self._orig_users
        auth._token_blacklist = self._orig_blacklist

    def test_revoke_token_success(self):
        import auth
        user = auth.create_user("rev@test.fr", "SecurePass123!", "Rev", "User")
        token = auth.generate_token(user)
        assert auth.revoke_token(token) is True
        # Token should now be in blacklist
        assert auth.jwt_decode(token) is None

    def test_revoke_invalid_token(self):
        import auth
        assert auth.revoke_token("garbage") is False

    def test_revoke_token_no_jti(self):
        import auth
        # Create a token without jti
        payload = {"sub": "test@x.fr", "exp": int(time.time()) + 3600}
        token = auth.jwt_encode(payload)
        assert auth.revoke_token(token) is False

    def test_cleanup_blacklist_removes_expired(self):
        import auth
        auth._token_blacklist = {
            "expired-jti-1": time.time() - 100,
            "expired-jti-2": time.time() - 50,
            "valid-jti": time.time() + 3600,
        }
        auth._cleanup_blacklist()
        assert "expired-jti-1" not in auth._token_blacklist
        assert "expired-jti-2" not in auth._token_blacklist
        assert "valid-jti" in auth._token_blacklist

    def test_cleanup_blacklist_empty(self):
        import auth
        auth._token_blacklist = {}
        auth._cleanup_blacklist()  # Should not raise
        assert auth._token_blacklist == {}


class TestBootstrapAdminEdgeCases:
    """Test bootstrap_admin with additional edge cases."""

    def setup_method(self):
        import auth
        self._orig_users = auth._users.copy()
        auth._users = {}

    def teardown_method(self):
        import auth
        auth._users = self._orig_users

    def test_bootstrap_creates_admin_when_empty(self):
        import auth
        result = auth.bootstrap_admin()
        assert result is not None
        assert result["role"] == "admin"
        assert result["email"] == auth._DEFAULT_ADMIN_EMAIL

    def test_bootstrap_returns_none_when_admin_exists(self):
        import auth
        auth.create_user("other-admin@test.fr", "SecurePass123!", "Other", "Admin", role="admin")
        result = auth.bootstrap_admin()
        assert result is None

    def test_bootstrap_promotes_existing_user(self):
        import auth
        # Create a user with the default admin email but not admin role
        auth.create_user(
            auth._DEFAULT_ADMIN_EMAIL, auth._DEFAULT_ADMIN_PASSWORD,
            "Admin", "User", role="collaborateur"
        )
        assert auth._users[auth._DEFAULT_ADMIN_EMAIL]["role"] == "collaborateur"
        result = auth.bootstrap_admin()
        assert result is not None
        assert result["role"] == "admin"


class TestVerifyEmailCodeEdgeCases:
    """Test verify_email_code edge cases."""

    def setup_method(self):
        import auth
        self._orig_users = auth._users.copy()
        self._orig_codes = auth._verification_codes.copy()
        auth._users = {}
        auth._verification_codes = {}

    def teardown_method(self):
        import auth
        auth._users = self._orig_users
        auth._verification_codes = self._orig_codes

    def test_verify_nonexistent_email(self):
        import auth
        assert auth.verify_email_code("noone@test.fr", "123456") is False

    def test_verify_expired_code_deletes_entry(self):
        import auth
        code = auth.generate_verification_code("exp@test.fr")
        auth._verification_codes["exp@test.fr"]["expires"] = time.time() - 1
        assert auth.verify_email_code("exp@test.fr", code) is False
        assert "exp@test.fr" not in auth._verification_codes

    def test_verify_max_attempts_deletes_entry(self):
        import auth
        code = auth.generate_verification_code("max@test.fr")
        auth._verification_codes["max@test.fr"]["attempts"] = auth.VERIFICATION_MAX_ATTEMPTS
        assert auth.verify_email_code("max@test.fr", code) is False
        assert "max@test.fr" not in auth._verification_codes

    def test_verify_wrong_code_increments_attempts(self):
        import auth
        code = auth.generate_verification_code("wrong@test.fr")
        auth.verify_email_code("wrong@test.fr", "000000")
        # Entry should still exist with incremented attempts
        assert "wrong@test.fr" in auth._verification_codes
        assert auth._verification_codes["wrong@test.fr"]["attempts"] == 1

    def test_verify_correct_code_marks_user_verified(self):
        import auth
        auth.create_user("verified@test.fr", "SecurePass123!", "V", "User")
        code = auth.generate_verification_code("verified@test.fr")
        assert auth.verify_email_code("verified@test.fr", code) is True
        assert auth._users["verified@test.fr"]["email_verifie"] is True

    def test_verify_correct_code_no_user_still_returns_true(self):
        import auth
        code = auth.generate_verification_code("nouser@test.fr")
        # No user created, but code verification should still succeed
        assert auth.verify_email_code("nouser@test.fr", code) is True


class TestDashboardPersistenceExtra:
    """Extra dashboard tests."""

    def setup_method(self):
        import auth
        self._orig = auth._dashboards.copy()
        auth._dashboards = {}

    def teardown_method(self):
        import auth
        auth._dashboards = self._orig

    def test_save_dashboard_stores_saved_at(self):
        import auth
        auth.save_dashboard("dash@test.fr", {"widgets": []})
        entry = auth._dashboards.get("dash@test.fr")
        assert entry is not None
        assert "saved_at" in entry
        assert entry["data"] == {"widgets": []}

    def test_load_dashboard_returns_none_for_unknown(self):
        import auth
        assert auth.load_dashboard("unknown@test.fr") is None

    def test_save_and_load_roundtrip(self):
        import auth
        data = {"analyses": 10, "alerts": 3}
        auth.save_dashboard("rt@test.fr", data)
        loaded = auth.load_dashboard("rt@test.fr")
        assert loaded["data"] == data

    def test_dashboard_email_normalized(self):
        import auth
        auth.save_dashboard("  DASH@Test.FR  ", {"v": 1})
        loaded = auth.load_dashboard("dash@test.fr")
        assert loaded is not None
        assert loaded["data"]["v"] == 1

    def test_dashboard_overwrite(self):
        import auth
        auth.save_dashboard("ow@test.fr", {"v": 1})
        auth.save_dashboard("ow@test.fr", {"v": 2})
        loaded = auth.load_dashboard("ow@test.fr")
        assert loaded["data"]["v"] == 2
