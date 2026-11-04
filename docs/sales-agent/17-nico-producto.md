# Nico como producto: un motor, varios negocios

*Diseño y plan de migración. 2026-11-04. Estado: fase 1 hecha (ver §8).*

## 1. Resumen

Nico hoy es un agente de ventas excelente **para Acomara** y difícil de usar para otra cosa: casi todo vive en `orchestrator/server.py` (~2.900 líneas) y ahí se mezclan el motor (idioma, sesión, derivación, emails, RAG, anti-duplicados, formato WhatsApp) con datos del negocio (frases con la marca, programas 18+2/12+2, temporada noviembre–marzo, regla de los 6.000 m, CRM SGI, teléfonos de caja).

La propuesta: **un motor (`nico_core/`) y una carpeta de configuración por negocio (`tenants/<negocio>/`)**. Acomara es el primer tenant, con cero cambio de comportamiento (lo prueba un test "golden"). Aconcagua Basecamp está esbozado como segundo tenant para probar que la forma funciona.

Recomendación: **un deploy por negocio** (mismo código, un proyecto de Vercel por negocio con `NICO_TENANT=<negocio>`), no multi-tenant en un solo deploy, al menos hasta tener 4–5 negocios andando. Y **construir, no comprar**, para negocios donde las reglas de venta duras importan (como Acomara); para un negocio chico con preguntas simples, una herramienta del mercado puede alcanzar (§9).

## 2. Inventario: qué es genérico y qué es de Acomara

Estado **antes** de este trabajo. La columna "Fase 1" dice dónde quedó.

### `orchestrator/server.py`

| Pieza | Tipo | Fase 1 |
|---|---|---|
| `I18N_PHRASES` (19 frases × es/en/pt, con "Acomara", "Aconcagua", "asesor", "noviembre a marzo") | Negocio | → `tenants/acomara/phrases.py` |
| Rutas del system prompt, datos clave e índice FAQ; prompt de respaldo "expediciones al Aconcagua" | Negocio | → `TenantConfig.knowledge` (los archivos no se movieron) |
| Zona horaria `ART` y "Fecha de hoy (Argentina)" en el prompt | Negocio | → `TenantConfig.locale` |
| Meses fuera de temporada (abril–octubre), palabras de intención de viaje ("aconcagua", "montaña"…) | Negocio | → `TenantConfig.season`; lógica a `nico_core/season.py` |
| Guía de opciones (18+2 y 12+2, después 14+2 y 17+2) | Negocio | → `TenantConfig.program_guide`; lógica a `nico_core/program_guide.py` |
| Llamadas a la regla de 6.000 m, al FAQ de fechas y al cierre con videollamada | Negocio | → hooks del tenant (`tenants/acomara/hooks.py`) |
| CRM (`check_client_status`), agente de caja (`internal_reply`), org de OpenBSP, agent id de Nico | Integración | → `TenantConfig.integrations` |
| Nombre del servicio en `/health`, `source` en la respuesta | Marca | → `integrations.service_name` |
| Detección de idioma es/en/pt | Motor, con palabras del rubro ("summit", "expedition", "ascent", "route", "climb", "ascenso") | → `TenantConfig.language_hints` (fase 2) |
| Instrucciones al modelo en `generate_reply` (en español, "un asesor del equipo", fechas en WhatsApp) | Motor con supuestos de Acomara | **Pendiente** (fase 2) |
| `format_whatsapp_departure_dates` (títulos "18+2 DÍAS \| …") | Negocio disfrazado de motor | **Pendiente** (fase 2, hook) |
| Comandos, anti-duplicados, pausa, derivación, verificación de email, burbujas, filtro de credenciales, endpoint OpenAI-compatible, auditoría | Motor | Queda en `server.py` (fase 3 lo mueve a `nico_core`) |
| Regex de derivación, "¿sos un bot?", saludos, agradecimientos | Motor (es/en/pt) | Queda |

### `orchestrator/*.py`

