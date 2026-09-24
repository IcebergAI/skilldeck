"""Support tickets, as filed by customers through the public help form."""

import sqlite3
from contextlib import closing

DB_PATH = "support.db"


def get_ticket(ticket_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, subject, body, customer_email FROM tickets WHERE id = ?",
            (ticket_id,),
        ).fetchone()
    return dict(row) if row else None
