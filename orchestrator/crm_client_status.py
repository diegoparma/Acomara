"""CRM client status checker.

Verifies if a client was previously contacted by checking for consultation records.
Searches by phone number (primary) or email (fallback).
"""

import os
import mysql.connector
from typing import Optional


def get_db_connection():
    """Create a connection to the CRM database."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "66.225.201.197"),
        user=os.getenv("DB_USER", "acomara_ai"),
        password=os.getenv("DB_PASSWORD"),
        database="acomara_ai_sgi",
        port=int(os.getenv("DB_PORT", "3306")),
    )


def check_client_status(phone: str = None, email: str = None) -> dict:
    """Check if a client was previously contacted.

    Searches by phone (primary) or email (fallback).

    Returns a dict with:
    - found: bool - whether the client was found in the system
    - contacted: bool - whether the client has previous consultations
    - client_id: int or None - the client ID
    - consultation_count: int - number of consultations
    - last_consultation_date: str or None - date of last consultation
    - client_name: str or None - client full name
    - search_by: str - 'phone' or 'email' indicating how we found them
    """
    if not phone and not email:
        return {
            "found": False,
            "contacted": False,
            "client_id": None,
            "consultation_count": 0,
            "last_consultation_date": None,
            "client_name": None,
            "search_by": None,
            "error": "No phone or email provided",
        }

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        client = None
        search_by = None

        # Search by phone first (primary method)
        if phone:
            phone_clean = phone.strip()
            cursor.execute(
                "SELECT idCliente, nombre, apellido FROM cliente WHERE (telefono = %s OR telefono LIKE %s) AND deleted IS NULL",
                (phone_clean, f"%{phone_clean}%")
            )
            client = cursor.fetchone()
            if client:
                search_by = "phone"

        # Fallback to email search
        if not client and email:
            email_clean = email.strip().lower()
            cursor.execute(
                "SELECT idCliente, nombre, apellido FROM cliente WHERE (eMail = %s OR eMail2 = %s OR LOWER(eMail) = %s OR LOWER(eMail2) = %s) AND deleted IS NULL",
                (email_clean, email_clean, email_clean, email_clean)
            )
            client = cursor.fetchone()
            if client:
                search_by = "email"

        if not client:
            cursor.close()
            conn.close()
            return {
                "found": False,
                "contacted": False,
                "client_id": None,
                "consultation_count": 0,
                "last_consultation_date": None,
                "client_name": None,
                "search_by": None,
            }

        client_id = client["idCliente"]
        client_name = f"{client['nombre']} {client['apellido']}".strip()

        # Check for previous consultations
        cursor.execute(
            "SELECT COUNT(*) as count, MAX(fecha) as last_date FROM consulta WHERE idCliente = %s AND deleted IS NULL",
            (client_id,)
        )
        consultation_data = cursor.fetchone()
        consultation_count = consultation_data["count"] if consultation_data else 0
        last_consultation_date = consultation_data["last_date"] if consultation_data else None

        cursor.close()
        conn.close()

        return {
            "found": True,
            "contacted": consultation_count > 0,
            "client_id": client_id,
            "consultation_count": consultation_count,
            "last_consultation_date": str(last_consultation_date) if last_consultation_date else None,
            "client_name": client_name,
            "search_by": search_by,
        }

    except Exception as e:
        return {
            "found": False,
            "contacted": False,
            "client_id": None,
            "consultation_count": 0,
            "last_consultation_date": None,
            "client_name": None,
            "search_by": None,
            "error": str(e),
        }
