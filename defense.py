"""Show the same pickup in both live modes, then record and verify a booking."""

import argparse
import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent import ROOT, review
from demo import confirm_change

QUESTION = "Who can cover pickup R24?"


async def show_request(question, mode, base_url, model):
    result = await review(question, mode, base_url, model, os.getenv("DISPATCH_MODEL_API_KEY"))
    calls = [call["tool"] for call in result["calls"] if call["dispatched"]]
    print(f"\n{mode} | {len(calls)} MCP call(s) | {' -> '.join(calls)}")
    print(result["answer"])
    return result["report"]


async def run(base_url, model, question=QUESTION):
    work_dir = ROOT / ".work"
    work_dir.mkdir(exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="defense-", dir=work_dir))
    with patch.dict(
        os.environ,
        {
            "DISPATCH_DATA": str(ROOT / "examples"),
            "DISPATCH_LEDGER": str(run_dir / "assignments.sqlite3"),
        },
    ):
        return await compare_and_confirm(base_url, model, question)


async def compare_and_confirm(base_url, model, question):
    print(f"Dispatcher: {question}")
    composed = await show_request(question, "composed", base_url, model)
    individual = await show_request(question, "individual", base_url, model)
    if "error" in composed or "error" in individual:
        print("Dispatch stopped without a verified report.")
        return 1
    if composed != individual:
        print("The two modes disagree on the dispatch report.")
        return 1
    if composed["status"] != "PROPOSED":
        return 0
    best = composed["candidates"][0]
    print(f"\nDemo assumption: volunteer {best['driver']} has agreed.")
    try:
        receipt = confirm_change(composed, best["driver"])
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"\nDispatcher asks again: {question}")
    report = await show_request(question, "composed", base_url, model)
    if receipt is None:
        if report != composed:
            print("Board changed after the skipped confirmation.")
            return 1
        print("Verified: the proposal is unchanged.")
        return 0
    expected = {
        "case_id": composed["case_id"],
        "driver": best["driver"],
        "pickup": composed["pickup"],
        "dropoff": composed["dropoff"],
        "pickup_at": best["pickup_at"],
        "delivered_at": best["delivered_at"],
    }
    if report.get("status") != "ALREADY_ASSIGNED" or report.get("assignment") != expected:
        print("The read-back does not match the confirmed booking.")
        return 1
    print("Verified the recorded driver, pickup and delivery against the confirmed proposal.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--question", default=QUESTION)
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args.base_url, args.model, args.question)))
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
