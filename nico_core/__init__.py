"""Nico core: the business-agnostic sales engine.

A business ("tenant") is described by a `TenantConfig` living in
`tenants/<slug>/`. The engine (today still mostly `orchestrator/server.py`)
reads everything business-specific from that object. Design and migration
plan: docs/sales-agent/17-nico-producto.md.
"""
from nico_core.tenant import TenantConfig, get_tenant, load_tenant

__all__ = ["TenantConfig", "get_tenant", "load_tenant"]
