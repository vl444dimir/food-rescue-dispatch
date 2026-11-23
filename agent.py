"""Model-selected tool calls over stdio MCP for a food-rescue dispatcher."""

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent
SERVERS = {"composed": "synapse/plan_rescue_server.py", "individual": "atomic_server.py"}
SYSTEM = (
    "Help the dispatcher find a replacement volunteer. Make one tool call per turn. "
    "Use the complete planning tool if available. Otherwise read the cancelled pickup first, "
    "screen volunteers using the exact case_ref it returns, then evaluate routes with that same "
    "case_ref and the entire driver_ids list copied from screening. Never guess identifiers. "
    "Return a proposal only. A dispatcher must obtain volunteer consent before recording a booking."
)
STATUSES = {"PROPOSED", "NO_FEASIBLE_DRIVER", "NEEDS_INFO", "ALREADY_ASSIGNED"}


@asynccontextmanager
async def connect(mode):
    env = {"PYTHONPATH": str(ROOT)}
    env.update(
        {
            k: os.environ[k]
            for k in ("DISPATCH_DATA", "DISPATCH_LEDGER", "DISPATCH_AT")
            if k in os.environ
        }
    )
    params = StdioServerParameters(
        command=sys.executable, args=[str(ROOT / SERVERS[mode])], cwd=str(ROOT), env=env
    )
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as diagnostics:
        try:
            async with (
                stdio_client(params, errlog=diagnostics) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                yield session
        except Exception:
            diagnostics.seek(0)
            print(diagnostics.read(), file=sys.stderr)
            raise


def tool_value(result):
    if result.isError:
        return {"error": " ".join(part.text for part in result.content if part.type == "text")}
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


def clock(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


def answer_from_report(report):
    if "error" in report:
        return "Unable to verify. " + report["error"]
    line = f"{report['case_id']} | {report['status']} | {report['reason']}"
    line += (
        f"\n{report['pickup']} to {report['dropoff']}, load {report['units']}. "
        f"Board at {clock(report['as_of'])} on {report['service_date']} ({report['timezone']})."
    )
    if report.get("candidates"):
        p = report["candidates"][0]
        line += (
            f"\nContact {p['driver']}. Pickup {clock(p['pickup_at'])}, delivery complete "
            f"{clock(p['delivered_at'])}, {p['deadline_slack_min']} min before closing. "
            f"{len(report['candidates'])} feasible of {report['screened']} screened."
        )
        if len(report["candidates"]) > 1:
            alt = report["candidates"][1]
            line += f"\nNext option: {alt['driver']}, delivery {clock(alt['delivered_at'])}."
        if report["blocked_routes"]:
            reasons = {
                "existing_booking": "conflicts with an existing booking",
                "pickup_deadline": "misses donor closing",
                "delivery_deadline": "misses recipient closing",
                "shift_return": "cannot return before shift end",
                "cold_time_limit": "exceeds the transport limit",
                "road_unknown": "missing road estimate",
                "unverified_position": "needs a new check-in",
            }
            details = [
                f"{driver} ({', '.join(reasons.get(r, r) for r in why)})"
                for driver, why in sorted(report["blocked_routes"].items())
            ]
            line += "\nRoutes ruled out or unverified: " + ", ".join(details[:3]) + "."
    if "earliest_possible_delivery" in report:
        line += (
            f" Earliest possible {clock(report['earliest_possible_delivery'])}, "
            f"closing {clock(report['dropoff_deadline'])}."
        )
    if booked := report.get("assignment"):
        line += (
            f"\nRecorded pickup {clock(booked['pickup_at'])}, "
            f"delivery {clock(booked['delivered_at'])} with {booked['driver']}."
        )
    return line


def guard(name, args, requested, ref, pool):
    if not isinstance(args, dict):
        return "Supply a JSON object."
    if name in {"plan_rescue", "get_cancelled_pickup"} and args != {"case_id": requested}:
        return f"Use the requested case_id {requested}."
    if name in {"screen_volunteers", "evaluate_routes"} and (
        ref is None or args.get("case_ref") != ref
    ):
        return f"Use the observed case_ref {ref}." if ref else "Read the cancellation first."
    if name == "evaluate_routes":
        if pool is None:
            return "Screen volunteers first."
        ids = args.get("driver_ids")
        if (
            not isinstance(ids, list)
            or not all(isinstance(i, str) for i in ids)
            or sorted(ids) != sorted(pool)
        ):
            return "Use every screened driver_id exactly once: " + str(pool)
    return None


async def review(question, mode, base_url, model, api_key=None):
    ids = set(re.findall(r"\bR[0-9]{1,12}\b", question.upper()))
    if len(ids) != 1:
        raise ValueError("Specify exactly one pickup ID such as R24.")
    requested = ids.pop()
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    trace = []
    ref = pool = None
    refreshes = 0
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with connect(mode) as session, httpx.AsyncClient(timeout=240, headers=headers) as http:
        available = {t.name: t for t in (await session.list_tools()).tools}
        schemas = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": t.description,
                    "parameters": t.inputSchema,
                },
            }
            for name, t in available.items()
        ]
        for turn in range(1, 9):
            try:
                response = await http.post(
                    base_url.rstrip("/") + "/chat/completions",
                    json={
                        "model": model,
                        "messages": messages,
                        "tools": schemas,
                        "temperature": 0,
                        "parallel_tool_calls": False,
                        "max_tokens": 350,
                    },
                )
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                if not isinstance(message, dict):
                    raise TypeError("Missing model message")
                calls = message.get("tool_calls") or []
                if not isinstance(calls, list) or any(
                    not isinstance(call, dict)
                    or not isinstance(call.get("id"), str)
                    or not isinstance(call.get("function"), dict)
                    or not isinstance(call["function"].get("name"), str)
                    for call in calls
                ):
                    raise ValueError("Invalid model tool call")
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                detail = (
                    f"HTTP {exc.response.status_code}"
                    if isinstance(exc, httpx.HTTPStatusError)
                    else type(exc).__name__
                )
                error = f"Could not obtain a model tool request ({detail}). Check the model endpoint and model ID."
                return {
                    "mode": mode,
                    "model": model,
                    "question": question,
                    "calls": trace,
                    "turns": turn,
                    "report": {"error": error},
                    "answer": error,
                }
            if not calls:
                messages.append(
                    {
                        "role": "user",
                        "content": "Use the tools to obtain the verified route report.",
                    }
                )
                continue
            messages.append(
                {"role": "assistant", "content": message.get("content"), "tool_calls": calls}
            )
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments"))
                except (ValueError, TypeError):
                    args = None
                invalid = (
                    guard(name, args, requested, ref, pool)
                    if name in available
                    else "Unknown tool."
                )
                value = (
                    {"error": invalid}
                    if invalid
                    else tool_value(await session.call_tool(name, args))
                )
                trace.append(
                    {"tool": name, "arguments": args, "dispatched": not invalid, "result": value}
                )
                if not invalid:
                    if name == "get_cancelled_pickup":
                        ref = value.get("case_ref")
                        pool = None
                    if name == "screen_volunteers":
                        pool = value.get("driver_ids")
                    if (
                        "Dispatch board changed or reference is invalid." in value.get("error", "")
                        and refreshes < 2
                    ):
                        ref = pool = None
                        refreshes += 1
                    elif "error" in value or (
                        value.get("case_id") == requested and value.get("status") in STATUSES
                    ):
                        return {
                            "mode": mode,
                            "model": model,
                            "question": question,
                            "calls": trace,
                            "turns": turn,
                            "report": value,
                            "answer": answer_from_report(value),
                        }
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(value)}
                )
    return {
        "mode": mode,
        "model": model,
        "question": question,
        "calls": trace,
        "turns": 8,
        "report": {"error": "Tool budget exhausted."},
        "answer": "No verified plan.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default="Who can cover pickup R24?")
    parser.add_argument("--mode", choices=SERVERS, default="composed")
    parser.add_argument(
        "--base-url", default=os.getenv("DISPATCH_MODEL_URL", "http://127.0.0.1:8080/v1")
    )
    parser.add_argument("--model", default=os.getenv("DISPATCH_MODEL", "local-model"))
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(
            review(
                args.question,
                args.mode,
                args.base_url,
                args.model,
                os.getenv("DISPATCH_MODEL_API_KEY"),
            )
        )
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    if args.trace:
        print(json.dumps(result, indent=2))
    else:
        print(
            "Agent MCP calls:", " -> ".join(c["tool"] for c in result["calls"] if c["dispatched"])
        )
        print(result["answer"])
    if "error" in result["report"]:
        raise SystemExit(1)
