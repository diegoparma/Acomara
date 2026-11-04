# Evals de Nico — 2026-11-04 01:08 · offline-main

## Resumen

Modo: **offline-stub** · commit `130c9c8` (claude/loving-davinci-otqdgy) · 2026-11-04T01:08:58+00:00

330 conversaciones (semilla 7, 0 personas escritas por LLM) · 5.518 turnos promedio · errores: 0 · Nico: `gpt-4.1-mini` · simulador: `gpt-4.1-mini` · juez: `gpt-4.1`

Costo total: **USD 0.00** (USD 0.0000 por conversación)

> Corrida OFFLINE: Nico respondió con un stub (inicio de la respuesta del FAQ), el cliente fue un guion fijo y los puntajes salen solo de los chequeos deterministas. Sirve para probar el harness y las reglas fijas del código, no la calidad del prompt.

## Puntajes por dimensión (1-5)

| dimensión | media | IC 95% |
|---|---|---|
| **overall (0-100)** | 72.29 | ±1.26 |
| humanness | 3.02 | ±0.13 |
| accuracy | 4.54 | ±0.11 |
| rules | 4.03 | ±0.12 |
| sales | 3.90 | ±0.05 |
| language | 3.12 | ±0.19 |
| length | 4.97 | ±0.02 |

## Top 10 patrones de falla

1. **IDENTICAL_REPLY** (humanness, sev 2): Repite la misma frase larga palabra por palabra. 267 conv. (80.9%; regex 267, juez 0). Ej. (p7-0000, turno 2): "Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2"
2. **LANGUAGE_DRIFT** (rules, sev 3): Responde en otro idioma que el del cliente. 157 conv. (47.6%; regex 157, juez 0). Ej. (p7-0000, turno 0): "Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario"
3. **EMPTY_REPLY** (rules, sev 1): Nico no respondió nada a un mensaje. 186 conv. (56.4%; regex 186, juez 0). Ej. (p7-0002, turno 6): "quanto custa?"
4. **VOSEO_WITH_USTED** (language, sev 1): Le habla de vos a un cliente que escribe en español neutro / de usted. 75 conv. (22.7%; regex 75, juez 0). Ej. (p7-0004, turno 2): "Si querés, pasame tu email y te mando el detalle completo con precios y fechas."
5. **SHORT_PROGRAM_TO_INEXPERIENCED** (accuracy, sev 3): Recomienda 12+2/14+2 a alguien sin 6.000 m. 24 conv. (7.3%; regex 24, juez 0). Ej. (p7-0007, turno 0): "12+2 (recommended)"
6. **OFF_SEASON_NOT_EXPLAINED** (accuracy, sev 2): El cliente pidió fechas fuera de temporada y nunca se le dijo que es nov-feb/mar. 22 conv. (6.7%; regex 22, juez 0). Ej. (p7-0013, turno 6): ""
7. **NO_VIDEOCALL_FOR_BUYER** (sales, sev 1): Cliente listo para reservar y nunca se le ofreció videollamada. 10 conv. (3.0%; regex 10, juez 0). Ej. (p7-0014, turno 3): ""
8. **TOO_LONG** (length, sev 1): Respuesta más larga que el límite del canal. 10 conv. (3.0%; regex 10, juez 0). Ej. (p7-0105, turno 5): "El precio es USD 7.250, y algunas salidas tienen promoción entre USD 5.990 y USD 6.390 según los lugares libres de cada …"
9. **EMAIL_ASKED_TWICE** (rules, sev 2): Pide el email más de una vez. 1 conv. (0.3%; regex 1, juez 0). Ej. (p7-0219, turno 4): "I just need your email to pass you to the advisor. What is it?"

## Chequeos deterministas (regex)

| código | sev | conv. | tasa | ocurrencias |
|---|---|---|---|---|
| IDENTICAL_REPLY | 2 | 267 | 80.9% | 342 |
| EMPTY_REPLY | 1 | 186 | 56.4% | 318 |
| LANGUAGE_DRIFT | 3 | 157 | 47.6% | 278 |
| VOSEO_WITH_USTED | 1 | 75 | 22.7% | 132 |
| SHORT_PROGRAM_TO_INEXPERIENCED | 3 | 24 | 7.3% | 24 |
| OFF_SEASON_NOT_EXPLAINED | 2 | 22 | 6.7% | 22 |
| FAQ_ONLY_PRICE | 1 | 18 | 5.5% | 42 |
| NO_VIDEOCALL_FOR_BUYER | 1 | 10 | 3.0% | 10 |
| TOO_LONG | 1 | 10 | 3.0% | 10 |
| EMAIL_ASKED_TWICE | 2 | 1 | 0.3% | 1 |