| Módulo | Tipo | Nota |
|---|---|---|
| `sales_rules.py` | Negocio (Fernando: 6.000 m, videollamada, alternativa 18+2) | Se queda donde está; lo enchufa `tenants/acomara/hooks.py` |
| `departures.py` | Negocio (temporada "2026/27", programas `1[2478]+2`) | Ídem |
| `crm_client_status.py` | Adaptador CRM de Acomara (SGI PHP + MySQL) | Lo nombra la config de Acomara |
| `caja_interno.py` | Ruteo interno de Acomara (teléfonos del equipo) | Ídem |
| `handoff_email.py` | Motor; asuntos con "[Acomara]" | Marca desde `runtime["brand_name"]` |
| `observability.py` | Motor; títulos "Acomara" | Marca por parámetro |
| `security.py` | Motor; User-Agent "Acomara" | Por parámetro |
| `policies.py`, `inbound.py`, `session_client.py`, `human_activity.py` | Motor | Sin cambios |
| `humanize.py` | Motor + voz rioplatense | Lo edita otra sesión: no se tocó. Fase 2: voz como config |
| `conversation_audit.py` | Motor (palabras clave genéricas de ventas) | Sin cambios |

## 3. Arquitectura objetivo

```
                 ┌──────────────── canal ────────────────┐
WhatsApp/OpenBSP │  /v1/chat/completions (hoy)           │  email, web chat (futuro)
                 └───────────────────┬───────────────────┘
                                     ▼
┌────────────────────────── nico_core (motor) ──────────────────────────┐
│ normalizar → ruteo interno → sesión → humano activo → CRM → email      │
│ → derivación → pausa → frases fijas → hooks.fixed_replies             │
│ → guía de opciones → RAG (+hooks.select/rewrite_evidence) → modelo     │
│ → hooks.close_reply → políticas (email, temporada) → formato → envío   │
└──────┬──────────────┬───────────────┬──────────────┬──────────────────┘
       │              │               │              │
   TenantConfig   SessionStore    CrmLookup     Handoff (email)
   (tenants/x)   (session-agent)  (adaptador)   (Resend/SMTP)
```

### `TenantConfig` (hoy, en `nico_core/tenant.py`)

| Campo | Qué es | Acomara |
|---|---|---|
| `slug`, `brand_name` | Identidad | `acomara`, "Acomara" |
| `phrases` | Frases fijas por idioma (claves obligatorias en `REQUIRED_PHRASES`) | 19 frases × 3 idiomas |
| `languages` | Idiomas; el primero es el de respaldo | es, en, pt |
| `knowledge` | System prompt, datos clave, índice FAQ (rutas, no copias) | `docs/sales-agent/02-system-prompt.md`, `docs/knowledge/…` |
| `locale` | Zona horaria y etiqueta para "hoy" | UTC-3, "Argentina" |
| `season` | Meses en que opera + palabras de intención | nov–mar |
| `program_guide` | Respuesta fija a "¿qué opciones hay?" | 18+2/12+2 → 14+2/17+2 |
| `hooks` | Reglas de venta en código (§4) | 6.000 m, fechas, videollamada |
| `integrations` | CRM, ruteo interno, ids de OpenBSP/Supabase, nombre del servicio | SGI, caja, ids actuales |
| `placeholder` | Marca un tenant que no está listo para producción | `False` |

Para completar en fase 2: `voice` (reglas de `humanize.py`: voseo, emojis, largo de burbujas), `prompt_instructions` (las reglas fijas que hoy arma `generate_reply`), `qualification_fields` (qué datos junta Nico antes de derivar: fechas, cantidad de personas, experiencia; hoy implícitos en el prompt) y `handoff` (destinatarios por tipo: lead, derivación, alerta de bot).

**Por qué Python y no YAML (por ahora):** la config tiene regex y funciones; en Python no hace falta ninguna dependencia nueva y los tests la validan. Lo que edita alguien que no programa (frases, datos clave, prompt) ya está o puede estar en archivos de texto que la config solo nombra.

## 4. Puntos de extensión

| Punto | Interfaz | Hoy |
|---|---|---|
| **Reglas fijas antes del modelo** | `hooks.fixed_replies: (texto, idioma) -> str \| None` | Regla de 6.000 m |
| **Evidencia** | `hooks.select_evidence(hits, filas, texto, idioma, top_k)` y `hooks.rewrite_evidence(respuesta, hoy)` | FAQ de fechas primero; saca salidas pasadas |
| **Cierre** | `hooks.close_reply(respuesta, CloseContext)` | Videollamada + alternativa 18+2 |
| **CRM** | `integrations.crm_lookup(phone=, email=) -> dict` (mismo formato que `NOT_FOUND`) | SGI; `no_crm` por defecto |
| **Ruteo interno** | `integrations.internal_router(teléfono, texto) -> str \| None` | Caja; nada por defecto |
| **Canal** | Hoy un solo canal de entrada: el endpoint OpenAI-compatible que llama OpenBSP. Fase 3: interfaz `Channel` (parsear entrada, enviar burbujas, límites de largo) para sumar email o web chat sin tocar el motor | OpenBSP |
| **Memoria de sesión** | `session_client.py` contra session-agent (compartido con otros proyectos: no se cambia por Nico). Fase 3: interfaz `SessionStore` con la misma firma (`get/upsert/append_event/delete`) para poder usar otro almacén en un negocio que no use session-agent | session-agent |
| **Conocimiento** | `knowledge.*` (rutas). Fase 3: fuente pluggable (Google Drive, Notion, la web del negocio) que genere el índice con `scripts/build_cloud_index.py` | Archivos del repo |
| **Derivación** | Hoy un destinatario por deploy (`HANDOFF_EMAIL_TO`). Fase 2: `handoff` en la config con destinatarios por motivo | Email del equipo |

