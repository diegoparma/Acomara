# Base de conocimiento de Nico: cómo está pensada

*Actualizado nov 2026. Cómo editarla: `docs/knowledge/README.md`.*

## El problema que resuelve

Hasta octubre 2026 el mismo dato vivía en varios lugares escritos a mano: el FAQ crudo de la web (en inglés), los fragmentos para la búsqueda (generados con awk), los datos clave del prompt, los docs de estado y algunas frases del código. Cuando Fernando cambió el precio a USD 7.250, `estado-nico-para-fernando.md` siguió diciendo USD 6.990; la temporada figuraba como "noviembre a febrero" en un lado y "noviembre a marzo" en otro; el FAQ decía "más de 5.000 m" para los programas cortos y Fernando dice 6.000 m. Además el parser awk cortaba solo en líneas terminadas en "?", así que mezclaba entradas: un fragmento de 12.000 caracteres juntaba edad mínima, tasa de cumbre, dificultad y seis menús, y el itinerario del 18+2 traía pegados el del Polaco y el del 14+2.

## El modelo

Una fuente canónica, estructurada, y todo lo demás generado:

```
docs/knowledge/fuente/
  valores.yaml      precios, %, seña, links, temporada: una vez, con fuente, confianza y vigencia
  salidas.yaml      fechas de salida por programa
  datos-clave.yaml  datos fijos del prompt (texto con {valores})
  faq.yaml          entradas del FAQ: key, id, topic, pregunta y respuesta por idioma,
                    also_asked (cómo lo preguntan los clientes), source, confidence, valid_until
        │
        ▼  scripts/build_knowledge.py (sin red)
  datos-clave.md         → prompt de sistema
  faq_rag_chunks.jsonl   → un fragmento por entrada e idioma
  faq_structured.md      → versión legible + tabla de valores vigentes
        │
        ▼  scripts/build_cloud_index.py (OpenAI; re-embebe solo lo que cambió)
  faq_cloud_index.jsonl  → búsqueda en producción (anota el modelo de embeddings)
```

Reglas:
- **Un precio se escribe una vez.** Los textos usan `{price_regular}`; el generador lo formatea por idioma (USD 7.250 en es/pt, USD 7,250 en en). Un test falla si un precio confirmado aparece escrito a mano en otra fuente.
- **Jerarquía.** `datos-clave` (lo que dijo Fernando) > FAQ `confirmed` > FAQ `web`. Lo `pending` no se publica.
- **Vigencia.** Valores y salidas tienen `valid_until` (fin de temporada 2026/27). Vencido, el build y los tests fallan: obliga a revisar precios antes de la próxima temporada.
- **Una entrada = una pregunta.** El FAQ migrado quedó en 73 entradas (75 con las nuevas) (antes 63 fragmentos, varios mezclados). Los ids `faq-NNN` viejos se mantienen (el código y los logs los usan); las entradas nuevas toman números nuevos y el duplicado `faq-053` se retiró.
- **Multilingüe por metadatos.** La mayoría de las respuestas están solo en inglés (así vienen de la web); cada entrada tiene además la pregunta en español y `also_asked` en es/en/pt. El modelo responde en el idioma del cliente.
- **Consistencia entre fuentes.** `tests/test_knowledge_base.py` revisa que todo monto en USD que puede leer un cliente (prompt, reglas, FAQ, índice, `estado-nico-para-fernando.md`, frases del código) exista en `fuente/`.

## Búsqueda

- Producción: embeddings (OpenAI) sobre "pregunta + also_asked + respuesta", top 4, con el mensaje solo y con el contexto reciente (para "¿y cuánto sale?"); fechas forzadas por código (`departures.py`).
- Nuevo, opcional: `RETRIEVAL_MODE=hybrid` fusiona el ranking de embeddings con BM25 por palabras clave (RRF). Código en `orchestrator/kb_retrieval.py`.
- El servidor ahora toma el modelo de embeddings del índice (`embed_model`) y registra un error si las dimensiones no coinciden.

### Benchmark (`scripts/eval_retrieval.py`, preguntas etiquetadas es/en/pt con seguimientos)

Por palabras clave (BM25, sin red), 4 de noviembre de 2026:

| Fragmentos | hit@1 | hit@3 | hit@4 | MRR | hit@4 es | hit@4 en | hit@4 pt |
|---|---|---|---|---|---|---|---|
| Antes (awk, solo inglés) | 27,5% | 38,9% | 44,3% | 0,353 | 32,3% | 68,6% | 13,3% |
| Con fuente/ + preguntas es + also_asked (131 preguntas) | 69,5% | 84,0% | 88,5% | 0,783 | 93,8% | 82,4% | 86,7% |
| + 11 respuestas traducidas al español, un fragmento por entrada, 2 entradas nuevas (157 preguntas) | 67,5% | 85,4% | 88,5% | 0,774 | 93,4% | 83,6% | 84,6% |

La segunda tanda suma 26 preguntas más difíciles (más portugués y seguimientos), así que el total no se compara 1 a 1 con la fila anterior: sobre las 131 originales, la misma configuración da 89,3% en hit@4.

Embeddings e híbrido: **pendiente**, necesita `OPENAI_API_KEY` (no estaba en la sesión cloud). Con la clave:

```bash
python3 scripts/build_cloud_index.py && python3 scripts/eval_retrieval.py --mode all --misses
```

Si híbrido gana a dense en hit@4 sin perder en hit@1, activar `RETRIEVAL_MODE=hybrid` en Vercel.

## Lo que falta

- Respuestas de Fernando: `docs/knowledge/pendientes-para-fernando.md` (contradicciones, datos viejos, preguntas sin respuesta como cancelación y saldo).
- Cruzar precios, fechas y permisos con `aconcagua-plan-admin` y servicios/treks con `aconcagua-basecamp-web`.
- Respuestas en español: hoy 18 de 75 entradas tienen versión es (precio, reserva, fechas, Plaza Francia, experiencia, logística sin guía, fuera de temporada, rutas, extendido vs. corto, vuelos, días extra, incluye, no incluye, noche de regreso, permiso, seguro, porteadores, grupo). Seguir con equipo y comida.
- Las respuestas en es y en de una misma entrada no ocupan dos lugares del top 4: la búsqueda se queda con el mejor fragmento de cada entrada (`kb_retrieval.one_per_entry`).
