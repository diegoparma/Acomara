# Evals de Nico — 2026-11-04 01:18 · offline-main

## Resumen

Modo: **offline-stub** · commit `659cceb` (claude/loving-davinci-otqdgy) · 2026-11-04T01:18:50+00:00

320 conversaciones (semilla 7, 0 personas escritas por LLM) · 5.681 turnos promedio · errores: 0 · Nico: `gpt-4.1-mini` · simulador: `gpt-4.1-mini` · juez: `gpt-4.1`

Costo total: **USD 0.00** (USD 0.0000 por conversación)

> Corrida OFFLINE: Nico respondió con un stub (inicio de la respuesta del FAQ), el cliente fue un guion fijo y los puntajes salen solo de los chequeos deterministas. Sirve para probar el harness y las reglas fijas del código, no la calidad del prompt.

## Puntajes por dimensión (1-5)

| dimensión | media | IC 95% |
|---|---|---|
| **overall (0-100)** | 72.81 | ±1.35 |
| humanness | 2.98 | ±0.13 |
| accuracy | 4.62 | ±0.11 |
| rules | 3.96 | ±0.13 |
| sales | 3.95 | ±0.04 |
| language | 3.33 | ±0.20 |
| length | 4.97 | ±0.02 |

## Top 10 patrones de falla

1. **IDENTICAL_REPLY** (humanness, sev 2): Repite la misma frase larga palabra por palabra. 263 conv. (82.2%; regex 263, juez 0). Ej. (p7-0000, turno 3): "Usually, 30-44lbs (14-20Kg), it will depend on the personal equipment of each one."
2. **LANGUAGE_DRIFT** (rules, sev 3): Responde en otro idioma que el del cliente. 127 conv. (39.7%; regex 127, juez 0). Ej. (p7-0001, turno 1): "PRICE It varies from USD 650 to USD 1400 if you buy it through us, according to the pre-sale -if available-nationality, route, and departure date. It's not incl"
3. **EMPTY_REPLY** (rules, sev 1): Nico no respondió nada a un mensaje. 188 conv. (58.8%; regex 188, juez 0). Ej. (p7-0002, turno 6): "Is rescue insurance included? Is it mandatory? 😬😁"
4. **VOSEO_WITH_USTED** (language, sev 1): Le habla de vos a un cliente que escribe en español neutro / de usted. 64 conv. (20.0%; regex 64, juez 0). Ej. (p7-0005, turno 1): "Si querés, te las paso en detalle."
5. **SHORT_PROGRAM_TO_INEXPERIENCED** (accuracy, sev 3): Recomienda 12+2/14+2 a alguien sin 6.000 m. 21 conv. (6.6%; regex 21, juez 0). Ej. (p7-0009, turno 0): "12+2 (recommended)"
6. **OFF_SEASON_NOT_EXPLAINED** (accuracy, sev 2): El cliente pidió fechas fuera de temporada y nunca se le dijo que es nov-feb/mar. 13 conv. (4.1%; regex 13, juez 0). Ej. (p7-0028, turno 3): ""
7. **TOO_LONG** (length, sev 1): Respuesta más larga que el límite del canal. 10 conv. (3.1%; regex 10, juez 0). Ej. (p7-0007, turno 4): "Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario A saída de 5/12 é do 14…"
8. **NO_VIDEOCALL_FOR_BUYER** (sales, sev 1): Cliente listo para reservar y nunca se le ofreció videollamada. 5 conv. (1.6%; regex 5, juez 0). Ej. (p7-0023, turno 4): ""

## Chequeos deterministas (regex)

| código | sev | conv. | tasa | ocurrencias |
|---|---|---|---|---|
| IDENTICAL_REPLY | 2 | 263 | 82.2% | 338 |
| EMPTY_REPLY | 1 | 188 | 58.8% | 337 |
| LANGUAGE_DRIFT | 3 | 127 | 39.7% | 278 |
| VOSEO_WITH_USTED | 1 | 64 | 20.0% | 116 |
| SHORT_PROGRAM_TO_INEXPERIENCED | 3 | 21 | 6.6% | 21 |
| FAQ_ONLY_PRICE | 1 | 17 | 5.3% | 40 |
| OFF_SEASON_NOT_EXPLAINED | 2 | 13 | 4.1% | 13 |
| TOO_LONG | 1 | 10 | 3.1% | 10 |
| NO_VIDEOCALL_FOR_BUYER | 1 | 5 | 1.6% | 5 |

