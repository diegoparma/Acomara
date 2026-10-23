#!/usr/bin/env python3
"""Tests for the SGI endpoint path of the CRM client checker.

No network: requests.post is patched. Run with:
    python3 tests/test_crm_client_status.py
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import crm_client_status  # noqa: E402
from orchestrator.crm_client_status import check_client_status  # noqa: E402

ENV = {"CRM_STATUS_URL": "https://sgi.example/nico_cliente_status.php", "CRM_STATUS_TOKEN": "t"}


def fake_response(status: int, payload: dict | None = None):
    response = mock.Mock(status_code=status)
    response.json.return_value = payload or {}
    response.raise_for_status.side_effect = None if status < 400 else Exception(f"HTTP {status}")
    return response


class EndpointTests(unittest.TestCase):
    def test_found_client_with_consultations(self):
        payload = {"found": True, "client_id": 7, "client_name": "Ana Pérez",
                   "consultation_count": 3, "last_consultation_date": "2026-09-01", "search_by": "phone"}
        with mock.patch.dict(os.environ, ENV), \
             mock.patch.object(crm_client_status.requests, "post", return_value=fake_response(200, payload)) as post:
            result = check_client_status(phone="5492611234567")
        self.assertTrue(result["found"])
        self.assertTrue(result["contacted"])
        self.assertEqual(result["consultation_count"], 3)
        self.assertEqual(result["client_name"], "Ana Pérez")
        self.assertEqual(post.call_args.kwargs["headers"], {"X-Nico-Token": "t"})

    def test_registered_without_consultations_is_not_contacted(self):
        payload = {"found": True, "client_id": 8, "client_name": "Bo", "consultation_count": 0, "search_by": "email"}
        with mock.patch.dict(os.environ, ENV), \
             mock.patch.object(crm_client_status.requests, "post", return_value=fake_response(200, payload)):
            result = check_client_status(email="bo@example.com")
        self.assertTrue(result["found"])
        self.assertFalse(result["contacted"])

    def test_not_found(self):
        with mock.patch.dict(os.environ, ENV), \
             mock.patch.object(crm_client_status.requests, "post", return_value=fake_response(200, {"found": False})):
            result = check_client_status(phone="5492611234567")
        self.assertFalse(result["found"])
        self.assertNotIn("error", result)

    def test_rejected_input_is_treated_as_not_found(self):
        with mock.patch.dict(os.environ, ENV), \
             mock.patch.object(crm_client_status.requests, "post", return_value=fake_response(400, {"error": "input"})):
            result = check_client_status(phone="123")
        self.assertFalse(result["found"])
        self.assertNotIn("error", result)

    def test_endpoint_failure_does_not_raise(self):
        with mock.patch.dict(os.environ, ENV), \
             mock.patch.object(crm_client_status.requests, "post", side_effect=Exception("timeout")):
            result = check_client_status(phone="5492611234567")
        self.assertFalse(result["found"])
        self.assertIn("error", result)

    def test_without_env_uses_mysql(self):
        env = {k: v for k, v in os.environ.items() if k not in ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(crm_client_status, "get_db_connection", side_effect=Exception("no db")) as db, \
             mock.patch.object(crm_client_status.requests, "post") as post:
            check_client_status(phone="5492611234567")
        db.assert_called_once()
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