## Resultados de venta

| resultado | tasa |
|---|---|
| email_requested | 87.3% |
| client_gave_email | 42.7% |
| email_captured | 42.7% |
| videocall_offered | 6.1% |
| paused | 4.5% |

## Por idioma

| grupo | n | overall | % con falla crítica |
|---|---|---|---|
| en | 82 | 73.01 | 29.3% |
| es_ar | 83 | 73.38 | 53.0% |
| es_neutro | 83 | 71.95 | 55.4% |
| pt_br | 82 | 70.81 | 81.7% |

## Por intención

| grupo | n | overall | % con falla crítica |
|---|---|---|---|
| asks_if_bot | 30 | 82.29 | 50.0% |
| basecamp_only | 30 | 72.86 | 53.3% |
| family_decision | 30 | 72.99 | 60.0% |
| info_seeker | 30 | 66.21 | 63.3% |
| medical_question | 30 | 66.11 | 70.0% |
| off_season | 30 | 62.25 | 63.3% |
| price_shopper | 30 | 68.99 | 56.7% |
| ready_to_book | 30 | 72.13 | 56.7% |
| short_program_fan | 30 | 73.20 | 66.7% |
| troll_spam | 30 | 78.69 | 0.0% |
| wants_human | 30 | 79.45 | 63.3% |

## Por estilo

| grupo | n | overall | % con falla crítica |
|---|---|---|---|
| burst | 47 | 62.99 | 61.7% |
| emojis | 47 | 76.46 | 51.1% |
| long_email | 47 | 79.91 | 48.9% |
| normal | 48 | 74.10 | 58.3% |
| terse | 47 | 73.60 | 61.7% |
| typos | 47 | 73.13 | 51.1% |
| voice_note | 47 | 65.77 | 51.1% |

## Por experiencia

| grupo | n | overall | % con falla crítica |
|---|---|---|---|
| above_6000 | 66 | 71.32 | 53.0% |
| aconcagua_before | 77 | 73.13 | 59.7% |
| kilimanjaro | 66 | 74.58 | 48.5% |
| none | 59 | 70.85 | 66.1% |
| trekking_4000 | 62 | 71.20 | 46.8% |

## Tokens y costo

| rol | modelo | llamadas | input | cached | output | USD |
|---|---|---|---|---|---|---|
| nico | gpt-4.1-mini | 1530 | 0 | 0 | 0 | 0.00 |
| nico_embeddings | text-embedding-3-small | 1530 | 0 | 0 | 0 | 0.00 |

## Peores 12 conversaciones

<details><summary>p7-0122 · es_ar · off_season · voice_note · trekking_4000 — overall 38.8</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: LANGUAGE_DRIFT (t0); EMPTY_REPLY (t1); LANGUAGE_DRIFT (t2); IDENTICAL_REPLY (t2); LANGUAGE_DRIFT (t3); EMPTY_REPLY (t4); EMPTY_REPLY (t5); EMPTY_REPLY (t6)

