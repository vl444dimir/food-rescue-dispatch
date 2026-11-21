"""Show the same pickup in both live modes, then record and verify a booking."""

import argparse
import asyncio
import os
import tempfile
from pathlib import Path

from agent import ROOT, review
from demo import demonstrate

CASE_ID = "R24"
DRIVER_ID = "V20"
QUESTION = f"Who can cover pickup {CASE_ID}?"


async def show_request(mode, base_url, model):
    result = await review(QUESTION, mode, base_url, model, os.getenv("DISPATCH_MODEL_API_KEY"))
    calls = [call["tool"] for call in result["calls"] if call["dispatched"]]
    print(f"\n{mode} | {len(calls)} MCP call(s) | {' -> '.join(calls)}")
    print(result["answer"])
    return result["report"]


async def run(base_url, model):
    work_dir = ROOT / ".work"
    work_dir.mkdir(exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="defense-", dir=work_dir))
    os.environ["DISPATCH_DATA"] = str(ROOT / "examples")
    os.environ["DISPATCH_LEDGER"] = str(run_dir / "assignments.sqlite3")

    print(f"Dispatcher: {QUESTION}")
    composed = await show_request("composed", base_url, model)
    individual = await show_request("individual", base_url, model)
    if (
        composed != individual
        or composed.get("status") != "PROPOSED"
        or composed["candidates"][0]["driver"] != DRIVER_ID
    ):
        print(f"Expected both modes to propose {DRIVER_ID} first for {CASE_ID}.")
        return 1

    print(f"\nDispatcher confirmation (demo assumption: volunteer {DRIVER_ID} has agreed)")
    if await demonstrate([CASE_ID], DRIVER_ID):
        return 1

    print(f"\nDispatcher asks again: {QUESTION}")
    report = await show_request("composed", base_url, model)
    if report.get("status") == "PROPOSED":
        print("No assignment was recorded in this run.")
    elif report.get("status") != "ALREADY_ASSIGNED":
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.base_url, args.model)))
