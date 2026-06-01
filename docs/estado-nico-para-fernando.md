# Estado del Arte de Nico — Agente de Ventas Acomara
*Documento interno · Mayo 2026*

---

## Qué es Nico

Nico es el agente de ventas digital de Acomara. Funciona 24/7 por WhatsApp (y otros canales) y tiene una sola misión: convertir consultas en leads calificados para que un asesor humano cierre la venta.

No reemplaza al asesor — lo libera para que aparezca en el momento justo.

---

## Qué sabe Nico (Base de Conocimiento)

Nico tiene acceso a una base de conocimiento propia de Acomara con toda la información publicada sobre las expediciones. Esta base cubre:

| Tema | Qué puede responder |
|------|---------------------|
| **Programas** | Opciones 18+2, 14+2, 12+2 y Ruta Polaca 17+2 — descripción, diferencias, a quién conviene cada uno |
| **Rutas** | Ruta Normal y Glaciar Polaco 360° — altitudes, campamentos, perfil de dificultad |
| **Precios** | USD 6.990 estándar / USD 5.990 promocional (según evidencia publicada, siempre aclarando "sujeto a disponibilidad") |
| **Temporada y fechas** | Noviembre a marzo — fechas de salida publicadas |
| **Qué incluye** | Servicios incluidos en el programa vs. opcionales (porteadores, EAP, WiFi, traslados privados, etc.) |
| **Permisos y seguros** | Permiso de parque, cobertura de rescate y evacuación |
| **Equipamiento** | Qué llevar, qué alquilar, listas de gear |
| **Logística** | Campamentos, alimentación, menú de altura, grupos privados vs. abiertos |
| **Seguridad** | Protocolos de seguridad, guías, tamaño de grupos |
| **Propinas** | Política y montos habituales |

**Regla de oro:** Nico solo responde con información que existe en esta base. Si algo no está, no lo inventa — deriva al asesor.

---

## Qué NO puede hacer Nico (límites duros)

Estas restricciones son técnicas, no opcionales:

- **No confirma disponibilidad real de cupos** por fecha específica
- **No toma reservas** ni da confirmaciones de pago
- **No hace cotizaciones personalizadas** ni inventa descuentos
- **No da consejos médicos ni farmacológicos**
- **No mezcla información propia** con la del FAQ — cero alucinaciones

Cuando el usuario necesita algo fuera de este alcance, Nico responde con una frase fija y deriva.

---

## Frases Determinísticas (Respuestas Fijas)

Estas respuestas las genera el sistema directamente — no el modelo de IA — para garantizar consistencia total:

### Información no disponible
> *"No dispongo de esa información, pero si lo deseas puedes escribir tu correo y le pediré a un asesor humano que te contacte para ayudarte con eso."*

### Derivación a asesor
> *"Un asesor humano puede ayudarte con eso y guiarte a través de las mejores opciones."*

### Temas médicos
> *"La evaluación médica la realizan los médicos de montaña. Por favor consultá el protocolo médico."*

### Pedido de email (turno 2–4, una sola vez)
> *"Si querés, puedo enviarte el detalle completo según tu caso. ¿A qué email te lo mando?"*

### Confirmación de email recibido
> *"¡Gracias! Ya tengo tu correo registrado y un asesor humano se va a comunicar con vos pronto."*

### Fuera de temporada (consultas en abril–octubre)
> *"Importante: las expediciones al Aconcagua se realizan únicamente entre noviembre y marzo..."*

### Derivación ejecutada (después de recopilar email)
> *"Perfecto, ya derivé tu solicitud a un asesor humano. Te va a contactar a la brevedad."*

---

## Cómo se Comporta Nico

### Estilo de conversación
- Consultivo, no agresivo. Guía sin presionar.
- Respuestas cortas: máximo 2 líneas en WhatsApp (280 caracteres).
- Cada respuesta resuelve la duda **y** genera un micro-avance natural (una pregunta o sugerencia).
- Nunca repite la misma frase dos veces en la misma conversación.

### Idioma automático
Nico detecta si el usuario habla español, inglés o portugués y responde en el mismo idioma durante toda la conversación. Nunca mezcla idiomas.

### Captura de email
Entre el turno 2 y el 4, Nico pide el correo **una sola vez**, presentándolo como un beneficio ("te envío el detalle completo"). Si el usuario no lo da, sigue la conversación normalmente.

### Verificación de seguridad del email
Cuando recibe un email, el sistema lo verifica automáticamente contra una base de datos de brechas reales (Have I Been Pwned):
- **Email válido** → continúa la conversación y notifica al asesor
- **Email sospechoso** → pausa la conversación y deriva sin continuar la venta

Esto protege contra bots, spam y leads falsos.

### Escalamiento a humano
Nico escala automáticamente cuando detecta:
- Pedido explícito de hablar con una persona
- Confirmación de cupo o reserva
- Preguntas médicas o legales
- Información que no está en la base de conocimiento

---

## Lo que Nico hace bien hoy

- Responde consultas frecuentes sin intervención humana, las 24 horas
- Califica leads progresivamente (fecha objetivo, experiencia, grupo, país)
- Captura emails y notifica al equipo con el historial completo
- Opera en 3 idiomas sin configuración manual
- Nunca inventa información ni promete lo que no puede cumplir

---

## Lo que todavía hace el asesor humano

- Confirmar disponibilidad real de cupos
- Cerrar ventas y tomar reservas
- Negociar descuentos o condiciones especiales
- Acompañar casos con preguntas médicas complejas
- Atender clientes VIP o grupos grandes

---

*Este documento refleja el estado de Nico a mayo de 2026. Para ver cambios técnicos recientes, ver `docs/sales-agent/13-conversation-fix-log.md`.*
