# Conversation Audit & Fix Log

**Fecha:** 2026-05-18 (actualizado 2026-05-20)
**Scope:** Auditoría de las últimas 10 conversaciones + plan de fixes.
**Origen:** Hallazgos del scan profundo (ver `reports/conversation_deep_scan_latest_10.json` y `reports/conversation_deep_scan_latest_10_full.json`).

---

## 2026-05-20 — Consolidación de endpoint

- Eliminado `/webhooks/openbsp` (~520 líneas) en `orchestrator/server.py`.
- Motivo: en producción Vercel **no** está seteado `OPENBSP_SEND_URL`, por lo que ese handler no podía entregar respuestas a WhatsApp aunque recibiera tráfico. OpenBSP integra vía Chat Completions custom-model contra `/v1/chat/completions`, único path con tráfico real.
- Beneficio: cada fix futuro se aplica una sola vez. Causa raíz de la repetición de bugs (email loop, language drift) atacada de fondo.
- Tests: `scripts/test_email_security.py` quedó deshabilitado con early-exit; pegaba al endpoint eliminado y exige reescritura para `/v1/chat/completions`.
- Helpers ahora huérfanos (sin callers): `normalize_inbound`, `maybe_send_openbsp`. Conservados sin tocar para evitar churn; se podan en próximo pase de limpieza.

---

## Conversaciones auditadas

| # | ID corto | Teléfono | Nombre | Idioma usuario | Errores detectados |
|---|---|---|---|---|---|
| 1 | `14b02acd` | +972 542420122 | — | EN | LANGUAGE_DRIFT (bot respondió en ES) |
| 2 | `11953b50` | +55 51 96972619 | **Diego** | PT | PRICE_INCONSISTENCY (USD 1.399 vs 1.499), LANGUAGE_DRIFT |
| 3 | `6abd8f9b` | +54 9 261 6415435 | — | ES | EMAIL_REQUEST repetido dentro del mismo turno |
| 4 | `1d0d5e8f` | +61 407050626 | **Wes Holloway** (`wesholloway800@gmail.com`) | EN | EMAIL_REQUEST_REPEATED, no usa el nombre, ack pobre tras recibir email |
| 5 | `93422aec` | +55 31 92771013 | — | PT | LANGUAGE_DRIFT (bot ES), typo "Nobiembre", respuesta truncada fuera de temporada |
| 6 | `7726ce7d` | +33 609901977 | **Jacques Akkulak** (`jacques.akkulak@orange.fr`) | EN | DUPLICATE_REPLIES x4, EMAIL_LOOP_AFTER_CAPTURE x4 |
| 7 | `69e42d76` | — | **Rick Stone** (test) | ES | Bot no respondió |
| 8 | `c7a58f45` | — | **Rick Stone** (test) | ES | Bot no respondió |
| 9 | `b58661e5` | +54 9 261 5155152 | (usuario: **Agustina**) | ES | Latencia 1h36, respuesta manual |
| 10 | `0f923c01` | — | **Rick Stone** (test) | — | "wkkkkk", sin respuesta |

---

## Fixes aplicados en este ciclo

### ✅ Fix #1 — Cortar el loop "pedí el email N veces"
- `orchestrator/security.py::should_request_email` ahora también bloquea cuando hay `email_captured`, `captured_email` o `email_requested` ya seteados.
- `orchestrator/server.py`: tras `extract_email_from_text`, persistimos en sesión: `email_captured=true`, `captured_email`, `email_captured_at_ts`, `email_requested=true` (en ambos endpoints: `/webhooks/openbsp` y `/v1/chat/completions`).
- `docs/sales-agent/02-system-prompt.md`: añadida regla dura — si alguna de esas flags está en true, el LLM NO puede volver a pedir email.
- Resultado esperado: caso Jacques (4 repeticiones tras dar email) no se vuelve a reproducir.

### ✅ Fix #2 — Idioma sigue al usuario, no al primer turno
- `orchestrator/server.py::detect_language_from_text` ahora prioriza tokens fuertes (es/en/pt) antes del conteo de keywords.
- Nuevo `detect_language_confident()` que retorna `None` en mensajes ambiguos cortos (ej. "Hola", "Olá", "Hi").
- `get_session_language` rota a un nuevo idioma sólo cuando hay señal confiable; en caso ambiguo conserva el idioma anterior.
- En ambos endpoints, `conversation_language` se sobreescribe únicamente con detección confiable; greetings ya no fijan el idioma.
- Resultado esperado: casos `14b02acd` y `93422aec` se responden en el idioma del usuario tras el segundo mensaje real.

### ✅ Fix #6 — Acuse rico cuando llega el email
- En el path normal del LLM (en ambos endpoints): si en este turno `extracted_email` es no-nulo y `email_received_acked` no estaba, reemplazamos la respuesta del LLM por la frase `email_received_ack` (multilingüe) que incluye el email y los próximos pasos.
- Nueva phrase `email_received_ack` en `I18N_PHRASES` (es/en/pt).
- Resultado esperado: caso Wes ya no termina con "Great! We'll be in touch shortly." plano, sino con un ack útil.