Regla para los hooks: si se puede expresar como dato (una lista, una frase, un mes), va como dato; si necesita lógica (comparar alturas, cruzar una fecha con las salidas), va como hook. El motor nunca importa nada de `tenants/`.

## 5. Multi-tenant o un deploy por negocio

| | Un deploy por negocio (recomendado) | Multi-tenant (un deploy, tenant por número/organización) |
|---|---|---|
| Aislamiento | Total: secretos, logs, límites y caídas separados | Un bug o un pico de un negocio afecta a todos |
| Secretos | Cada proyecto de Vercel tiene los suyos | Hay que guardar claves por tenant y elegirlas por pedido |
| Deploy | Un cambio de Acomara no redeploya ABC si no se quiere (cada proyecto puede seguir una rama o un tag) | Un deploy para todos |
| Costo | Vercel cobra por uso, no por proyecto: casi igual | Igual |
| Código | `NICO_TENANT` fijo al arrancar: lo que ya está hecho | Hay que pasar el tenant por todo el pipeline en vez de leerlo una vez |
| Cuándo cambiar | — | Con muchos negocios chicos parecidos, o si se vende Nico a terceros |

El diseño no cierra la puerta: el motor ya lee todo de un objeto `TenantConfig`; pasar a multi-tenant es elegir ese objeto por pedido (por `organization_id` de OpenBSP) en vez de por variable de entorno.

## 6. Cómo se enchufan los evals

Otra sesión está armando `evals/`. La forma propuesta para que sirvan a varios negocios:

- **Tests deterministas por tenant**: `tests/test_acomara_golden.py` congela todas las frases fijas y las salidas de las reglas para un corpus de mensajes. Cada tenant nuevo tiene el suyo. Es la red que permite refactorizar el motor.
- **Evals con modelo por tenant**: `evals/<tenant>/casos.*` (conversaciones y criterios), corridos con `NICO_TENANT=<tenant>`. El arnés no necesita saber de qué negocio se trata: arranca el server con el tenant y manda los mensajes.
- **Evals genéricos para todos**: derivación, cambio de idioma, "¿sos un bot?", no repetir el pedido de email, no inventar precios. Se corren contra cada tenant y validan el motor.
- **Gate de producción**: un tenant con `placeholder=True` no se despliega; uno real necesita su golden y sus evals en verde.

## 7. Plan de migración por fases

| Fase | Qué | Riesgo | Estado |
|---|---|---|---|
| **1. Extraer datos de negocio** | `TenantConfig`, `tenants/acomara`, frases, conocimiento, temporada, guía de opciones, hooks, marca e integraciones. Test golden + test de un segundo tenant | Bajo: golden idéntico | **Hecha** (este PR) |
| **2. Completar la config** | `voice` (cuando la sesión de voz cierre `humanize.py`), instrucciones del prompt de `generate_reply`, ~~palabras del rubro en la detección de idioma~~ (hecho), formato de fechas como hook, destinatarios de derivación, textos de emails y respuesta de credenciales por idioma. Mover `sales_rules.py` y `departures.py` a `tenants/acomara/` cuando no haya otras sesiones tocándolos | Medio: tocan el prompt; el golden de prompts lo cubre | Siguiente |
| **3. Partir `server.py`** | El pipeline a `nico_core/pipeline.py`, adaptadores `Channel` y `SessionStore`, `server.py` queda como app Flask fina | Medio: mucho movimiento de código; tests de flujo existentes | Después |
| **4. Segundo negocio real** | ABC con textos y precios validados contra su web, su índice FAQ, su prompt; deploy propio | Bajo para Acomara | Cuando Diego decida |
| **5. Herramientas** | Script "nuevo tenant" (copia una plantilla y valida), validación de config en CI, guía para cargar conocimiento | Bajo | Opcional |