## Resultados de venta

| resultado | tasa |
|---|---|
| email_requested | 88.1% |
| client_gave_email | 50.6% |
| email_captured | 50.6% |
| videocall_offered | 4.4% |
| paused | 3.1% |

## Por idioma

| grupo | n | overall | % con falla crítica |
|---|---|---|---|
| en | 80 | 72.96 | 22.5% |
| es_ar | 80 | 72.61 | 53.7% |
| es_neutro | 80 | 71.46 | 48.7% |
| pt_br | 80 | 74.20 | 57.5% |

## Por intención

| grupo | n | overall | % con falla crítica |
|---|---|---|---|
| agency_reseller | 20 | 82.29 | 35.0% |
| asks_if_bot | 20 | 80.85 | 55.0% |
| basecamp_only | 20 | 68.30 | 55.0% |
| family_decision | 20 | 72.75 | 40.0% |
| gear_and_insurance | 20 | 71.63 | 45.0% |
| info_seeker | 20 | 69.81 | 60.0% |
| medical_question | 20 | 73.61 | 45.0% |
| off_season | 20 | 66.30 | 45.0% |
| payment_methods | 20 | 69.19 | 25.0% |
| price_shopper | 20 | 66.56 | 65.0% |
| private_expedition | 20 | 67.94 | 60.0% |
| ready_to_book | 20 | 70.62 | 70.0% |
| short_program_fan | 20 | 74.81 | 60.0% |
| trek_only | 20 | 72.74 | 40.0% |
| troll_spam | 20 | 77.30 | 5.0% |
| wants_human | 20 | 80.23 | 25.0% |

## Por estilo

| grupo | n | overall | % con falla crítica |
|---|---|---|---|
| burst | 40 | 68.34 | 55.0% |
| code_switch | 40 | 71.94 | 60.0% |
| emojis | 40 | 74.08 | 40.0% |
| long_email | 40 | 84.70 | 27.5% |
| normal | 40 | 76.22 | 45.0% |
| terse | 40 | 71.61 | 55.0% |
| typos | 40 | 73.02 | 27.5% |
| voice_note | 40 | 62.55 | 55.0% |

## Por experiencia

| grupo | n | overall | % con falla crítica |
|---|---|---|---|
| above_6000 | 62 | 74.20 | 33.9% |
| aconcagua_before | 89 | 73.60 | 51.7% |
| kilimanjaro | 56 | 73.45 | 51.8% |
| none | 58 | 70.72 | 44.8% |
| trekking_4000 | 55 | 71.50 | 43.6% |

## Tokens y costo

| rol | modelo | llamadas | input | cached | output | USD |
|---|---|---|---|---|---|---|
| nico | gpt-4.1-mini | 1510 | 0 | 0 | 0 | 0.00 |
| nico_embeddings | text-embedding-3-small | 1510 | 0 | 0 | 0 | 0.00 |

## Peores 12 conversaciones

<details><summary>p7-0206 · es_ar · price_shopper · voice_note · none — overall 16.2</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: FAQ_ONLY_PRICE (t1); FAQ_ONLY_PRICE (t1); LANGUAGE_DRIFT (t1); FAQ_ONLY_PRICE (t2); FAQ_ONLY_PRICE (t2); LANGUAGE_DRIFT (t2); IDENTICAL_REPLY (t2); IDENTICAL_REPLY (t2)

[0] CLIENTE: [audio transcrito] eh hola quería info del aconcagua o sea nada bueno eso
[0] NICO: ¡Hola! Gracias por escribirnos. ¿En qué te puedo ayudar?
        Si te sirve, además de responderte por acá te mando por email toda la info: precios, fechas, servicios, lista de equipo y recomendaciones.
