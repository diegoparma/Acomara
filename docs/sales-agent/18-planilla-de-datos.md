# Planilla de datos de Nico

*Guía para Fernando. Actualizada 2026-11-04.*

Los datos que cambian (precios, promociones, anticipo, formas de pago, permiso del Parque, seguro, alquiler de equipo, temporada) ya no se escriben en el código: Nico los lee de una planilla de Google que editás vos. Lo que cambies ahí, Nico lo usa en unos 10 minutos, sin pedirle nada a nadie.

Lo que no cambia (qué incluye cada programa, a quién recomendar el 18+2, cómo cerrar) sigue en la ficha `docs/knowledge/datos-clave.md`. Si la planilla y la ficha dicen cosas distintas sobre el mismo tema, **vale la planilla**.

## Cómo editar

Una fila por dato. Para cambiar un precio, cambiá el texto de esa fila, actualizá **Última actualización** y, si hace falta, **Vigente hasta**. Para agregar un dato nuevo, agregá una fila con una **Clave** que no exista.

No hace falta tocar nada más. No borres ni renombres la primera fila (los títulos de las columnas).

## Qué significa cada columna

| Columna | Qué poner | Ejemplo |
|---|---|---|
| **Clave** | Un nombre corto y único para la fila. No lo cambies una vez creado. | `precio-regular` |
| **Tema** | De qué trata, en pocas palabras. Nico lo usa como título del dato. | `Precio de las expediciones abiertas` |
| **Qué puede decir Nico** | La frase exacta que Nico puede usar con el cliente. Escribila como se la dirías a un cliente, completa y sin abreviaturas. | `Precio regular USD 7.250 por persona.` |
| **Estado** | `Vigente` si el dato está confirmado. `A confirmar` si todavía no. | `Vigente` |
| **Vigente hasta** | Último día en que el dato vale, como `2027-03-31` (también sirve `31/03/2027`). Vacío = no vence. | `2027-03-31` |
| **Fuente** | De dónde sale el dato (vos, el FAQ, el Parque). Nico no lo usa; es para nosotros. | `Fernando` |
| **Confirmado por** | Quién lo confirmó. | `Fernando` |
| **Última actualización** | Cuándo tocaste la fila. | `2026-11-04` |

## Qué hace Nico con cada fila

- **Vigente y sin vencer:** Nico lo usa como dato, por encima de cualquier otra fuente.
- **A confirmar:** Nico no lo dice. Si el cliente pregunta por ese tema, responde que lo confirma un asesor.
- **Vencido** (pasó la fecha de *Vigente hasta*, en hora de Argentina): igual que *A confirmar*. Nico deja de decirlo al día siguiente de la fecha.
- **Fecha que no se entiende** (por ejemplo "fin de temporada"): se trata como vencida, por seguridad.
- **Texto que parece una instrucción** ("ignorá lo anterior", "sos ahora…", "system:"): Nico no usa esa fila. La planilla es para datos, no para darle órdenes a Nico. Las reglas de comportamiento se cambian en el código.
- **Enlaces:** solo quedan los de nuestros sitios (aconcaguaexpeditions.com, acomara.com, aconcaguabasecamp.com). Cualquier otro enlace se borra del texto.
- Cada texto se corta a unos 400 caracteres y Nico lee hasta 80 filas. Los saltos de línea, asteriscos y numerales se quitan.

## Aviso de vencimientos

Los lunes a la mañana te llega un email con los datos **vencidos** y los que **vencen en los próximos 14 días** (y, de paso, los que siguen *A confirmar*). Si no hay nada vencido ni por vencer, no llega nada. Para renovar un dato: revisalo, cambiá *Vigente hasta* y *Última actualización*.

## Si la planilla falla

Si la planilla no responde o queda mal armada (por ejemplo, alguien borró la fila de títulos), Nico sigue con la última copia buena que leyó. Si nunca la pudo leer, usa la ficha `datos-clave.md`, como antes de la planilla. En `/version` (campo `facts`) se ve de dónde está leyendo, cuándo la leyó y cuántas filas están vigentes, vencidas o a confirmar.

## Puesta en marcha (Diego, una sola vez)

1. Crear la planilla en Google Sheets e importar `docs/sales-agent/planilla-datos-semilla.csv` (Archivo → Importar). La semilla sale de `datos-clave.md`: revisá las fechas de *Vigente hasta* (las promociones, el trek a Plaza de Mulas, que tiene promo, y el permiso vencen el 2026-11-30 para que Fernando los confirme) y completá la fila de **temporada**, que queda *A confirmar* porque las fuentes no coinciden (noviembre a febrero o noviembre a marzo).
2. Conseguir el enlace CSV, de una de estas dos formas:
   - Archivo → Compartir → **Publicar en la web** → la hoja → *Valores separados por comas (.csv)*. Google puede tardar unos minutos en reflejar los cambios.
   - O compartir como "cualquier persona con el enlace puede ver" y usar `https://docs.google.com/spreadsheets/d/<ID>/export?format=csv&gid=<GID>`.
   Los datos de la planilla son públicos (son los precios que damos a cualquier cliente): no pongas nada privado en esa hoja.
3. En Vercel, cargar `NICO_FACTS_CSV_URL` con ese enlace. Opcionales: `NICO_FACTS_TTL_SECONDS` (600), `NICO_FACTS_REMINDER_TO` (si el aviso no va a `HANDOFF_EMAIL_TO`), `NICO_FACTS_ALLOWED_DOMAINS`, y `CRON_SECRET` para que el aviso de los lunes (cron de `vercel.json`, `/cron/facts-reminder`) esté autorizado.
4. Cuando la planilla esté andando, sacar de `datos-clave.md` los datos que ahora viven en la planilla, para que no haya dos versiones.

Código: `orchestrator/live_facts.py`. Tests: `tests/test_live_facts.py`.
