# Orquestador OpenBSP + Session-Agent + RAG

## Objetivo
Conectar WhatsApp (via OpenBSP) con memoria de sesion (session-agent) y respuestas comerciales basadas en evidencia (RAG cloud-only).

## Componentes
- `orchestrator/server.py`: servicio HTTP principal.
- `docs/knowledge/faq_cloud_index.jsonl`: indice vectorial de FAQs (generado por script).
- `docs/sales-agent/02-system-prompt.md`: prompt comercial de sistema.

## Endpoint principal
- `POST /v1/chat/completions`

Es un endpoint compatible con OpenAI Chat Completions. OpenBSP lo consume en modo
"modelo personalizado": envia el contexto de la conversacion por headers
(`conversation-id`, `contact-id`, `contact-address`, etc.) y el mensaje del
usuario en `messages`. El orquestador normaliza campos, consulta RAG, actualiza
sesion y devuelve la respuesta como una completion.

## Variables de entorno
Ver `.env.example`.

Claves importantes:
- `OPENAI_API_KEY`
- `OPENAI_EMBED_MODEL`
- `OPENAI_CHAT_MODEL`
- `TOP_K`
- `SESSION_AGENT_BASE_URL` (opcional)
- `ORCHESTRATOR_API_KEY` (protege `/v1/chat/completions`)
- `OPENBSP_MULTI_MESSAGE_ENABLED` (opcional; activa respuestas multi-mensaje via tool `respond`)

## Flujo de ejecucion
1. Inbound entra por `/v1/chat/completions`.
2. Se extraen campos minimos: mensaje, conversation_id, contact_id, etc.
3. Se registra evento inbound en session-agent (si esta configurado).
4. Se recuperan `top_k` FAQs por similitud.
5. Se genera respuesta comercial con evidencia.
6. Se guarda estado y evento outbound en session-agent.
7. La respuesta se devuelve a OpenBSP como completion (texto o, si esta
   habilitado, varios mensajes via el tool `respond`).

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
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_ORCHESTRATOR_API_KEY' \
  -H 'organization-id: acomara' \
  -H 'organization-address: 54911XXXXXXX' \
  -H 'conversation-id: conv-001' \
  -H 'contact-id: lead-001' \
  -H 'contact-address: 54911YYYYYYY' \
  -d '{
    "model": "gpt-4.1-mini",
    "messages": [{"role": "user", "content": "Que diferencia hay entre ruta normal y polish?"}]
  }'
```

## Respuesta esperada
El endpoint devuelve una completion compatible con OpenAI Chat Completions:
- `choices[0].message.content`: texto sugerido para el cliente.
- Si `OPENBSP_MULTI_MESSAGE_ENABLED` esta activo y OpenBSP envia el tool
  `respond`, la respuesta puede venir como `tool_calls` con varios mensajes
  cortos en lugar de un unico bloque.

## Nota sobre OpenBSP
OpenBSP integra como "modelo personalizado" (protocolo Chat Completions) y llama
a `POST /v1/chat/completions`. El envio al cliente lo realiza OpenBSP a partir de
la completion devuelta; el orquestador no hace POST de salida por su cuenta.
