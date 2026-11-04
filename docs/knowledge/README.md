# Conocimiento de Nico

Todo lo que Nico sabe sale de **`fuente/`**. El resto de esta carpeta se genera: no se edita a mano.

| Qué querés cambiar | Dónde |
|---|---|
| Un precio, porcentaje, seña, link | `fuente/valores.yaml` (una sola vez; se reemplaza en todos lados) |
| Fechas de salida | `fuente/salidas.yaml` |
| Un dato que Nico tiene que saber siempre (va fijo en el prompt) | `fuente/datos-clave.yaml` |
| Una pregunta frecuente, o cómo la preguntan los clientes | `fuente/faq.yaml` (`also_asked`) |

Después de editar:

```bash
python3 scripts/build_knowledge.py
```

```bash
python3 scripts/build_cloud_index.py
```

El primero regenera `datos-clave.md`, `faq_rag_chunks.jsonl` y `faq_structured.md` (sin red). El segundo actualiza el índice de búsqueda `faq_cloud_index.jsonl`; necesita `OPENAI_API_KEY` y solo vuelve a calcular los fragmentos que cambiaron. Para ver qué falta sin clave: `python3 scripts/build_cloud_index.py --check`.

Antes de subir, `python3 tests/test_knowledge_base.py` revisa que:
- lo generado esté al día con `fuente/`;
- ningún precio confirmado esté escrito a mano fuera de `valores.yaml`;
- ningún texto que lee el cliente (prompt, reglas, FAQ, índice, docs de estado) mencione un monto en USD que no esté en `fuente/`;
- no haya valores vencidos (`valid_until`);
- la búsqueda por palabras clave no empeore (set de preguntas en `eval/`).

## Cómo se usa cada archivo

- `datos-clave.md` → se agrega al prompt de sistema (`orchestrator/server.py`, `load_system_prompt`). Vale más que el FAQ.
- `faq_cloud_index.jsonl` → lo que Nico busca en cada mensaje (top 4). Lo leen también `orchestrator/departures.py` (fechas) y `sales_rules.py`.
- `faq_structured.md` → para leer: valores vigentes con su fuente y el FAQ por tema.
- `eval/preguntas-busqueda.yaml` → preguntas de clientes etiquetadas; `python3 scripts/eval_retrieval.py` mide si se encuentra la respuesta.
- `pendientes-para-fernando.md` → lo que falta confirmar.
- `archivo/faq_raw_2026-05.txt` → el FAQ de la web tal como se migró (solo referencia).

## Confianza

Cada valor y entrada dice de dónde sale (`source`) y cuánto confiamos (`confidence`):
- `confirmed`: lo confirmó Fernando.
- `web`: viene del FAQ de la web (mayo 2026); puede estar viejo.
- `pending`: falta confirmar; no se publica.

Cuando Fernando contesta algo en una conversación, `scripts/extract_advisor_answers.py` junta sus respuestas para pasarlas a `fuente/`.
