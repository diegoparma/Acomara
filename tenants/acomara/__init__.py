"""Acomara: guided Aconcagua expeditions. The first tenant of the Nico engine.

Every value here was moved out of orchestrator/ unchanged; the golden test
(tests/test_acomara_golden.py) proves Acomara's replies are identical.
"""
from nico_core.tenant import TenantConfig
from tenants.acomara.phrases import I18N_PHRASES

TENANT = TenantConfig(
    slug="acomara",
    brand_name="Acomara",
    phrases=I18N_PHRASES,
    languages=("es", "en", "pt"),
)
