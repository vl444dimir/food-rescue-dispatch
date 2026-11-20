"""Compare real agent runs across MCP surfaces on the same isolated dispatch snapshot."""

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
from mcp.shared.exceptions import McpError

from agent import review


def expected(case_id, report):
    if case_id == "R24":
        candidates = report.get("candidates") or [{}]
        return (
            report.get("status"),
            candidates[0].get("driver"),
            candidates[0].get("delivered_at"),
        ) == ("PROPOSED", "V20", 987)
    if case_id == "R25":
        return (
            report.get("status") == "NO_FEASIBLE_DRIVER"
            and report.get("earliest_possible_delivery") == 962
        )
    if case_id == "R26":
        return report.get("status") == "NEEDS_INFO" and not report["candidates"]
    return "Unknown cancellation R999." in report.get("error", "")


async def compare(url, model, rounds, output):
    runs = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory() as folder,
        patch.dict(
            os.environ,
            {
                "DISPATCH_LEDGER": str(Path(folder) / "assignments.sqlite3"),
                "DISPATCH_DATA": str(Path(__file__).resolve().parent / "examples"),
            },
        ),
    ):
        for index in range(rounds):
            for offset, case in enumerate(("R24", "R25", "R26", "R999")):
                modes = ["composed", "individual"]
                if (offset + index) % 2:
                    modes.reverse()
                pair = []
                question = f"Who can cover pickup {case}?"
                for mode in modes:
                    try:
                        run = await review(
                            question, mode, url, model, os.getenv("DISPATCH_MODEL_API_KEY")
                        )
                    except (
                        httpx.HTTPError,
                        McpError,
                        OSError,
                        RuntimeError,
                        ValueError,
                        ExceptionGroup,
                    ) as exc:
                        run = {
                            "mode": mode,
                            "model": model,
                            "question": question,
                            "calls": [],
                            "report": {"error": str(exc)},
                        }
                    run.update(
                        round=index + 1,
                        case=case,
                        passed_expected_result=expected(case, run["report"]),
                    )
                    count = sum(c["dispatched"] for c in run["calls"])
                    print(
                        f"Round {index + 1} {case} {mode}: {count} MCP calls, pass={run['passed_expected_result']}",
                        flush=True,
                    )
                    pair.append(run)
                    runs.append(run)
                    output.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
                same = (
                    pair[0]["report"] == pair[1]["report"]
                    if case != "R999"
                    else all(r["passed_expected_result"] for r in pair)
                )
                for run in pair:
                    run["same_outcome"] = same
                output.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
    return all(r["passed_expected_result"] and r["same_outcome"] for r in runs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".work/comparison.json"))
    parser.add_argument(
        "--base-url", default=os.getenv("DISPATCH_MODEL_URL", "http://127.0.0.1:8080/v1")
    )
    parser.add_argument("--model", default=os.getenv("DISPATCH_MODEL", "local-model"))
    parser.add_argument("--rounds", type=int, choices=range(1, 11), default=2)
    args = parser.parse_args()
    raise SystemExit(
        0 if asyncio.run(compare(args.base_url, args.model, args.rounds, args.output)) else 1
    )
