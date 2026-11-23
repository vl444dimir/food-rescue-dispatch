import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import answer_from_report
from food_rescue.service import ROOT, Snapshot, record_unavailable


class EvidenceTests(unittest.TestCase):
    def test_build_and_dataset_hashes(self):
        record = json.loads((ROOT / "evidence/synapse-build.json").read_bytes())
        for path, wanted in record["sha256"].items():
            with self.subTest(path=path):
                canonical = (ROOT / path).read_text(encoding="utf-8").encode()
                self.assertEqual(hashlib.sha256(canonical).hexdigest(), wanted)

    def test_two_rounds_match_current_planner(self):
        traces = json.loads((ROOT / "evidence/comparison.json").read_bytes())
        self.assertEqual(len(traces), 24)
        keys = {(r["round"], r["scenario"], r["mode"]) for r in traces}
        self.assertEqual(
            keys,
            {
                (i, c, m)
                for i in (1, 2)
                for c in (
                    "baseline",
                    "tight_window",
                    "missing_policy",
                    "unknown",
                    "declined",
                    "late",
                )
                for m in ("composed", "individual")
            },
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "DISPATCH_DATA": str(ROOT / "examples"),
                },
            ),
        ):
            for seq, r in enumerate(traces):
                with self.subTest(scenario=r["scenario"], mode=r["mode"], round=r["round"]):
                    os.environ["DISPATCH_LEDGER"] = str(Path(tmp) / f"{seq}.sqlite3")
                    os.environ["DISPATCH_AT"] = "16:50" if r["scenario"] == "late" else ""
                    if r["scenario"] == "declined":
                        record_unavailable(Snapshot("R24").ref, "V20", "UNAVAILABLE R24 V20")
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
                    self.assertGreater(r["elapsed_seconds"], 0)
                    self.assertEqual(r["answer"], answer_from_report(r["report"]))
                    if r["case"] == "R999":
                        self.assertIn("Unknown cancellation R999", r["report"]["error"])
                    else:
                        s = Snapshot(r["case"])
                        self.assertEqual(r["report"], s.rank(s.screen()["driver_ids"]))
