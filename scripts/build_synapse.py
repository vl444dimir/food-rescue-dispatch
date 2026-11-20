"""Repeat a Custom build in an isolated source directory with your configured provider."""

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="custom")
    parser.add_argument("--model", default=os.getenv("DISPATCH_MODEL"))
    parser.add_argument("--base-url", default=os.getenv("DISPATCH_MODEL_URL"))
    parser.add_argument("--cli", help="Path to Synapse CLI 0.1.9 (default: synapse on PATH)")
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".work" / "generated" / "plan_rescue_server.py"
    )
    args = parser.parse_args()
    cli = args.cli or shutil.which("synapse")
    if not cli:
        raise SystemExit("Install @2ndbrainlabs-ai/synapse-cli@0.1.9 or supply --cli.")
    intent = " ".join((ROOT / "synapse/intent.txt").read_text(encoding="utf-8").splitlines())
    command = [cli, "build", "--custom", "--local", "--provider", args.provider, "-q", intent]
    if args.model:
        command.extend(["--model", args.model])
    if args.base_url:
        command.extend(["--llm-base-url", args.base_url])
    with tempfile.TemporaryDirectory() as name:
        directory = Path(name)
        shutil.copy2(ROOT / "synapse/workflow.py", directory)
        subprocess.run(
            command, cwd=directory, check=True, env={**os.environ, "SYNAPSE_TELEMETRY": "0"}
        )
        generated = directory / "plan_rescue_server.py"
        if not generated.is_file():
            raise SystemExit(
                "Synapse did not produce the named plan_rescue server. Inspect its build output."
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(generated, args.output)
    print("Generated server:", args.output)
