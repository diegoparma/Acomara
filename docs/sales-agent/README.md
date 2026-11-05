# Documentación del agente Nico

Índice de `docs/sales-agent/`. Empezar por 15 (cómo se comporta) y 16 (cómo se mide).

- `01-agent-design.md`: diseño original del agente de ventas.
- `02-system-prompt.md`: system prompt vigente (la voz y las reglas del modelo).
- `03-knowledge-base-strategy.md`: cómo está pensada la base de conocimiento.
- `04-operating-playbook.md`: playbook operativo.
- `05-cloud-only-rag.md`: búsqueda de fragmentos (RAG) sin modelos locales.
- `06-openbsp-session-orchestrator.md`: orquestador OpenBSP + memoria de sesiones + RAG.
- `07-vercel-deploy.md`: deploy del orquestador en Vercel.
- `08-email-security-verification.md`: verificación y seguridad del email.
- `09-auditoria-conversaciones-2026-05-05.md`: auditoría técnica de mayo.
- `13-conversation-fix-log.md`: registro de arreglos a partir de conversaciones.
- `14-whatsapp-bloqueo-brasil.md`: envíos bloqueados a Brasil (error 130497).
- `15-reglas-de-nico.md`: manual de reglas, en el orden en que Nico las evalúa.
- `16-evals.md`: evals con conversaciones simuladas y tope de costo.
- `18-planilla-de-datos.md`: planilla de Google con los datos que cambian.
- `19-cierre-orquestado.md`: tablero del pase final de mejoras (2026-11-05).
- `planilla-datos-semilla.csv`: datos iniciales de la planilla.

Otros lugares:

- `docs/knowledge/fuente/`: fuente única de datos (`datos-clave.yaml`, `faq.yaml`, `salidas.yaml`, `valores.yaml`); se reconstruye con `scripts/build_knowledge.py`.
- `docs/estado-nico-para-fernando.md`: estado de Nico en lenguaje simple para Fernando.
