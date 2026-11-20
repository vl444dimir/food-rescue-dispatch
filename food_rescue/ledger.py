"""Only the human confirmation command opens a writable local booking ledger."""

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = """CREATE TABLE IF NOT EXISTS assignments (
    service_date TEXT NOT NULL, case_id TEXT NOT NULL, driver TEXT NOT NULL,
    pickup TEXT NOT NULL, pickup_at INTEGER NOT NULL, dropoff TEXT NOT NULL, delivered_at INTEGER NOT NULL,
    PRIMARY KEY (service_date, case_id))"""


def ledger_path():
    return Path(os.getenv("DISPATCH_LEDGER", ROOT / ".work" / "assignments.sqlite3")).resolve()


def load_day(day, connection=None):
    def read(conn):
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='assignments'"
        ).fetchone():
            return []
        return [
            dict(zip(("case_id", "driver", "pickup", "pickup_at", "dropoff", "delivered_at"), row))
            for row in conn.execute(
                "SELECT case_id,driver,pickup,pickup_at,dropoff,delivered_at "
                "FROM assignments WHERE service_date=? ORDER BY case_id",
                (day,),
            )
        ]

    if connection is not None:
        return read(connection)
    path = ledger_path()
    if not path.exists():
        return []
    from contextlib import closing

    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        return read(conn)
