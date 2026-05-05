# Auditoria tecnica de conversaciones - 2026-05-05

## Alcance
- Organizacion auditada: `7cb6ffa2-4452-4d65-b880-bfa31b197eee`
- Conversaciones revisadas: 23 totales
- Conversacion de testing excluida para metricas de produccion: `361e99c8-e6ab-4264-a7ee-ff71ce146d25`
- Conversaciones reales consideradas: 22

## Resumen ejecutivo
Se confirmaron problemas sistemicos que no dependen solo del system prompt.
Las causas principales estan en la logica del orquestador:
1. manejo de idioma por sesion fragil,
2. exposicion de informacion operativa en comandos,
3. ausencia de idempotencia de mensajes entrantes,
4. bug en lookup CRM por email.

## Hallazgos con evidencia

### 1) Desviacion de idioma (recurrente)
Sintoma observado:
- usuarios en espanol reciben respuestas en ingles en conversaciones reales.

Causas tecnicas encontradas:
- detector de idioma con cobertura limitada y fallback agresivo,
- estado de `conversation_language` inicializado en ingles al reset,
- idioma recalculado turno a turno en vez de consolidarlo de forma robusta.

Evidencia en codigo:
- `orchestrator/server.py`:
  - `detect_language_from_text(...)`
  - `get_session_language(...)`
  - `build_reset_session_vars(...)`
  - actualizacion de `conversation_language` al final del flujo en ambos endpoints.

Impacto:
- inconsistencia de tono y lenguaje,
- baja confianza del usuario,
- degradacion de conversion.

### 2) Fuga de informacion por comando de version
Sintoma observado:
- en conversaciones se expusieron datos internos de runtime/deploy.

Causa tecnica:
- endpoint/comando `/version` disponible sin restriccion fuerte en canal publico,
- salida de version con metadata operativa sensible.

Evidencia en codigo:
- `orchestrator/server.py`: `build_version_payload()`, `build_version_text()`, manejo de comando `/version`.

Impacto:
- riesgo de seguridad operacional,
- huella de infraestructura visible para terceros.

### 3) Bug en consulta CRM por email
Sintoma observado:
- lookup CRM por email puede fallar o comportarse de forma incorrecta.

Causa tecnica:
- llamado posicional incorrecto a `check_client_status(...)` con email enviado como `phone`.

Evidencia en codigo:
- `orchestrator/server.py`: llamadas a `check_client_status(extracted_email)`.
- firma esperada: `check_client_status(phone=None, email=None)` en `orchestrator/crm_client_status.py`.

Impacto:
- peor contexto comercial,
- peor personalizacion,
- handoff menos preciso.

### 4) Repeticion/doble respuesta por falta de idempotencia
Sintoma observado:
- doble respuesta en algunos inicios y repeticiones en escenarios de reintento.

Causa tecnica:
- no hay control de deduplicacion por `external_id`/`message_id` en procesamiento inbound.

Evidencia en codigo:
- `orchestrator/server.py`: no existe guard de idempotencia previo a generar respuesta.

Impacto:
- respuestas duplicadas,
- ruido de conversacion,
- experiencia inestable.

### 5) Loop de respuesta deterministica al pausar
Sintoma observado:
- en una conversacion se repitio varias veces `Great! We'll be in touch shortly.`

Causa tecnica probable:
- flujo de `conversation_paused` con reply deterministico + falta de salida/normalizacion de estado en algunos caminos.

Evidencia en codigo:
- `orchestrator/server.py`: `build_paused_reply(...)` y ramas `if session_vars.get("conversation_paused")`.

Impacto:
- bloqueo funcional de la conversacion,
- perdida de oportunidades comerciales.

## Cambios aplicados hoy (primer bloque)

Archivo modificado: `orchestrator/server.py`

1. Idioma:
- fallback de idioma mas conservador para este dominio,
- ampliacion de keywords ES/PT/EN para mejorar deteccion,
- default de reset cambiado a espanol (`conversation_language = "es"`).

2. Seguridad `/version`:
- endpoint `/version` ahora devuelve payload reducido (sin detalles sensibles de infraestructura),
- comando `/version` en webhook publico ahora queda deshabilitado por defecto,
  y solo se habilita con `ENABLE_PUBLIC_VERSION_COMMAND=true`.

3. CRM:
- fix de llamadas a `check_client_status(...)` usando argumento nombrado `email=...`.

## Pendientes prioritarios (siguiente iteracion)
1. Implementar idempotencia inbound (clave por proveedor + ventana temporal).
2. Consolidar el lock de idioma por sesion con politica explicita de cambio de idioma.
3. Reducir duplicacion de logica entre endpoints (`/webhooks/openbsp` y `/v1/chat/completions`).
4. Endurecer tests para cubrir:
   - idioma estable por sesion,
   - deduplicacion,
   - escenarios de reintento/concurrencia,
   - hardening de comandos.

## Plan de trabajo recomendado
Fase 1 (inmediata):
- idempotencia inbound + tests.

Fase 2:
- refactor a flujo unico compartido por ambos endpoints.

Fase 3:
- ajustes de estado de pausa/handoff para evitar loops y asegurar salida limpia.

## Criterio de exito
- 0 respuestas en idioma incorrecto para conversaciones ES/EN mono-idioma,
- 0 respuestas duplicadas por reintentos del proveedor,
- 0 exposicion de metadata sensible en canales publicos,
- handoff y CRM consistentes en ambos endpoints.