[1] CLIENTE: [audio transcrito] eh y cuánto sale o sea nada bueno eso
[1] NICO: PRICE It varies from USD 650 to USD 1400 if you buy it through us, according to the pre-sale -if available-nationality, route, and departure date. It's not included in the expedition price. Or from USD 1100 to USD 1800 if you buy it on your own.
[2] CLIENTE: [audio transcrito] eh vamos 4 con mi grupo, la idea es diciembre o sea nada bueno eso
[2] NICO: PRICE It varies from USD 650 to USD 1400 if you buy it through us, according to the pre-sale -if available-nationality, route, and departure date. It's not included in the expedition price. Or from USD 1100 to USD 1800 if you buy it on your own.
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[3] CLIENTE: [audio transcrito] eh nunca subí más de 3000 metros o sea nada bueno eso
[3] NICO: PRICE It varies from USD 650 to USD 1400 if you buy it through us, according to the pre-sale -if available-nationality, route, and departure date. It's not included in the expedition price. Or from USD 1100 to USD 1800 if you buy it on your own.
[4] CLIENTE: [audio transcrito] eh mi mail es florencia0206@examplecom o sea nada bueno eso
[4] NICO: (no respondió)
[5] CLIENTE: [audio transcrito] eh uff es caro, no tienen algún descuento o sea nada bueno eso
[5] NICO: (no respondió)
[6] CLIENTE: [audio transcrito] eh qué incluye el permiso está incluido o sea nada bueno eso
[6] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[7] CLIENTE: [audio transcrito] eh lo tengo que hablar con mi señora antes o sea nada bueno eso
[7] NICO: (no respondió)
[8] CLIENTE: [audio transcrito] eh dale, lo pienso y te escribo o sea nada bueno eso
[8] NICO: (no respondió)
```

</details>

<details><summary>p7-0240 · en · off_season · voice_note · none — overall 32.5</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: SHORT_PROGRAM_TO_INEXPERIENCED (t0); IDENTICAL_REPLY (t3); IDENTICAL_REPLY (t3); EMPTY_REPLY (t4); EMPTY_REPLY (t5); EMPTY_REPLY (t6); OFF_SEASON_NOT_EXPLAINED (t6)

[0] CLIENTE: [audio transcrito] uh hello, can you tell me about your aconcagua expeditions like yeah that's it
[0] NICO: I recommend starting with two options:
1. 18+2 (highly recommended)
2. 12+2 (recommended)
        There are other alternatives as well. If you'd like, I can list them in detail.
[1] CLIENTE: [audio transcrito] uh can we go in july like yeah that's it
[1] NICO: Usually, 30-44lbs (14-20Kg), it will depend on the personal equipment of each one. The loads are divided into two parts: Up to 4300m/14000ft (Plaza de Mulas / Plaza Argentina) From 4300m/14000ft (high camps)
[2] CLIENTE: [audio transcrito] uh we are 3 friends from utrecht, thinking about january like yeah that's it
[2] NICO: If you're planning to climb Aconcagua, these are our scheduled departures for the 2026/27 season (November and December 2026; January and February 2027): 18+2 DAYS | NORMAL EXTENDED (recommended) Nov 14, 22 Dec 1, 4, 20, 27 Jan 2, 10, 31
        If you'd like, send me your email and I'll share the full details with prices and dates.
[3] CLIENTE: [audio transcrito] uh i've never been above 3,000 m like yeah that's it
[3] NICO: Usually, 30-44lbs (14-20Kg), it will depend on the personal equipment of each one. The loads are divided into two parts: Up to 4300m/14000ft (Plaza de Mulas / Plaza Argentina) From 4300m/14000ft (high camps)
[4] CLIENTE: [audio transcrito] uh my email is emily0240@examplecom like yeah that's it
[4] NICO: (no respondió)
[5] CLIENTE: [audio transcrito] uh what departure dates do you have like yeah that's it
[5] NICO: (no respondió)
[6] CLIENTE: [audio transcrito] uh thanks like yeah that's it
[6] NICO: (no respondió)
```

</details>

<details><summary>p7-0095 · en · payment_methods · voice_note · kilimanjaro — overall 32.5</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: SHORT_PROGRAM_TO_INEXPERIENCED (t0); IDENTICAL_REPLY (t3); IDENTICAL_REPLY (t3); EMPTY_REPLY (t4); EMPTY_REPLY (t5); EMPTY_REPLY (t6); EMPTY_REPLY (t9)

[0] CLIENTE: [audio transcrito] uh hello, can you tell me about your aconcagua expeditions like yeah that's it
[0] NICO: I recommend starting with two options:
1. 18+2 (highly recommended)
2. 12+2 (recommended)
        There are other alternatives as well. If you'd like, I can list them in detail.
