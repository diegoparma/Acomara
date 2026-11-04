"""Acomara: guided Aconcagua expeditions. The first tenant of the Nico engine.

Every value here was moved out of orchestrator/ unchanged; the golden test
(tests/test_acomara_golden.py) proves Acomara's replies are identical.
"""
from nico_core.program_guide import ProgramGuideConfig
from nico_core.season import SeasonConfig
from nico_core.tenant import IntegrationsConfig, KnowledgeConfig, LanguageHints, LocaleConfig, TenantConfig
from orchestrator.caja_interno import internal_reply
from orchestrator.conversation_audit import DEFAULT_ORG_ID
from orchestrator.crm_client_status import check_client_status
from orchestrator.human_activity import DEFAULT_NICO_AGENT_ID
from tenants.acomara.hooks import HOOKS
from tenants.acomara.phrases import I18N_PHRASES

TENANT = TenantConfig(
    slug="acomara",
    brand_name="Acomara",
    phrases=I18N_PHRASES,
    languages=("es", "en", "pt"),
    knowledge=KnowledgeConfig(
        # Edited by other work streams: referenced here, not moved.
        system_prompt_path="docs/sales-agent/02-system-prompt.md",
        key_facts_path="docs/knowledge/datos-clave.md",
        index_path="docs/knowledge/faq_cloud_index.jsonl",
        fallback_system_prompt=(
            "Eres un asistente comercial de expediciones al Aconcagua. "
            "Responde con precision y no inventes datos."
        ),
    ),
    # Argentina has no DST: Mendoza is UTC-3 all year.
    locale=LocaleConfig(utc_offset_hours=-3, tz_abbreviation="ART", label="Argentina"),
    # Southern Hemisphere season: expeditions November to March.
    season=SeasonConfig(
        months=frozenset({11, 12, 1, 2, 3}),
        trip_intent_tokens=(
            "tour", "expedicion", "expedición", "expedition", "trek", "trekking",
            "ascen", "subir", "climb", "summit", "viaje", "viagem", "paseo",
            "passeio", "passei", "passe", "salida", "departure", "saida", "saída",
            "aconcagua", "montaña", "montanha", "mountain", "alta montaña",
            "alta montanha", "fecha", "data", "date",
        ),
    ),
    # "¿Qué opciones tienen?": Fernando leads with the 18+2 and the 12+2.
    # Portuguese gets the Spanish text, as before the split.
    program_guide=ProgramGuideConfig(
        known_product_re=r"\b(18\s*\+\s*2|17\s*\+\s*2|14\s*\+\s*2|12\s*\+\s*2)\b",
        first_intent_keywords=(
            "opciones",
            "alternativas",
            "programas",
            "itinerarios",
            "expediciones",
            "que opciones",
            "cuales son",
            "what options",
            "which options",
            "alternatives",
            "programs",
            "itineraries",
            "expeditions",
        ),
        followup_keywords=(
            "otras",
            "otras opciones",
            "otras alternativas",
            "las otras",
            "restantes",
            "demas",
            "todas",
            "lista",
            "listame",
            "all options",
            "other options",
            "other alternatives",
            "the other",
            "list the others",
        ),
        first_reply={
            "en": (
                "I recommend starting with two options:\n"
                "1. 18+2 (highly recommended)\n"
                "2. 12+2 (recommended)\n\n"
                "There are other alternatives as well. If you'd like, I can list them in detail."
            ),
            "es": (
                "Para empezar, te recomiendo estas dos opciones:\n"
                "1. 18+2 (muy recomendada)\n"
                "2. 12+2 (recomendada)\n\n"
                "También hay otras alternativas. Si querés, te las paso en detalle."
            ),
        },
        followup_reply={
            "en": "The other alternatives are:\n1. 14+2\n2. 17+2",
            "es": "Las otras alternativas son:\n1. 14+2\n2. 17+2",
        },
    ),
    hooks=HOOKS,
    # Mountaineering words that were part of the engine's language detection.
    language_hints=LanguageHints(
        strong={"en": ("summit", "expedition", "ascent")},
        keywords={"es": ("ascenso",), "en": ("expedition", "route")},
        stopwords={"en": ("climb", "climbing")},
    ),
    integrations=IntegrationsConfig(
        service_name="acomara-orchestrator",
        user_agent="Acomara-SalesAgent/1.0",
        # SGI endpoint (sgi_endpoint/nico_cliente_status.php), MySQL fallback.
        crm_lookup=check_client_status,
        # Team phones go to the cash-flow agent in aconcagua-plan-admin.
        internal_router=internal_reply,
        openbsp_organization_id=DEFAULT_ORG_ID,
        agent_id=DEFAULT_NICO_AGENT_ID,
    ),
)
