import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from agent import ROOT, connect, guard, review, tool_value


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_recovers_when_dispatch_board_changes_between_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            board = Path(folder) / "dispatch.json"
            shutil.copy(ROOT / "examples/dispatch.json", board)
            shutil.copy(ROOT / "examples/roads.json", folder)
            calls = [
                "get_cancelled_pickup",
                "screen_volunteers",
                "get_cancelled_pickup",
                "screen_volunteers",
                "evaluate_routes",
            ]
            refs = []

            async def model_reply(url, **request):
                # Program the model's choices only. Every tool call still reaches the real server.
                previous = [
                    json.loads(m["content"])
                    for m in request["json"]["messages"]
                    if m["role"] == "tool"
                ]
                step = len(previous)
                name = calls[step]
                args = {"case_id": "R24"}
                if step in (1, 3):
                    refs.append(previous[-1]["case_ref"])
                    args = {"case_ref": refs[-1]}
                if step == 1:
                    b = json.loads(board.read_bytes())
                    b["drivers"]["V20"]["last_seen"] = None
                    board.write_text(json.dumps(b), encoding="utf-8")
                if step == 4:
                    args = {"case_ref": refs[-1], "driver_ids": previous[-1]["driver_ids"][::-1]}
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": str(step),
                                            "type": "function",
                                            "function": {
                                                "name": name,
                                                "arguments": json.dumps(args),
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                )

            with (
                patch.dict(
                    os.environ,
                    {
                        "DISPATCH_DATA": folder,
                        "DISPATCH_LEDGER": str(Path(folder) / "ledger"),
                        "DISPATCH_AT": "",
                    },
                ),
                patch("agent.httpx.AsyncClient.post", side_effect=model_reply),
            ):
                out = await review(
                    "Who can cover r24?", "individual", "http://model.invalid", "test"
                )
            self.assertNotEqual(refs[0], refs[1])
            self.assertIn("changed", out["calls"][1]["result"]["error"])
            self.assertTrue(all(c["dispatched"] for c in out["calls"]))
            self.assertEqual(out["report"]["candidates"][0]["driver"], "V29")

    async def test_provider_failure_produces_no_proposal(self):
        reply = httpx.Response(503, request=httpx.Request("POST", "http://model.invalid"))
        with patch("agent.httpx.AsyncClient.post", return_value=reply):
            result = await review("Cover R24", "composed", "http://model.invalid", "test")
        self.assertIn("HTTP 503", result["report"]["error"])
        self.assertEqual(result["calls"], [])

    async def test_public_tools_and_actual_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "ledger.sqlite3"
            with patch.dict(
                os.environ,
                {
                    "DISPATCH_LEDGER": str(ledger),
                    "DISPATCH_AT": "",
                    "DISPATCH_DATA": str(ROOT / "examples"),
                },
            ):
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