[1] CLIENTE: [audio transcrito] uh how much does it cost like yeah that's it
[1] NICO: Usually, 30-44lbs (14-20Kg), it will depend on the personal equipment of each one. The loads are divided into two parts: Up to 4300m/14000ft (Plaza de Mulas / Plaza Argentina) From 4300m/14000ft (high camps)
[2] CLIENTE: [audio transcrito] uh we are 6 friends from bangalore, thinking about december like yeah that's it
[2] NICO: If you're planning to climb Aconcagua, these are our scheduled departures for the 2026/27 season (November and December 2026; January and February 2027): 18+2 DAYS | NORMAL EXTENDED (recommended) Nov 14, 22 Dec 1, 4, 20, 27 Jan 2, 10, 31
        If you'd like, send me your email and I'll share the full details with prices and dates.
[3] CLIENTE: [audio transcrito] uh i climbed kilimanjaro last year like yeah that's it
[3] NICO: Usually, 30-44lbs (14-20Kg), it will depend on the personal equipment of each one. The loads are divided into two parts: Up to 4300m/14000ft (Plaza de Mulas / Plaza Argentina) From 4300m/14000ft (high camps)
[4] CLIENTE: [audio transcrito] uh my email is hannah0095@examplecom like yeah that's it
[4] NICO: (no respondió)
[5] CLIENTE: [audio transcrito] uh how do i pay can i use a credit card and keep the promo price like yeah that's it
[5] NICO: (no respondió)
[6] CLIENTE: [audio transcrito] uh how much is the deposit and when is the balance due like yeah that's it
[6] NICO: (no respondió)
[7] CLIENTE: [audio transcrito] uh can i pay in crypto like yeah that's it
[7] NICO: The price is USD 7,250, and some departures have a promotion between USD 5,990 and USD 6,390 depending on the spots left on each date. You can reserve your spot with a small deposit.
[8] CLIENTE: [audio transcrito] uh that's expensive, any discount like yeah that's it
[8] NICO: FLY IN You may arrive in Mendoza (MDZ Airport): until Day 1 at 11 AM for Extended programs of 17-18 + 2 extra days until Day 1 at 8 AM for Fast or Extreme itineraries of 12-14 + 2 extra days We recommend coming 1-2 days before Day 1 if you need to Rent Gear.
[9] CLIENTE: [audio transcrito] uh thanks like yeah that's it
[9] NICO: (no respondió)
```

</details>

<details><summary>p7-0236 · es_ar · off_season · voice_note · none — overall 38.8</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: LANGUAGE_DRIFT (t0); EMPTY_REPLY (t1); LANGUAGE_DRIFT (t2); IDENTICAL_REPLY (t2); LANGUAGE_DRIFT (t3); EMPTY_REPLY (t4); EMPTY_REPLY (t5); EMPTY_REPLY (t6)

[0] CLIENTE: [audio transcrito] eh buenas, estoy viendo lo del aconcagua o sea nada bueno eso
[0] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[1] CLIENTE: [audio transcrito] eh se puede ir en julio o sea nada bueno eso
[1] NICO: (no respondió)
[2] CLIENTE: [audio transcrito] eh somos 2 amigos de montevideo y queremos ir en febrero o sea nada bueno eso
[2] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[3] CLIENTE: [audio transcrito] eh nunca subí más de 3000 metros o sea nada bueno eso
[3] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[4] CLIENTE: [audio transcrito] eh qué fechas de salida tienen o sea nada bueno eso
[4] NICO: (no respondió)
[5] CLIENTE: [audio transcrito] eh lo tengo que hablar con mi señora antes o sea nada bueno eso
[5] NICO: (no respondió)
[6] CLIENTE: [audio transcrito] eh gracias o sea nada bueno eso
[6] NICO: (no respondió)
```

</details>

<details><summary>p7-0055 · en · payment_methods · normal · none — overall 38.8</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: SHORT_PROGRAM_TO_INEXPERIENCED (t0); IDENTICAL_REPLY (t3); IDENTICAL_REPLY (t3); EMPTY_REPLY (t4); EMPTY_REPLY (t5); EMPTY_REPLY (t6)

