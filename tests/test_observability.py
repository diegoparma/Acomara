#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.observability import (
    _normalize_deployment_url,
    _resolve_app_version,
    build_safe_version_response,
    build_version_payload,
    build_version_text,
)


def _env_from_dict(values: dict[str, str]):
    def _env(key: str, default: str | None = None) -> str | None:
        return values.get(key, default)

    return _env


class VersionPayloadTests(unittest.TestCase):
    def test_normalize_vercel_url_adds_https(self):
        self.assertEqual(
            _normalize_deployment_url("acomara-orchestrator.vercel.app"),
            "https://acomara-orchestrator.vercel.app",
        )

    def test_payload_exposes_deployment_id_and_url(self):
        payload = build_version_payload(
            env=_env_from_dict(
                {
                    "VERCEL_ENV": "production",
                    "VERCEL_GIT_COMMIT_SHA": "0a17f1600a81b4f7",
                    "VERCEL_DEPLOYMENT_ID": "dpl_abc123",
                    "VERCEL_URL": "acomara-orchestrator.vercel.app",
                }
            ),
            is_cloud_runtime=lambda: True,
            python_version="3.12.13",
        )
        self.assertEqual(payload["deployment_id"], "dpl_abc123")
        self.assertEqual(payload["deployment_url"], "https://acomara-orchestrator.vercel.app")
        self.assertEqual(payload["deployment"], "dpl_abc123")

    def test_safe_response_includes_deployment_fields(self):
        payload = build_version_payload(
            env=_env_from_dict(
                {
                    "VERCEL_ENV": "production",
                    "VERCEL_GIT_COMMIT_SHA": "0a17f1600a81b4f7",
                    "VERCEL_DEPLOYMENT_ID": "dpl_abc123",
                    "VERCEL_URL": "acomara-orchestrator.vercel.app",
                }
            ),
            is_cloud_runtime=lambda: True,
            python_version="3.12.13",
        )
        safe = build_safe_version_response(payload)
        self.assertEqual(safe["deployment_id"], "dpl_abc123")
        self.assertEqual(safe["deployment_url"], "https://acomara-orchestrator.vercel.app")

    def test_text_includes_deployment_details(self):
        payload = build_version_payload(
            env=_env_from_dict(
                {
                    "VERCEL_ENV": "production",
                    "VERCEL_GIT_COMMIT_SHA": "0a17f1600a81b4f7",
                    "VERCEL_DEPLOYMENT_ID": "dpl_abc123",
                    "VERCEL_URL": "acomara-orchestrator.vercel.app",
                }
            ),
            is_cloud_runtime=lambda: True,
            python_version="3.12.13",
        )
        text = build_version_text(payload)
        self.assertIn("Deployment ID: dpl_abc123", text)
        self.assertIn("Deployment URL: https://acomara-orchestrator.vercel.app", text)

    def test_auto_version_uses_commit_when_app_version_missing(self):
        payload = build_version_payload(
            env=_env_from_dict(
                {
                    "VERCEL_ENV": "production",
                    "VERCEL_GIT_COMMIT_SHA": "0a17f1600a81b4f7",
                    "VERCEL_DEPLOYMENT_ID": "dpl_abc123",
                }
            ),
            is_cloud_runtime=lambda: True,
            python_version="3.12.13",
        )
        self.assertEqual(payload["version"], "git-0a17f1600a81")

    def test_app_version_explicit_override(self):
        payload = build_version_payload(
            env=_env_from_dict(
                {
                    "VERCEL_ENV": "production",
                    "VERCEL_GIT_COMMIT_SHA": "0a17f1600a81b4f7",
                    "VERCEL_DEPLOYMENT_ID": "dpl_abc123",
                    "APP_VERSION": "2026-06-09.0a17f16",
                }
            ),
            is_cloud_runtime=lambda: True,
            python_version="3.12.13",
        )
        self.assertEqual(payload["version"], "2026-06-09.0a17f16")

    def test_resolve_app_version_fallback_to_deployment(self):
        env = _env_from_dict({})
        self.assertEqual(_resolve_app_version(env, "unknown", "dpl_abc123"), "deploy-dpl_abc123")


if __name__ == "__main__":
    unittest.main()