### ✅ Fix #7 — Heads-up de temporada
- Nueva utilidad `mentions_out_of_season(text)` que detecta meses **abril–octubre** o fechas numéricas en ese rango junto a un verbo/intent de viaje.
- En el path normal del LLM, se prepende una nota canónica (`out_of_season`) una sola vez por conversación (`out_of_season_warned`).
- Nueva phrase `out_of_season` en `I18N_PHRASES` (es/en/pt).
- Regla agregada al system prompt para que el LLM no invente excepciones ni use frases como "Nobiembre".
- Resultado esperado: caso `93422aec` (consulta para 27/05) recibe un mensaje claro indicando ventana válida.

### ✅ Fix #8 — Telemetría más precisa
- `orchestrator/conversation_audit.py` ahora detecta también:
  - `EMAIL_REQUEST_REPEATED` (≥2 pedidos del bot)
  - `EMAIL_LOOP_AFTER_CAPTURE` (el usuario ya dio email y el bot vuelve a pedirlo)
  - `NEAR_DUPLICATE_REPLIES` (mismas primeras 80 chars en ≥2 respuestas)
  - `PRICE_INCONSISTENCY` (≥2 montos USD distintos)
- Reporte regenerado (`reports/conversation_audit_latest.json`): pasa de 6/40 con issues a 16/40 (mayor sensibilidad).

---

## Fixes pendientes (a revisar juntos)

### ⏸ Fix #3 — Precio único y validado
- **Problema real detectado:** `11953b50` cita USD 1.399 y USD 1.499 en el mismo hilo (Trek Plaza Francia).
- **Propuesta:** consolidar precios en `docs/knowledge/pricing.json` (canon único), excluir chunks RAG con precios sueltos.
- **Pendiente de confirmar contigo:**
  - Cuál es el precio canónico vigente de Plaza Francia.
  - Si el bot debe **nunca** confirmar precio (derivar siempre) o si puede leer del canon.

### ⏸ Fix #4 — Detección y uso del nombre
- **Problema real detectado:** Wes Holloway y Diego firmaron su nombre; el bot nunca lo usó.
- **Propuesta:** extraer firma con regex (`Regards,\s*(...)`, "soy/me llamo/I'm"), persistir en `customer_name`, exponer al prompt.
- **Pendiente:** definir si lo usamos en saludos sucesivos o sólo en el handoff.

### ⏸ Fix #5 — Anti-repetition guard de plantillas
- **Problema real detectado:** caso Jacques — la plantilla "I can have a specialist send you pricing… What's your email?" se mandó 4 veces idéntica.
- **Propuesta:** comparar contra `last_assistant_reply` y forzar variación o salir del flujo.
- **Pendiente:** decidir umbral de similitud y respuesta alternativa.

### ⏸ Otros hallazgos a revisar
- **Rick Stone (test):** 3 conversaciones sin respuesta del bot. ¿Son testing tuyo? Si sí, agregarlos a `KNOWN_TEST_CONVERSATION_IDS` para excluir del audit.
- **Agustina (`b58661e5`):** respuesta a 1h36 con minúscula. ¿Intervención manual o bot caído?
- **Handoff de Wes (`1d0d5e8f`):** ¿se llegó a notificar al asesor humano? Validar que el flujo `try_send_handoff_email` haya disparado.

---

## Métrica de impacto

| Métrica | Antes (10 últimas) | Esperado tras estos fixes |
|---|---|---|
| Conversaciones con loop de email | 2/10 (Jacques, Wes) | 0/10 |
| Conversaciones con language drift | 2/10 (`14b02acd`, `93422aec`) | 0/10 |
| Email recibido sin ack útil | 1/10 (Wes) | 0/10 |
| Consulta fuera de temporada mal manejada | 1/10 (`93422aec`) | 0/10 |
| Issues detectados por audit | 6/40 (global) | 16/40 (más sensibilidad) |

---

## Cómo validar después del deploy

1. Conversación de prueba: enviar mensaje en EN tras un "Hola" inicial → el bot debe responder en EN al segundo turno.
2. Compartir email → el siguiente turno debe ser el `email_received_ack` exacto, sin volver a pedir email durante el resto de la sesión.
3. Pedir info de tour para "mayo" o "27/05" → el bot debe responder con la nota de `out_of_season` antes del resto.
4. Correr `GET /audit/conversations?api_key=...` y confirmar que las nuevas claves `EMAIL_LOOP_AFTER_CAPTURE`, `NEAR_DUPLICATE_REPLIES`, `PRICE_INCONSISTENCY` aparecen en `issue_counts` cuando corresponda.
