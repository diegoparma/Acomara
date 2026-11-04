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

TENANT_SLUGS = sorted(p.name for p in (ROOT / "tenants").iterdir() if (p / "__init__.py").exists())


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


if __name__ == "__main__":
    unittest.main()
