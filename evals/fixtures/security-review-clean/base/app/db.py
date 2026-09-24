import sqlite3
from contextlib import closing

DB_PATH = "app.db"


def query_one(sql, params=()):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchone()
