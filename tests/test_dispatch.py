import json
import os
import random
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from food_rescue.ledger import TABLE, load_day
from food_rescue.model import Board, Driver, Pickup
from food_rescue.routing import Booking, exclusion, route_for_driver
from food_rescue.service import (
    ROOT,
    Snapshot,
    confirm_assignment,
    evaluate,
    from_reference,
    record_unavailable,
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
    def test_earliest_route_against_minute_by_minute_enumeration(self):
        rng = random.Random(24)
        locations = ("home", "donor", "pantry", "stop")
        for scenario in range(400):
            roads = {
                (a, b): rng.randint(1, 12) if a != b else 0 for a in locations for b in locations
            }
            stop_at = rng.randint(507, 537)
            stop_end = stop_at + rng.randint(2, 8)
            deadline = rng.randint(540, 565)
            donor_close = rng.randint(515, 549)
            opens = rng.randint(512, 539)
            limit = rng.randint(5, 25)
            handle = rng.randint(1, 5)
            case = pickup(
                pickup_window=[500, donor_close],
                dropoff_window=[opens, deadline],
                max_onboard=limit,
            )
            d = driver(shifts=[[490, 565]])
            # Independently enumerate every loading minute, both sides of the fixed stop.
            feasible = []
            for start in range(500, donor_close - handle + 1):
                loaded = start + handle
                delivered = max(loaded + roads["donor", "pantry"], opens) + handle
                if delivered > deadline or delivered - loaded > limit:
                    continue
                before = (
                    500 + roads["home", "donor"] <= start
                    and delivered + roads["pantry", "stop"] <= stop_at
                    and stop_end + roads["stop", "home"] <= 565
                )
                after = (
                    500 + roads["home", "stop"] <= stop_at
                    and stop_end + roads["stop", "donor"] <= start
                    and delivered + roads["pantry", "home"] <= 565
                )
                if before or after:
                    feasible.append(delivered)
            plan, _ = route_for_driver(
                d,
                case,
                handle,
                lambda a, b, table=roads: table[a, b],
                [Booking("stop", stop_at, "stop", stop_end)],
            )
            with self.subTest(scenario=scenario):
                self.assertEqual(
                    plan["delivered_at"] if plan else None, min(feasible, default=None)
                )
                if plan:
                    loaded = plan["pickup_done"]
                    # Replay the selected route minute by minute, delaying only the loaded leg.
                    for extra in range(1, deadline - loaded + 2):
                        done = max(loaded + roads["donor", "pantry"] + extra, opens) + handle
                        missed = set()
                        if done > deadline:
                            missed.add("delivery_deadline")
                        if done - loaded > limit:
                            missed.add("cold_time_limit")
                        if plan["bookings_before_pickup"] == 0:
                            if done + roads["pantry", "stop"] > stop_at:
                                missed.add("existing_booking")
                        elif done + roads["pantry", "home"] > 565:
                            missed.add("shift_return")
                        if missed:
                            break
                    margin = plan["delivery_leg_delay"]
                    self.assertEqual(margin["max_extra_minutes"], extra - 1)
                    self.assertCountEqual(margin["limiting_constraints"], missed)

    def test_delay_can_replace_waiting_before_pantry_opens(self):
        case = pickup(perishable=False, max_onboard=None, dropoff_window=[550, 560])
        plan, _ = route_for_driver(driver(), case, 5, travel, [])
        self.assertEqual(plan["deadline_slack_min"], 5)
        self.assertEqual(
            plan["delivery_leg_delay"],
            {"max_extra_minutes": 30, "limiting_constraints": ["delivery_deadline"]},
        )

    def test_delay_margin_reports_zero_and_simultaneous_limits(self):
        plan, _ = route_for_driver(
            driver(shifts=[[400, 540]]),
            pickup(dropoff_window=[450, 530], max_onboard=15),
            5,
            travel,
            [],
        )
        self.assertEqual(plan["delivery_leg_delay"]["max_extra_minutes"], 0)
        self.assertCountEqual(
            plan["delivery_leg_delay"]["limiting_constraints"],
            ["delivery_deadline", "cold_time_limit", "shift_return"],
        )

    def test_next_booking_limits_delay_even_with_open_pantry(self):
        fixed = [Booking("stop", 541, "stop", 550)]
        plan, _ = route_for_driver(driver(), pickup(), 5, travel, fixed)
        self.assertEqual(plan["deadline_slack_min"], 80)
        self.assertEqual(
            plan["delivery_leg_delay"],
            {"max_extra_minutes": 1, "limiting_constraints": ["existing_booking"]},
        )

    def test_prior_booking_invalidates_older_checkin(self):
        booking = [Booking("donor", 470, "pantry", 499)]
        case = pickup(pickup_window=[480, 506])
        plan, reason = route_for_driver(
            driver(position="donor", last_seen=490), case, 5, travel, booking
        )
        self.assertIsNone(plan)
        self.assertEqual(reason, ["unverified_position"])
        self.assertIsNotNone(
            route_for_driver(driver(position="donor", last_seen=500), case, 5, travel, booking)[0]
        )

    def test_fixed_booking_duration_must_cover_travel(self):
        fixed = [Booking("home", 503, "pantry", 505)]
        plan, why = route_for_driver(driver(), pickup(), 5, travel, fixed)
        self.assertIsNone(plan)
        self.assertIn("existing_booking", why)
        ongoing = [Booking("home", 499, "pantry", 501)]
        self.assertEqual(
            route_for_driver(driver(), pickup(), 5, travel, ongoing), (None, ["existing_booking"])
        )

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
            os.environ,
            {
                "DISPATCH_DATA": str(self.folder),
                "DISPATCH_LEDGER": str(self.ledger),
                "DISPATCH_AT": "",
            },
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
        self.assertEqual(
            p["candidates"][0]["delivery_leg_delay"],
            {"max_extra_minutes": 23, "limiting_constraints": ["cold_time_limit"]},
        )
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

    def test_known_deadline_beats_missing_cold_policy(self):
        self.edit("dispatch.json", lambda b: b["cases"]["R25"].update(max_onboard=None))
        self.assertEqual(self.report("R25")["status"], "NO_FEASIBLE_DRIVER")

    def test_time_change_invalidates_proposal_and_rechecks_deadline(self):
        ref = self.report("R24")["case_ref"]
        with patch.dict(os.environ, {"DISPATCH_AT": "16:50"}):
            with self.assertRaisesRegex(ValueError, "changed"):
                confirm_assignment(ref, "V20", "ASSIGN R24 V20")
            later = self.report("R24")
            self.assertEqual(later["status"], "NO_FEASIBLE_DRIVER")
            self.assertEqual(later["earliest_possible_delivery"], 1047)
        self.assertFalse(self.ledger.exists())
        for clock in ("15:29", "25:01", "16:78"):
            with patch.dict(os.environ, {"DISPATCH_AT": clock}), self.assertRaises(ValueError):
                Snapshot("R24")

    def test_no_cold_carriers_is_decisive_even_without_checkins_or_policy(self):
        def no_cold(board):
            for d in board["drivers"].values():
                d.update(cold_carrier=False, last_seen=None)

        self.edit("dispatch.json", no_cold)
        self.assertEqual(self.report("R26")["status"], "NO_FEASIBLE_DRIVER")

    def test_decline_promotes_backup_for_only_this_case(self):
        self.edit("dispatch.json", lambda b: b["cases"].update(R89=b["cases"]["R24"]))
        ref = self.report("R24")["case_ref"]
        with self.assertRaisesRegex(ValueError, "confirmation"):
            record_unavailable(ref, "V20", "yes")
        self.assertFalse(self.ledger.exists())
        record_unavailable(ref, "V20", "UNAVAILABLE R24 V20")
        next_report = self.report("R24")
        self.assertEqual(next_report["candidates"][0]["driver"], "V29")
        self.assertEqual(next_report["excluded"]["reported_unavailable"], 1)
        self.assertEqual(self.report("R89")["candidates"][0]["driver"], "V20")
        with self.assertRaisesRegex(ValueError, "changed"):
            confirm_assignment(ref, "V20", "ASSIGN R24 V20")
        confirm_assignment(next_report["case_ref"], "V29", "ASSIGN R24 V29")
        self.assertEqual(self.report("R24")["assignment"]["driver"], "V29")

    def test_release_only_own_booking_before_pickup_and_free_driver(self):
        self.edit("dispatch.json", lambda b: b["cases"].update(R89=b["cases"]["R24"]))
        confirm_assignment(Snapshot("R24").ref, "V20", "ASSIGN R24 V20")
        assigned = self.report("R24")
        with self.assertRaisesRegex(ValueError, "assigned driver"):
            record_unavailable(assigned["case_ref"], "V29", "UNAVAILABLE R24 V29")
        record_unavailable(assigned["case_ref"], "V20", "UNAVAILABLE R24 V20")
        self.assertEqual(self.report("R89")["candidates"][0]["driver"], "V20")
        next_report = self.report("R24")
        self.assertEqual(next_report["candidates"][0]["driver"], "V29")
        confirm_assignment(next_report["case_ref"], "V29", "ASSIGN R24 V29")
        self.edit("dispatch.json", lambda b: b["cases"]["R24"].update(as_of=958))
        with self.assertRaisesRegex(ValueError, "before pickup"):
            record_unavailable(Snapshot("R24").ref, "V29", "UNAVAILABLE R24 V29")
        self.assertEqual(len(load_day("2026-11-20")), 1)

    def test_racing_decline_and_accept_respect_snapshot(self):
        ref = Snapshot("R24").ref

        def commit(command):
            try:
                op = confirm_assignment if command == "ASSIGN" else record_unavailable
                return op(ref, "V20", f"{command} R24 V20")["status"]
            except ValueError:
                return "REJECTED"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(commit, ("ASSIGN", "UNAVAILABLE")))
        self.assertEqual(results.count("REJECTED"), 1)
        report = self.report("R24")
        if "ASSIGNED" in results:
            self.assertEqual(report["assignment"]["driver"], "V20")
        else:
            self.assertEqual(report["candidates"][0]["driver"], "V29")

    def test_cannot_rewind_after_a_later_confirmation(self):
        with patch.dict(os.environ, {"DISPATCH_AT": "15:32"}):
            confirm_assignment(Snapshot("R24").ref, "V20", "ASSIGN R24 V20")
        self.assertEqual(self.report("R24")["as_of"], 932)
        with (
            patch.dict(os.environ, {"DISPATCH_AT": "15:31"}),
            self.assertRaisesRegex(ValueError, "last recorded change"),
        ):
            Snapshot("R24")

    def test_no_verified_positions(self):
        def stale(board):
            for row in board["drivers"].values():
                row["last_seen"] = None

        self.edit("dispatch.json", stale)
        self.assertEqual(self.report("R24")["status"], "NEEDS_INFO")

    def test_existing_assignment_only_database_upgrades_on_confirmed_change(self):
        with closing(sqlite3.connect(self.ledger)) as conn, conn:
            conn.execute(TABLE)
            conn.execute(
                "INSERT INTO assignments VALUES (?,?,?,?,?,?,?)",
                ("2026-11-20", "R24", "V20", "P24", 950, "D24", 987),
            )
        assigned = self.report("R24")
        self.assertEqual(assigned["assignment"]["driver"], "V20")
        with closing(sqlite3.connect(self.ledger)) as conn:
            self.assertEqual(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                [("assignments",)],
            )
        record_unavailable(assigned["case_ref"], "V20", "UNAVAILABLE R24 V20")
        self.assertEqual(self.report("R24")["candidates"][0]["driver"], "V29")

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