Reglas de la migración: pasos chicos, un commit por paso, el golden no cambia; los archivos que editan otras sesiones (`humanize.py`, el system prompt, `docs/knowledge/*`) no se mueven, se referencian.

## 8. Qué quedó hecho en la fase 1

- `nico_core/tenant.py`: `TenantConfig`, `KnowledgeConfig`, `LocaleConfig`, `IntegrationsConfig`, `load_tenant` / `get_tenant` (`NICO_TENANT`, por defecto `acomara`).
- `nico_core/season.py`, `nico_core/program_guide.py`, `nico_core/hooks.py`: lógica genérica que antes estaba en `server.py`.
- `tenants/acomara/`: frases, rutas, temporada, guía de opciones, hooks (regla de 6.000 m, fechas, videollamada) e integraciones (SGI, caja, ids).
- `tenants/aconcagua_basecamp/` (**placeholder**): otra identidad, frases, prompt y datos clave; sin guía de opciones, sin hooks, sin CRM, sin índice FAQ.
- Tests: `tests/test_acomara_golden.py` (frases, reglas, formato WhatsApp, prompt al modelo), `tests/test_tenants.py` (carga, completitud, marca), `tests/test_second_tenant.py` (levanta el server con ABC y verifica que no se filtra nada de Acomara).
- `server.py` mantiene los mismos nombres públicos (`I18N_PHRASES`, `check_client_status`, `today_in_argentina`, …): ningún test ni script existente cambió.

**Para desplegar otro negocio hoy:** crear `tenants/<negocio>/` copiando el de ABC, escribir su prompt y datos clave, crear un proyecto de Vercel con el mismo repo y `NICO_TENANT=<negocio>` más sus propias variables (OpenAI, OpenBSP, session-agent, email de derivación).

## 9. ¿Construir o comprar?

Comparación cualitativa: los precios cambian seguido, verificarlos antes de decidir.

| | Nico (propio) | Agentes IA de plataformas de soporte (Intercom Fin, Zendesk AI) | Plataformas de mensajería con IA (respond.io, Kommo, Botmaker, Treble) | Constructores de bots (Voiceflow, Chatbase, Botpress) |
|---|---|---|---|---|
| WhatsApp | Sí, vía OpenBSP | Sí, con su inbox | Sí, es su fuerte | Sí, con integraciones |
| Reglas duras de venta (6.000 m, temporada, salidas pasadas) | En código, con tests | Instrucciones en texto al modelo: justo lo que falló en las simulaciones de octubre | Flujos fijos + IA; reglas finas, difícil | Flujos visuales; algo de código posible |
| CRM propio (SGI) | Adaptador a medida | Mejor con su propio CRM / integraciones estándar | CRM incluido (Kommo) o integraciones | Webhooks/código |
| Silencio cuando escribe un humano, bots detectados, caja interna | Sí | Parcial (handoff sí; lo demás no) | Handoff sí | A construir |
| Voz rioplatense, pocas líneas, burbujas | Controlada | Configurable en tono, no en detalle | Limitada | Configurable |
| Inbox para el equipo, reportes, multi-agente humano | No (usa OpenBSP + dashboard simple) | Excelente | Excelente | Básico |
| Evals y regresiones | Golden + evals propios | Pruebas de la plataforma, sin control fino | Pocas | Algunas |
| Costo | OpenAI + Vercel (bajo) + tiempo de desarrollo y mantenimiento | Por resolución o por asiento; sube con el volumen | Por asiento/contactos | Por plan/mensajes |
| Dependencia | De Diego (y de quien mantenga el código) | Del proveedor | Del proveedor | Del proveedor |

**Lectura:** lo que hace valioso a Nico para Acomara son justamente las reglas que el modelo no aplica solo (documentadas en `sales_rules.py`, `departures.py` y el log de fixes) y las integraciones propias (SGI, Supabase, caja). Eso es lo que una herramienta del mercado no da sin el mismo trabajo. A cambio, una herramienta da inbox, reportes y cero mantenimiento.

- **Construir (Nico)** para negocios con reglas de venta propias, precios que cambian por fecha o integraciones a medida: Acomara, ABC, logística de mulas.
- **Comprar** para un negocio con preguntas simples y sin CRM propio, o si nadie va a mantener el código: el costo de una plataforma es menor que el de sostener un motor.
- **Mixto** posible: Nico como "modelo" detrás de una plataforma con inbox (como hoy con OpenBSP), así el equipo usa un inbox de mercado y las reglas siguen en código.
