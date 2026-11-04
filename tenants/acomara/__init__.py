"""Acomara: guided Aconcagua expeditions. The first tenant of the Nico engine.

Every value here was moved out of orchestrator/ unchanged; the golden test
(tests/test_acomara_golden.py) proves Acomara's replies are identical.
"""
from nico_core.tenant import KnowledgeConfig, LocaleConfig, TenantConfig
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
)
