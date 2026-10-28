"""Reproducible network-denial wrapper; execute from the worktree root."""

import json
import socket
import sys
from pathlib import Path

attempts = []


def blocked(*args, **kwargs):
    attempts.append("NETWORK_REFUSED")
    raise AssertionError("ACCEL acceptance must remain offline")


socket.create_connection = socket.getaddrinfo = socket.socket.connect = blocked
socket.socket.connect_ex = socket.socket.sendto = blocked
import pytest  # noqa: E402

code = pytest.main(sys.argv[1:])
record = {"denied_network_attempts": len(attempts), "pytest_exit_code": int(code)}
Path("review_pack").mkdir(exist_ok=True)
Path("review_pack/OFFLINE-TEST-NETWORK-RECEIPT.json").write_text(
    json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n"
)
print(json.dumps(record, sort_keys=True))
sys.exit(int(code) if not attempts else 1)
