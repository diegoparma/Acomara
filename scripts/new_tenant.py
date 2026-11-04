#!/usr/bin/env python3
"""Create tenants/<slug>/ from tenants/_template/ for a new business on Nico.

Usage:
    python3 scripts/new_tenant.py <slug> "<Brand Name>"

The new tenant is a placeholder: it loads and passes tests/test_tenants.py
right away, and it is not ready to deploy until its texts are rewritten
(see the checklist in the generated __init__.py).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tenants" / "_template"


def create_tenant(slug: str, brand: str, root: Path = ROOT) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", slug):
        raise ValueError("slug: lowercase letters, digits and underscores, starting with a letter")
    target = root / "tenants" / slug
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    values = {
        "{SLUG}": slug,
        "{SLUG_DASH}": slug.replace("_", "-"),
        "{SLUG_CAMEL}": "".join(part.capitalize() for part in slug.split("_")),
        "{BRAND}": brand.replace('"', "'"),
    }
    target.mkdir(parents=True)
    for tmpl in sorted(TEMPLATE.glob("*.tmpl")):
        text = tmpl.read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace(key, value)
        (target / tmpl.name.removesuffix(".tmpl")).write_text(text, encoding="utf-8")
    return target


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    target = create_tenant(argv[1], argv[2])
    print(f"Created {target.relative_to(ROOT)}. Run: python3 -m pytest tests/test_tenants.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
