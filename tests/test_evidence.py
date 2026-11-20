import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from food_rescue.service import ROOT, Snapshot


class EvidenceTests(unittest.TestCase):
    def test_build_and_dataset_hashes(self):
        record = json.loads((ROOT / "evidence/synapse-build.json").read_bytes())
        for path, wanted in record["sha256"].items():
            with self.subTest(path=path):
                canonical = (ROOT / path).read_text(encoding="utf-8").encode()
                self.assertEqual(hashlib.sha256(canonical).hexdigest(), wanted)

    def test_two_rounds_match_current_planner(self):
        traces = json.loads((ROOT / "evidence/comparison.json").read_bytes())
        self.assertEqual(len(traces), 16)
        keys = {(r["round"], r["case"], r["mode"]) for r in traces}
        self.assertEqual(
            keys,
            {
                (i, c, m)
                for i in (1, 2)
                for c in ("R24", "R25", "R26", "R999")
                for m in ("composed", "individual")
            },
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "DISPATCH_LEDGER": str(Path(tmp) / "test.sqlite3"),
                    "DISPATCH_DATA": str(ROOT / "examples"),
                },
            ),
        ):
            for r in traces:
                with self.subTest(case=r["case"], mode=r["mode"], round=r["round"]):
                    self.assertTrue(r["passed_expected_result"] and r["same_outcome"])
                    self.assertTrue(all(c["dispatched"] for c in r["calls"]))
                    tools = [c["tool"] for c in r["calls"]]
                    expected = (
                        ["plan_rescue"]
                        if r["mode"] == "composed"
                        else ["get_cancelled_pickup"]
                        if r["case"] == "R999"
                        else ["get_cancelled_pickup", "screen_volunteers", "evaluate_routes"]
                    )
                    self.assertEqual(tools, expected)
                    self.assertEqual(r["calls"][-1]["result"], r["report"])
                    if r["case"] == "R999":
                        self.assertIn("Unknown cancellation R999", r["report"]["error"])
                    else:
                        s = Snapshot(r["case"])
                        self.assertEqual(r["report"], s.rank(s.screen()["driver_ids"]))