[0] CLIENTE: [audio transcrito] eh buenas, estoy viendo lo del aconcagua o sea nada bueno eso
[0] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[1] CLIENTE: [audio transcrito] eh vamos 6 con mi grupo, la idea es febrero o sea nada bueno eso
[1] NICO: (no respondió)
[2] CLIENTE: [audio transcrito] eh hice el lanín y algunos trekkings de 4000 o sea nada bueno eso
[2] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[3] CLIENTE: [audio transcrito] eh se puede ir en julio o sea nada bueno eso
[3] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[4] CLIENTE: [audio transcrito] eh mi mail es florencia0122@examplecom o sea nada bueno eso
[4] NICO: (no respondió)
[5] CLIENTE: [audio transcrito] eh qué fechas de salida tienen o sea nada bueno eso
[5] NICO: (no respondió)
[6] CLIENTE: [audio transcrito] eh en esas fechas no puedo, hay otras o sea nada bueno eso
[6] NICO: (no respondió)
[7] CLIENTE: [audio transcrito] eh gracias o sea nada bueno eso
[7] NICO: El precio es USD 7.250, y algunas salidas tienen promoción entre USD 5.990 y USD 6.390 según los lugares libres de cada fecha. Se puede reservar con un pequeño anticipo.
```

</details>

<details><summary>p7-0301 · pt_br · info_seeker · burst · above_6000 — overall 41.2</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: LANGUAGE_DRIFT (t0); LANGUAGE_DRIFT (t0); LANGUAGE_DRIFT (t1); IDENTICAL_REPLY (t1); EMPTY_REPLY (t2); EMPTY_REPLY (t3); IDENTICAL_REPLY (t5); EMPTY_REPLY (t6)

[0] CLIENTE: Oi,
[0] CLIENTE: quero informações sobre o Aconcágua
[0] NICO: ¡Hola! Gracias por escribirnos. ¿En qué te puedo ayudar?
        Si te sirve, además de responderte por acá te mando por email toda la info: precios, fechas, servicios, lista de equipo y recomendaciones.
[0] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[1] CLIENTE: Somos 2 amigos de Florianópolis,
[1] CLIENTE: queremos ir em dezembro
[1] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[1] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[2] CLIENTE: Já subi o Huascarán,
[2] CLIENTE: 6768 m
[2] NICO: (no respondió)
[2] NICO: (no respondió)
[3] CLIENTE: Qual programa vocês recomendam?
[3] NICO: (no respondió)
[4] CLIENTE: Meu e-mail é pedro.0301@example.com
[4] NICO: Ótimo, já anotei seu email. Se depois quiser falar com um consultor, é só me avisar.
[5] CLIENTE: O que está incluído?
[5] CLIENTE: A permissão do parque está incluída?
[5] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[5] NICO: (no respondió)
[6] CLIENTE: Quanto custa?
[6] NICO: (no respondió)
[7] CLIENTE: Essas datas não dão,
[7] CLIENTE: tem outras?
[7] NICO: (no respondió)
[7] NICO: (no respondió)
[8] CLIENTE: Valeu!
[8] NICO: ¡De nada! Cualquier cosa me escribís por acá.
```

</details>

<details><summary>p7-0034 · pt_br · off_season · burst · none — overall 45.0</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: LANGUAGE_DRIFT (t0); LANGUAGE_DRIFT (t0); IDENTICAL_REPLY (t1); EMPTY_REPLY (t2); EMPTY_REPLY (t3); EMPTY_REPLY (t4); OFF_SEASON_NOT_EXPLAINED (t6)

[0] CLIENTE: Olá,
[0] CLIENTE: tudo bem?
[0] CLIENTE: Vocês fazem expedição ao Aconcágua?
[0] NICO: ¡Hola! Gracias por escribirnos. ¿En qué te puedo ayudar?
        Si te sirve, además de responderte por acá te mando por email toda la info: precios, fechas, servicios, lista de equipo y recomendaciones.
[0] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[0] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
        Se quiser, me passa seu email e te mando o detalhe completo com preços e datas.
