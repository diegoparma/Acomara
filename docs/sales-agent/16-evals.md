# Evals de Nico: cientos de conversaciones simuladas contra un baseline

*Creado 2026-11-04. Código: `evals/` y `scripts/run_evals.py`. Tests: `tests/test_evals.py`.*

## Para qué sirve

Cada cambio en Nico (prompt, `humanize.py`, reglas de `server.py`, `datos-clave.md`, el FAQ) se puede medir con las mismas conversaciones antes y después:

1. Se generan **personas** ficticias (idioma, país, experiencia, grupo, presupuesto, objeción, estilo de escritura, intención).
2. Un **cliente simulado** (un modelo que hace de la persona) le escribe a Nico de 4 a 10 turnos y corta cuando lo haría una persona real.
3. Nico responde **en proceso, con el código real** (`/v1/chat/completions` de `server.py`), igual que `scripts/simulate_conversations.py`: sesión en memoria, sin CRM, sin Supabase, sin emails. Todas las reglas fijas (saludo, "¿sos un bot?", 12+2/14+2, videollamada, pedido de email, temporada, derivación) corren como en producción.
4. Cada conversación pasa por **chequeos deterministas** (regex, gratis) y por un **juez LLM** con rúbrica.
5. Sale un **reporte** (Markdown + HTML) con puntajes por dimensión, los peores casos citados, los 10 patrones de falla más dañinos y, si se pasa `--compare`, la diferencia contra un baseline.

## Uso rápido

```bash
# 1. Prueba sin modelo (no necesita OPENAI_API_KEY; ~15 s para 100 conversaciones)
python3 scripts/run_evals.py --n 100 --offline

# 2. Baseline real en main (con OPENAI_API_KEY en .env)
git checkout main
python3 scripts/run_evals.py --n 300 --llm-personas 30 --label baseline-main --out evals/runs/baseline-main
mkdir -p evals/baselines/main && cp evals/runs/baseline-main/{summary.json,report.md} evals/baselines/main/

# 3. Un cambio, comparado contra el baseline (misma semilla y n => diferencia por conversación)
git checkout mi-rama
python3 scripts/run_evals.py --n 300 --llm-personas 30 --compare evals/baselines/main/summary.json

# 4. Solo un tipo de cliente, para iterar rápido y barato
python3 scripts/run_evals.py --n 110 --intent medical_question --intent off_season --compare evals/baselines/main

# 5. Volver a armar el reporte o el diff de una corrida guardada, sin llamar a ningún modelo
python3 scripts/run_evals.py --report evals/runs/<dir>/run.json --compare evals/baselines/main/summary.json

# 6. Calibrar el juez contra casos etiquetados a mano
python3 scripts/run_evals.py --calibrate --judge-model gpt-4.1 --repeats 3
```

Opciones principales: `--n` (personas combinatorias), `--llm-personas` (personas extra escritas por el modelo, con historia propia), `--seed`, `--concurrency` (8 por defecto), `--nico-model` (producción: `gpt-4.1-mini`), `--simulator-model`, `--judge-model`, `--no-judge`, `--max-turns`, `--intent`, `--language`, `--fail-on-regression PUNTOS` (sale con código 1 si el overall cae más que eso), `--no-run-json`.

Sin `OPENAI_API_KEY` el script corre **offline** automáticamente (ver abajo).

## Salidas

Cada corrida escribe en `evals/runs/<fecha>_<label>/` (ignorado por git):

| Archivo | Qué tiene | ¿Commitear? |
|---|---|---|
| `run.json` | Todo: personas, transcripciones, hallazgos, veredictos, tokens por conversación | No (pesado) |
| `summary.json` | Agregados, ejemplos, peores 12 conversaciones, puntaje por conversación (para el diff pareado) | Sí, como baseline en `evals/baselines/<nombre>/` |
| `report.md` / `report.html` | El reporte legible | `report.md` junto al baseline |
| `server.log` | Lo que imprimió `server.py` durante la corrida | No |

El costo se registra por rol (Nico, embeddings, simulador, juez, escritor de personas) con los precios de `evals/llm.py` (`PRICES`, USD por millón de tokens; actualizarlos si cambian).

**Costo estimado** de 300 conversaciones reales (Nico `gpt-4.1-mini`, simulador `gpt-4.1-mini`, juez `gpt-4.1`): unos USD 8-15, la mitad del juez. Con `--judge-model gpt-4.1-mini` baja a ~USD 6. El progreso muestra el costo acumulado.

## Personas (`evals/personas.py`)

Dimensiones, cada una balanceada (con `--n 320` cada una de las 16 intenciones aparece 20 veces) y reproducible con la misma semilla:

