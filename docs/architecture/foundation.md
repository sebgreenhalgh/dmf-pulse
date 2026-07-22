# Foundation architecture

FND-001 is a small typed modular-monolith foundation. It exposes four boundaries:

- `config`: pure validation, deterministic overlays, normalized paths, and safe redaction;
- `system`: injected clock/process/filesystem probes used only at explicit runtime;
- `assurance`: canonical JSON/hash, evidence validation, manifest validation, secret scanning, and review-pack creation;
- `cli`: Typer rendering and stable exit/error contracts over those boundaries.

Package import performs no network, subprocess, database, filesystem write, environment mutation, or logging setup. Configuration contains references to future credentials, never credential values. CPU is the compatibility baseline; optional `nvidia-smi` discovery cannot make health fail.

No FPL domain package exists in this milestone. Future modules remain specification boundaries until their own approved vertical-slice tickets.