[1] CLIENTE: Vou sozinho,
[1] CLIENTE: pensando em janeiro
[1] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[1] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[2] CLIENTE: Nunca subi mais
[2] CLIENTE: de 3000 metros
[2] NICO: (no respondió)
[2] NICO: (no respondió)
[3] CLIENTE: Dá pra ir em julho?
[3] NICO: (no respondió)
[4] CLIENTE: Quais as datas de saída?
[4] NICO: (no respondió)
[5] CLIENTE: Tá caro,
[5] CLIENTE: tem desconto?
[5] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[5] NICO: (no respondió)
[6] CLIENTE: Valeu!
[6] NICO: De nada! Qualquer coisa me escreve por aqui.
```

</details>

<details><summary>p7-0238 · en · family_decision · voice_note · trekking_4000 — overall 45.0</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: FAQ_ONLY_PRICE (t3); FAQ_ONLY_PRICE (t3); FAQ_ONLY_PRICE (t5); FAQ_ONLY_PRICE (t5); IDENTICAL_REPLY (t5); IDENTICAL_REPLY (t5); IDENTICAL_REPLY (t5); EMPTY_REPLY (t6)

[0] CLIENTE: [audio transcrito] uh hi, i'm interested in climbing aconcagua like yeah that's it
[0] NICO: Hi! Thanks for reaching out. How can I help?
        If it's useful, besides answering here I can email you all the info: prices, dates, services, gear list and recommendations.
[1] CLIENTE: [audio transcrito] uh we are 4 friends from utrecht, thinking about january like yeah that's it
[1] NICO: If you're planning to climb Aconcagua, these are our scheduled departures for the 2026/27 season (November and December 2026; January and February 2027): 18+2 DAYS | NORMAL EXTENDED (recommended) Nov 14, 22 Dec 1, 4, 20, 27 Jan 2, 10, 31
[2] CLIENTE: [audio transcrito] uh i've done multi-day treks up to 4,000 m like yeah that's it
[2] NICO: FLY IN You may arrive in Mendoza (MDZ Airport): until Day 1 at 11 AM for Extended programs of 17-18 + 2 extra days until Day 1 at 8 AM for Fast or Extreme itineraries of 12-14 + 2 extra days We recommend coming 1-2 days before Day 1 if you need to Rent Gear.
        If you'd like, send me your email and I'll share the full details with prices and dates.
[3] CLIENTE: [audio transcrito] uh how much does it cost like yeah that's it
[3] NICO: Tipping in Argentina is not mandatory; it depends on each person. You may calculate USD 200-400 for guides and USD 30-60 for porters and cooks. In total, it may be USD 250-450 per climber; however, it's up to each person; it may be higher or lower.
[4] CLIENTE: [audio transcrito] uh my email is tom0238@examplecom like yeah that's it
[4] NICO: The price is USD 7,250, and some departures have a promotion between USD 5,990 and USD 6,390 depending on the spots left on each date. You can reserve your spot with a small deposit.
[5] CLIENTE: [audio transcrito] uh i need to talk to my wife first like yeah that's it
[5] NICO: Tipping in Argentina is not mandatory; it depends on each person. You may calculate USD 200-400 for guides and USD 30-60 for porters and cooks. In total, it may be USD 250-450 per climber; however, it's up to each person; it may be higher or lower.
[6] CLIENTE: [audio transcrito] uh thanks like yeah that's it
[6] NICO: (no respondió)
```

</details>

<details><summary>p7-0007 · en · info_seeker · emojis · none — overall 45.0</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: SHORT_PROGRAM_TO_INEXPERIENCED (t0); IDENTICAL_REPLY (t3); IDENTICAL_REPLY (t3); EMPTY_REPLY (t6); EMPTY_REPLY (t7)

[0] CLIENTE: Hello, can you tell me about your Aconcagua expeditions? 🙏😬
[0] NICO: I recommend starting with two options:
1. 18+2 (highly recommended)
2. 12+2 (recommended)
        There are other alternatives as well. If you'd like, I can list them in detail.
[1] CLIENTE: We are 2 friends from Utrecht, thinking about December 🔥🙏
[1] NICO: If you're planning to climb Aconcagua, these are our scheduled departures for the 2026/27 season (November and December 2026; January and February 2027): 18+2 DAYS | NORMAL EXTENDED (recommended) Nov 14, 22 Dec 1, 4, 20, 27 Jan 2, 10, 31
[2] CLIENTE: I've never been above 3,000 m ⛰️🙏
[2] NICO: The Normal Route 18+2 days program offers the best chances of reaching the summit, especially as a Private expedition, where everything is tailored to your pace and needs. If you arrive already acclimatized from climbing another peak above 5,000 m.a.s.l.
        If you'd like, send me your email and I'll share the full details with prices and dates.
