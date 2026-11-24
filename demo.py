"""Run the composed dispatch tool directly, or record a volunteer's accepted pickup locally."""

import argparse
import asyncio
import json
import os
import sys

from agent import (
    ROOT,
    SERVERS,
    answer_from_report,
    clock,
    connect,
    delay_note,
    tool_value,
)
from food_rescue.service import confirm_assignment, record_unavailable


def confirm_change(report, driver, *, unavailable=False):
    """Show and commit exactly the selected route from the proposal the dispatcher saw."""
    case = report["case_id"]
    choice = next((p for p in report["candidates"] if p["driver"] == driver), None)
    if choice is None and unavailable:
        booked = report.get("assignment")
        if booked and booked["driver"] == driver and report["as_of"] < booked["pickup_at"]:
            choice = booked
    if choice is None:
        raise ValueError(
            "No eligible proposal or pre-pickup assignment for the selected volunteer."
        )
    action = "UNAVAILABLE" if unavailable else "ASSIGN"
    print(
        f"Selected {driver} for {case}: {report['pickup']} at {clock(choice['pickup_at'])}, "
        f"{report['dropoff']} by {clock(choice['delivered_at'])}."
    )
    if not unavailable:
        print(delay_note(choice))
    condition = "the volunteer declines or cancels" if unavailable else "the volunteer accepts"
    print(f"After {condition}, type {action} {case} {driver} to confirm.")
    try:
        confirmation = input().strip()
    except EOFError:
        confirmation = ""
    if confirmation != f"{action} {case} {driver}":
        print("No change recorded.")
        return None
    operation = record_unavailable if unavailable else confirm_assignment
    receipt = operation(report["case_ref"], driver, confirmation)
    print(json.dumps(receipt))
    return receipt


async def demonstrate(ids, driver=None, unavailable=False):
    async with connect("composed") as session:
        print("Available MCP tools:", ", ".join(t.name for t in (await session.list_tools()).tools))
        for case_id in ids:
            report = tool_value(await session.call_tool("plan_rescue", {"case_id": case_id}))
            print("\n" + answer_from_report(report))
            if "error" in report:
                return 1
            if driver:
                try:
                    receipt = confirm_change(report, driver, unavailable=unavailable)
                except ValueError as exc:
                    print(str(exc))
                    return 1
                if unavailable and receipt:
                    new_plan = tool_value(
                        await session.call_tool("plan_rescue", {"case_id": case_id})
                    )
                    print(answer_from_report(new_plan))
                    if "error" in new_plan:
                        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="*", default=["R24", "R25", "R26"])
    parser.add_argument(
        "--at", metavar="HH:MM", help="Evaluate at this local time on the board's service day"
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--assign",
        metavar="DRIVER",
        help="Record a single proposed assignment after human confirmation",
    )
    actions.add_argument(
        "--unavailable",
        metavar="DRIVER",
        help="Record a confirmed refusal or pre-pickup cancellation, then replan",
    )
    parser.add_argument("--client-config", action="store_true")
    args = parser.parse_args()
    if args.at is not None:
        os.environ["DISPATCH_AT"] = args.at
    if args.client_config:
        print(
            json.dumps(
                {
                    "mcpServers": {
                        "food-rescue": {
                            "command": sys.executable,
                            "args": [str(ROOT / SERVERS["composed"])],
                            "env": {"PYTHONPATH": str(ROOT)},
                        }
                    }
                },
                indent=2,
            )
        )
    else:
        if (args.assign or args.unavailable) and len(args.cases) != 1:
            parser.error("Pass one pickup ID when recording a dispatch change.")
        raise SystemExit(
            asyncio.run(
                demonstrate(args.cases, args.assign or args.unavailable, bool(args.unavailable))
            )
        )
