#!/usr/bin/env python3
"""Volatile facts from Fernando's sheet (orchestrator/live_facts.py).

No network: every fetch goes through a fake fetcher. Run with:
    python3 tests/test_live_facts.py
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import live_facts as lf  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "live_facts"
KEY_FACTS = ROOT / "docs" / "knowledge" / "datos-clave.md"
SEED = ROOT / "docs" / "sales-agent" / "planilla-datos-semilla.csv"
URL = "https://docs.google.com/spreadsheets/d/x/export?format=csv"
TODAY = date(2026, 11, 4)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _ts(year: int, month: int, day: int, hour: int = 15) -> float:
    return datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp()


class FakeFetcher:
    def __init__(self, *responses: str | Exception) -> None:
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, url: str, timeout: float) -> str:
        self.calls += 1
        item = self.responses[min(self.calls, len(self.responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        lf.reset_cache()
        self.env = mock.patch.dict(os.environ, {"NICO_FACTS_CSV_URL": URL}, clear=False)
        self.env.start()
        os.environ.pop("NICO_FACTS_TTL_SECONDS", None)

    def tearDown(self) -> None:
        self.env.stop()
        lf.reset_cache()


class ParsingTest(_Base):
    def test_parses_spanish_headers_and_rows(self) -> None:
        facts, skipped = lf.parse_csv(_fixture("valid.csv"))
        self.assertEqual(skipped, 0)
        self.assertEqual([f.key for f in facts], ["precio-regular", "promo", "seguro", "permiso", "temporada"])
        precio = facts[0]
        self.assertEqual(precio.topic, "Precio")
        self.assertEqual(precio.text, "Precio regular USD 7.250 por persona.")
        self.assertEqual(precio.valid_until, date(2027, 3, 31))
        self.assertEqual(precio.confirmed_by, "Fernando")

    def test_header_variants_bom_crlf_case_accents(self) -> None:
        facts, _ = lf.parse_csv("﻿" + _fixture("headers_variants.csv").lstrip("﻿"))
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].key, "anticipo")
        self.assertEqual(facts[0].state(TODAY), "vigente")  # "Vigénte" counts as Vigente

    def test_spanish_locale_date(self) -> None:
        self.assertEqual(lf.parse_date("30/10/2026"), date(2026, 10, 30))
        self.assertEqual(lf.parse_date("2026-10-30"), date(2026, 10, 30))
        self.assertIsNone(lf.parse_date("pronto"))
        self.assertIsNone(lf.parse_date(""))

    def test_missing_columns_rejected(self) -> None:
        with self.assertRaises(lf.FactsParseError):
            lf.parse_csv(_fixture("missing_columns.csv"))

    def test_html_login_page_rejected(self) -> None:
        with self.assertRaises(lf.FactsParseError):
            lf.parse_csv(_fixture("login_page.html"))

    def test_seed_csv_imports_cleanly(self) -> None:
        facts, skipped = lf.parse_csv(SEED.read_text(encoding="utf-8"))
        self.assertEqual(skipped, 0)
        by_key = {f.key: f for f in facts}
        self.assertFalse(any(f.rejected for f in facts))
        self.assertEqual(by_key["temporada"].state(TODAY), "a_confirmar")
        for key in ("precio_regular", "precio_promo", "precio_privada", "trek_plaza_mulas",
                    "trek_plaza_francia", "anticipo", "pago_paypal", "pago_transferencia",
                    "pago_usdt", "pago_tarjeta", "permiso_parque", "seguro_rescate", "alquiler_equipo"):
            self.assertEqual(by_key[key].state(TODAY), "vigente", key)

    def test_shared_topic_names_the_row_to_confirm(self) -> None:
        csv_text = (
            "Clave,Tema,Qué puede decir Nico,Estado,Vigente hasta\n"
            "precio_regular,Precios,Precio regular USD 7.250.,Vigente,2027-02-28\n"
            "precio_promo,Precios,Promo USD 5.990.,Vigente,2026-11-01\n"
        )
        facts, _ = lf.parse_csv(csv_text)
        block = lf.render_block(facts, TODAY)
        self.assertIn("- Precios: Precio regular USD 7.250.", block)
        confirm = block.split("## A confirmar por un asesor", 1)[1]
        self.assertIn("- Precios (precio promo)", confirm)
        self.assertNotIn("- Precios\n", confirm + "\n")


class ValidityTest(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.facts, _ = lf.parse_csv(_fixture("valid.csv"))
        self.by_key = {f.key: f for f in self.facts}

    def test_states(self) -> None:
        self.assertEqual(self.by_key["precio-regular"].state(TODAY), "vigente")
        self.assertEqual(self.by_key["seguro"].state(TODAY), "vigente")  # empty date = no expiry
        self.assertEqual(self.by_key["permiso"].state(TODAY), "vencido")
        self.assertEqual(self.by_key["temporada"].state(TODAY), "a_confirmar")

    def test_last_valid_day_is_inclusive(self) -> None:
        promo = self.by_key["promo"]
        self.assertEqual(promo.state(date(2026, 11, 10)), "vigente")
        self.assertEqual(promo.state(date(2026, 11, 11)), "vencido")

    def test_unreadable_date_is_not_valid(self) -> None:
        facts, _ = lf.parse_csv("Clave,Tema,Qué puede decir Nico,Estado,Vigente hasta\nx,X,Dato.,Vigente,pronto\n")
        self.assertEqual(facts[0].state(TODAY), "vencido")

    def test_expiry_uses_argentina_time(self) -> None:
        # 2026-11-11 01:00 UTC is still 2026-11-10 22:00 in Mendoza.
        self.assertEqual(lf.today_argentina(datetime(2026, 11, 11, 1, tzinfo=timezone.utc)), date(2026, 11, 10))
        self.assertEqual(lf.today_argentina(datetime(2026, 11, 11, 4, tzinfo=timezone.utc)), date(2026, 11, 11))

    def test_block_only_gives_valid_rows_as_facts(self) -> None:
        block = lf.render_block(self.facts, TODAY)
        self.assertTrue(block.startswith("# DATOS QUE CAMBIAN"))
        self.assertIn("USD 7.250", block)
        self.assertIn("USD 400", block)
        self.assertIn("USD 5.990", block)
        # Expired permit and the "A confirmar" season are not given as facts...
        self.assertNotIn("USD 650", block)
        self.assertNotIn("noviembre a marzo", block)
        # ...but the model is told those topics go to an advisor.
        confirm = block.split("## A confirmar por un asesor", 1)[1]
        self.assertIn("- Permiso del Parque", confirm)
        self.assertIn("- Temporada", confirm)
        self.assertIn("lo confirma un asesor", confirm)

    def test_block_after_expiry_moves_row(self) -> None:
        block = lf.render_block(self.facts, date(2026, 11, 11))
        self.assertNotIn("USD 5.990", block)
        self.assertIn("- Promociones", block.split("## A confirmar por un asesor", 1)[1])


class SanitizeTest(_Base):
    def test_injection_row_not_used_as_fact(self) -> None:
        facts, _ = lf.parse_csv(_fixture("injection.csv"))
        by_key = {f.key: f for f in facts}
        self.assertTrue(by_key["precio"].rejected)
        self.assertTrue(by_key["raro"].rejected)
        self.assertEqual(by_key["raro"].topic, "raro")  # suspicious topic not echoed
        block = lf.render_block(facts, TODAY)
        self.assertNotIn("descuento", block)
        self.assertNotIn("im_start", block)
        self.assertNotIn("SYSTEM", block)
        self.assertIn("- precio", block.split("## A confirmar por un asesor", 1)[1])

    def test_urls_outside_allowlist_removed(self) -> None:
        facts, _ = lf.parse_csv(_fixture("injection.csv"))
        pago = {f.key: f for f in facts}["pago"]
        self.assertFalse(pago.rejected)
        self.assertNotIn("evil.example.com", pago.text)
        self.assertIn("(enlace quitado)", pago.text)
        self.assertIn("www.aconcaguaexpeditions.com/booking", pago.text)

    def test_cell_flattened_and_capped(self) -> None:
        text = lf.sanitize_cell("línea 1\n## línea 2​\t**negrita** " + "x " * 500, lf.MAX_FACT_CHARS)
        self.assertNotIn("\n", text)
        self.assertNotIn("#", text)
        self.assertNotIn("*", text)
        self.assertNotIn("​", text)
        self.assertLessEqual(len(text), lf.MAX_FACT_CHARS + 1)

    def test_total_size_capped(self) -> None:
        rows = "\n".join(f"k{i},Tema {i},{'Dato largo de precio. ' * 18},Vigente," for i in range(200))
        facts, skipped = lf.parse_csv("Clave,Tema,Qué puede decir Nico,Estado,Vigente hasta\n" + rows)
        self.assertEqual(len(facts), lf.MAX_ROWS)
        self.assertEqual(skipped, 200 - lf.MAX_ROWS)
        self.assertLess(len(lf.render_block(facts, TODAY)), lf.MAX_BLOCK_CHARS + 1_500)

    def test_duplicate_and_empty_keys_skipped(self) -> None:
        csv_text = "Clave,Tema,Qué puede decir Nico,Estado\na,A,Uno.,Vigente\na,A,Dos.,Vigente\n,B,Tres.,Vigente\n,,,\n"
        facts, skipped = lf.parse_csv(csv_text)
        self.assertEqual([f.text for f in facts], ["Uno."])
        self.assertEqual(skipped, 2)


class CacheAndFallbackTest(_Base):
    def test_env_unset_is_exactly_datos_clave(self) -> None:
        os.environ.pop("NICO_FACTS_CSV_URL")
        fetcher = FakeFetcher(_fixture("valid.csv"))
        self.assertEqual(lf.key_facts_text(KEY_FACTS, fetcher=fetcher), KEY_FACTS.read_text(encoding="utf-8"))
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(lf.revision(fetcher=fetcher), "datos-clave")
        self.assertEqual(lf.status()["source"], "datos-clave.md")

    def test_never_loaded_falls_back_to_datos_clave(self) -> None:
        fetcher = FakeFetcher(OSError("timeout"))
        text = lf.key_facts_text(KEY_FACTS, now=_ts(2026, 11, 4), fetcher=fetcher)
        self.assertEqual(text, KEY_FACTS.read_text(encoding="utf-8"))
        status = lf.status()
        self.assertEqual(status["source"], "datos-clave.md")
        self.assertIn("timeout", status["last_error"])

    def test_sheet_block_appended_after_datos_clave(self) -> None:
        fetcher = FakeFetcher(_fixture("valid.csv"))
        text = lf.key_facts_text(KEY_FACTS, now=_ts(2026, 11, 4), fetcher=fetcher)
        self.assertTrue(text.startswith(KEY_FACTS.read_text(encoding="utf-8").rstrip()))
        self.assertGreater(text.index("# DATOS QUE CAMBIAN"), text.index("# DATOS CLAVE"))

    def test_cache_within_ttl(self) -> None:
        fetcher = FakeFetcher(_fixture("valid.csv"))
        t0 = _ts(2026, 11, 4)
        lf.get_snapshot(now=t0, fetcher=fetcher)
        lf.get_snapshot(now=t0 + 599, fetcher=fetcher)
        self.assertEqual(fetcher.calls, 1)
        lf.get_snapshot(now=t0 + 601, fetcher=fetcher)
        self.assertEqual(fetcher.calls, 2)

    def test_ttl_from_env(self) -> None:
        os.environ["NICO_FACTS_TTL_SECONDS"] = "60"
        fetcher = FakeFetcher(_fixture("valid.csv"))
        t0 = _ts(2026, 11, 4)
        lf.get_snapshot(now=t0, fetcher=fetcher)
        lf.get_snapshot(now=t0 + 61, fetcher=fetcher)
        self.assertEqual(fetcher.calls, 2)

    def test_failure_keeps_last_good_copy(self) -> None:
        good = _fixture("valid.csv")
        fetcher = FakeFetcher(good, OSError("HTTP 500"), _fixture("login_page.html"), _fixture("missing_columns.csv"))
        t0 = _ts(2026, 11, 4)
        first = lf.get_snapshot(now=t0, fetcher=fetcher)
        for step in (1, 2, 3):
            snap = lf.get_snapshot(now=t0 + 700 * step, fetcher=fetcher)
            self.assertIs(snap, first)
        self.assertEqual(fetcher.calls, 4)
        self.assertEqual(lf.status(now=t0)["source"], "sheet")
        self.assertIsNotNone(lf.status(now=t0)["last_error"])

    def test_failure_backs_off(self) -> None:
        fetcher = FakeFetcher(OSError("down"))
        t0 = _ts(2026, 11, 4)
        lf.get_snapshot(now=t0, fetcher=fetcher)
        lf.get_snapshot(now=t0 + 10, fetcher=fetcher)
        self.assertEqual(fetcher.calls, 1)
        lf.get_snapshot(now=t0 + lf.FAILURE_RETRY_SECONDS + 1, fetcher=fetcher)
        self.assertEqual(fetcher.calls, 2)

    def test_revision_changes_with_content_and_day(self) -> None:
        fetcher = FakeFetcher(_fixture("valid.csv"), _fixture("headers_variants.csv"))
        t0 = _ts(2026, 11, 4)
        r1 = lf.revision(now=t0, fetcher=fetcher)
        self.assertEqual(lf.revision(now=t0 + 10, fetcher=fetcher), r1)
        r2 = lf.revision(now=t0 + 700, fetcher=fetcher)
        self.assertNotEqual(r2, r1)
        # Same content, next day in Argentina: the prompt must be re-rendered.
        self.assertNotEqual(lf.revision(now=t0 + 86_400, fetcher=fetcher), r2)

    def test_status_counts(self) -> None:
        lf.get_snapshot(now=_ts(2026, 11, 4), fetcher=FakeFetcher(_fixture("valid.csv")))
        status = lf.status(now=_ts(2026, 11, 4))
        self.assertEqual(status["source"], "sheet")
        self.assertEqual(status["rows_valid"], 3)
        self.assertEqual(status["rows_expired"], 1)
        self.assertEqual(status["rows_to_confirm"], 1)
        self.assertIsNotNone(status["loaded_at"])


class ReminderTest(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.sent: list[tuple[dict, str, str]] = []

    def _sender(self, runtime: dict, subject: str, body: str):
        self.sent.append((runtime, subject, body))
        return True, 200, {"ok": True}

    def test_report_lists_expired_and_expiring(self) -> None:
        facts, _ = lf.parse_csv(_fixture("valid.csv"))
        report = lf.expiry_report(facts, TODAY)
        self.assertEqual([f.key for f in report["expired"]], ["permiso"])
        self.assertEqual([f.key for f in report["expiring"]], ["promo"])  # 2026-11-10, within 14 days
        self.assertEqual([f.key for f in report["to_confirm"]], ["temporada"])

    def test_sends_email_once_a_week(self) -> None:
        fetcher = FakeFetcher(_fixture("valid.csv"))
        t0 = _ts(2026, 11, 4)
        with mock.patch.dict(os.environ, {"HANDOFF_EMAIL_TO": "ventas@example.com", "NICO_FACTS_REMINDER_TO": "fer@example.com"}):
            result = lf.send_expiry_reminder(now=t0, fetcher=fetcher, sender=self._sender)
            self.assertTrue(result["sent"])
            runtime, subject, body = self.sent[0]
            self.assertEqual(runtime["handoff_email_to"], "fer@example.com")
            self.assertIn("1 vencidos, 1 por vencer", subject)
            self.assertIn("permiso", body)
            self.assertIn("promo", body)
            again = lf.send_expiry_reminder(now=t0 + 3600, fetcher=fetcher, sender=self._sender)
            self.assertFalse(again["sent"])
            self.assertEqual(len(self.sent), 1)
            forced = lf.send_expiry_reminder(now=t0 + 7200, force=True, fetcher=fetcher, sender=self._sender)
            self.assertTrue(forced["sent"])
            later = lf.send_expiry_reminder(now=t0 + 7 * 86_400, fetcher=fetcher, sender=self._sender)
            self.assertTrue(later["sent"])

    def test_nothing_to_report_sends_nothing(self) -> None:
        csv_text = "Clave,Tema,Qué puede decir Nico,Estado,Vigente hasta\na,A,Uno.,Vigente,2027-03-31\n"
        result = lf.send_expiry_reminder(now=_ts(2026, 11, 4), fetcher=FakeFetcher(csv_text), sender=self._sender)
        self.assertFalse(result["sent"])
        self.assertEqual(self.sent, [])

    def test_no_sheet_sends_nothing(self) -> None:
        os.environ.pop("NICO_FACTS_CSV_URL")
        result = lf.send_expiry_reminder(now=_ts(2026, 11, 4), sender=self._sender)
        self.assertFalse(result["sent"])
        self.assertEqual(self.sent, [])


class ServerHookTest(_Base):
    def test_system_prompt_and_version_use_sheet(self) -> None:
        from orchestrator import server

        lf.get_snapshot(fetcher=FakeFetcher(_fixture("valid.csv")))
        prompt = server.load_system_prompt()
        self.assertIn("# DATOS CLAVE", prompt)
        self.assertIn("# DATOS QUE CAMBIAN", prompt)
        client = server.app.test_client()
        data = client.get("/version").get_json()
        self.assertEqual(data["facts"]["source"], "sheet")

    def test_reminder_endpoint_requires_secret(self) -> None:
        from orchestrator import server

        client = server.app.test_client()
        with mock.patch.dict(os.environ, {"CRON_SECRET": "s3cret", "ORCHESTRATOR_API_KEY": ""}):
            self.assertEqual(client.get("/cron/facts-reminder").status_code, 401)
            with mock.patch.object(lf, "send_expiry_reminder", return_value={"sent": False}) as fake:
                resp = client.get("/cron/facts-reminder", headers={"Authorization": "Bearer s3cret"})
                self.assertEqual(resp.status_code, 200)
                fake.assert_called_once_with(force=False)


if __name__ == "__main__":
    unittest.main()
