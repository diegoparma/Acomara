# Reglas de Nico

*Manual de comportamiento del agente de ventas. Actualizado 2026-10-06.*

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
| 5 | **Email compartido** | Guarda el email, lo verifica contra Have I Been Pwned (solo como dato) y le manda a Fer un aviso de **nuevo lead** que dice si el email aparece en filtraciones. Nico sigue atendiendo. Solo pausa si parece un bot: email casi sin charla previa (turno 1-2) que tampoco aparece en filtraciones, o 3 emails distintos en la misma conversación. | `EMAIL_VERIFICATION_ENABLED` (true) |
| 6 | **Derivación a asesor** | Solo si el cliente lo pide explícitamente ("hablar con un asesor", "talk to a human", "falar com um atendente", etc.). Tiene que nombrar a un humano: "quiero hablar con mi esposa" no deriva. Si no tiene email verificado, primero lo pide. Al derivar: manda email al asesor y pausa la conversación. | `HANDOFF_EMAIL_COOLDOWN_SECONDS` (1800) |
| 7 | **Conversación pausada** | Un solo aviso ("te vamos a contactar"), después un mensaje de cierre, y después silencio. | `PAUSED_REPLY_THRESHOLD` (1) |
| 8 | **Primer saludo** | Si el primer mensaje es solo un saludo ("Hola", "Hi"), responde una bienvenida fija y ofrece mandar info por email. | — |
| 8a | **Agradecimiento suelto** | "Gracias", "Thanks!": responde corto ("¡De nada! Cualquier cosa me escribís por acá."), alternando dos frases. No llama al modelo. Un primer mensaje que solo muestra interés ("Hola, quiero info") recibe la bienvenida, igual que un saludo. | — |
| 8b | **"¿Sos un bot?"** | Responde con una frase fija y honesta: es el asistente digital del equipo y puede pasar con un asesor. No llama al modelo. | — |
| 8c | **12+2 / 14+2 sin experiencia** | Si el cliente pregunta si le sirve el 12+2 o el 14+2 y no dice haber estado arriba de 6.000 m (cuenta una altura como "6200", con o sin "m", o haber subido el Aconcagua; el Kilimanjaro no cuenta), responde con una frase fija: son solo para quien superó los 6.000 m, y le recomienda el 18+2 (mismo precio). No llama al modelo. | — |
| 9 | **Opciones de programas** | Si pregunta por opciones sin nombrar un programa: recomienda 18+2 y 12+2; si pide más, lista 14+2 y 17+2. | — |
| 10 | **Respuesta con IA** | En cualquier otro caso: busca en la base de preguntas frecuentes (4 fragmentos) con el mensaje solo y con el mensaje más lo último que se habló, y se queda con lo mejor de las dos búsquedas (así "¿y cuánto sale?" encuentra el precio del programa del que se venía hablando) y genera la respuesta con el modelo, bajo las reglas del system prompt (sección 3). El modelo recibe la fecha de hoy (hora de Argentina). Las salidas que ya pasaron se sacan del texto del FAQ en el código, antes de que lo vea el modelo; si el cliente pregunta por fechas, el FAQ de fechas va siempre en la evidencia. De la sesión solo recibe el turno, si ya se pidió o recibió el email y si ya se avisó lo de temporada. También recibe los últimos 10 mensajes de la conversación (OpenBSP manda solo el último, así que Nico los guarda en la sesión como `recent_turns`). | `OPENAI_CHAT_MODEL` (en producción: gpt-4.1-mini), `TOP_K` (4) |
| 10b | **Cierre con videollamada** | Cuando el cliente elige una fecha (un "5/12" cuenta solo si es una salida real: "somos 4/5 personas" no) o habla de reservar (preguntar por cancelaciones o reembolsos no cuenta), la respuesta cierra invitando a una videollamada (día, hora y ciudad) y pide el email si todavía no lo tiene; si eligió una fecha, aclara que la disponibilidad la confirma un asesor, y si esa fecha es solo del 12+2 o el 14+2 sugiere la salida más cercana del 18+2. Una vez por conversación. Si el email ya se pidió, se saca de la respuesta del modelo cualquier nuevo pedido. | — |
| 11 | **Pedido de email** | Una sola vez, en los turnos 3 o 4, si todavía no lo tiene. Si el cliente manda el email junto con una pregunta, agradece en una línea y responde la pregunta igual. Si la respuesta del modelo ya pide el email, no se agrega el pedido fijo. | — |
| 12 | **Fuera de temporada** | Si menciona un viaje entre abril y octubre, avisa una vez que la temporada es de noviembre a marzo. Una fecha numérica solo cuenta si cae fuera de temporada leída como día/mes y como mes/día ("5/12" es el 5 de diciembre); los rangos con unidad ("4-6 personas") y el "may" verbo en inglés no cuentan. | — |
| 13 | **Formato de fechas y tono** | Formatea las fechas de salida para WhatsApp y limpia la respuesta del modelo: negritas de WhatsApp en lugar de Markdown, sin guiones largos, sin volver a saludar, sin frases de asistente ("¿Hay algo más en lo que pueda ayudarte?") y sin frases cortadas. Las respuestas de 2-3 párrafos salen en mensajes separados. | `OPENBSP_MULTI_MESSAGE_ENABLED` (burbujas) |
| 14 | **Filtro de seguridad** | Nunca envía nada que parezca una contraseña, token o credencial. | — |
| 15 | **Respuesta duplicada** | Si la respuesta es idéntica a la última enviada hace menos de 30 segundos, no la manda. Si pasó más tiempo, el cliente volvió a preguntar: la manda empezando con "Como te decía,". Antes de enviar vuelve a leer la sesión, por si otro mensaje del cliente procesado en paralelo ya la mandó. | — |

## 2. Idioma

- Idiomas: español, inglés y portugués.
- Si el cliente lo pide explícitamente ("English please", "en español"), queda fijo.
- Si no, sigue al cliente cuando el mensaje tiene señales claras del idioma. Si no hay señales ("ok", un email, "Anytime today"), mantiene el idioma anterior.
- "Aconcagua" no cuenta como palabra en español.

## 3. Reglas del system prompt (lo que la IA puede y no puede decir)

Fuente: `docs/sales-agent/02-system-prompt.md` (v3.4) más la ficha `docs/knowledge/datos-clave.md` (programas, precio, permiso y seguro), que se agrega al final del prompt y vale más que cualquier fragmento del FAQ. Lo que confirme Fernando se suma a esa ficha.

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

1. **Email sin filtraciones ya no pausa (cambiado 2026-09-26).** Antes, un email que no aparecía en ninguna filtración pausaba la conversación: pasó en 33 de 34 pausas, y 29 de esas conversaciones eran charlas reales de 3 o más mensajes. Ahora es solo un dato del aviso a Fer. Con los emails reales, la regla nueva habría pausado 3 conversaciones en lugar de 33. Revisar en unas semanas si se cuela algún bot.
2. **Silencio por humano activo (12 h).** En la simulación con el historial real, se habrían silenciado 310 de 1.119 mensajes de clientes. En 202 respondió Fer después y en 13 no respondió nadie. Revisar el número después de unas semanas.
3. **Registro `[OPENBSP_SHAPE]`: resuelto.** OpenBSP manda solo el último mensaje del cliente, sin historial (verificado 2026-09-26), así que la regla 3 necesita consultar Supabase. El registro se quitó el 2026-10-08.