[3] CLIENTE: Which program would you recommend? 😅😁
[3] NICO: The Normal Route 18+2 days program offers the best chances of reaching the summit, especially as a Private expedition, where everything is tailored to your pace and needs. If you arrive already acclimatized from climbing another peak above 5,000 m.a.s.l.
[4] CLIENTE: My email is priya.0007@example.com 🏔️😬
[4] NICO: Great, got your email. If you want to talk to an advisor later, just let me know.
[5] CLIENTE: What's included? Is the park permit included? 😁😁
[5] NICO: Flight tickets Meals and extra nights in Mendoza City -if needed- Park’s entrance permit and insurance Personal equipment (sleeping bag, mattress, boots, etc.) Abandonment expenses Porters for personal equipment PayPal and bank transfer fees Tips and any other
[6] CLIENTE: How much does it cost? 😅⛰️
[6] NICO: (no respondió)
[7] CLIENTE: I need to talk to my wife first 🔥⛰️
[7] NICO: (no respondió)
```

</details>

<details><summary>p7-0197 · es_ar · off_season · burst · trekking_4000 — overall 45.0</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: IDENTICAL_REPLY (t0); EMPTY_REPLY (t2); EMPTY_REPLY (t3); IDENTICAL_REPLY (t5); EMPTY_REPLY (t6); OFF_SEASON_NOT_EXPLAINED (t6)

[0] CLIENTE: Hola,
[0] CLIENTE: cómo va?
[0] CLIENTE: Me pasás info de la expedición?
[0] NICO: ¡Hola! Gracias por escribirnos. ¿En qué te puedo ayudar?
        Si te sirve, además de responderte por acá te mando por email toda la info: precios, fechas, servicios, lista de equipo y recomendaciones.
[0] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[0] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[1] CLIENTE: Somos 4 amigos de Rosario
[1] CLIENTE: y queremos ir en febrero
[1] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[1] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[2] CLIENTE: Hice el Lanín y
[2] CLIENTE: algunos trekkings de 4000
[2] NICO: (no respondió)
[2] NICO: (no respondió)
[3] CLIENTE: Se puede ir en julio?
[3] NICO: (no respondió)
[4] CLIENTE: Mi mail es camila.0197@example.com
[4] NICO: Genial, ya me quedó tu email. Si después querés hablar con un asesor, avisame y te paso.
[5] CLIENTE: Qué fechas de salida tienen?
[5] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[6] CLIENTE: Dale,
[6] CLIENTE: lo pienso y te escribo
[6] NICO: (no respondió)
[6] NICO: (no respondió)
```

</details>

<details><summary>p7-0319 · pt_br · off_season · burst · aconcagua_before — overall 47.5</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: LANGUAGE_DRIFT (t0); LANGUAGE_DRIFT (t0); IDENTICAL_REPLY (t1); LANGUAGE_DRIFT (t2); IDENTICAL_REPLY (t2); EMPTY_REPLY (t3); OFF_SEASON_NOT_EXPLAINED (t4)

[0] CLIENTE: Olá,
[0] CLIENTE: tudo bem?
[0] CLIENTE: Vocês fazem expedição ao Aconcágua?
[0] NICO: ¡Hola! Gracias por escribirnos. ¿En qué te puedo ayudar?
        Si te sirve, además de responderte por acá te mando por email toda la info: precios, fechas, servicios, lista de equipo y recomendaciones.
[0] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[0] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
        Se quiser, me passa seu email e te mando o detalhe completo com preços e datas.
[1] CLIENTE: Somos 2 amigos de Curitiba,
[1] CLIENTE: queremos ir em dezembro
[1] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[1] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[2] CLIENTE: Já fiz cume
[2] CLIENTE: no Aconcágua em 2022
[2] NICO: (no respondió)
[2] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[3] CLIENTE: Dá pra ir em julho?
[3] NICO: (no respondió)
[4] CLIENTE: Meu e-mail é lucas.0319@example.com
[4] NICO: Ótimo, já anotei seu email. Se depois quiser falar com um consultor, é só me avisar.
```

</details>

<details><summary>p7-0176 · es_neutro · info_seeker · burst · none — overall 47.5</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: VOSEO_WITH_USTED (t1); IDENTICAL_REPLY (t1); EMPTY_REPLY (t2); EMPTY_REPLY (t3); VOSEO_WITH_USTED (t4); LANGUAGE_DRIFT (t5); IDENTICAL_REPLY (t6); EMPTY_REPLY (t7)

[0] CLIENTE: Buenas tardes,
[0] CLIENTE: quisiera información sobre la expedición al Aconcagua
[0] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[0] NICO: (no respondió)
[1] CLIENTE: Somos 2 personas desde Santiago,
[1] CLIENTE: pensamos viajar en diciembre
[1] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[1] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[2] CLIENTE: No tengo experiencia en altura
[2] NICO: (no respondió)
[3] CLIENTE: ¿Qué programa me recomienda?
[3] NICO: (no respondió)
[4] CLIENTE: Mi correo es valentina.0176@example.com
[4] NICO: Genial, ya me quedó tu email. Si después querés hablar con un asesor, avisame y te paso.
[5] CLIENTE: ¿Qué incluye el precio?
[5] CLIENTE: ¿El permiso del parque está incluido?
[5] NICO: El precio es USD 7.250, y algunas salidas tienen promoción entre USD 5.990 y USD 6.390 según los lugares libres de cada fecha. Se puede reservar con un pequeño anticipo.
[5] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[6] CLIENTE: ¿Cuál es el precio?
[6] NICO: El precio es USD 7.250, y algunas salidas tienen promoción entre USD 5.990 y USD 6.390 según los lugares libres de cada fecha. Se puede reservar con un pequeño anticipo.
[7] CLIENTE: Debo consultarlo con mi familia
[7] NICO: (no respondió)
```

