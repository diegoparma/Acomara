"""CRM client status checker.

Verifies if a client was previously contacted by checking for consultation records.
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


def check_client_status(email: str) -> dict:
    """Check if a client was previously contacted.

    Returns a dict with:
    - found: bool - whether the client was found in the system
    - contacted: bool - whether the client has previous consultations
    - client_id: int or None - the client ID
    - consultation_count: int - number of consultations
    - last_consultation_date: str or None - date of last consultation
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Search for client by email
        cursor.execute(
            "SELECT idCliente, nombre, apellido FROM cliente WHERE eMail = %s OR eMail2 = %s AND deleted IS NULL",
            (email, email)
        )
        client = cursor.fetchone()

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
        }

    except Exception as e:
        return {
            "found": False,
            "contacted": False,
            "client_id": None,
            "consultation_count": 0,
            "last_consultation_date": None,
            "client_name": None,
            "error": str(e),
        }
