import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

from defense import compare_and_confirm
from demo import confirm_change
from food_rescue.service import ROOT, Snapshot


class DefenseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.ledger = Path(folder.name) / "ledger.sqlite3"
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "DISPATCH_DATA": str(ROOT / "examples"),
                    "DISPATCH_LEDGER": str(self.ledger),
                    "DISPATCH_AT": "",
                },
            )
        )
        snapshot = Snapshot("R24")
        self.report = snapshot.rank(snapshot.screen()["driver_ids"])

    def test_backup_confirmation_shows_its_own_times_even_if_dispatcher_cancels(self):
        with patch("builtins.input", return_value=""), redirect_stdout(io.StringIO()) as output:
            self.assertIsNone(confirm_change(self.report, "V29"))
        self.assertIn("Selected V29 for R24: P24 at 15:58, D24 by 16:35.", output.getvalue())
        self.assertFalse(self.ledger.exists())

    def test_confirmation_shows_constraints_for_the_selected_backup(self):
        with patch("builtins.input", return_value=""), redirect_stdout(io.StringIO()) as output:
            confirm_change(self.report, "V22")
        self.assertIn(
            "Limited by pantry closing and the perishable-load time limit.", output.getvalue()
        )
        self.assertFalse(self.ledger.exists())

    async def test_claimed_booking_requires_exact_readback(self):
        wrong = {"status": "ALREADY_ASSIGNED", "assignment": {"driver": "V29"}}
        for last in (self.report, wrong):
            with (
                self.subTest(last=last["status"]),
                patch(
                    "defense.show_request",
                    new=AsyncMock(side_effect=[self.report, self.report, last]),
                ),
                patch(
                    "defense.confirm_change", return_value={"driver": "V20", "status": "ASSIGNED"}
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await compare_and_confirm("", "", "Who can cover R24?"), 1)

    async def test_consensus_on_impossible_trip_does_not_prompt(self):
        snapshot = Snapshot("R25")
        report = snapshot.rank(snapshot.screen()["driver_ids"])
        with (
            patch("defense.show_request", new=AsyncMock(return_value=report)) as ask,
            patch("defense.confirm_change") as confirm,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(await compare_and_confirm("", "", "Who can cover R25?"), 0)
        self.assertEqual(
            [c.args[:2] for c in ask.await_args_list],
            [("Who can cover R25?", "composed"), ("Who can cover R25?", "individual")],
        )
        confirm.assert_not_called()
