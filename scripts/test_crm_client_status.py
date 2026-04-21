#!/usr/bin/env python3
"""Test CRM client status checker."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT))
from orchestrator.crm_client_status import check_client_status

def test_client_lookup():
    """Test looking up clients in the CRM."""

    # Test with phone numbers and emails
    test_cases = [
        ("5491234567", None, "Phone lookup example"),
        (None, "test@example.com", "Email fallback example"),
        ("invalid_phone", "invalid@example.com", "Non-existent client"),
    ]

    print("Testing CRM client status checker...\n")

    for phone, email, description in test_cases:
        print(f"📞 {description}")
        if phone:
            print(f"   Phone: {phone}")
        if email:
            print(f"   Email: {email}")

        result = check_client_status(phone=phone, email=email)

        print(f"   Found: {result['found']}")
        if result['found']:
            print(f"   Client: {result['client_name']} (ID: {result['client_id']})")
            print(f"   Contacted: {result['contacted']}")
            print(f"   Consultations: {result['consultation_count']}")
            if result['last_consultation_date']:
                print(f"   Last consultation: {result['last_consultation_date']}")
            print(f"   Search method: {result.get('search_by', 'unknown')}")
        else:
            print(f"   Status: Not found in CRM")

        if "error" in result:
            print(f"   ❌ Error: {result['error']}")
        print()


if __name__ == "__main__":
    test_client_lookup()
