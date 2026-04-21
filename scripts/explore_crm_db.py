#!/usr/bin/env python3
"""Explore CRM database structure to understand client contact status."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

import mysql.connector

def explore_database(db_name: str) -> None:
    """Explore tables and structure of a database."""
    host = os.getenv("DB_HOST")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    port = int(os.getenv("DB_PORT", "3306"))

    print(f"\n{'='*60}")
    print(f"Exploring database: {db_name}")
    print(f"{'='*60}\n")

    try:
        conn = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=db_name,
            port=port,
        )
        cursor = conn.cursor()

        # Get all tables
        cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = %s", (db_name,))
        tables = cursor.fetchall()

        if not tables:
            print(f"No tables found in {db_name}")
            cursor.close()
            conn.close()
            return

        print(f"Tables in {db_name}:")
        for table in tables:
            table_name = table[0]
            print(f"\n  📋 {table_name}")

            # Get columns
            cursor.execute(f"DESCRIBE {table_name}")
            columns = cursor.fetchall()
            for col in columns:
                col_name, col_type, nullable, key, default, extra = col
                print(f"     - {col_name}: {col_type} ({nullable})")

            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]
            print(f"     Rows: {row_count}")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Error connecting to {db_name}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    explore_database("acomara_ai_dashboard")
    explore_database("acomara_ai_sgi")