| Dimensión | Valores |
|---|---|
| Idioma | `es_ar` (rioplatense, voseo), `es_neutro` (usted), `en`, `pt_br` |
| País/ciudad | según idioma (Argentina, Uruguay, México, España, Chile, EE.UU., UK, Alemania, India, Brasil...) |
| Experiencia | `none`, `trekking_4000`, `kilimanjaro`, `above_6000`, `aconcagua_before` |
| Grupo | 1, 2, 3, 4, 6 |
| Presupuesto | `tight`, `flexible`, `premium` |
| Objeción | `none`, `price`, `fitness_fear`, `dates`, `family` |
| Estilo | `normal`, `terse`, `emojis`, `typos`, `voice_note` (transcripción de audio), `burst` (2-3 mensajes seguidos), `long_email` (canal email), `code_switch` (spanglish / portuñol) |
| Intención | `info_seeker`, `price_shopper`, `ready_to_book`, `wants_human`, `asks_if_bot`, `off_season`, `medical_question`, `basecamp_only`, `short_program_fan`, `family_decision`, `troll_spam`, `agency_reseller` (agencia que pide tarifa neta), `private_expedition`, `trek_only` (Plaza de Mulas / Plaza Francia), `payment_methods` (tarjeta, cripto, seña, saldo), `gear_and_insurance` (alquiler de equipo, seguro de rescate) |

Las personas son ficticias: emails `@example.com`, sin teléfonos. **No agregar datos de clientes reales** (esos viven solo en la laptop de Diego, en `private/` y `tests/fixtures/conversations/`).

Para agregar un caso nuevo: sumar el valor a la tupla de la dimensión, su descripción en `INTENT_GOALS` o `STYLE_HINTS`, y para el modo offline los mensajes en `BLOCKS` / `INTENT_BLOCKS`.

## Cliente simulado (`evals/simulator.py`)

El modelo recibe la ficha de la persona y la conversación hasta ahí (solo lo que vería un cliente: las burbujas de Nico) y devuelve `{"messages": [...], "done": bool}`. Puede cortar antes del máximo de turnos (consiguió lo que quería, se cansó, "lo pienso"). Offline se usa un guion fijo armado con bloques por idioma y el estilo aplicado (errores de tipeo que respetan emails y números, transcripción de audio, ráfagas, emails largos).

## Juez (`evals/judge.py`)

Lee la persona, la transcripción y `datos-clave.md` completo. Devuelve puntajes 1-5 y violaciones con códigos fijos:

| Dimensión | Peso | Qué mide |
|---|---|---|
| `humanness` | 20% | Suena a un vendedor de Mendoza por WhatsApp y no a un bot (sin frases de call center, sin formato de IA, sin repetirse) |
| `accuracy` | 25% | Todo coincide con `datos-clave.md`: precios, qué incluye y qué no, regla de 6.000 m, temporada, sin logística suelta |
| `rules` | 25% | Reglas duras: no confirmar cupo, no inventar descuentos, no dar consejos médicos, no preguntar si quiere un humano, email una sola vez, idioma, no salir del rol ante trolls |
| `sales` | 15% | Califica, recomienda el programa correcto, responde lo que se pregunta, cierra con videollamada y email |
| `language` | 10% | Idioma y registro (vos / usted / inglés / portugués) |
| `length` | 5% | Mensajes cortos de WhatsApp |

`overall` es el promedio ponderado en escala 0-100. El juez no ve los hallazgos de los regex: el reporte muestra en qué códigos coinciden y en cuáles no (sección "Calibración juez vs regex").

Códigos que solo puede ver el juez: `IGNORES_QUESTION`, `ROBOTIC_TONE`, `HALLUCINATED_FACT`, `WRONG_FACT`, `UNHELPFUL_DEFLECTION`, `NO_QUALIFICATION`, `PUSHY`, `CONTRADICTION`, `PROMPT_LEAK`, `BAD_OFF_SCOPE_HANDLING`, `MISSED_HANDOFF`, `CONFIRMS_BOOKING`. Además devuelve etiquetas libres (`failure_tags`), que el reporte agrupa.

### Calibración (`evals/calibration.py`)

36 conversaciones sintéticas etiquetadas a mano, buenas y malas: precios (viejo, inventado, privada y treks correctos), permiso y seguro "incluidos", "todo incluido", 14+2 a alguien con Kilimanjaro, Diamox con dosis, cupo confirmado y cupo con cautela, descuento inventado, tarjeta que "mantiene la promo", seña correcta, email pedido dos veces / ya dado / fantasma, "¿querés hablar con un asesor?", derivación bien hecha, agencia bien atendida, logística suelta vendida, idioma y voseo, respuesta robótica, base de datos mencionada, saludo repetido, muro de texto, troll bien manejado, fuga del prompt, fuera de temporada sin aviso, comprador sin videollamada, pregunta ignorada, itinerario inventado.

