"""Snapshot-bound workflow shared by both MCP surfaces and the human booking command."""

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from . import ledger
from .model import Board, Roads
from .routing import Booking, Infeasible, exclusion, make_matrix, route_for_driver

ROOT = Path(__file__).resolve().parents[1]
CASE_ID = re.compile(r"[A-Z][A-Z0-9-]{0,30}")


class Snapshot:
    def __init__(self, case_id, connection=None):
        if not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id):
            raise ValueError("Invalid case ID.")
        folder = Path(os.getenv("DISPATCH_DATA", ROOT / "examples"))
        board_bytes = (folder / "dispatch.json").read_text(encoding="utf-8").encode()
        road_bytes = (folder / "roads.json").read_text(encoding="utf-8").encode()
        self.board = Board.model_validate_json(board_bytes)
        self.roads = Roads.model_validate_json(road_bytes)
        self.case_id = case_id
        if case_id not in self.board.cases:
            raise ValueError(f"Unknown cancellation {case_id}.")
        self.case = self.board.cases[case_id]
        self.bookings = ledger.load_day(self.board.service_date, connection)
        revision = hashlib.sha256(
            board_bytes
            + b"\0"
            + road_bytes
            + b"\0"
            + json.dumps(self.bookings, sort_keys=True).encode()
        )
        self.ref = case_id + "-" + revision.hexdigest()[:12]

    def screen(self):
        eligible, excluded = [], Counter()
        for name, driver in self.board.drivers.items():
            reason = exclusion(name, driver, self.case, self.board.fresh_for)
            if reason:
                excluded[reason] += 1
            else:
                eligible.append(name)
        return {"driver_ids": sorted(eligible), "excluded": dict(sorted(excluded.items()))}

    def rank(self, driver_ids):
        pool = self.screen()
        if sorted(driver_ids) != pool["driver_ids"]:
            raise ValueError("Candidate list differs from this snapshot. Repeat screening.")
        case = self.case
        report = {
            "case_id": self.case_id,
            "case_ref": self.ref,
            "as_of": case.as_of,
            "service_date": self.board.service_date,
            "timezone": self.board.timezone,
            "dropoff_deadline": case.dropoff_window[1],
            "units": case.units,
            "screened": len(self.board.drivers),
            "eligible": len(driver_ids),
            "excluded": pool["excluded"],
            "route_failures": {},
            "candidates": [],
            "road_source": self.roads.source,
            "status": "",
            "reason": "",
        }
        assigned = next((b for b in self.bookings if b["case_id"] == self.case_id), None)
        if assigned:
            return {
                **report,
                "status": "ALREADY_ASSIGNED",
                "reason": "Recorded by dispatcher: " + assigned["driver"],
            }
        if case.perishable and case.max_onboard is None:
            return {
                **report,
                "status": "NEEDS_INFO",
                "reason": "Missing transport time limit for perishable goods.",
            }
        matrix = make_matrix(self.roads)
        handling = self.board.handling_minutes
        loaded = max(case.as_of, case.pickup_window[0]) + handling
        if loaded > case.pickup_window[1]:
            return {
                **report,
                "status": "NO_FEASIBLE_DRIVER",
                "reason": "Pickup would finish after closing even with a driver at the donor.",
            }
        try:
            onward = matrix(case.pickup, case.dropoff)
        except Infeasible:
            return {
                **report,
                "status": "NEEDS_INFO",
                "reason": "No road estimate from donor to recipient.",
            }
        earliest = max(loaded + onward, case.dropoff_window[0]) + handling
        if earliest > case.dropoff_window[1]:
            return {
                **report,
                "status": "NO_FEASIBLE_DRIVER",
                "earliest_possible_delivery": earliest,
                "reason": "Even a driver already at the donor would finish delivery after closing.",
            }
        if case.perishable and onward + handling > case.max_onboard:
            return {
                **report,
                "status": "NO_FEASIBLE_DRIVER",
                "reason": "The direct trip alone exceeds the configured transport limit.",
            }
        failures = Counter()
        for name in driver_ids:
            fixed = [
                Booking(b["pickup"], b["pickup_at"], b["dropoff"], b["delivered_at"])
                for b in self.bookings
                if b["driver"] == name
            ]
            plan, reasons = route_for_driver(
                self.board.drivers[name], case, self.board.handling_minutes, matrix, fixed
            )
            if plan is None:
                failures.update(reasons)
                continue
            report["candidates"].append({"driver": name, **plan})
        report["route_failures"] = dict(sorted(failures.items()))
        report["candidates"].sort(
            key=lambda r: (r["delivered_at"], r["road_minutes_full_tour"], r["driver"])
        )
        if report["candidates"]:
            report.update(
                status="PROPOSED", reason="Dispatcher and volunteer confirmation required."
            )
        elif failures["road_unknown"] or any(
            pool["excluded"].get(key) for key in ("unverified_position", "unverified_cold_carrier")
        ):
            report.update(
                status="NEEDS_INFO",
                reason="No verified route. Refresh missing road, position or equipment data.",
            )
        else:
            report.update(
                status="NO_FEASIBLE_DRIVER",
                reason="No eligible driver can complete this pickup within the constraints.",
            )
        return report


def open_case(case_id):
    s = Snapshot(case_id)
    return {
        "case_ref": s.ref,
        "case_id": case_id,
        "as_of": s.case.as_of,
        "units": s.case.units,
        "pickup": s.case.pickup,
        "dropoff": s.case.dropoff,
        "deadline": s.case.dropoff_window[1],
    }


def from_reference(ref, connection=None):
    case_id, sep, _ = ref.rpartition("-")
    if not sep:
        raise ValueError("Use the case_ref returned by get_cancelled_pickup.")
    s = Snapshot(case_id, connection)
    if s.ref != ref:
        raise ValueError("Dispatch board changed or reference is invalid. Request a fresh plan.")
    return s


def screen(ref):
    return from_reference(ref).screen()


def evaluate(ref, driver_ids):
    return from_reference(ref).rank(driver_ids)


def confirm_assignment(case_ref, driver, confirmation):
    """Persist an accepted assignment under a write lock; MCP never exposes this function."""
    case_id = case_ref.rpartition("-")[0]
    if confirmation != f"ASSIGN {case_id} {driver}":
        raise ValueError("Exact dispatcher confirmation is required after the volunteer accepts.")
    initial = from_reference(case_ref)

    def chosen(snapshot):
        report = snapshot.rank(snapshot.screen()["driver_ids"])
        picked = next((p for p in report["candidates"] if p["driver"] == driver), None)
        if picked is None:
            raise ValueError("This driver has no current proposal.")
        return picked

    chosen(initial)
    path = ledger.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(ledger.TABLE)
        s = from_reference(case_ref, conn)
        picked = chosen(s)
        conn.execute(
            "INSERT INTO assignments VALUES (?,?,?,?,?,?,?)",
            (
                s.board.service_date,
                case_id,
                driver,
                s.case.pickup,
                picked["pickup_at"],
                s.case.dropoff,
                picked["delivered_at"],
            ),
        )
    return {"case_id": initial.case_id, "driver": driver, "status": "ASSIGNED"}
