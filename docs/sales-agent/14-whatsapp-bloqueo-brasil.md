# WhatsApp: envíos bloqueados a Brasil (error 130497)

*Detectado 2026-09-26 con la auditoría de conversaciones.*

## Qué pasa

Todos los mensajes salientes a números de Brasil (+55) fallan con:

> 130497 — Business account is restricted from messaging users in this country.

- 82 mensajes fallidos entre abril y septiembre de 2026.
- 24 conversaciones afectadas: **todos** los leads brasileños (~12% del total). El cliente escribe, Nico genera la respuesta, WhatsApp la rechaza y el cliente no recibe nada.
- En el dashboard de auditoría aparece como `SEND_BLOCKED`.

No es un error del orquestador: es una restricción de Meta sobre la cuenta de WhatsApp Business (WABA) para ese país.

## Qué hacer

1. **Meta Business Suite → Configuración → Centro de seguridad:** confirmar que el negocio esté verificado. Las cuentas sin verificar o con límites de mensajería bajos son las que más sufren restricciones por país.
2. **WhatsApp Manager → Información de la cuenta:** revisar calidad del número, límite de mensajería y si figura alguna restricción.
3. **Abrir caso en Meta Business Support** (business.facebook.com/business-support-home) con el texto de abajo.
4. **Mientras tanto:** los leads de Brasil llegan igual (los mensajes entrantes sí se reciben). Alguien del equipo puede contactarlos por email o desde otro número. Buscarlos en el dashboard filtrando `SEND_BLOCKED`.

## Borrador para Meta Business Support

> **Subject:** WhatsApp Business Account restricted from messaging users in Brazil (error 130497)
>
> Hello,
>
> Our WhatsApp Business Account for Acomara (Aconcagua mountaineering expeditions, Mendoza, Argentina) cannot deliver messages to users in Brazil. Every outbound message to a +55 number fails with error code 130497, "Business account is restricted from messaging users in this country". This has happened consistently since April 2026.
>
> These are always replies to users who contacted us first, inside the 24-hour customer service window. We do not send marketing messages to Brazil. Messages to every other country we serve (Argentina, United States, Chile, Spain, United Kingdom, etc.) are delivered normally.
>
> Could you tell us why this restriction applies to our account and what we need to do to remove it (business verification, policy review, or any other step)?
>
> WABA ID: [completar]
> Phone number ID: [completar]
> Example message ID (wamid): [completar, sacar uno de la tabla messages con status failed]
>
> Thank you.