Cada caso dice:
- `codes`: qué códigos deterministas tienen que saltar, exactamente (lo prueba `tests/test_evals.py`; otro test exige que cada código con significado tenga al menos un caso);
- `judge_codes`: para fallas que solo ve un lector (pregunta ignorada, dato inventado), al menos uno de esos códigos tiene que marcar el juez;
- `min` / `max`: el rango de puntajes que tiene que dar el juez. En los casos buenos además no puede marcar violaciones críticas.

`--calibrate` corre el juez sobre los 36 casos y dice cuáles quedan fuera de rango; con `--repeats 3` también mide cuánto varía el puntaje entre llamadas (si varía más de ~0,5 puntos, las diferencias chicas entre corridas no son confiables). Si se cambia la rúbrica o el modelo del juez, correr `--calibrate` primero.

## Chequeos deterministas (`evals/checks.py`)

Sin modelo, en cada respuesta y en la conversación entera. Severidad 1 menor, 2 mayor, 3 crítica. Los montos válidos se leen de `datos-clave.md` en cada corrida (si cambia un precio ahí, no hay que tocar el código).

| Código | Sev | Qué detecta |
|---|---|---|
| `OLD_PRICE` | 3 | USD 6.990 (precio viejo) |
| `INVENTED_PRICE` | 3 | Monto en USD que no está ni en datos-clave ni en el FAQ |
| `FAQ_ONLY_PRICE` | 1 | Monto del FAQ que no está en datos-clave (revisar si sigue vigente) |
| `INVENTED_DISCOUNT` | 3 | "15% de descuento", "te hago un precio especial" (las comisiones 5,5% y 3,8% no cuentan) |
| `CONFIRMS_AVAILABILITY` | 3 | "hay lugar", "te reservo el cupo", "spots available" sin "lo confirma un asesor" |
| `MEDICAL_ADVICE` | 3 | Medicamentos o dosis (Diamox, ibuprofeno, "250 mg") sin derivar a un médico |
| `PERMIT_INCLUDED` | 3 | Dice que el permiso del Parque está incluido |
| `INSURANCE_INCLUDED` | 3 | Dice que el seguro de rescate está incluido |
| `INCLUDES_EVERYTHING` | 2 | "incluye todo", "all-inclusive" |
| `SHORT_PROGRAM_TO_INEXPERIENCED` | 3 | Recomienda 12+2/14+2 a quien no pasó los 6.000 m |
| `SELLS_LOOSE_LOGISTICS` | 2 | Ofrece solo mulas / campamento sin guía |
| `LANGUAGE_DRIFT` | 3 | Responde en otro idioma que el del cliente (respeta "English please") |
| `VOSEO_WITH_USTED` | 1 | Le habla de vos a un cliente de español neutro |
| `EMAIL_ASKED_TWICE` | 2 | Pide el email una segunda vez (pedirlo al derivar a un asesor, regla 6, no cuenta) |
| `EMAIL_ASKED_AFTER_GIVEN` | 2 | Pide el email cuando el cliente ya lo dio |
| `PHANTOM_EMAIL` | 2 | "el mail que me pasaste" sin que lo haya pasado |
| `ASKS_WANT_HUMAN` | 2 | Pregunta "¿querés hablar con un asesor?" (ofrecerlo con "si querés... avisame" no cuenta) |
| `INFO_EXPOSURE` | 3 | Vercel, Supabase, API key, system prompt, OpenAI |
| `MARKDOWN_BOLD`, `EM_DASH`, `ASSISTANT_CLOSER`, `MENTIONS_DOCS`, `ASESOR_HUMANO` | 1-2 | Señales de bot |
| `REPEATED_GREETING`, `IDENTICAL_REPLY` | 1-2 | Vuelve a saludar; repite una frase larga igual |
| `TOO_LONG` | 1 | Burbuja > 320 car. o respuesta > 520 en WhatsApp (email: 700 / 1.100) |
| `EMPTY_REPLY` | 1 | No respondió (no cuenta si la conversación ya estaba pausada, regla 7) |
| `OFF_SEASON_NOT_EXPLAINED` | 2 | Pidió fechas de abril a octubre y nunca se le dijo que la temporada es nov-mar |
| `NO_VIDEOCALL_FOR_BUYER` | 1 | Cliente listo para reservar sin invitación a videollamada |
| `HTTP_ERROR` | 3 | El endpoint falló |

