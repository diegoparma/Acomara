# 19 · Cierre orquestado (2026-11-05)

Tablero compartido del pase final de mejoras sobre Nico. El orquestador planifica, delega en subagentes,
integra en una sola rama y despliega. Cada subagente agrega su reporte en su sección.

- Rollback: rama `claude/pre-cierre-2` = `origin/main` antes del pase (`df095e9`).
- Rama de trabajo: `claude/lucid-dirac-wa6foy`.
- Validación gratis: `python -m pytest -q tests` y `python scripts/run_evals.py --offline --n 320 --seed 7 --compare evals/baselines/offline-main/summary.json`.
- Punto de partida medido hoy: 406 tests OK; offline n=320 seed 7 = **76.4** (offline-main guardado = 72.8, de un commit anterior).

## Tareas

| # | Tarea | Subagente | Archivos que puede tocar | Estado |
|---|---|---|---|---|
| A | Arreglos de frases fijas en código | A (código) | `orchestrator/server.py`, `orchestrator/policies.py`, `orchestrator/sales_rules.py`, `orchestrator/humanize.py`, `orchestrator/usted.py`, `tests/test_cierre_fixes.py` | en curso |
| B | Ajustes de prompt/voz según `fallas-top10.md` | B (prompt) | `docs/sales-agent/02-system-prompt.md` | hecho |
| C | Ordenar docs | C (docs) | `docs/sales-agent/15-reglas-de-nico.md`, `docs/estado-nico-para-fernando.md`, `docs/sales-agent/README.md` | hecho |
| — | Integración, eval real (≤ USD 4), PR, deploy, verificación | orquestador | todo | pendiente |

## Reporte A (código)

Todo en código determinista, sin llamadas a OpenAI. Tests: **426 OK** (406 + 20 nuevos en `tests/test_cierre_fixes.py`). Un test existente cambió a propósito (`tests/test_followups.py::test_burst_duplicate_is_dropped`: ahora la repetición dentro de la ráfaga devuelve una frase corta, no vacío).

1. **Primer mensaje con datos.** `server.py::is_generic_opening` ya no devuelve verdadero si el mensaje trae datos del cliente o un pedido concreto (`_OPENING_DATA_RE`: "nunca estuve en altura", "somos 3", fechas, país, experiencia...). Va al camino normal (LLM). "Hola", "Buenas" y "Hola, quiero info" siguen con la bienvenida.
2. **`/reset` por `/v1/chat/completions`.** `server.py::build_reset_session_vars` ahora pisa también `customer_name`, `emails_seen`, `captured_email`, `email_captured`, `email_received_acked`, `email_declined`, `out_of_season_warned`, `thanks_reply_count`, `program_options_stage`, `repeat_alt_count`, `new_lead_email_sent`, etc. El store de sesiones hace merge al hacer upsert (y el delete puede fallar), así que esas claves sobrevivían al reset. Además `extract_command` tolera BOM, comillas y puntuación (`/reset.`, `"/reset"`).
3. **Email.** `policies.py::declines_or_defers_email` detecta "después te lo paso", "prefiero no darlo", etc. (es/en/pt); `process_inbound_message` marca `email_declined` + `email_requested`, y `drop_repeated_email_ask` lo respeta. Pedido de derivación: ya no repregunta el email si ya hay uno capturado (aunque falle o esté pendiente la verificación), visto o rechazado (`email_not_needed`).
4. **Portugués.** `server.py::_PT_ONLY_RE` (quanto, custa, permissão, cume, tudo bem, boa tarde...) para detectar pt en mensajes cortos que se leían como español; `_followup_program_options_reply` ahora tiene versión pt; las frases nuevas `repeat_alt_*` existen en es/en/pt.
5. **Silencios.** `server.py::resolve_duplicate_reply`: dentro de los 30 s ya no devuelve vacío; manda una de 4 frases cortas rotativas (`repeat_alt_1..4`, contador `repeat_alt_count`). Sigue el descarte solo en el caso de dos requests realmente paralelos (relectura de sesión en el endpoint) y el silencio de conversación pausada (regla 7), que es por diseño.
6. **Voseo.** `humanize.py::_USTED_RE` suma "quisiera/quisiéramos"; nuevo `client_uses_tuteo` + `usted.py::to_tuteo` (querés→quieres, pasame→pásame, escribís→escribes...) para quien escribe de "tú"; `to_usted` suma "¿Estuviste en altura alguna vez?" y "Mirá/Fijate".

**Cambio de comportamiento para el manual (`15-reglas-de-nico.md`)**: regla 15 ya no calla dentro de los 30 s: manda una frase corta distinta ("Eso mismo te lo dejé en el mensaje anterior..."); solo se calla si es un request paralelo. Regla 5/6: no se repregunta el email si ya hay uno (aunque no esté verificado) o el cliente dijo que lo pasa después/prefiere no darlo; la derivación sigue sin pedirlo. La bienvenida fija solo sale para saludos o interés sin datos. El registro del idioma pt usa más palabras exclusivas del portugués.

**Offline n=320 seed 7**: overall **76.4 -> 81.7** (offline-main guardado 72.8). `EMPTY_REPLY` 172 -> **9** conversaciones (el resto son pausas por diseño); `VOSEO_WITH_USTED` 53 -> **24** (lo que queda es "Si querés, pasame tu email" a personas "es_neutro" que no dan ninguna marca de registro en sus mensajes, no se puede detectar). `IDENTICAL_REPLY` sube 248 -> 261 porque el stub repite siempre la misma respuesta y ahora las repeticiones salen como frase corta en lugar de silencio; con el modelo real no pasa.


## Reporte B (prompt)

Cambio en `02-system-prompt.md` (12.847 -> 13.257 bytes, +410): antes de la regla "si no hay información suficiente" se agregaron dos párrafos cortos. (1) Si datos-clave o la hoja inyectada traen la respuesta (precios, qué incluye y qué no, pago, fechas), contestar directo en el idioma del cliente; apunta a la falla 5 (derivar de más), y de paso 6 y 9. (2) Ante preguntas de fechas o cupo, respuesta corta con salidas/temporada conocidas y "la disponibilidad la confirma un asesor", sin confirmar cupo ni callar; apunta a la falla 8. No se tocaron las reglas duras (12+2/14+2, email una vez, idioma, no confirmar cupo). Tests: `pytest -q tests` 406 verdes en la corrida final (una corrida intermedia dio 4 fallas en `test_evals.py`, coincidente con ediciones concurrentes de A). Eval offline (n=320, semilla 7): overall 76,4 (+3,6 vs baseline offline-main), mezclado con los cambios de A y casi sin sensibilidad al prompt.

## Reporte C (docs)

Solo documentación. `15-reglas-de-nico.md`: actualizadas reglas 1 (/reset completo, también por chat/completions), 2, 6 (email no repreguntado), 8/8a (bienvenida solo sin datos), 15 (frase corta rotativa en vez de silencio), sección Idioma (frases fijas en pt, detección de portugués, tuteo/usted) y sección 3 (responder directo con datos-clave/planilla; fechas con "la disponibilidad la confirma un asesor"); numeración intacta. `estado-nico-para-fernando.md`: nueva sección "Qué cambió esta semana" marcada como pendiente de despliegue. `sales-agent/README.md`: índice nuevo. Tests: 426 OK.

## Integración y despliegue

_pendiente_
