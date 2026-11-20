import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import connect, guard, tool_value


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_tools_and_actual_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "ledger.sqlite3"
            with patch.dict(os.environ, {"DISPATCH_LEDGER": str(ledger)}):
                async with connect("composed") as one, connect("individual") as several:
                    self.assertEqual(
                        [t.name for t in (await one.list_tools()).tools], ["plan_rescue"]
                    )
                    self.assertEqual(
                        {t.name for t in (await several.list_tools()).tools},
                        {"get_cancelled_pickup", "screen_volunteers", "evaluate_routes"},
                    )
                    for case in ("R24", "R25", "R26"):
                        opened = tool_value(
                            await several.call_tool("get_cancelled_pickup", {"case_id": case})
                        )
                        ref = opened["case_ref"]
                        pool = tool_value(
                            await several.call_tool("screen_volunteers", {"case_ref": ref})
                        )
                        report = tool_value(
                            await several.call_tool(
                                "evaluate_routes",
                                {"case_ref": ref, "driver_ids": pool["driver_ids"]},
                            )
                        )
                        composed = tool_value(await one.call_tool("plan_rescue", {"case_id": case}))
                        self.assertEqual(report["case_id"], case)
                        self.assertEqual(report, composed)
                    bad = await one.call_tool("plan_rescue", {"case_id": "R999"})
                    self.assertIn("Unknown cancellation R999", tool_value(bad)["error"])
                self.assertFalse(ledger.exists())

    def test_agent_rejects_invented_identifiers(self):
        self.assertTrue(guard("plan_rescue", {"case_id": "R42"}, "R24", None, None))
        self.assertTrue(
            guard(
                "evaluate_routes", {"case_ref": "real", "driver_ids": ["V1"]}, "R24", "real", ["V2"]
            )
        )
        self.assertTrue(guard("screen_volunteers", {"case_ref": "invented"}, "R24", None, None))
