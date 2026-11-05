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
| B | Ajustes de prompt/voz según `fallas-top10.md` | B (prompt) | `docs/sales-agent/02-system-prompt.md` | en curso |
| C | Ordenar docs | C (docs) | `docs/sales-agent/15-reglas-de-nico.md`, `docs/estado-nico-para-fernando.md`, `docs/sales-agent/README.md` | pendiente (después de A y B) |
| — | Integración, eval real (≤ USD 4), PR, deploy, verificación | orquestador | todo | pendiente |

## Reporte A (código)

_pendiente_

## Reporte B (prompt)

_pendiente_

## Reporte C (docs)

_pendiente_

## Integración y despliegue

_pendiente_
