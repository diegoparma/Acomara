#!/usr/bin/env python3
"""Fixed phrases switch to "usted" for clients who write formally.

No network. Run with:
    python3 tests/test_usted.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import sales_rules  # noqa: E402
from orchestrator.humanize import humanize_reply  # noqa: E402
from orchestrator.server import I18N_PHRASES  # noqa: E402
from orchestrator.usted import USTED_PHRASES, to_usted  # noqa: E402

_VOS_WORDS = ("querés", "pasame", "decime", "avisame", "contame", "escribís", "dejás", " tu ", " te ")


def _spanish_sources() -> str:
    texts = list(I18N_PHRASES["es"].values())
    for name in dir(sales_rules):
        value = getattr(sales_rules, name)
        if isinstance(value, dict) and isinstance(value.get("es"), str):
            texts.append(value["es"])
    return "\n".join(texts)


class UstedPhrasesTests(unittest.TestCase):
    def test_every_phrase_still_exists_in_the_code(self):
        sources = _spanish_sources()
        for phrase in USTED_PHRASES:
            with self.subTest(phrase=phrase[:50]):
                self.assertIn(phrase, sources)

    def test_every_vos_phrase_in_the_code_has_an_usted_version(self):
        for key, text in I18N_PHRASES["es"].items():
            with self.subTest(key=key):
                converted = to_usted(text.replace("{email}", "ana@example.com"))
                self.assertFalse(any(w in f" {converted} " for w in _VOS_WORDS), converted)

    def test_usted_versions_have_no_vos_and_are_clean(self):
        for target in USTED_PHRASES.values():
            with self.subTest(target=target[:50]):
                self.assertFalse(any(w in f" {target} " for w in _VOS_WORDS), target)
                if target.endswith(","):  # a prefix glued to another reply
                    continue
                plain = target.replace("{", "").replace("}", "")
                self.assertEqual(humanize_reply(plain), plain.strip())

    def test_phrase_inside_a_model_reply(self):
        reply = "El permiso va aparte.\n\n" + I18N_PHRASES["es"]["proactive_email_request"]
        self.assertEqual(
            to_usted(reply),
            "El permiso va aparte.\n\nSi quiere, páseme su email y le mando el detalle completo con precios y fechas.",
        )

    def test_placeholders_are_carried_over(self):
        ack = I18N_PHRASES["es"]["email_received_ack"].format(email="ana@example.com")
        out = to_usted(ack)
        self.assertIn("Ya tengo su email (ana@example.com)", out)
        self.assertIn("cuénteme", out)
        alt = sales_rules.EXTENDED_ALTERNATIVE["es"].format(picked="5/12", program="14+2", alt="8/12")
        self.assertIn("Si no es su caso, le conviene el 18+2, que cuesta lo mismo: la salida más cercana es el 8/12.", to_usted(alt))

    def test_model_text_is_left_alone(self):
        text = "Si querés te cuento más del 18+2."
        self.assertEqual(to_usted(text), text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