[0] CLIENTE: Hello, can you tell me about your Aconcagua expeditions?
[0] NICO: I recommend starting with two options:
1. 18+2 (highly recommended)
2. 12+2 (recommended)
        There are other alternatives as well. If you'd like, I can list them in detail.
[1] CLIENTE: How much does it cost?
[1] NICO: Usually, 30-44lbs (14-20Kg), it will depend on the personal equipment of each one. The loads are divided into two parts: Up to 4300m/14000ft (Plaza de Mulas / Plaza Argentina) From 4300m/14000ft (high camps)
[2] CLIENTE: We are 2 friends from Sydney, thinking about December
[2] NICO: If you're planning to climb Aconcagua, these are our scheduled departures for the 2026/27 season (November and December 2026; January and February 2027): 18+2 DAYS | NORMAL EXTENDED (recommended) Nov 14, 22 Dec 1, 4, 20, 27 Jan 2, 10, 31
        If you'd like, send me your email and I'll share the full details with prices and dates.
[3] CLIENTE: I've never been above 3,000 m
[3] NICO: Usually, 30-44lbs (14-20Kg), it will depend on the personal equipment of each one. The loads are divided into two parts: Up to 4300m/14000ft (Plaza de Mulas / Plaza Argentina) From 4300m/14000ft (high camps)
[4] CLIENTE: How do I pay? Can I use a credit card and keep the promo price?
[4] NICO: (no respondió)
[5] CLIENTE: How much is the deposit and when is the balance due?
[5] NICO: (no respondió)
[6] CLIENTE: Can I pay in crypto?
[6] NICO: (no respondió)
```

</details>

<details><summary>p7-0184 · es_ar · payment_methods · voice_note · trekking_4000 — overall 41.2</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: FAQ_ONLY_PRICE (t1); FAQ_ONLY_PRICE (t1); LANGUAGE_DRIFT (t1); FAQ_ONLY_PRICE (t3); FAQ_ONLY_PRICE (t3); LANGUAGE_DRIFT (t3); IDENTICAL_REPLY (t3); IDENTICAL_REPLY (t3)

[0] CLIENTE: [audio transcrito] eh hola quería info del aconcagua o sea nada bueno eso
[0] NICO: ¡Hola! Gracias por escribirnos. ¿En qué te puedo ayudar?
        Si te sirve, además de responderte por acá te mando por email toda la info: precios, fechas, servicios, lista de equipo y recomendaciones.
[1] CLIENTE: [audio transcrito] eh y cuánto sale o sea nada bueno eso
[1] NICO: PRICE It varies from USD 650 to USD 1400 if you buy it through us, according to the pre-sale -if available-nationality, route, and departure date. It's not included in the expedition price. Or from USD 1100 to USD 1800 if you buy it on your own.
[2] CLIENTE: [audio transcrito] eh voy solo, la idea es ir en febrero o sea nada bueno eso
[2] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[3] CLIENTE: [audio transcrito] eh hice el lanín y algunos trekkings de 4000 o sea nada bueno eso
[3] NICO: PRICE It varies from USD 650 to USD 1400 if you buy it through us, according to the pre-sale -if available-nationality, route, and departure date. It's not included in the expedition price. Or from USD 1100 to USD 1800 if you buy it on your own.
```

</details>

<details><summary>p7-0119 · es_neutro · private_expedition · code_switch · trekking_4000 — overall 45.0</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: SHORT_PROGRAM_TO_INEXPERIENCED (t1); LANGUAGE_DRIFT (t1); LANGUAGE_DRIFT (t2); LANGUAGE_DRIFT (t3); IDENTICAL_REPLY (t3); LANGUAGE_DRIFT (t4); LANGUAGE_DRIFT (t5); EMPTY_REPLY (t6)

[0] CLIENTE: Buenas tardes, quisiera información sobre la expedición al Aconcagua please
[0] NICO: ¡Hola! Gracias por escribirnos. ¿En qué te puedo ayudar?
        Si te sirve, además de responderte por acá te mando por email toda la info: precios, fechas, servicios, lista de equipo y recomendaciones.
[1] CLIENTE: ¿Ofrecen expediciones privadas con guía exclusivo? ¿Cuál es el price? please
[1] NICO: I recommend starting with two options:
1. 18+2 (highly recommended)
2. 12+2 (recommended)
        There are other alternatives as well. If you'd like, I can list them in detail.
