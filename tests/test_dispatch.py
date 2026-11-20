import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from food_rescue.ledger import load_day
from food_rescue.model import Board, Driver, Pickup
from food_rescue.routing import Booking, exclusion, route_for_driver
from food_rescue.service import (
    ROOT,
    Snapshot,
    confirm_assignment,
    evaluate,
    from_reference,
)


def driver(**changes):
    row = {
        "shifts": [[400, 700]],
        "capacity": 3,
        "load": 0,
        "position": "home",
        "last_seen": 498,
        "return_to": "home",
        "cold_carrier": True,
        "stops": [],
    }
    return Driver(**{**row, **changes})


def pickup(**changes):
    row = {
        "as_of": 500,
        "cancelled_driver": "original",
        "units": 3,
        "perishable": True,
        "pickup": "donor",
        "dropoff": "pantry",
        "pickup_window": [450, 600],
        "dropoff_window": [450, 610],
        "max_onboard": 30,
    }
    return Pickup(**{**row, **changes})


def travel(origin, destination):
    return 0 if origin == destination else 10


class RoutingTests(unittest.TestCase):
    def test_delivery_and_exact_shift_boundary(self):
        plan, reasons = route_for_driver(
            driver(shifts=[[400, 540]]), pickup(dropoff_window=[450, 530]), 5, travel, []
        )
        self.assertEqual(reasons, [])
        self.assertEqual(
            (plan["pickup_at"], plan["delivered_at"], plan["shift_return_at"]), (510, 530, 540)
        )
        self.assertIsNone(route_for_driver(driver(shifts=[[400, 539]]), pickup(), 5, travel, [])[0])

    def test_wait_at_donor_for_cold_delivery(self):
        plan, _ = route_for_driver(
            driver(), pickup(dropoff_window=[570, 610], max_onboard=15), 5, travel, []
        )
        self.assertEqual((plan["pickup_done"], plan["delivered_at"]), (560, 575))
        self.assertIsNone(route_for_driver(driver(), pickup(max_onboard=14), 5, travel, [])[0])

    def test_insert_after_and_during_existing_booking(self):
        fixed = [Booking("home", 510, "pantry", 530)]
        plan, _ = route_for_driver(driver(), pickup(), 5, travel, fixed)
        self.assertEqual((plan["bookings_before_pickup"], plan["pickup_at"]), (1, 540))
        ongoing = [Booking("home", 490, "donor", 515)]
        plan, _ = route_for_driver(driver(), pickup(), 5, travel, ongoing)
        self.assertEqual(plan["pickup_at"], 515)

    def test_preserve_next_appointment(self):
        fixed = [Booking("pantry", 530, "home", 625)]
        plan, _ = route_for_driver(driver(), pickup(), 5, travel, fixed)
        self.assertEqual((plan["bookings_before_pickup"], plan["delivered_at"]), (0, 530))

    def test_screen_exclusions_and_exact_bounds(self):
        self.assertIsNone(exclusion("spare", driver(last_seen=485), pickup(), 15))
        self.assertEqual(exclusion("original", driver(), pickup(), 15), "cancelled_original")
        for change, reason in [
            ({"load": 1}, "capacity"),
            ({"last_seen": 484}, "unverified_position"),
            ({"last_seen": 501}, "unverified_position"),
            ({"shifts": [[450, 500]]}, "off_shift"),
            ({"cold_carrier": False}, "cold_carrier_unavailable"),
            ({"cold_carrier": None}, "unverified_cold_carrier"),
        ]:
            with self.subTest(change=change):
                self.assertEqual(exclusion("spare", driver(**change), pickup(), 15), reason)


class DispatchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.ledger = self.folder / "assignments.sqlite3"
        for name in ("dispatch.json", "roads.json"):
            (self.folder / name).write_bytes((ROOT / "examples" / name).read_bytes())
        env = patch.dict(
            os.environ, {"DISPATCH_DATA": str(self.folder), "DISPATCH_LEDGER": str(self.ledger)}
        )
        env.start()
        self.addCleanup(env.stop)

    def edit(self, name, mutate):
        path = self.folder / name
        value = json.loads(path.read_bytes())
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def report(self, case):
        s = Snapshot(case)
        return s.rank(s.screen()["driver_ids"])

    def test_demo_cases_and_read_only(self):
        p = self.report("R24")
        self.assertEqual((p["screened"], p["eligible"], len(p["candidates"])), (50, 8, 6))
        self.assertEqual(
            (p["candidates"][0]["driver"], p["candidates"][0]["deadline_slack_min"]), ("V20", 33)
        )
        self.assertEqual(self.report("R25")["earliest_possible_delivery"], 962)
        self.assertEqual(self.report("R26")["status"], "NEEDS_INFO")
        self.assertFalse(self.ledger.exists())

    def test_unknown_refs_and_tampered_pool(self):
        for key in ("../../data", "R999"):
            with self.assertRaises(ValueError):
                Snapshot(key)
        s = Snapshot("R24")
        with self.assertRaisesRegex(ValueError, "Candidate list"):
            evaluate(s.ref, s.screen()["driver_ids"][:-1])
        self.edit("dispatch.json", lambda board: board.update(fresh_for=14))
        with self.assertRaisesRegex(ValueError, "changed"):
            from_reference(s.ref)

    def test_new_case_and_rerank_after_road_change(self):
        self.edit("dispatch.json", lambda b: b["cases"].update(R89=b["cases"]["R24"]))

        def change(roads):
            pts = roads["places"]
            roads["minutes"][pts.index("V20-start")][pts.index("P24")] = 60

        self.edit("roads.json", change)
        self.assertEqual(self.report("R89")["candidates"][0]["driver"], "V29")

    def test_unknown_common_road(self):
        def missing(roads):
            pts = roads["places"]
            roads["minutes"][pts.index("P24")][pts.index("D24")] = None

        self.edit("roads.json", missing)
        self.assertEqual(self.report("R24")["status"], "NEEDS_INFO")

    def test_no_verified_positions(self):
        def stale(board):
            for row in board["drivers"].values():
                row["last_seen"] = None

        self.edit("dispatch.json", stale)
        self.assertEqual(self.report("R24")["status"], "NEEDS_INFO")

    def test_deliberate_confirmation_and_cross_case_invalidation(self):
        self.edit("dispatch.json", lambda b: b["cases"].update(R89=b["cases"]["R24"]))
        ref = Snapshot("R24").ref
        other = Snapshot("R89").ref
        with self.assertRaisesRegex(ValueError, "confirmation"):
            confirm_assignment(ref, "V20", "yes")
        self.assertFalse(self.ledger.exists())
        self.assertEqual(confirm_assignment(ref, "V20", "ASSIGN R24 V20")["status"], "ASSIGNED")
        self.assertEqual(self.report("R24")["status"], "ALREADY_ASSIGNED")
        with self.assertRaisesRegex(ValueError, "changed"):
            confirm_assignment(other, "V20", "ASSIGN R89 V20")
        next_report = self.report("R89")
        self.assertNotIn("V20", [p["driver"] for p in next_report["candidates"]])
        self.assertEqual(len(load_day("2026-11-20")), 1)

    def test_two_dispatchers_cannot_double_book(self):
        ref = Snapshot("R24").ref

        def book():
            try:
                return confirm_assignment(ref, "V20", "ASSIGN R24 V20")["status"]
            except ValueError:
                return "REJECTED"

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(
                list(pool.map(lambda _: book(), range(2))), ["ASSIGNED", "REJECTED"]
            )
        self.assertEqual(len(load_day("2026-11-20")), 1)

    def test_unproposed_driver_rejected(self):
        with self.assertRaisesRegex(ValueError, "no current proposal"):
            confirm_assignment(Snapshot("R24").ref, "V10", "ASSIGN R24 V10")
        self.assertEqual(load_day("2026-11-20"), [])
        self.assertFalse(self.ledger.exists())

    def test_invalid_data(self):
        with self.assertRaises(ValueError):
            driver(load=4)
        with self.assertRaises(ValueError):
            driver(shifts=[[450, 510], [500, 700]])
        with self.assertRaises(ValueError):
            pickup(pickup_window=[510, 500])
        b = json.loads((self.folder / "dispatch.json").read_bytes())
        b["cases"]["R24"]["cancelled_driver"] = "unknown"
        with self.assertRaises(ValueError):
            Board.model_validate(b)
