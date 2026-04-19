# Cloud-only RAG para Agente de Ventas (sin modelos locales)

## Objetivo
Usar la base FAQ de Acomara con modelos externos por API, sin descargar modelos GGUF locales.

## Stack recomendado
- Embeddings: OpenAI `text-embedding-3-small`
- Respuesta comercial: OpenAI `gpt-4.1-mini`
- Conocimiento base: `docs/knowledge/faq_rag_chunks.jsonl`

## Archivos creados
- `scripts/build_cloud_index.py`: genera embeddings por chunk y crea `faq_cloud_index.jsonl`
- `scripts/answer_sales_query.py`: recupera top-k por similitud y genera respuesta comercial
- `.env.example`: variables de entorno requeridas
- `requirements.txt`: dependencias Python

## Setup rapido
1. Crear entorno e instalar dependencias:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. Configurar secretos:
   - `cp .env.example .env`
   - Completar `OPENAI_API_KEY` en `.env`
3. Crear indice cloud:
   - `python scripts/build_cloud_index.py`
4. Probar pregunta comercial:
   - `python scripts/answer_sales_query.py "Cual es la diferencia entre ruta Normal y Polish?"`

## Flujo
1. Se carga FAQ estructurada (`faq_rag_chunks.jsonl`).
2. Se generan embeddings por API (sin inferencia local).
3. Se calcula similitud coseno y se toman top-k resultados.
4. Se responde con prompt comercial y evidencia recuperada.

## Notas operativas
- Si actualizas la FAQ, volver a correr `build_cloud_index.py`.
- Ajustar `TOP_K` en `.env` (por defecto 4).
- Si no hay evidencia suficiente, el agente debe derivar a humano.

## Siguiente mejora (fase 2)
- Reemplazar indice local JSONL por vector DB cloud (Pinecone, Supabase pgvector o Weaviate Cloud).
- Agregar re-ranking por API (Cohere o Jina) para mayor precision en preguntas ambiguas.
- Persistir historial por lead y etapa del pipeline en CRM.
