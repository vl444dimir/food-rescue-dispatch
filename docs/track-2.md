# Track 2 submission

## A 60-second demonstration

1. Ask “Who can cover pickup R24?” The pantry closes at 17:00. Volunteer V27 could arrive earlier but already has a fixed appointment. The best feasible option is V20. From 15:30 allow 20 minutes to reach the donor, 5 to load, 27 to drive and 5 to unload. Delivery finishes at 16:27.
2. Ask the same question for R25. Even a driver at the donor would finish 22 minutes after the pantry closes. For R26, a missing cold transport limit calls for a dispatcher check.
3. Open the comparison, then run the assignment command. The model only plans. Once the volunteer agrees, the dispatcher types an exact confirmation to record the booking. A repeat query reports the recorded assignment.

## Check against the participant guide

| Track 2 criterion or deliverable | What judges can verify |
| --- | --- |
| Python, Synapse Custom, one complete tool | The generated server exposes `plan_rescue(case_id)`. It reads the cancellation, screens volunteers, then evaluates routes using the screened IDs. [Source functions](../synapse/workflow.py) · [Generator intent](../synapse/intent.txt) · [Generated Python](../synapse/plan_rescue_server.py) · [Build record](../evidence/synapse-build.json) |
| Agent using the tool | A real model sees schemas discovered over MCP stdio and supplies the tool name and arguments. The client renders the verified result and records requests rejected for invented identifiers. [Agent](../agent.py) |
| Same job with one and several tools | The comparison changes only the exposed tool surface. It keeps the questions, model, temperature, policy, dispatch board and routing code fixed, alternates mode order and uses a fresh conversation each time. [Runner](../compare.py) · [Traces](../evidence/comparison.json) |
| Tool design | One cancellation ID returns ranked alternatives, pickup and delivery times, slack, and reasons for exclusions. Feasibility uses directed road estimates, handling time, fixed appointments and the return before shift end. |
| Errors and edge cases | A missed deadline and missing data produce different decisions. Unknown IDs produce explicit tool errors. Tests change road data, probe exact boundaries, compare both actual servers and invalidate outdated plans. [Tests](../tests) |
| Confirmation before changes | Neither MCP surface can write. The separate dispatcher command prompts for an exact confirmation, revalidates under an SQLite write lock and records one local booking. Tests simulate two people booking the same case. [Booking implementation](../food_rescue/service.py) |

The organizers set qualitative criteria for Track 2. [Participant guide, page 2](https://drive.google.com/file/d/1k_A_9cFr7WL9qyG6NAxbBJyp1goZS8l6/view)

## Recorded comparison

Two rounds with local Qwen3-4B-Instruct-2507, temperature zero. Counts below are actual model-to-MCP calls in each round. A call to the composed tool performs the same three internal operations.

| Pickup | Composed | Individual | Verified outcome in both rounds |
| --- | ---: | ---: | --- |
| R24 | 1 | 3 | V20, delivery at 16:27 with 33 minutes to spare |
| R25 | 1 | 3 | No feasible driver, earliest possible 16:02 |
| R26 | 1 | 3 | Transport limit missing, no proposal |
| R999 | 1 | 1 | Unknown cancellation reported at lookup |

All 16 conversations reached the expected outcome. Across both rounds, the model made 8 composed calls and 20 individual calls, including the missing ID. Every proposed call reached the advertised server. These counts measure agent-to-server interactions on this fixture. Field reliability, time saved by dispatchers and completed deliveries need a pilot with a food rescue organization.

## Rebuild the generated server

Install Synapse CLI 0.1.9, then activate the Python environment from the README. Use a local model endpoint with tool calling.

```sh
npm install -g @2ndbrainlabs-ai/synapse-cli@0.1.9
python scripts/build_synapse.py --cli synapse --base-url http://127.0.0.1:8080/v1 --model Qwen3-4B-Instruct-2507
```

On Windows omit `--cli synapse` to let the script resolve the launcher on PATH. The command runs `synapse build --custom --local` on the Python functions in an isolated directory and writes a fresh server under `.work/generated/`. A local model's first generation produced a differently named tool. The submitted build used a more explicit intent, and its advertised schema and outputs were checked over MCP. Generated source can vary between builds.
