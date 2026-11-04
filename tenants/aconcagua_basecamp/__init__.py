"""Aconcagua Basecamp (www.aconcaguabasecamp.com): PLACEHOLDER tenant.

Sketch of a second business on the Nico engine, to prove the config shape.
Not deployed and not ready to be: the texts are drafts and every fact must be
checked against the ABC web (repo diegoparma/aconcagua-basecamp-web) before
use, per CLAUDE.md ("si Nico menciona servicios sueltos o precios de
campamento, que coincidan con los de esa web").

What it shows:
- Same engine, different identity, phrases, knowledge and season words.
- No program guide and no Acomara hooks: options questions and everything
  else go to the model with ABC's own prompt and key facts.
- No CRM and no internal router (defaults).
- No FAQ index yet: the engine answers from prompt + key facts.

Split with Acomara (CLAUDE.md): Acomara sells guided expeditions; ABC sells
base camp services, unguided logistics and services for agencies. A client
of ABC asking for a guided expedition is a handoff, not a sale here.
"""
from nico_core.season import SeasonConfig
from nico_core.tenant import IntegrationsConfig, KnowledgeConfig, LocaleConfig, TenantConfig
from tenants.aconcagua_basecamp.phrases import PHRASES

TENANT = TenantConfig(
    slug="aconcagua_basecamp",
    brand_name="Aconcagua Basecamp",
    placeholder=True,
    notes="Borrador: textos y datos sin validar contra aconcaguabasecamp.com.",
    phrases=PHRASES,
    languages=("es", "en", "pt"),
    knowledge=KnowledgeConfig(
        system_prompt_path="tenants/aconcagua_basecamp/system-prompt.md",
        key_facts_path="tenants/aconcagua_basecamp/datos-clave.md",
        index_path=None,
        fallback_system_prompt=(
            "Eres un asistente comercial de servicios de campamento base en el Aconcagua. "
            "Responde con precision y no inventes datos."
        ),
    ),
    locale=LocaleConfig(utc_offset_hours=-3, tz_abbreviation="ART", label="Argentina"),
    # Same park season as Acomara; the trip words are about camp services.
    season=SeasonConfig(
        months=frozenset({11, 12, 1, 2, 3}),
        trip_intent_tokens=(
            "aconcagua", "campamento", "base camp", "basecamp", "plaza de mulas",
            "plaza argentina", "confluencia", "mula", "mule", "porteador", "porter",
            "servicio", "service", "servico", "logistica", "logistics", "expedicion",
            "expedition", "trek", "climb", "subir", "viaje", "trip", "viagem",
            "fecha", "date", "data",
        ),
    ),
    integrations=IntegrationsConfig(
        service_name="aconcagua-basecamp-orchestrator",
        user_agent="AconcaguaBasecamp-SalesAgent/1.0",
    ),
)
