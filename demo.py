"""Run the composed dispatch tool directly, or record a volunteer's accepted pickup locally."""

import argparse
import asyncio
import json
import sys

from agent import ROOT, SERVERS, answer_from_report, connect, tool_value
from food_rescue.service import confirm_assignment


async def demonstrate(ids, driver=None):
    async with connect("composed") as session:
        print("Available MCP tools:", ", ".join(t.name for t in (await session.list_tools()).tools))
        for case_id in ids:
            report = tool_value(await session.call_tool("plan_rescue", {"case_id": case_id}))
            print("\n" + answer_from_report(report))
            if "error" in report:
                return 1
            if driver:
                if driver not in [p["driver"] for p in report["candidates"]]:
                    print("No proposal for the selected volunteer.")
                    return 1
                print(
                    f"After the volunteer accepts, type ASSIGN {case_id} {driver} to record the local booking."
                )
                try:
                    confirmation = input().strip()
                except EOFError:
                    confirmation = ""
                if confirmation != f"ASSIGN {case_id} {driver}":
                    print("Booking cancelled.")
                    return 0
                try:
                    print(json.dumps(confirm_assignment(report["case_ref"], driver, confirmation)))
                except ValueError as exc:
                    print(str(exc))
                    return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="*", default=["R24", "R25", "R26"])
    parser.add_argument(
        "--assign",
        metavar="DRIVER",
        help="Record a single proposed assignment after human confirmation",
    )
    parser.add_argument("--client-config", action="store_true")
    args = parser.parse_args()
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
        if args.assign and len(args.cases) != 1:
            parser.error("Pass one pickup ID when recording an assignment.")
        raise SystemExit(asyncio.run(demonstrate(args.cases, args.assign)))
