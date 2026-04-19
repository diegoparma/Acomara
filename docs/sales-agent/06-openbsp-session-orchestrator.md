# Orquestador OpenBSP + Session-Agent + RAG

## Objetivo
Conectar WhatsApp (via OpenBSP) con memoria de sesion (session-agent) y respuestas comerciales basadas en evidencia (RAG cloud-only).

## Componentes
- `orchestrator/server.py`: servicio HTTP principal.
- `docs/knowledge/faq_cloud_index.jsonl`: indice vectorial de FAQs (generado por script).
- `docs/sales-agent/02-system-prompt.md`: prompt comercial de sistema.

## Endpoint principal
- `POST /webhooks/openbsp`

Recibe payload inbound, normaliza campos, consulta RAG, actualiza sesion y devuelve respuesta.

## Variables de entorno
Ver `.env.example`.

Claves importantes:
- `OPENAI_API_KEY`
- `OPENAI_EMBED_MODEL`
- `OPENAI_CHAT_MODEL`
- `TOP_K`
- `SESSION_AGENT_BASE_URL` (opcional)
- `OPENBSP_SEND_URL` (opcional)

## Flujo de ejecucion
1. Inbound entra por `/webhooks/openbsp`.
2. Se extraen campos minimos: mensaje, conversation_id, contact_id, etc.
3. Se registra evento inbound en session-agent (si esta configurado).
4. Se recuperan `top_k` FAQs por similitud.
5. Se genera respuesta comercial con evidencia.
6. Se guarda estado y evento outbound en session-agent.
7. Opcional: se envia mensaje a OpenBSP via `OPENBSP_SEND_URL`.

## Arranque local
1. Crear/activar venv
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2. Instalar dependencias
   - `pip install -r requirements.txt`
3. Completar variables
   - `cp .env.example .env`
4. Asegurar indice FAQ
   - `python scripts/build_cloud_index.py`
5. Ejecutar orquestador
   - `python orchestrator/server.py`

## Test rapido
Ejemplo con curl:

```bash
curl -X POST http://localhost:8080/webhooks/openbsp \
  -H 'Content-Type: application/json' \
  -d '{
    "channel": "whatsapp",
    "organization_id": "acomara",
    "organization_address": "54911XXXXXXX",
    "conversation_id": "conv-001",
    "contact_id": "lead-001",
    "contact_address": "54911YYYYYYY",
    "text": "Que diferencia hay entre ruta normal y polish?"
  }'
```

## Respuesta esperada
El endpoint devuelve JSON con:
- `reply`: texto sugerido para cliente
- `sources`: chunks FAQ usados como evidencia
- `openbsp_send`: estado de envio outbound (si aplica)

## Nota sobre OpenBSP
El envio real depende del contrato HTTP que configures en `OPENBSP_SEND_URL`.
El orquestador ya envia un payload estandar, pero puedes adaptar facilmente el shape en `maybe_send_openbsp()`.
