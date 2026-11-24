# Food Rescue Dispatch

A food pantry closes at 5 p.m. The volunteer who was going to collect a donation has just cancelled. Give the agent the pickup ID and it finds who can still deliver on time, checks their existing bookings and explains how much delay the load can tolerate.

**Vibe-a-thon · Track 2 · One Smart Tool from Many Small Functions.** Built in Python with Synapse Custom and the Model Context Protocol (MCP).

[Recorded terminal demo](evidence/defense-transcript.txt) · [Generated MCP tool](synapse/plan_rescue_server.py) · [Agent](agent.py) · [Track 2 comparison](docs/track-2.md) · [Development history](#development-history)

## Try a pickup

From the repository root on Windows with Python 3.11+ installed, run the following in PowerShell. The first run installs the dependencies. This demo calls the generated tool directly and uses the included data.

```powershell
.\demo.ps1
```

On the Pittsburgh test board, 6 of 50 volunteers can cover pickup **R24**. V20 can collect at **15:50** and finish delivery at **16:27**, 33 minutes before the pantry closes. The perishable load allows **23 extra minutes** on the road. If V20 declines, V29 can finish at 16:35.

The demo also includes a pantry that closes too early (R25) and a perishable load with a missing transport limit (R26). Only a dispatcher can save a booking, after the volunteer agrees and the dispatcher confirms the selected route.

[Linux and macOS setup, live model setup and dispatcher commands](docs/running.md)

## One tool or three?

Synapse Custom exposes `plan_rescue(case_id)`. It reads the cancelled pickup, screens volunteers, then checks each candidate’s route against donor hours, pantry hours, transport limits and existing commitments. We gave the same local Qwen model the same six scenarios twice with each tool setup.

| Agent tool setup | MCP calls for R24 | MCP calls across 12 runs | Expected outcomes |
| --- | ---: | ---: | ---: |
| One composed tool | 1 | 12 | 12 / 12 |
| Three individual tools | 3 | 32 | 12 / 12 |

Both setups selected V20 for R24. The unknown-pickup scenario stopped at the first lookup in both modes. [Comparison by scenario](docs/track-2.md#recorded-comparison) · [All 24 model traces](evidence/comparison.json) · [Synapse build record](evidence/synapse-build.json)

## Why this case matters

A field study of Pittsburgh’s 412 Food Rescue found that 672 of 4,574 pickup requests drew no volunteer claim. The operator also describes the work of finding replacement drivers after cancellations. This demo focuses on that dispatch decision. It uses the public FoodGo test dataset, saved road estimates and simulated cancellations. The benchmark measures tool calls and dispatch decisions. [Field study](https://cdn.aaai.org/ojs/7051/7051-13-10280-1-10-20200526.pdf) · [Operator’s account](https://foodrescuehero.org/streamlining-for-good-food-rescue-hero-maximizes-impact-through-2023-tech-improvements/) · [Data sources, licenses and assumptions](examples/SOURCES.md)

## Verify the results

With the project environment activated, run the test suite. It checks the generated tool, dispatch constraints, confirmations and saved comparison traces.

```sh
python -m unittest discover -s tests -v
```

To repeat the 24 model runs after configuring the local model endpoint, use `python compare.py --rounds 2 --output .work/comparison.json`. [Model setup](docs/running.md#run-the-agent)

## Development history

Five commits from November 20–23, 2026 trace the first dispatch agent, Windows demo fixes, volunteer refusals and the perishable-load delay check. They were imported from the team's development repository with the original author dates and GitHub attribution. Each imported commit records its original ID in the `Source-Commit` trailer. [Browse the five commits and their diffs](https://github.com/vl444dimir/food-rescue-dispatch/commits/43bfe61ea8c687e4c80f27bd09464af7f98067a8/)
