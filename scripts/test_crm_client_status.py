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

    # Test with a few example emails
    test_emails = [
        "diego@example.com",  # Non-existent
        "test@example.com",   # Non-existent
    ]

    print("Testing CRM client status checker...\n")

    for email in test_emails:
        print(f"📧 Looking up: {email}")
        result = check_client_status(email)

        print(f"   Found: {result['found']}")
        if result['found']:
            print(f"   Client: {result['client_name']} (ID: {result['client_id']})")
            print(f"   Contacted: {result['contacted']}")
            print(f"   Consultations: {result['consultation_count']}")
            if result['last_consultation_date']:
                print(f"   Last consultation: {result['last_consultation_date']}")
        else:
            print(f"   Status: Not found in CRM")

        if "error" in result:
            print(f"   ❌ Error: {result['error']}")
        print()


if __name__ == "__main__":
    test_client_lookup()
