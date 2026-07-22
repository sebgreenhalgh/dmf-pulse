# DMF Pulse agent instructions

## Mission

Implement only the active approved milestone. Preserve governance, security, reproducibility, portability, and future module boundaries.

## Authority

1. Current official target-season FPL rules and controlling provider terms.
2. Newest approved ACTIVE/ACCEPTED DMFP-20 decision.
3. Most-specific accepted DMFP module specification.
4. DMFP-00 master architecture.
5. Earlier notes and exploratory research.
6. Implementation convenience.

Tickets constrain scope, allowed files, public contracts, tests and acceptance; they cannot override a higher authority.
Tickets are subordinate execution contracts to all six authority levels above.

Use `specs/manifests/authority_manifest.json` to resolve each scope. Stop on a genuine conflict and record exact locators/hashes; do not invent FPL rules, provider rights, numerical models, or future architecture decisions.

## Foundation constraints

- Distribution/import/command: `dmf-pulse`, `dmf_pulse`, and `dmf`; canonical version `0.2.0` for RUL-002.
- Python 3.13, uv, Hatchling, and `src/` layout.
- FND-001 runtime dependencies are limited to Pydantic v2, Typer, and PyYAML plus unavoidable transitives.
- FND-001 development dependencies are limited to Ruff, mypy, pytest, Hypothesis, coverage, build, and unavoidable transitives.
- UTC internally; reject naive datetimes. `Europe/London` is display-only by default.
- No network, database, provider, model, solver, FastAPI, browser, UI, environment mutation, subprocess, or filesystem-write side effect at import.
- Secret references are identifiers, never values. Never read, store, or print real credentials.
- CPU compatibility is required. NVIDIA/CUDA is optional discovery only and must degrade healthily.
- Support Windows PowerShell and Linux/POSIX. Canonical automation uses uv/Python, not Bash or Make alone.
- No broad TODO, `pass`, `NotImplementedError`, hidden stub, fake success, or future-stage placeholder module in accepted scope.

## Rules foundation constraints

- Rules are versioned split YAML compiled to canonical JSON; policy values never hide in scorer code.
- YAML is a strict safe subset: no duplicate keys, anchors, aliases, merges, custom tags, non-string keys, implicit dates, or binary floats.
- `REFERENCE_ONLY` may score research/synthetic scenarios. `CAPTURED_UNVERIFIED` may validate, compile, show, and diff but cannot activate; unresolved required values also block scoring.
- Runtime scoring is pure and explicitly bound to a compiled ruleset hash. Active artifacts are immutable and never resolved through a mutable `latest` alias.
- Never infer an incomplete target-season rule, source right, approval, or activation state.

## Repository map

- Approved authority: `specs/approved/` and `specs/manifests/`
- Production package: `src/dmf_pulse/`
- Configuration: `config/`
- Tests: `tests/`
- Ticket contracts/evidence: `tickets/<id>/` and `evidence/tickets/<id>/`
- Portable automation: `scripts/`
- Generated review output: `review_pack/` (ignored)

## Work method

1. Read the active ticket, authority, decisions, contracts, and relevant excerpts.
2. Update `PLANS.md` for nontrivial work.
3. Write contracts/tests before or alongside implementation.
4. Implement the smallest complete vertical slice without future-stage code.
5. Run targeted tests at checkpoints, then every literal acceptance command.
6. Review scope, secrets, package installation, process timeouts, paths, evidence, dependency provenance, and CI permissions.
7. Store exact command evidence and build the capped review pack.

## Done means

The public command works from a clean installed wheel outside the source tree; required formatting, lint, typing, tests, branch coverage, build, frozen sync, repository validation, and secret scan pass; evidence hashes validate; exclusions remain absent; and independent review has no unresolved P0/P1 finding. Human acceptance/merge remains separate.
