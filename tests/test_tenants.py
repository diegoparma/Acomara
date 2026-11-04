#!/usr/bin/env python3
"""Tenant configs load, are complete, and Acomara is the default.

Run with:
    python3 tests/test_tenants.py
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nico_core.tenant import TenantConfig, load_tenant  # noqa: E402

TENANT_SLUGS = sorted(
    p.name for p in (ROOT / "tenants").iterdir() if (p / "__init__.py").exists() and not p.name.startswith("_")
)


class TenantLoadingTests(unittest.TestCase):
    def test_acomara_is_the_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NICO_TENANT", None)
            self.assertEqual(load_tenant().slug, "acomara")

    def test_env_selects_the_tenant(self) -> None:
        with mock.patch.dict(os.environ, {"NICO_TENANT": "Acomara"}):
            self.assertEqual(load_tenant().slug, "acomara")

    def test_rejects_slugs_that_are_not_module_names(self) -> None:
        with self.assertRaises(ValueError):
            load_tenant("../etc")

    def test_server_serves_the_active_tenant(self) -> None:
        from orchestrator import server

        self.assertEqual(server.TENANT.slug, "acomara")
        self.assertIs(server.I18N_PHRASES, server.TENANT.phrases)


class AcomaraBrandingTests(unittest.TestCase):
    """Values that used to be hard-coded in orchestrator/ and now come from the tenant."""

    def test_service_name_and_dashboard(self) -> None:
        from orchestrator import server
        from orchestrator.observability import render_audit_dashboard_html

        self.assertEqual(server.build_version_payload()["service"], "acomara-orchestrator")
        html = render_audit_dashboard_html({}, brand_name=server.TENANT.brand_name)
        self.assertIn("<title>Acomara Audit Dashboard</title>", html)
        self.assertIn("<h1>Acomara Conversation Audit</h1>", html)

    def test_email_subjects_carry_the_brand(self) -> None:
        from orchestrator import handoff_email

        runtime = {"brand_name": "Acomara", "handoff_email_from": "a@x.com", "handoff_email_to": "b@x.com",
                   "handoff_email_api_key": "k"}
        msg = {k: "conv-1" for k in ("conversation_id", "organization_id", "contact_id", "contact_address", "channel", "text")}
        with mock.patch.object(handoff_email, "_http_json", return_value=(200, {})) as http:
            handoff_email.send_handoff_email(runtime, msg, {})
            handoff_email.send_new_lead_email(runtime, msg, "c@x.com", {})
        subjects = [c.kwargs["body"]["subject"] for c in http.call_args_list]
        self.assertEqual(subjects[0], "[Acomara] Solicitud de asesor humano - conv-1")
        self.assertEqual(subjects[1], "[Acomara] Nuevo lead con email - c@x.com")

    def test_integrations_are_the_acomara_ones(self) -> None:
        from orchestrator import caja_interno, crm_client_status, server

        self.assertIs(server.check_client_status, crm_client_status.check_client_status)
        self.assertIs(server.internal_reply, caja_interno.internal_reply)
        self.assertEqual(server.DEFAULT_ORG_ID, "7cb6ffa2-4452-4d65-b880-bfa31b197eee")
        self.assertEqual(server.DEFAULT_NICO_AGENT_ID, "50ce8caf-1088-4a42-ac2e-bda296174530")
        self.assertEqual(server.TENANT.integrations.user_agent, "Acomara-SalesAgent/1.0")


class TenantCompletenessTests(unittest.TestCase):
    def test_every_tenant_is_complete(self) -> None:
        self.assertIn("acomara", TENANT_SLUGS)
        for slug in TENANT_SLUGS:
            with self.subTest(tenant=slug):
                tenant = load_tenant(slug)
                self.assertIsInstance(tenant, TenantConfig)
                self.assertEqual(tenant.slug, slug)
                self.assertEqual(tenant.validate(), [])

    def test_acomara_is_not_a_placeholder(self) -> None:
        self.assertFalse(load_tenant("acomara").placeholder)


class SeasonConfigTests(unittest.TestCase):
    def test_no_season_never_warns(self) -> None:
        from nico_core.season import mentions_off_season

        self.assertFalse(mentions_off_season("Queremos ir en julio de viaje", None))

    def test_another_season_shape(self) -> None:
        # A northern-hemisphere business operating June-September.
        from nico_core.season import SeasonConfig, mentions_off_season

        summer = SeasonConfig(months=frozenset({6, 7, 8, 9}), trip_intent_tokens=("viaje", "trip"))
        self.assertFalse(mentions_off_season("Queremos ir en julio de viaje", summer))
        self.assertTrue(mentions_off_season("A trip in December", summer))
        self.assertTrue(mentions_off_season("Trip in May", summer))
        self.assertFalse(mentions_off_season("May I book a trip in July?", summer))
        self.assertTrue(mentions_off_season("viaje el 15/12", summer))


class NewTenantScriptTests(unittest.TestCase):
    def test_template_creates_a_complete_placeholder(self) -> None:
        import importlib
        import shutil
        import tempfile

        sys.path.insert(0, str(ROOT / "scripts"))
        from new_tenant import create_tenant

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tenants").mkdir()
            shutil.copy(ROOT / "tenants" / "__init__.py", root / "tenants" / "__init__.py")
            target = create_tenant("mulas_test", "Mulas Test", root=root)
            self.assertEqual(
                sorted(p.name for p in target.iterdir()),
                ["__init__.py", "datos-clave.md", "phrases.py", "system-prompt.md"],
            )
            with self.assertRaises(FileExistsError):
                create_tenant("mulas_test", "Mulas Test", root=root)
            # Load it as tenants.mulas_test from the temporary tree.
            import tenants

            tenants.__path__.append(str(root / "tenants"))
            try:
                tenant = importlib.import_module("tenants.mulas_test").TENANT
            finally:
                tenants.__path__.remove(str(root / "tenants"))
                sys.modules.pop("tenants.mulas_test", None)
                sys.modules.pop("tenants.mulas_test.phrases", None)
            self.assertTrue(tenant.placeholder)
            self.assertEqual(tenant.validate(), [])
            self.assertIn("Mulas Test", tenant.phrases["es"]["bot_question"])
            self.assertEqual(tenant.integrations.service_name, "mulas-test-orchestrator")

    def test_rejects_bad_slugs(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from new_tenant import create_tenant

        with self.assertRaises(ValueError):
            create_tenant("Bad-Slug", "X")


if __name__ == "__main__":
    unittest.main()
