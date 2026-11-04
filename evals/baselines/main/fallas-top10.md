# Nico en `main`: las 10 fallas principales (baseline con modelo real)

*Corrida del 2026-11-04. Código de Nico: `main` (`130c9c8`), con el harness de `claude/loving-davinci-otqdgy` (`4f8c061`). 330 conversaciones simuladas (300 combinatorias y 30 escritas por el modelo, semilla 7). Nico `gpt-4.1-mini`, cliente simulado `gpt-4.1-mini`, juez `gpt-4.1`. Costo total: USD 9,18 (USD 0,028 por conversación). Números completos en `report.md` y `summary.json`.*

**Todas las citas salen de conversaciones simuladas** con personas ficticias (`@example.com`). No hay datos de clientes reales.

**Overall: 50,4 / 100** (±2,0). Por dimensión, de 1 a 5: humanness 2,70 · accuracy 3,23 · rules 2,75 · sales 2,58 · language 3,88 · length 4,12.

## Cómo leer los números

- **"regex"**: lo detectó un chequeo determinista. Es confiable y sirve para medir antes y después.
- **"juez"**: lo marcó el juez LLM. Ve fallas que un regex no ve, pero exagera en algunos códigos. Por ejemplo, marcó `INVENTED_PRICE` en 45 conversaciones y los regex solo en 3, que además son falsos positivos (repetir el presupuesto del cliente, sumar precio + permiso + seguro). Por eso el precio inventado **no** entra en esta lista.
- El juez solo lee `datos-clave.md`. Cosas que están en el FAQ pero no en datos-clave las marca como inventadas; un caso es el "Extra Acclimatization Program" (`faq-048`).
- En **37 de las 330 conversaciones (11 %) el juez no devolvió veredicto**: su JSON se cortó por `max_tokens=1200` (`evals/judge.py:92`). Se pierden sobre todo las conversaciones largas. Arreglarlo le toca a la sesión del harness.
- Los conteos son conversaciones con al menos una ocurrencia, sobre 330.

---

## A. Reglas en código (`server.py`, frases fijas)

Son las más baratas de arreglar y las que más se repiten: el modelo no tiene la culpa, la frase sale siempre igual.

### 1. La lista fija de programas recomienda el 12+2 a cualquiera — 110 conv. (regex 50, juez 103)

`_first_program_options_reply` (regla 9) contesta "1. 18+2 (muy recomendada) 2. 12+2 (recomendada)" antes de saber la experiencia. Salió en 104 conversaciones; en 50 de ellas el cliente no había pasado los 6.000 m. Contradice la regla de 6.000 m de Fernando y además le baja el puntaje de accuracy y de sales a toda la conversación.

> "Para empezar, te recomiendo estas dos opciones: 1. 18+2 (muy recomendada) 2. 12+2 (recomendada)" (a un cliente sin experiencia de altura, l7-0010)

### 2. Las frases fijas tratan de vos a quien escribe de usted — 77 de 85 conversaciones en español neutro (regex)

En 74 de esas 77, el voseo viene de una frase fija: el pedido de email, "ya me quedó tu email", "avisame y te paso". Al cliente de México o España le llegan con voseo aunque el modelo le venga hablando de usted. *(La rama `gracious-fermi-gwx1jf-usted` / `-saludo` apunta justo a esto.)*

> "Si querés, pasame tu email y te mando el detalle completo con precios y fechas." (p7-0005, cliente de español neutro)

### 3. Pide el email cuando ya se lo dieron o está por dárselo — 68 conv. (juez; regex 6) + 19 con el email pedido dos veces

En 38 de los 68 casos es el pedido fijo de email ("Si querés, pasame tu email…" / "Se quiser, me passa seu email…"), que se dispara después de que el cliente ya lo escribió o dijo que lo iba a pasar. En los demás, el modelo da a entender que todavía le falta el email.

> "Si querés, pasame tu email y te mando el detalle completo con precios y fechas." (p7-0009: el cliente ya había dado el email en el mensaje anterior, y encima escribe en portugués)

### 4. Silencios y repeticiones literales — 21 conv. sin respuesta (regex; 46 según el juez) · 53 con una frase larga repetida igual (regex)

Al cliente que insiste o se queja de que no le contestan, Nico no le responde nada (la regla 15 suprime la repetición y no queda otra cosa). Además, en 35 de las 53 conversaciones con frase repetida lo repetido es la lista de fechas, y la lista fija "Las otras alternativas son: 1. 14+2 2. 17+2" sale dos veces.

> Cliente: "He notado que me han enviado nuevamente las opciones 14+2 y 17+2 sin mayor detalle…" → Nico: *(no respondió)* (l7-0013)

## B. Voz / prompt (lo que escribe el modelo)

### 5. Deriva a un asesor en vez de contestar — 152 conv. (juez, 46 %)

Es la falla más frecuente. Preguntas que Nico puede contestar con datos-clave (fechas, pagos, seguro, dinámica del grupo) terminan en "eso te lo confirma un asesor", a veces varias veces en la misma charla. En 129 de los 152 casos la cita es una derivación explícita a un asesor o consultor.

