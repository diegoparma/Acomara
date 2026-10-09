#!/usr/bin/env python3
"""Email verification (HIBP), email capture policy and inbound header parsing.

No network: HIBP is replaced by a fake urlopen. Run with:
    python3 tests/test_security_and_inbound.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import security  # noqa: E402
from orchestrator.inbound import validate_and_normalize_headers  # noqa: E402
from orchestrator.server import apply_email_ack_or_request_policy  # noqa: E402


def _http_error(code: int) -> HTTPError:
    return HTTPError("https://haveibeenpwned.com", code, "err", {}, None)


class CheckEmailReputationTests(unittest.TestCase):
    def _check(self, **urlopen_kwargs):
        with mock.patch.object(security, "urlopen", **urlopen_kwargs) as urlopen:
            result = security.check_email_reputation(" Ana@Gmail.com ", "key")
        return result, urlopen

    def test_breach_history_means_real_account(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value.getcode.return_value = 200
        result, urlopen = self._check(return_value=resp)
        self.assertEqual(result, (False, True))
        req = urlopen.call_args.args[0]
        self.assertIn("/breachedaccount/ana%40gmail.com?truncateResponse=true", req.full_url)
        self.assertEqual(req.get_header("Hibp-api-key"), "key")

    def test_no_breach_history_is_flagged(self):
        result, _ = self._check(side_effect=_http_error(404))
        self.assertEqual(result, (True, True))

    def test_rate_limit_and_errors_fail_open(self):
        for side_effect in (_http_error(429), _http_error(500), URLError("down"), TimeoutError()):
            with self.subTest(side_effect=side_effect):
                result, _ = self._check(side_effect=side_effect)
                self.assertEqual(result, (False, False))

    def test_missing_api_key_skips_the_check(self):
        with mock.patch.object(security, "urlopen") as urlopen:
            self.assertEqual(security.check_email_reputation("a@b.com", ""), (False, False))
        urlopen.assert_not_called()


class ExtractEmailEdgeCaseTests(unittest.TestCase):
    def test_trailing_punctuation_is_dropped(self):
        self.assertEqual(security.extract_email_from_text("mi mail: ana.p@gmail.com."), "ana.p@gmail.com")

    def test_plus_and_subdomains(self):
        self.assertEqual(security.extract_email_from_text("x+tag@mail.co.uk gracias"), "x+tag@mail.co.uk")

    def test_at_sign_without_domain_is_not_an_email(self):
        self.assertIsNone(security.extract_email_from_text("nos vemos @ Mendoza"))


class PauseConversationTests(unittest.TestCase):
    def test_marks_paused_without_mutating_input(self):
        original = {"conversation_turn_count": 2}
        with mock.patch.object(security.time, "time", return_value=1234):
            updated = security.pause_conversation(original, "a@b.com", "bot")
        self.assertEqual(original, {"conversation_turn_count": 2})
        self.assertTrue(updated["conversation_paused"])
        self.assertEqual(updated["pause_reason"], "bot")
        self.assertEqual(updated["paused_at_ts"], 1234)
        self.assertEqual(updated["paused_email"], "a@b.com")

    def test_without_email(self):
        self.assertNotIn("paused_email", security.pause_conversation({}, None, "x"))


class EmailCapturePolicyTests(unittest.TestCase):
    def test_email_shared_is_acknowledged_once(self):
        session = {"conversation_turn_count": 3}
        first = apply_email_ack_or_request_policy("Respuesta IA", session, "ana@gmail.com", "es")
        self.assertIn("Ya tengo tu email", first)
        self.assertEqual(session["captured_email"], "ana@gmail.com")
        self.assertTrue(session["email_requested"])
        self.assertFalse(session["proactive_email_capture_pending"])
        second = apply_email_ack_or_request_policy("Otra respuesta", session, "ana@gmail.com", "es")
        self.assertEqual(second, "Otra respuesta")

    def test_email_requested_once_in_window(self):
        session = {"conversation_turn_count": 3}
        first = apply_email_ack_or_request_policy("Respuesta", session, None, "es")
        self.assertTrue(first.startswith("Respuesta\n\n"))
        self.assertTrue(session["proactive_email_capture_pending"])
        session["conversation_turn_count"] = 4
        self.assertEqual(apply_email_ack_or_request_policy("Otra", session, None, "es"), "Otra")

    def test_no_request_outside_window(self):
        session = {"conversation_turn_count": 1}
        self.assertEqual(apply_email_ack_or_request_policy("Hola", session, None, "en"), "Hola")
        self.assertNotIn("email_requested", session)


class InboundHeadersTests(unittest.TestCase):
    def test_defaults_when_headers_missing(self):
        out = validate_and_normalize_headers({})
        self.assertEqual(out["conversation_id"], "openbsp-conversation")
        self.assertEqual(out["channel"], "whatsapp")
        self.assertEqual(out["contact_id"], "openbsp-contact")

    def test_values_are_stripped_and_stringified(self):
        out = validate_and_normalize_headers({"conversation-id": "  abc ", "contact-id": 42, "x-channel": "web"})
        self.assertEqual(out["conversation_id"], "abc")
        self.assertEqual(out["contact_id"], "42")
        self.assertEqual(out["channel"], "web")

    def test_x_prefixed_contact_fallbacks(self):
        out = validate_and_normalize_headers({"x-contact-id": "c9", "x-contact-address": "+549"})
        self.assertEqual(out["contact_id"], "c9")
        self.assertEqual(out["contact_address"], "+549")

    def test_oversized_header_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_and_normalize_headers({"conversation-id": "x" * 1001})


if __name__ == "__main__":
    unittest.main(verbosity=2)