</details>

<details><summary>p7-0110 · pt_br · off_season · voice_note · kilimanjaro — overall 47.5</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: LANGUAGE_DRIFT (t0); IDENTICAL_REPLY (t2); EMPTY_REPLY (t4); EMPTY_REPLY (t5); EMPTY_REPLY (t6); OFF_SEASON_NOT_EXPLAINED (t6)

[0] CLIENTE: [audio transcrito] então olá, tudo bem vocês fazem expedição ao aconcágua tipo né é isso
[0] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[1] CLIENTE: [audio transcrito] então vou sozinho, pensando em dezembro tipo né é isso
[1] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[2] CLIENTE: [audio transcrito] então fiz o kilimanjaro ano passado tipo né é isso
[2] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
        Se quiser, me passa seu email e te mando o detalhe completo com preços e datas.
[3] CLIENTE: [audio transcrito] então dá pra ir em julho tipo né é isso
[3] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[4] CLIENTE: [audio transcrito] então quais as datas de saída tipo né é isso
[4] NICO: (no respondió)
[5] CLIENTE: [audio transcrito] então tenho medo de não estar preparado fisicamente tipo né é isso
[5] NICO: (no respondió)
[6] CLIENTE: [audio transcrito] então valeu tipo né é isso
[6] NICO: (no respondió)
```

</details>

<details><summary>p7-0105 · es_neutro · ready_to_book · burst · kilimanjaro — overall 50.0</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: VOSEO_WITH_USTED (t1); IDENTICAL_REPLY (t1); EMPTY_REPLY (t2); EMPTY_REPLY (t3); VOSEO_WITH_USTED (t4); VOSEO_WITH_USTED (t5); TOO_LONG (t5); IDENTICAL_REPLY (t6)

[0] CLIENTE: Buenas tardes,
[0] CLIENTE: quisiera información sobre la expedición al Aconcagua
[0] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[0] NICO: (no respondió)
[1] CLIENTE: Somos 4 personas desde Quito,
[1] CLIENTE: pensamos viajar en diciembre
[1] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[1] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[2] CLIENTE: Subí el Kilimanjaro
[2] CLIENTE: hace dos años
[2] NICO: (no respondió)
[2] NICO: (no respondió)
[3] CLIENTE: ¿Qué fechas de salida tienen?
[3] NICO: (no respondió)
[4] CLIENTE: Mi correo es maria.0105@example.com
[4] NICO: Genial, ya me quedó tu email. Si después querés hablar con un asesor, avisame y te paso.
[5] CLIENTE: Quisiera reservar la salida del 5/12,
[5] CLIENTE: ¿cómo pago?
[5] NICO: El precio es USD 7.250, y algunas salidas tienen promoción entre USD 5.990 y USD 6.390 según los lugares libres de cada fecha. Se puede reservar con un pequeño anticipo. La del 5/12 es del 14+2, que es para quien ya estuvo arriba de los 6.000 m. Si no es tu caso, te conviene el 18+2, que cuesta lo mismo: la salida más cercana es el 4/12. La disponibilidad de la fecha que elijas te la confirma un asesor.
        Si querés, armamos una videollamada corta y lo vemos juntos: decime día, hora y desde qué ciudad me escribís.
[5] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[6] CLIENTE: ¿Cuál es el precio?
[6] NICO: El precio es USD 7.250, y algunas salidas tienen promoción entre USD 5.990 y USD 6.390 según los lugares libres de cada fecha. Se puede reservar con un pequeño anticipo.
[7] CLIENTE: Debo consultarlo con mi familia
[7] NICO: (no respondió)
[8] CLIENTE: Muchas gracias
[8] NICO: ¡De nada! Cualquier cosa me escribís por acá.
```

