# Acomara — agente de ventas "Nico"

Agente de ventas por WhatsApp/email para expediciones al Aconcagua. Diseño y operación en `docs/sales-agent/`; estado general en `docs/estado-nico-para-fernando.md`.

## Parte del negocio Aconcagua

Este repo es parte del mismo negocio que:

- **`~/Documents/Aconcagua Service Provider`**: licitación y concesión del Parque Provincial Aconcagua vía Zurbriggen 6962 SAS, infraestructura de campamentos, permisos, admin/investor room. Si una tarea toca precios, programas, temporada o permisos, revisar también ese repo para mantener los datos consistentes.
- **`~/Documents/aconcagua-basecamp-web`** (github diegoparma/aconcagua-basecamp-web): web de **Aconcagua Basecamp**, la marca hermana que vende servicios de campamento base sueltos (www.aconcaguabasecamp.com). Reparto de búsquedas: Acomara = expediciones guiadas; ABC = servicios de campamento, logística sin guía y agencias. No copiar textos entre los dos sitios; si Nico menciona servicios sueltos o precios de campamento, que coincidan con los de esa web.

## Dependencias

- **`~/Documents/session_agent`** (github diegoparma/session-agent): memoria de sesiones, consumida vía `SESSION_AGENT_BASE_URL` (`orchestrator/session_client.py`). Es infraestructura **compartida con otros proyectos**: no hacerle cambios pensados solo para Acomara sin evaluar el impacto en los demás.
