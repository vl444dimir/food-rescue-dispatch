# Track 2 submission

## What to show the judges

1. Ask “Who can cover pickup R24?” V27 already has a fixed appointment. V20 can finish at 16:27, 33 minutes before the pantry closes. Ask the audience what happens if the loaded drive takes 24 minutes longer. Unloading would finish at 16:51, but 56 minutes would have passed since loading. The tool shows a 23-minute delay margin because this scenario sets a 55-minute transport limit.
2. Ask the same question for R25. Even a driver at the donor would finish 22 minutes after the pantry closes. For R26, a missing cold transport limit calls for a dispatcher check.
3. Open the comparison, then run the assignment command. The model only plans. Once the volunteer agrees, the dispatcher types an exact confirmation to record the booking. A repeat query reports the recorded assignment.
4. To answer “What if V20 says no?”, use the confirmed refusal command on the same board. V29 becomes first and the delivery moves to 16:35. A later dispatch time can invalidate every route for that same pickup.

## Check against the participant guide

| Track 2 criterion or deliverable | What judges can verify |
| --- | --- |
| Python, Synapse Custom, one complete tool | The generated server exposes `plan_rescue(case_id)`. It reads the cancellation, screens volunteers, then evaluates routes using the screened IDs. [Source functions](../synapse/workflow.py) · [Generator intent](../synapse/intent.txt) · [Generated Python](../synapse/plan_rescue_server.py) · [Build record](../evidence/synapse-build.json) |
| Agent using the tool | A real model sees schemas discovered over MCP stdio and supplies the tool name and arguments. The client renders the verified result and records requests rejected for invented identifiers. [Agent](../agent.py) |
| Same job with one and several tools | The comparison changes only the exposed tool surface. It keeps the questions, model, temperature, policy, dispatch board and routing code fixed, alternates mode order and uses a fresh conversation each time. [Runner](../compare.py) · [Traces](../evidence/comparison.json) |
| Tool design | One cancellation ID returns ranked alternatives, pickup and delivery times, slack, and reasons for exclusions. Feasibility uses directed road estimates, handling time, fixed appointments and the return before shift end. |
| Errors and edge cases | A missed deadline, missing policy and unknown ID produce distinct outcomes. The agent can recover from a changed board by reading a fresh snapshot. A finished commitment after the last check-in requires a new location. Tests also interrupt model requests and replay simultaneous human decisions. [Tests](../tests) |
| Confirmation before changes | Neither MCP surface can write. The separate dispatcher command prompts for an exact confirmation, revalidates under an SQLite write lock and records one local booking. Tests simulate two people booking the same case. [Booking implementation](../food_rescue/service.py) |

The organizers set qualitative criteria for Track 2. [Participant guide, page 2](https://drive.google.com/file/d/1k_A_9cFr7WL9qyG6NAxbBJyp1goZS8l6/view)

## Recorded comparison

Two rounds with local Qwen3-4B-Instruct-2507, temperature zero. Counts below are actual model-to-MCP calls in each round. A call to the composed tool performs the same three internal operations.

| Pickup | Composed | Individual | Verified outcome in both rounds |
| --- | ---: | ---: | --- |
| R24 | 1 | 3 | V20, delivery at 16:27. The pantry closes 33 minutes later. The transport limit leaves 23 extra driving minutes. |
| R25 | 1 | 3 | No feasible driver, earliest possible 16:02 |
| R26 | 1 | 3 | Transport limit missing, no proposal |
| R999 | 1 | 1 | Unknown cancellation reported at lookup |
| R24 after V20 declines | 1 | 3 | V29, delivery at 16:35 |
| R24 at 16:50 | 1 | 3 | No feasible driver, earliest possible 17:27 |

Each comparison uses an isolated ledger. The two modes start from the same refusal history and clock. The trace includes rejected attempts, elapsed seconds from opening the MCP session to returning a report, and the complete output for each conversation.

All 24 conversations returned the expected result. The composed mode made 12 MCP calls across its 12 conversations, and the individual mode made 32 across its 12. Neither mode produced a rejected attempt on this run. Median elapsed time on this Windows PC with the local Qwen3-4B model already loaded was 4.3 seconds and 24.6 seconds respectively. Both modes reached the same dispatch decisions.

The Windows defense run also shows the 23-minute margin, the assignment and the model reading it back. For this recording an automated input supplied the exact confirmation for a simulated volunteer on an isolated ledger. [Terminal transcript](../evidence/defense-transcript.txt)

## What the fund would need for a pilot

The board covers one service day, volunteers currently on shift and one pickup and delivery inserted between fixed commitments. Check-ins, acceptance and the time limit for perishable goods must come from the operator. Travel estimates use a saved road network. A proposed route with 33 minutes to spare gives the dispatcher a reason to call V20. A completed delivery requires confirmation from the receiving organization.

For a pilot, record the current manual baseline and compare the median time from a cancellation to an accepted replacement, the share of pickups delivered before closing, and cases sent for manual verification. The demo measures agent behavior; no partner delivery outcomes have been measured.

## Rebuild the generated server

Install Synapse CLI 0.1.9, then activate the Python environment from the README. Use a local model endpoint with tool calling.

```sh
npm install -g @2ndbrainlabs-ai/synapse-cli@0.1.9
python scripts/build_synapse.py --cli synapse --base-url http://127.0.0.1:8080/v1 --model Qwen3-4B-Instruct-2507
```

On Windows omit `--cli synapse` to let the script resolve the launcher on PATH. The command runs `synapse build --custom --local` on the Python functions in an isolated directory and writes a fresh server under `.work/generated/`. A local model's first generation produced a differently named tool. The submitted build used a more explicit intent, and its advertised schema and outputs were checked over MCP. Generated source can vary between builds.
