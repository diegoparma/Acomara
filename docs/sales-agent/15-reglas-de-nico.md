# Reglas de Nico

*Manual de comportamiento del agente de ventas. Actualizado 2026-09-26.*

Este documento describe **todo lo que Nico decide antes de responder**, en el orden en que lo evalúa, más las alertas de la auditoría. Si cambiás una regla en el código, actualizá este archivo.

Código principal: `orchestrator/server.py` (`chat_completions` y `process_inbound_message`).

## 1. Flujo por mensaje

Cada mensaje de WhatsApp que entra pasa por estas reglas en orden. La primera que corta, decide.

| # | Regla | Qué hace | Configurable |
|---|---|---|---|
| 1 | **Comandos** | `/reset` o `/new` reinician la conversación; `/version` muestra la versión desplegada. | — |
| 2 | **Mensaje repetido** | Si llega el mismo mensaje dentro de 120 s (reintento de OpenBSP), no responde nada. Antes reenviaba la respuesta anterior y el cliente la recibía dos veces. | — |
| 3 | **Humano activo** | Si Fer (u otro asesor) escribió en la conversación en las últimas 12 h, desde el celular o desde la plataforma, Nico no responde. Si Supabase no contesta en 2 s, Nico responde igual. | `HUMAN_SILENCE_HOURS` (12; 0 desactiva) |
| 4 | **Cliente en el CRM** | Busca el teléfono (y después el email) en el CRM. Si ya fue contactado, Nico lo trata como cliente conocido. | — |
| 5 | **Email compartido** | Guarda el email y lo verifica contra Have I Been Pwned. Si **no** aparece en ninguna filtración, lo marca como sospechoso: pausa la conversación y manda alerta al admin. ⚠️ Ver "Reglas a revisar". | `EMAIL_VERIFICATION_ENABLED` (true) |
| 6 | **Derivación a asesor** | Solo si el cliente lo pide explícitamente ("hablar con un asesor", "talk to a human", etc.). Si no tiene email verificado, primero lo pide. Al derivar: manda email al asesor y pausa la conversación. | `HANDOFF_EMAIL_COOLDOWN_SECONDS` (1800) |
| 7 | **Conversación pausada** | Un solo aviso ("te vamos a contactar"), después un mensaje de cierre, y después silencio. | `PAUSED_REPLY_THRESHOLD` (1) |
| 8 | **Primer saludo** | Si el primer mensaje es solo un saludo ("Hola", "Hi"), responde una bienvenida fija y ofrece mandar info por email. | — |
| 9 | **Opciones de programas** | Si pregunta por opciones sin nombrar un programa: recomienda 18+2 y 12+2; si pide más, lista 14+2 y 17+2. | — |
| 10 | **Respuesta con IA** | En cualquier otro caso: busca en la base de preguntas frecuentes (4 fragmentos) y genera la respuesta con el modelo, bajo las reglas del system prompt (sección 2). | `OPENAI_CHAT_MODEL` (gpt-5.4), `TOP_K` (4) |
| 11 | **Pedido de email** | Una sola vez, en los turnos 3 o 4, si todavía no lo tiene. | — |
| 12 | **Fuera de temporada** | Si menciona un viaje entre abril y octubre, avisa una vez que la temporada es de noviembre a marzo. | — |
| 13 | **Formato de fechas** | Formatea las fechas de salida para que se lean bien en WhatsApp. | — |
| 14 | **Filtro de seguridad** | Nunca envía nada que parezca una contraseña, token o credencial. | — |
| 15 | **Respuesta duplicada** | Si la respuesta es idéntica a la última enviada hace menos de 3 minutos, no la manda. Antes de enviar vuelve a leer la sesión, por si otro mensaje del cliente procesado en paralelo ya la mandó. | — |

## 2. Idioma

- Idiomas: español, inglés y portugués.
- Si el cliente lo pide explícitamente ("English please", "en español"), queda fijo.
- Si no, sigue al cliente cuando el mensaje tiene señales claras del idioma. Si no hay señales ("ok", un email, "Anytime today"), mantiene el idioma anterior.
- "Aconcagua" no cuenta como palabra en español.

