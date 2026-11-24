"""Only the human confirmation command opens a writable local booking ledger."""

import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = """CREATE TABLE IF NOT EXISTS assignments (
    service_date TEXT NOT NULL, case_id TEXT NOT NULL, driver TEXT NOT NULL,
    pickup TEXT NOT NULL, pickup_at INTEGER NOT NULL, dropoff TEXT NOT NULL, delivered_at INTEGER NOT NULL,
    PRIMARY KEY (service_date, case_id))"""
UNAVAILABLE_TABLE = """CREATE TABLE IF NOT EXISTS unavailable (
    service_date TEXT NOT NULL, case_id TEXT NOT NULL, driver TEXT NOT NULL,
    previous_pickup_at INTEGER, previous_delivered_at INTEGER,
    PRIMARY KEY (service_date, case_id, driver))"""


def ledger_path():
    return Path(os.getenv("DISPATCH_LEDGER", ROOT / ".work" / "assignments.sqlite3")).resolve()


def load_state(day, connection=None):
    def read(conn):
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        bookings = (
            [
                dict(
                    zip(
                        ("case_id", "driver", "pickup", "pickup_at", "dropoff", "delivered_at"), row
                    )
                )
                for row in conn.execute(
                    "SELECT case_id,driver,pickup,pickup_at,dropoff,delivered_at "
                    "FROM assignments WHERE service_date=? ORDER BY case_id",
                    (day,),
                )
            ]
            if "assignments" in tables
            else []
        )
        unavailable = (
            list(
                conn.execute(
                    "SELECT case_id,driver FROM unavailable WHERE service_date=? ORDER BY case_id,driver",
                    (day,),
                )
            )
            if "unavailable" in tables
            else []
        )
        latest = (
            conn.execute(
                "SELECT minute FROM dispatch_clock WHERE service_date=?", (day,)
            ).fetchone()
            if "dispatch_clock" in tables
            else None
        )
        return bookings, unavailable, latest[0] if latest else 0

    if connection is not None:
        return read(connection)
    path = ledger_path()
    if not path.exists():
        return [], [], 0
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("BEGIN")
        return read(conn)


def load_day(day, connection=None):
    return load_state(day, connection)[0]


@contextmanager
def write_transaction():
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(TABLE)
        conn.execute(UNAVAILABLE_TABLE)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS dispatch_clock (service_date TEXT PRIMARY KEY, minute INTEGER NOT NULL)"
        )
        yield conn


def advance_clock(conn, day, minute):
    conn.execute(
        "INSERT INTO dispatch_clock VALUES (?,?) ON CONFLICT(service_date) "
        "DO UPDATE SET minute=max(minute,excluded.minute)",
        (day, minute),
    )
