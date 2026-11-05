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
| C | Ordenar docs | C (docs) | `docs/sales-agent/15-reglas-de-nico.md`, `docs/estado-nico-para-fernando.md`, `docs/sales-agent/README.md` | pendiente (después de A y B) |
| — | Integración, eval real (≤ USD 4), PR, deploy, verificación | orquestador | todo | pendiente |

## Reporte A (código)

_pendiente_

## Reporte B (prompt)

Cambio en `02-system-prompt.md` (12.847 -> 13.257 bytes, +410): antes de la regla "si no hay información suficiente" se agregaron dos párrafos cortos. (1) Si datos-clave o la hoja inyectada traen la respuesta (precios, qué incluye y qué no, pago, fechas), contestar directo en el idioma del cliente; apunta a la falla 5 (derivar de más), y de paso 6 y 9. (2) Ante preguntas de fechas o cupo, respuesta corta con salidas/temporada conocidas y "la disponibilidad la confirma un asesor", sin confirmar cupo ni callar; apunta a la falla 8. No se tocaron las reglas duras (12+2/14+2, email una vez, idioma, no confirmar cupo). Tests: `pytest -q tests` 406 verdes en la corrida final (una corrida intermedia dio 4 fallas en `test_evals.py`, coincidente con ediciones concurrentes de A). Eval offline (n=320, semilla 7): overall 76,4 (+3,6 vs baseline offline-main), mezclado con los cambios de A y casi sin sensibilidad al prompt.

## Reporte C (docs)

_pendiente_

## Integración y despliegue

_pendiente_
