"""Retain exact acceptance command, combined output bytes, timing and exit status."""

import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

name, *command = sys.argv[1:]
if re.fullmatch(r"[A-Z0-9-]+", name) is None or not command:
    raise SystemExit("usage: record_command.py UPPERCASE-NAME command [arguments]")
root = Path(__file__).resolve().parent
log = root / (name + ".log")
receipt = root / (name + ".json")
if log.exists() or receipt.exists():
    raise SystemExit("command evidence is append-only; use a fresh attempt name")
started = datetime.now(UTC)
start = time.perf_counter()
with log.open("xb") as stream:
    result = subprocess.run(
        command, stdout=stream, stderr=subprocess.STDOUT, timeout=2400, check=False
    )
record = {
    "command": command,
    "started_at": started.isoformat(),
    "elapsed_seconds": time.perf_counter() - start,
    "exit_code": result.returncode,
    "output_file": log.name,
    "output_byte_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
}
receipt.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(record, sort_keys=True))
print(log.read_text(encoding="utf-8", errors="replace")[-2500:])
sys.exit(result.returncode)