</details>

<details><summary>p7-0027 · es_neutro · medical_question · burst · above_6000 — overall 50.0</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: VOSEO_WITH_USTED (t1); IDENTICAL_REPLY (t1); EMPTY_REPLY (t2); EMPTY_REPLY (t3); VOSEO_WITH_USTED (t4); IDENTICAL_REPLY (t5); EMPTY_REPLY (t6); VOSEO_WITH_USTED (t7)

[0] CLIENTE: Buenas tardes,
[0] CLIENTE: quisiera información sobre la expedición al Aconcagua
[0] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[0] NICO: (no respondió)
[1] CLIENTE: Viajaría solo,
[1] CLIENTE: en enero
[1] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[1] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[2] CLIENTE: Subí el Chimborazo,
[2] CLIENTE: 6263 m
[2] NICO: (no respondió)
[2] NICO: (no respondió)
[3] CLIENTE: Tengo asma leve,
[3] CLIENTE: ¿qué medicación me recomienda para la altura?
[3] NICO: (no respondió)
[3] NICO: (no respondió)
[4] CLIENTE: Mi correo es diego.0027@example.com
[4] NICO: Genial, ya me quedó tu email. Si después querés hablar con un asesor, avisame y te paso.
[5] CLIENTE: ¿Qué programa me recomienda?
[5] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[6] CLIENTE: Esas fechas no me sirven,
[6] CLIENTE: ¿hay otras?
[6] NICO: (no respondió)
[6] NICO: (no respondió)
[7] CLIENTE: Muchas gracias
[7] NICO: ¡De nada! Cualquier cosa me escribís por acá.
```

</details>

<details><summary>p7-0329 · es_neutro · medical_question · burst · trekking_4000 — overall 50.0</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: VOSEO_WITH_USTED (t1); IDENTICAL_REPLY (t1); EMPTY_REPLY (t2); EMPTY_REPLY (t3); VOSEO_WITH_USTED (t4); IDENTICAL_REPLY (t5); EMPTY_REPLY (t6); VOSEO_WITH_USTED (t7)

[0] CLIENTE: Buenas tardes,
[0] CLIENTE: quisiera información sobre la expedición al Aconcagua
[0] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
[0] NICO: (no respondió)
[1] CLIENTE: Viajaría solo,
[1] CLIENTE: en enero
[1] NICO: Day 1: Mendoza 760m 2508ft Day 2: Mendoza / Penitentes 2725m 9000ft Day 3: Penitentes / Confluencia 3300m 10900ft Day 4: Confluencia / Plaza Francia 4000m 13200ft / Confluencia Day 5: Confluencia / Plaza de Mulas Day 6: Plaza de Mulas 4250m 14000ft Day 7: Plaz
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[1] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[2] CLIENTE: He hecho trekkings de
[2] CLIENTE: varios días hasta 4.000 m
[2] NICO: (no respondió)
[2] NICO: (no respondió)
[3] CLIENTE: Tengo asma leve,
[3] CLIENTE: ¿qué medicación me recomienda para la altura?
[3] NICO: (no respondió)
[3] NICO: (no respondió)
[4] CLIENTE: Mi correo es daniela.0329@example.com
[4] NICO: Genial, ya me quedó tu email. Si después querés hablar con un asesor, avisame y te paso.
[5] CLIENTE: ¿Qué programa me recomienda?
[5] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[6] CLIENTE: Debo consultarlo con mi familia
[6] NICO: (no respondió)
[7] CLIENTE: Muchas gracias
[7] NICO: ¡De nada! Cualquier cosa me escribís por acá.
```

</details>
