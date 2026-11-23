# Food Rescue Dispatch

A volunteer has cancelled. Who can still collect the donation and deliver it before the receiving pantry closes? Ask the agent for a pickup ID. It proposes a volunteer, gives pickup and delivery times, and explains when a trip is impossible or needs more information.

In a study of Pittsburgh's 412 Food Rescue, 672 of 4,574 requests drew no volunteer claim. The operator also describes the work of finding drivers to cover cancellations. Our demo addresses the dispatcher's next decision when someone is needed. The research figures describe unclaimed requests and cannot be used to estimate food saved. [Field study](https://cdn.aaai.org/ojs/7051/7051-13-10280-1-10-20200526.pdf) · [Operator's account](https://foodrescuehero.org/streamlining-for-good-food-rescue-hero-maximizes-impact-through-2023-tech-improvements/)

## Run the demo

From the repository root on Windows, run this PowerShell command with a normal user account. The launcher creates a virtual environment on first use. Use Python 3.11 or later on PATH as `python`, a Python 3.11 installation registered with the `py` launcher, or `uv`. The initial install requires internet access.

```powershell
.\demo.ps1
```

On Linux or macOS with Python 3.11, run these commands in the repository root.

```sh
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python demo.py
```

The demo invokes the generated MCP server using the included offline data. On the fresh board it produces these results in Pittsburgh local time.

| Pickup | What the dispatcher learns |
| --- | --- |
| R24 | Contact V20 first. Pickup at 15:50, delivery complete at 16:27, 33 minutes before closing. Six of 50 volunteers have a verified feasible route. |
| R25 | The pantry closes at 15:40. Even a driver already at the donor could only finish at 16:02. |
| R26 | Ask for the permitted transport time for the perishable load before proposing a route. |

## Run the Track 2 defense demo on Windows

On the prepared Windows demo PC, open PowerShell in the repository root. The launcher can start the cached Qwen3-4B model. For another machine, configure the model endpoint described below or use the smaller CPU setup: extract the [llama.cpp Windows x64 CPU release](https://github.com/ggml-org/llama.cpp/releases/tag/b12603) into `.work\llama-runtime` with `llama-server.exe` directly inside, and save [Qwen3.5-0.8B-Q4_K_M.gguf](https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/blob/6ab461498e2023f6e3c1baea90a8f0fe38ab64d0/Qwen3.5-0.8B-Q4_K_M.gguf) directly in `.work`.

```powershell
.\demo.ps1 -Defense
```

The agent asks “Who can cover pickup R24?” in both modes and compares the complete reports. The board puts V20 first and V29 second. The demo assumes the first volunteer agreed. Type the confirmation shown. The demo reads the saved booking back and checks the volunteer, locations and times. Pressing Enter skips the change and verifies that the original proposal still stands. Each run has its own ledger under `.work\defense-*`. To show an impossible pickup, run `.\demo.ps1 -Defense -Question 'Who can cover pickup R25?'`.

## Run the agent

Use an OpenAI-compatible chat-completions endpoint with tool calling. Set `DISPATCH_MODEL_URL` to its base URL including `/v1` and `DISPATCH_MODEL` to its served model ID. The optional `DISPATCH_MODEL_API_KEY` is read from the environment. On the prepared Windows demo machine the launcher can start the cached Qwen model itself.

```powershell
.\demo.ps1 -Live -Question 'Who can cover pickup R24?'
.\demo.ps1 -Live -Mode individual -Question 'Who can cover pickup R24?'
```

With an activated environment, `python agent.py "Who can cover pickup R24?" --trace` shows the model's actual tool requests and results. `python demo.py --client-config` prints the local stdio configuration for another MCP client. The final text renders the verified tool report. The model selects tools and arguments.

## Record an accepted pickup

Once V20 has agreed, run the following command in the project's activated environment. It recalculates the proposal, prompts the dispatcher, and writes one booking to the local ledger only after the dispatcher types `ASSIGN R24 V20`. A changed board or a concurrent booking invalidates the old proposal. A later planning request returns the booking status.

```sh
python demo.py R24 --assign V20
```

If V20 declines or cancels before pickup, run `python demo.py R24 --unavailable V20` and enter `UNAVAILABLE R24 V20` after the volunteer confirms. This releases an existing booking for that case, records the refusal, and recalculates the route. V29 can finish at 16:35 on the sample board. A driver who declines one pickup remains eligible for others.

To replay a delayed callback on a fresh ledger, run `python demo.py R24 --at 16:50`. Even a driver at the donor would now finish at 17:27. The service uses the board's local service day and the supplied simulation time. To use the same time with the live agent, set `DISPATCH_AT` to `HH:MM`. A confirmed change advances the ledger's clock and invalidates earlier proposals.

The demo uses the single service day in [dispatch.json](examples/dispatch.json). Confirmations are stored in `.work/assignments.sqlite3` by default. Point `DISPATCH_LEDGER` at a separate file to run a fresh experiment. Live driver consent, outreach, traffic and delivery outcomes require a partner organization.

## Data and verification

The inputs combine FoodGo's public Pittsburgh test data with documented test scenarios and a saved road-time matrix. The algorithm considers working shifts, check-in time, load, handling requirements, booked trips, opening times and return travel. It tries each gap between fixed commitments, ranks feasible options by earliest completed delivery, and exposes the reason for an empty list. [Dataset credits and assumptions](examples/SOURCES.md)

```sh
python -m unittest discover -s tests -v
python compare.py --rounds 2 --output .work/comparison.json
```

Only the comparison requires a running model. The checked-in evidence contains two rounds, an identical question per case, the same model and both MCP modes. [Track 2 criteria, results and pitch](docs/track-2.md) · [Full model traces](evidence/comparison.json)
