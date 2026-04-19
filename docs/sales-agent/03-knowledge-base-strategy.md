# Estrategia para tu TXT de conocimiento (1 MB)

## Respuesta corta
Si, se puede usar perfecto. 1 MB es un tamano manejable.

## Recomendacion
Usar RAG simple desde el inicio:
1. Separar el TXT en chunks semanticos.
2. Crear embeddings por chunk.
3. Recuperar top-k chunks por consulta.
4. Responder solo con evidencia recuperada.

## Por que no meter todo el TXT en cada prompt
- Coste mayor por mensaje.
- Menor velocidad.
- Mas ruido en contexto.
- Mayor riesgo de respuestas inconsistentes.

## Especificacion tecnica sugerida
- Tamano chunk: 600 a 900 caracteres.
- Solapamiento: 80 a 120 caracteres.
- Metadata por chunk:
  - source_file
  - section_title
  - topic
  - version
  - updated_at
- top_k inicial: 4
- Re-ranking opcional: habilitar en fase 2

## Estructura recomendada del conocimiento
Crear una copia estructurada del TXT con secciones claras:
1. Itinerarios y modalidades
2. Fechas y disponibilidad
3. Precios y que incluye/no incluye
4. Requisitos fisicos y experiencia
5. Equipamiento
6. Proceso de reserva y pagos
7. Politicas de cancelacion
8. Seguridad y limites de responsabilidad
9. FAQ comerciales
10. Objeciones tipicas y respuestas

## Guardrails de respuesta
- Si no hay evidencia suficiente en chunks recuperados: responder "no tengo confirmado ese dato".
- Citar brevemente la fuente interna (seccion/tema).
- Para informacion critica (seguridad, legal, pagos), sugerir confirmacion humana.

## Plan de implementacion en 3 fases
### Fase 1 - Operativo rapido (1-2 dias)
- Limpiar el TXT.
- Separar en secciones.
- Ingesta en vector store.
- Probar 30 preguntas reales de clientes.

### Fase 2 - Calidad comercial (3-5 dias)
- Agregar FAQ y objeciones reales.
- Ajustar prompts para cierre.
- Definir reglas de handoff.

### Fase 3 - Escalado multicanal (1-2 semanas)
- Conectar WhatsApp y correo.
- Registrar interacciones en CRM.
- Medir conversion por etapa.

## Checklist antes de produccion
- [ ] Politicas comerciales validadas por equipo
- [ ] Precios vigentes y fecha de ultima actualizacion
- [ ] Plantillas de respuesta por canal
- [ ] Flujo de escalamiento a humano probado
- [ ] Prueba con casos dificiles (objeciones, dudas ambiguas, urgencias)

## Decision recomendada hoy
1. Mantener tu TXT como fuente maestra temporal.
2. Crear una version estructurada por secciones para RAG.
3. Activar agente de ventas v1 solo para dudas comerciales + avance de pipeline.