[2] CLIENTE: Somos 6 personas desde Medellín, pensamos viajar en enero please
[2] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
        If you'd like, send me your email and I'll share the full details with prices and dates.
[3] CLIENTE: He hecho trekkings de varios días hasta 4.000 m please
[3] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[4] CLIENTE: Mi correo es maria.0119@example.com please
[4] NICO: Great, got your email. If you want to talk to an advisor later, just let me know.
[5] CLIENTE: ¿Qué programa me recomienda? please
[5] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[6] CLIENTE: ¿Qué dates de salida tienen? please
[6] NICO: (no respondió)
[7] CLIENTE: Thank you so much please
[7] NICO: (no respondió)
```

</details>

<details><summary>p7-0056 · en · price_shopper · voice_note · kilimanjaro — overall 45.0</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: SHORT_PROGRAM_TO_INEXPERIENCED (t0); IDENTICAL_REPLY (t3); IDENTICAL_REPLY (t3); EMPTY_REPLY (t4); EMPTY_REPLY (t6)

[0] CLIENTE: [audio transcrito] uh hello, can you tell me about your aconcagua expeditions like yeah that's it
[0] NICO: I recommend starting with two options:
1. 18+2 (highly recommended)
2. 12+2 (recommended)
        There are other alternatives as well. If you'd like, I can list them in detail.
[1] CLIENTE: [audio transcrito] uh how much does it cost like yeah that's it
[1] NICO: Usually, 30-44lbs (14-20Kg), it will depend on the personal equipment of each one. The loads are divided into two parts: Up to 4300m/14000ft (Plaza de Mulas / Plaza Argentina) From 4300m/14000ft (high camps)
[2] CLIENTE: [audio transcrito] uh i'd be going solo, probably in december like yeah that's it
[2] NICO: If you're planning to climb Aconcagua, these are our scheduled departures for the 2026/27 season (November and December 2026; January and February 2027): 18+2 DAYS | NORMAL EXTENDED (recommended) Nov 14, 22 Dec 1, 4, 20, 27 Jan 2, 10, 31
        If you'd like, send me your email and I'll share the full details with prices and dates.
[3] CLIENTE: [audio transcrito] uh i climbed kilimanjaro last year like yeah that's it
[3] NICO: Usually, 30-44lbs (14-20Kg), it will depend on the personal equipment of each one. The loads are divided into two parts: Up to 4300m/14000ft (Plaza de Mulas / Plaza Argentina) From 4300m/14000ft (high camps)
[4] CLIENTE: [audio transcrito] uh my email is priya0056@examplecom like yeah that's it
[4] NICO: (no respondió)
[5] CLIENTE: [audio transcrito] uh that's expensive, any discount like yeah that's it
[5] NICO: FLY IN You may arrive in Mendoza (MDZ Airport): until Day 1 at 11 AM for Extended programs of 17-18 + 2 extra days until Day 1 at 8 AM for Fast or Extreme itineraries of 12-14 + 2 extra days We recommend coming 1-2 days before Day 1 if you need to Rent Gear.
[6] CLIENTE: [audio transcrito] uh what's included is the park permit included like yeah that's it
[6] NICO: (no respondió)
```

</details>

<details><summary>p7-0107 · pt_br · price_shopper · terse · aconcagua_before — overall 47.5</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: LANGUAGE_DRIFT (t0); EMPTY_REPLY (t1); LANGUAGE_DRIFT (t3); IDENTICAL_REPLY (t3); IDENTICAL_REPLY (t4); EMPTY_REPLY (t5); EMPTY_REPLY (t6)