> "Para condições específicas, um assessor pode te ajudar melhor." (p7-0168, ante una consulta sobre pagos)

### 6. Le contesta en español a los brasileños — 44 de 78 conversaciones en portugués (regex)

Es casi siempre el modelo y no una frase fija: copia el FAQ o datos-clave (que están en español o inglés) sin traducirlos. Le pasa también a algunos clientes en inglés (9). Además hay frases fijas solo en español o inglés que le llegan a clientes en portugués ("¡Gracias! Ya tengo tu email…", "I recommend starting with two options…").

> "El precio básico es USD 7.250 por persona para el 18+2 Normal Extendido…" (a una clienta que escribe en portugués, l7-0012)

### 7. Suena a bot, no califica y no cierra — tono robótico 100 conv. · no califica 101 · comprador sin videollamada 84 (juez)

Tres síntomas del mismo problema. Respuestas tipo folleto, ninguna pregunta sobre experiencia, grupo o fechas antes de recomendar, y cuando el cliente ya está listo, en vez de invitarlo a la videollamada, el cierre es "si después querés hablar con un asesor, avisame".

> "We recommend renting gear in advance to guarantee availability and quality; your equipment will be ready at the gear check." (l7-0006)

### 8. Tira la lista entera de fechas como si hubiera cupo — 83 conv. demasiado largas (regex; 56 de ellas por la lista de fechas) · 75 "confirma disponibilidad" (juez; 44 son listas de fechas)

A "¿qué fechas hay?", el modelo manda las cuatro salidas con todas sus fechas en un mensaje de 350 a 540 caracteres, sin aclarar que el cupo lo confirma un asesor. Ojo: el juez marca `CONFIRMS_AVAILABILITY` con más dureza que la regla. Listar las fechas programadas no es confirmar un lugar, y solo 2 casos los vio el regex. Lo que importa es el muro de texto y la falta de esa aclaración.

> "Estas son las fechas disponibles: 1. 18+2 días Normal Extendido: Nov 14, 22; Dic 1, 4, 20, 27; Ene 2, 10, 31; Feb 7 2. 14+2 días Ascenso Rápido: …" (l7-0021)

## C. Base de conocimiento (`datos-clave.md`, FAQ)

### 9. Lo que incluye y lo que no, contado a medias, más extras inventados — 65 conv. "incluye todo / no aclara exclusiones" (juez) · 27 con un dato inventado (juez)

Nico enumera lo que incluye y se olvida de lo que no incluye (vuelos, permiso, seguro, equipo personal), o mezcla los extras pagos con lo incluido. También inventa extras: duchas calientes en la privada, "pitching de barracas", que la familia acompaña "8 días" en base, que no se alquilan crampones. Hace falta una lista clara de incluido / no incluido / extras con precio, en español y portugués, que el modelo pueda copiar tal cual.

> "Incluye hotel en Mendoza, traslados, comidas en montaña, mulas, guías, carpas, botiquín, porteadores para equipo común y apoyo en campamentos base." (l7-0000; no dice que el permiso y el seguro van aparte)

### 10. Consejo médico copiado del FAQ — 29 conv. (juez; 15 mencionan Diamox)

Cuando le preguntan por asma, aclimatación o medicación, el modelo repite el FAQ (`faq-047`, `faq-048`): "no recomendamos Diamox", ejercicios de respiración, 3 a 5 litros de agua. No da dosis, pero la regla de Nico es derivar todo lo médico al médico de montaña. **Lo tiene que decidir Fernando:** o el FAQ se reescribe para Nico ("eso lo ve el médico de la expedición"), o se acepta esa postura como oficial y se ajusta la rúbrica.

> "No recomendamos Diamox ni otros medicamentos para la aclimatación, llevá solo los que un médico te haya prescripto." (p7-0135)

## D. Datos que cambian (temporada, fechas, precios)

No entró al top 10 por cantidad, pero hay que arreglarlo antes de medir otra cosa:

- **La temporada está escrita de dos formas.** `datos-clave.md` dice "temporada noviembre a febrero"; la regla 12 de `server.py` y la documentación dicen noviembre a marzo. *(La rama `gracious-cray-lb4lwk` la pone en nov-mar en la hoja.)* Con esto el juez marca como error ofrecer marzo, y el aviso de fuera de temporada falla en 13 de 20 conversaciones `off_season` según el juez (1 según el regex).
- **Fechas y promos dadas como precio cerrado.** "el precio va de USD 5.990 a USD 7.250 según fecha y promoción" sale sin decir qué fecha tiene promo ni hasta cuándo. En 15 conversaciones el juez marcó fechas contradictorias entre turnos (`WRONG_FACT`). Cuando las fechas y las promos vengan de la hoja de Fernando, conviene medir esto otra vez.

---

## Resumen por área

| Área | Fallas | Conversaciones afectadas (aprox.) |
|---|---|---|
| Reglas en código | 1, 2, 3, 4 | 110 · 77 · 68 · 21 + 53 |
| Voz / prompt | 5, 6, 7, 8 | 152 · 44 · ~100 · 83 |
| Base de conocimiento | 9, 10 | 65 · 29 |
| Datos que cambian | temporada, promos | 13 · 15 |
