"""Verify portable repository manifest hashes against staged Git object bytes."""

import hashlib
import json
import subprocess
from pathlib import Path

rows = json.loads(Path("evidence/tickets/PRC-013/current_manifest.json").read_text())["files"]
requests = "".join(":" + row["path"] + "\n" for row in rows).encode()
result = subprocess.run(
    ["git", "cat-file", "--batch"], input=requests, capture_output=True, timeout=120, check=True
)
offset = 0
for row in rows:
    end = result.stdout.index(b"\n", offset)
    header = result.stdout[offset:end].split()
    if len(header) != 3:
        raise SystemExit("Missing staged manifest member: " + row["path"])
    size = int(header[2])
    raw = result.stdout[end + 1 : end + 1 + size]
    offset = end + size + 2
    if size != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise SystemExit("Staged-byte manifest mismatch: " + row["path"])
print(json.dumps({"status": "PASS", "manifest_entries": len(rows), "source": "GIT_INDEX_BYTES"}))