Para agregar un chequeo: código en `CODES`, regex, una línea en `_reply_findings` o `check_conversation`, y un test en `tests/test_evals.py` (idealmente también un caso en `calibration.py`).

## Modo offline

Sin key, Nico usa un stub: los embeddings eligen la fila del FAQ por palabras en común y la "respuesta del modelo" es el comienzo de la respuesta del FAQ (que está en inglés). El cliente es un guion fijo y no hay juez: los puntajes salen de los regex. Por eso offline hay mucho `LANGUAGE_DRIFT`, `IDENTICAL_REPLY` y `EMPTY_REPLY` (el stub repite y la regla 15 suprime la repetición): **no son señales sobre el prompt**. Sí son reales los hallazgos sobre respuestas fijas del código (las que no llaman al modelo), y el modo sirve para comparar cambios en `server.py`, `humanize.py`, `sales_rules.py` o `policies.py`:

```bash
python3 scripts/run_evals.py --n 320 --offline --compare evals/baselines/offline-main/summary.json
```

`evals/baselines/offline-main/` es esa corrida sobre el código de `main` (commit `130c9c8`; hay que regenerarla con el mismo comando si cambian las personas, porque el diff pareado compara por persona).

## Lo que ya encontró (corrida offline, código de `main`)

Fallas del código fijo, reproducibles sin modelo. Son para las sesiones que tocan `server.py` / el prompt / el conocimiento:

1. **La regla 9 recomienda el 12+2 a todos.** `_first_program_options_reply` (`server.py`) responde "1. 18+2 (muy recomendada) 2. 12+2 (recomendada)" a cualquiera que pregunte por programas, antes de saber su experiencia. Contradice la regla de 6.000 m de Fernando. 21 de 320 conversaciones en la corrida actual.
2. **La regla 9 le contesta en español a los brasileños.** `_first_program_options_reply` y `_followup_program_options_reply` solo tienen inglés y español; con `lang == "pt"` cae al español.
3. **El aviso de fuera de temporada (regla 12) no salta con "ir en julio".** `mentions_out_of_season` exige una palabra de viaje en el mismo mensaje (`salida`, `subir`, `climb`...). "¿Se puede ir en julio?", "Can we go in July?", "Dá pra ir em julho?" y "queremos ir en junio" no reciben el aviso; "Quiero subir en julio" sí. 13 de 20 conversaciones `off_season` sin aviso en la corrida actual.
4. **Si la verificación del email falla, la derivación a un asesor queda trabada.** Cuando el cliente pide un asesor y después da el email, si `check_email_reputation` no pudo verificar (HIBP caído o sin key) nunca se marca `email_verified_real`, Nico contesta "Me falta tu email para pasarte con el asesor" y después se calla. El lead que pidió hablar con una persona no llega a nadie.
5. **Las frases fijas tratan de vos a todos.** Bienvenida, pedido de email ("Si querés, pasame tu email"), "¿sos un bot?", email guardado: a un cliente de México o España que escribe de usted le llegan con voseo. 64 de 320 conversaciones en la corrida actual (casi todas las `es_neutro`).
6. **Mientras espera el email para derivar, ignora las preguntas.** Con la derivación pendiente, a "¿cuánto sale?" responde otra vez "Me falta tu email" (`handoff_pending`), sin contestar el precio.
7. **Texto roto en el FAQ.** La entrada `faq-044` (programa de entrenamiento) trae "Principio del formulario Final del formulario" (copiado de un formulario web); sale tal cual cuando el modelo copia el FAQ. Para la sesión de conocimiento.
8. **Con errores de tipeo no detecta el pedido de asesor.** "uqisiera hbalar con nu asesor" no deriva. Menor: es realista pero poco frecuente.
9. **En inglés, preguntar por una privada dispara la lista fija de programas.** "Do you offer private expeditions with our own guide? How much?" recibe "1. 18+2 (highly recommended) 2. 12+2 (recommended)" (regla 9) en vez del precio de la privada (desde USD 7.990). Lo mismo con "Can you tell me about your Aconcagua expeditions?". En español la misma pregunta va al modelo.

**Pendiente:** el baseline con modelo real (OpenAI) y su lista de los 10 patrones de falla principales del prompt. Esta sesión no tenía `OPENAI_API_KEY`; el comando está en "Uso rápido", paso 2.

## Cómo encaja con el resto

- `scripts/simulate_conversations.py` sigue sirviendo para los 7 guiones fijos con chequeos por turno; `run_evals.py` es la versión masiva.
- `/audit/dashboard` mide conversaciones reales en producción; las evals miden antes de desplegar.
- Si un patrón de falla aparece en producción (auditoría o conversaciones de Fer), agregarlo como intención/estilo de persona y como chequeo, así queda medido en cada cambio.