[0] CLIENTE: fazem expedição ao aconcágua?
[0] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[1] CLIENTE: quanto custa?
[1] NICO: (no respondió)
[2] CLIENTE: queremos ir em janeiro
[2] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[3] CLIENTE: no aconcágua em 2022
[3] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[4] CLIENTE: tá caro, tem desconto?
[4] NICO: Si planeas escalar el Aconcagua, estas son nuestras salidas programadas para la temporada 2026/27 (noviembre y diciembre de 2026; enero y febrero de 2027): 18+2 DÍAS | NORMAL EXTENDIDO (recomendado) Nov 14, 22 Dic 1, 4, 20, 27 Ene 2, 10 |
[5] CLIENTE: do parque está incluída?
[5] NICO: (no respondió)
[6] CLIENTE: não estar preparado fisicamente
[6] NICO: (no respondió)
[7] CLIENTE: valeu!
[7] NICO: ¡De nada! Cualquier cosa me escribís por acá.
```

</details>

<details><summary>p7-0044 · en · off_season · voice_note · trekking_4000 — overall 48.8</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: SHORT_PROGRAM_TO_INEXPERIENCED (t0); EMPTY_REPLY (t5); IDENTICAL_REPLY (t6); EMPTY_REPLY (t7); OFF_SEASON_NOT_EXPLAINED (t7)

[0] CLIENTE: [audio transcrito] uh hello, can you tell me about your aconcagua expeditions like yeah that's it
[0] NICO: I recommend starting with two options:
1. 18+2 (highly recommended)
2. 12+2 (recommended)
        There are other alternatives as well. If you'd like, I can list them in detail.
[1] CLIENTE: [audio transcrito] uh can we go in july like yeah that's it
[1] NICO: Usually, 30-44lbs (14-20Kg), it will depend on the personal equipment of each one. The loads are divided into two parts: Up to 4300m/14000ft (Plaza de Mulas / Plaza Argentina) From 4300m/14000ft (high camps)
[2] CLIENTE: [audio transcrito] uh we are 6 friends from bangalore, thinking about december like yeah that's it
[2] NICO: If you're planning to climb Aconcagua, these are our scheduled departures for the 2026/27 season (November and December 2026; January and February 2027): 18+2 DAYS | NORMAL EXTENDED (recommended) Nov 14, 22 Dec 1, 4, 20, 27 Jan 2, 10, 31
        If you'd like, send me your email and I'll share the full details with prices and dates.
[3] CLIENTE: [audio transcrito] uh i've done multi-day treks up to 4,000 m like yeah that's it
[3] NICO: FLY IN You may arrive in Mendoza (MDZ Airport): until Day 1 at 11 AM for Extended programs of 17-18 + 2 extra days until Day 1 at 8 AM for Fast or Extreme itineraries of 12-14 + 2 extra days We recommend coming 1-2 days before Day 1 if you need to Rent Gear.
[4] CLIENTE: [audio transcrito] uh my email is hannah0044@examplecom like yeah that's it
[4] NICO: The price is USD 7,250, and some departures have a promotion between USD 5,990 and USD 6,390 depending on the spots left on each date. You can reserve your spot with a small deposit.
[5] CLIENTE: [audio transcrito] uh what departure dates do you have like yeah that's it
[5] NICO: (no respondió)
[6] CLIENTE: [audio transcrito] uh those dates don't work for me, any others like yeah that's it
[6] NICO: If you're planning to climb Aconcagua, these are our scheduled departures for the 2026/27 season (November and December 2026; January and February 2027): 18+2 DAYS | NORMAL EXTENDED (recommended) Nov 14, 22 Dec 1, 4, 20, 27 Jan 2, 10, 31
[7] CLIENTE: [audio transcrito] uh thanks like yeah that's it
[7] NICO: (no respondió)
```

</details>

<details><summary>p7-0089 · es_ar · private_expedition · voice_note · none — overall 51.2</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: LANGUAGE_DRIFT (t0); EMPTY_REPLY (t1); LANGUAGE_DRIFT (t2); IDENTICAL_REPLY (t2); LANGUAGE_DRIFT (t3); EMPTY_REPLY (t4); EMPTY_REPLY (t5); EMPTY_REPLY (t6)

[0] CLIENTE: [audio transcrito] eh buenas, estoy viendo lo del aconcagua o sea nada bueno eso
[0] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[1] CLIENTE: [audio transcrito] eh queremos una expedición privada, con guía solo para nosotros cuánto sale o sea nada bueno eso
[1] NICO: (no respondió)
[2] CLIENTE: [audio transcrito] eh vamos 4 con mi grupo, la idea es diciembre o sea nada bueno eso
[2] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
        Si querés, pasame tu email y te mando el detalle completo con precios y fechas.
