"""Member accounts for the running club's site.

users: id, display_name, bio, avatar_url, email, phone, home_address,
date_of_birth, national_id (collected for race-entry insurance), and
analytics_id (a random UUID, the only identifier the analytics vendor sees).
consents: user_id, purpose, granted_at, withdrawn_at.
"""

import sqlite3
from contextlib import closing

DB_PATH = "club.db"


def get_user(user_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def has_consent(user_id, purpose):
    """True if the member has granted, and not withdrawn, consent for purpose."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT 1 FROM consents"
            " WHERE user_id = ? AND purpose = ? AND withdrawn_at IS NULL",
            (user_id, purpose),
        ).fetchone()
    return row is not None


def add_race_entry(race_id, user_id):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute(
            "INSERT INTO race_entries (race_id, user_id) VALUES (?, ?)",
            (race_id, user_id),
        )
