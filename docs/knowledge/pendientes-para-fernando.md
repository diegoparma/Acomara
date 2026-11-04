# Pendientes para Fernando

Revisión de lo que sabe Nico (noviembre 2026). Son preguntas que solo vos podés contestar: donde la web dice una cosa y vos dijiste otra, o donde los clientes preguntan y no tenemos respuesta. Con contestar al lado alcanza; después lo cargamos en `docs/knowledge/fuente/`.

## 1. Cosas que se contradicen (¿cuál vale?)

1. **Llegada a Mendoza.** Vos dijiste "llegar el día anterior al día 1". La web decía "hasta las 11 h del día 1 (extendidos) o las 8 h (cortos)". Ya dejamos lo tuyo. ¿Hay que corregir la web?
2. **Traslado del aeropuerto.** Vos dijiste que los traslados al aeropuerto no están incluidos. La web dice que el día 1, a las 13 h, sale un traslado grupal del aeropuerto al hotel, y lo lista como incluido. ¿Ese traslado grupal existe esta temporada?
3. **Hotel.** La web dice "hotel 5 estrellas" (Diplomatic, Intercontinental, Huentala, NH, Hilton...) y "3 noches fuera del Parque". Vos dijiste "primera noche en Mendoza, habitación compartida". ¿Sigue siendo 5 estrellas? ¿Cuántas noches fuera del Parque incluye cada programa?
4. **Programas cortos.** La web dice que el 14+2 sirve si llegás aclimatado de otro cerro de **más de 5.000 m**. Vos dijiste **más de 6.000 m**. Ya dejamos 6.000 m en Nico. Hay que corregir la web.
5. **Plaza Francia.** Los itinerarios dicen 4.000 m y la explicación de programas dice 4.200 m. ¿Cuál ponemos?
6. **Temporada.** La web dice: baja del 19 nov al 14 dic, alta del 15 dic al 31 ene, baja del 1 al 20 feb. Pero la primera salida es el 14 nov y las de febrero terminan cerca del 26 feb. ¿Qué fechas tiene el Parque para 2026/27? Hoy Nico dice "salidas de noviembre a febrero" y, si alguien pregunta por abril–octubre, avisa "la temporada es de noviembre a marzo". ¿Marzo hay algo?
7. **Link del trek a Plaza Francia en español** dice "trekking abierto", pero el trek es solo privado. ¿Lo cambiamos?

## 2. Datos que pueden estar viejos

8. **Permiso del Parque 2026/27.** Nico dice USD 650 a 1.400 comprándolo con Acomara y USD 1.100 a 1.800 por cuenta propia. ¿Siguen esos valores? ¿Se sigue pagando en efectivo y en pesos si lo saca uno solo?
9. **Seguro.** Nico dice "ronda los USD 400 con Global Rescue"; la web copia condiciones de Global Rescue de julio 2023. ¿Sigue así? ¿Qué otros seguros acepta el Parque?
10. **Promociones.** ¿Qué salidas tienen hoy promoción (USD 5.990 a 6.390)? Nico no lo dice, deriva a un asesor; si nos pasás la lista la puede usar.
11. **"Programas LITE" y "ofertas especiales"** aparecen en la web. ¿Existen todavía?

## 3. Preguntas de clientes que Nico no puede contestar

12. **Cancelación antes de salir:** si alguien cancela, ¿se devuelve el anticipo de USD 699? ¿Hasta cuándo? ¿Se puede pasar a otra fecha u otra temporada?
13. **Saldo:** ¿cuándo se paga el resto?
14. **Tarjeta:** ¿cuánto sale pagar con tarjeta?
15. **Privadas desde USD 7.990:** ¿con mínimo de personas? ¿cualquier fecha?
16. **Descuentos** por grupo, pareja o por volver: ¿hay?
17. **Viajeros solos:** ¿con quién comparten carpa y habitación?
18. **Guías en portugués:** muchos clientes son de Brasil. ¿Algún guía habla portugués?
19. **Edad máxima y certificado médico:** el trámite del permiso dice "certificado médico solo si se requiere". ¿Cuándo se pide?
20. **Precios de los opcionales:** porteador personal por tramo (en la web se perdió la tabla), wifi Starlink, duchas, baño privado, carpa individual, habitación single, aclimatación extra (EAP), traslado privado.
21. **Trek a Plaza de Mulas (USD 4.890, promo 3.690):** ¿es el mismo trek de 8 días que la web ofrece para que familiares acompañen hasta el campamento base? ¿Tiene fechas propias?
22. **Plan de entrenamiento:** la web dice "ver el link", pero no hay link. ¿Qué le mandamos al cliente?
23. **Logística sin guía:** Nico dice "esta temporada no vendemos logística suelta". ¿Lo mandamos a Aconcagua Basecamp (www.aconcaguabasecamp.com), que sí vende servicios de campamento?

## 4. Para Diego: cruzar con los otros repos

En esta sesión no se pudo abrir otros repos, así que esto queda para cruzar a mano:

- **aconcagua-plan-admin** (Aconcagua Service Provider): precio regular y promociones 2026/27, fechas de salida (`fuente/salidas.yaml`), valores del permiso 2026/27, fechas de apertura y cierre del Parque y del Glaciar Polaco (la web dice 1 de diciembre).
- **aconcagua-basecamp-web**: trek a Plaza de Mulas (USD 4.890 / 3.690), trek a Plaza Francia (USD 1.499), y precios de servicios sueltos (mulas, porteadores, wifi, duchas). Si Nico nombra un servicio de campamento, tiene que coincidir con esa web.
- **Modelo de embeddings en producción.** El índice actual tiene vectores de 1.536 dimensiones, que no son de `text-embedding-3-large` (ese da 3.072 y es el valor por defecto del servidor). Si en Vercel `OPENAI_EMBED_MODEL` no está en el modelo con el que se armó el índice (probablemente `text-embedding-3-small`), Nico busca con vectores que no se pueden comparar y los fragmentos que encuentra son casi al azar. Para revisarlo: `GET /version` muestra `openai_embed_model`. Se arregla del todo reconstruyendo el índice (ver `docs/knowledge/README.md`): desde ahí el índice anota qué modelo usó y el servidor usa ese.
- **Textos con "noviembre a marzo"**: el aviso de fuera de temporada en `orchestrator/server.py` (`out_of_season`, es/en/pt) y la regla 12 de `docs/sales-agent/15-reglas-de-nico.md`. Cambiarlos cuando Fernando conteste el punto 6.