[3] CLIENTE: [audio transcrito] eh nunca subí más de 3000 metros o sea nada bueno eso
[3] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[4] CLIENTE: [audio transcrito] eh mi mail es martin0089@examplecom o sea nada bueno eso
[4] NICO: (no respondió)
[5] CLIENTE: [audio transcrito] eh qué programa nos conviene o sea nada bueno eso
[5] NICO: (no respondió)
[6] CLIENTE: [audio transcrito] eh qué fechas de salida tienen o sea nada bueno eso
[6] NICO: (no respondió)
[7] CLIENTE: [audio transcrito] eh en esas fechas no puedo, hay otras o sea nada bueno eso
[7] NICO: El precio es USD 7.250, y algunas salidas tienen promoción entre USD 5.990 y USD 6.390 según los lugares libres de cada fecha. Se puede reservar con un pequeño anticipo.
[8] CLIENTE: [audio transcrito] eh dale, lo pienso y te escribo o sea nada bueno eso
[8] NICO: (no respondió)
```

</details>

<details><summary>p7-0030 · en · off_season · burst · trekking_4000 — overall 51.2</summary>

```
juez offline: puntajes derivados de los chequeos deterministas
Problemas: SHORT_PROGRAM_TO_INEXPERIENCED (t0); IDENTICAL_REPLY (t2); IDENTICAL_REPLY (t2); IDENTICAL_REPLY (t5); IDENTICAL_REPLY (t5); IDENTICAL_REPLY (t6); OFF_SEASON_NOT_EXPLAINED (t7)

[0] CLIENTE: Hello,
[0] CLIENTE: can you tell me about your Aconcagua expeditions?
[0] NICO: Hi! Thanks for reaching out. How can I help?
        If it's useful, besides answering here I can email you all the info: prices, dates, services, gear list and recommendations.
[0] NICO: I recommend starting with two options:
1. 18+2 (highly recommended)
2. 12+2 (recommended)
        There are other alternatives as well. If you'd like, I can list them in detail.
[1] CLIENTE: Can we go in July?
[1] NICO: Yes, however, availability and proper quality are not guaranteed. We strongly recommend renting in advance to guarantee availability and adequate quality.
        If you'd like, send me your email and I'll share the full details with prices and dates.
[2] CLIENTE: We are 2 friends from Sydney,
[2] CLIENTE: thinking about January
[2] NICO: Yes, however, availability and proper quality are not guaranteed. We strongly recommend renting in advance to guarantee availability and adequate quality.
[2] NICO: If you're planning to climb Aconcagua, these are our scheduled departures for the 2026/27 season (November and December 2026; January and February 2027): 18+2 DAYS | NORMAL EXTENDED (recommended) Nov 14, 22 Dec 1, 4, 20, 27 Jan 2, 10, 31
[3] CLIENTE: I've done multi-day treks
[3] CLIENTE: up to 4,000 m
[3] NICO: (no respondió)
[3] NICO: The Normal Route 18+2 days program offers the best chances of reaching the summit, especially as a Private expedition, where everything is tailored to your pace and needs. If you arrive already acclimatized from climbing another peak above 5,000 m.a.s.l.
[4] CLIENTE: My email is hannah.0030@example.com
[4] NICO: Great, got your email. If you want to talk to an advisor later, just let me know.
[5] CLIENTE: What departure dates
[5] CLIENTE: do you have?
[5] NICO: The Normal Route 18+2 days program offers the best chances of reaching the summit, especially as a Private expedition, where everything is tailored to your pace and needs. If you arrive already acclimatized from climbing another peak above 5,000 m.a.s.l.
[5] NICO: Please visit: training comments to climb Aconcagua Principio del formulario Final del formulario
[6] CLIENTE: Those dates don't work for me,
[6] CLIENTE: any others?
[6] NICO: If you're planning to climb Aconcagua, these are our scheduled departures for the 2026/27 season (November and December 2026; January and February 2027): 18+2 DAYS | NORMAL EXTENDED (recommended) Nov 14, 22 Dec 1, 4, 20, 27 Jan 2, 10, 31
[6] NICO: The prices are the same in any open expedition, no matter how many days it takes, so there are no savings when doing a short program, while the primary services are the same for all open expeditions.
[7] CLIENTE: Thanks!
[7] NICO: You're welcome! Message me here anytime.
```

</details>
