# Deploy del Orquestador en Vercel

## Objetivo
Publicar el endpoint compatible con Chat Completions para usarlo en OpenBSP:
- `POST /v1/chat/completions`

## Archivos de deploy
- `api/index.py`
- `vercel.json`

## Variables de entorno en Vercel
Configura estas variables en el proyecto Vercel:
- `OPENAI_API_KEY`
- `OPENAI_EMBED_MODEL` (ej: `text-embedding-3-small`)
- `OPENAI_CHAT_MODEL` (ej: `gpt-4.1-mini`)
- `TOP_K` (ej: `4`)
- `SESSION_AGENT_BASE_URL` (ej: `https://session-agent-memory-live.onrender.com`)
- `SESSION_AGENT_ID` (ej: `sales-agent-v1`)
- `ORCHESTRATOR_API_KEY` (token para proteger `/v1/chat/completions`)

Opcionales:
- `OPENBSP_SEND_URL`
- `OPENBSP_API_KEY`

## Deploy rapido
1. Instalar CLI:
   - `npm i -g vercel`
2. Login:
   - `vercel login`
3. Desde la raiz del repo:
   - `vercel`
4. Deploy de produccion:
   - `vercel --prod`

## Probar endpoint desplegado
Ejemplo (`YOUR_DOMAIN` y `YOUR_ORCHESTRATOR_API_KEY`):

```bash
curl -X POST https://YOUR_DOMAIN/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_ORCHESTRATOR_API_KEY' \
  -H 'organization-id: acomara' \
  -H 'organization-address: 54911XXXXXXX' \
  -H 'conversation-id: conv-prod-001' \
  -H 'agent-id: sales-agent-v1' \
  -H 'contact-id: lead-prod-001' \
  -H 'contact-address: 54911YYYYYYY' \
  -d '{
    "model": "gpt-4.1-mini",
    "messages": [{"role":"user","content":"Cual es la mejor epoca para subir al Aconcagua?"}]
  }'
```

## Configuracion en OpenBSP (Modelo personalizado)
En el formulario:
- Proveedor: `Personalizado`
- Protocolo: `Chat Completions`
- API URL: `https://YOUR_DOMAIN/v1`
- Clave API: `YOUR_ORCHESTRATOR_API_KEY`
- Modelo: `gpt-4.1-mini`

OpenBSP llamara a `POST /v1/chat/completions` automaticamente.