## 3. Reglas del system prompt (lo que la IA puede y no puede decir)

Fuente: `docs/sales-agent/02-system-prompt.md` (v3.3).

**Nunca:**
- Confirmar cupo real por fecha, confirmar reservas ni hacer cotizaciones personalizadas.
- Inventar precios, promociones, descuentos o condiciones.
- Dar recomendaciones médicas (usa una frase fija que deriva a los médicos de montaña).
- Preguntarle al cliente si quiere hablar con un humano.
- Pedir el email más de una vez, o volver a pedir datos que el cliente ya dio.

**Sí:**
- Precios, fechas y promociones publicadas en las preguntas frecuentes, siempre "sujeto a disponibilidad".
- Traducir y simplificar el contenido de las preguntas frecuentes, sin agregar nada.
- Si no tiene la información: decirlo y ofrecer que un asesor lo contacte por email.
- Agregar el aviso de que los aranceles del Parque pueden cambiar, si la evidencia no lo menciona.

Prioridad de la información: políticas del Parque → seguridad → logística oficial → contenido de marketing.

## 4. Alertas de la auditoría

`/audit/dashboard` (requiere `ORCHESTRATOR_API_KEY`). Excluye las conversaciones de prueba.

| Alerta | Significa | Qué hacer |
|---|---|---|
| **Esperando respuesta humana** (`PAUSED_UNANSWERED`) | Conversación pausada donde el cliente volvió a escribir y nadie respondió. Aparece como tabla arriba del todo. | Responderle. |
| `SEND_BLOCKED` | WhatsApp rechazó el envío (por ejemplo, Brasil, error 130497). | Contactar por otro canal. Falta abrir el caso con Meta (desde la cuenta de Fer). Ver `14-whatsapp-bloqueo-brasil.md`. |
| `LANGUAGE_DRIFT` | Se respondió en otro idioma que el del cliente. Incluye mensajes de asesores. | Revisar si fue Nico. |
| `DUPLICATE_REPLIES` | Dos respuestas idénticas seguidas. | Debería bajar a cero con la regla 15. |
| `PAUSED_LOOP` | Tres o más avisos de "te vamos a contactar". | Debería bajar con la regla 7. |
| `CRM_ISSUES` | Nico mencionó un error del CRM o la base de datos. | Revisar la conexión al CRM. |
| `INFO_EXPOSURE` | Nico mencionó datos internos (Vercel, Supabase, claves). | Urgente: revisar el prompt. |

## 5. Quién escribió cada mensaje (en Supabase)

| Tiene `agent_id` | Tiene `sender_address` | Es |
|---|---|---|
| Nico (`50ce8caf-…`) | no | Nico |
| otro | no | Asesor desde la plataforma OpenBSP |
| no | no | Asesor desde la app de WhatsApp Business en el celular |
| no | sí | Cliente |

## 6. Reglas a revisar

1. **Email "sospechoso" por Have I Been Pwned.** Hoy un email que *no* aparece en ninguna filtración se considera sospechoso y pausa la conversación. Muchos emails reales nunca se filtraron. De abril a septiembre de 2026, **33 de las 34 pausas** vinieron de esta regla y solo 1 de un pedido de asesor. En la práctica funciona como "el cliente dejó su email → pasa a Fer", pero con una razón equivocada. Opciones: aceptarlo como derivación intencional y cambiar el nombre, o dejar de pausar y que Nico siga atendiendo.
2. **Silencio por humano activo (12 h).** En la simulación con el historial real, se habrían silenciado 310 de 1.119 mensajes de clientes. En 202 respondió Fer después y en 13 no respondió nadie. Revisar el número después de unas semanas.
3. **Registro temporal `[OPENBSP_SHAPE]`.** Muestra si OpenBSP ya manda el historial en cada pedido. Si lo manda, la regla 3 puede dejar de consultar Supabase. Quitar el registro cuando se decida.
