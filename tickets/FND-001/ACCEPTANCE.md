
# FND-001 acceptance contract

## Mandatory observable behaviour

### Package and CLI

- Distribution and import package are `dmf-pulse` / `dmf_pulse`.
- Version is `0.1.0` and has one canonical source.
- The console command is `dmf`.
- `dmf --version` returns the semantic version and exit code 0.
- The wheel contains `dmf_pulse/py.typed`.
- The installed-wheel smoke test runs outside the repository and proves the import path is the installed environment, not `src/`.

### Typed configuration

Implement a strict Pydantic v2 configuration model with at least:

- environment enum: development, test, staging, production, replay;
- internal timezone fixed to UTC;
- display timezone validated by `zoneinfo`, default Europe/London;
- artifact root as a normalised path;
- optional database DSN **reference**, never a DSN value;
- log level;
- compute configuration:
  - default device CPU;
  - optional requested accelerator CUDA;
  - fallback enabled;
- unknown fields forbidden;
- deterministic base → environment → explicit override precedence;
- load does not create directories or contact external systems;
- secret-looking values are rejected where a reference is required;
- config display is deterministic and redacted.

Required example files:

- `config/base/application.yaml`
- `config/environments/development.yaml`
- `config/environments/test.yaml`

### Doctor command

`dmf doctor --json` must return a deterministic schema containing at least:

- package version;
- Python version and compatibility result;
- OS/platform and architecture;
- current UTC time from an injected/testable clock boundary;
- configuration validation status;
- writable artifact-root check performed safely in a temporary probe and cleaned up;
- Git availability/version where available;
- uv availability/version where available;
- optional NVIDIA probe status.

NVIDIA requirements:

- no CUDA/PyTorch/JAX dependency;
- use only best-effort `nvidia-smi` discovery with a short timeout if implemented;
- unavailable GPU is a healthy nonblocking state;
- never record Windows Device ID, Product ID, serial number, username, or secret environment values.

### Evidence and manifests

The repository must include:

- exact copies of all supplied DMFP-00 through DMFP-20 files under `specs/approved/`;
- `specs/manifests/document_manifest.json` with SHA-256, bytes, ID, version and status;
- `specs/manifests/authority_manifest.json` mapping FND-001 and future high-level stages to controlling documents/decisions;
- `specs/manifests/decision_manifest.json` containing the relevant accepted/provisional decisions;
- validators that fail clearly on missing files, hash mismatch, duplicate IDs, malformed evidence, or more than 20 review-pack files;
- deterministic canonical JSON hashing.

### Repository guidance

Create concise, usable:

- `AGENTS.md`
- `PLANS.md`
- `CODE_REVIEW.md`
- `.codex/README.md`
- implementation and independent-review prompt templates
- FND-001 ticket/Definition of Ready/Acceptance records

Do not embed the entire research corpus into AGENTS.md.

### Security and supply chain

- `.gitignore` excludes secrets, private data, large data/model artifacts, logs and generated review packs.
- Repository licence is private/proprietary All Rights Reserved.
- Secret detection has first-party deterministic tests with fake secrets across mappings, strings, URLs and exception text.
- No secret value is printed by CLI/config/doctor/evidence output.
- `uv.lock` is committed and frozen acceptance uses it.
- A dependency report records direct/transitive packages, versions and licences where discoverable without pretending unknown licences are known.
- A build/package report records Python, platform, tool versions, wheel name/hash/content checks and clean-install result.

### CI

Required GitHub Actions behaviour:

- Ubuntu PR/push job: frozen sync, format check, lint, mypy, tests with coverage, build, clean-wheel verification, repository/evidence validation, secret scan.
- Use official GitHub actions and a conservative installation path.
- No production secret is required.
- Network is used only for dependency installation.
- A Windows smoke workflow may be scheduled/manual to conserve free private-repo minutes; document the choice.
- CI commands mirror local commands.

### Cross-platform local usage

README/operations docs must provide copy-paste setup for:

- Windows PowerShell;
- Linux/WSL2/POSIX shell;
- running without Make;
- optional Make convenience commands where available.

Canonical acceptance cannot depend solely on Bash, GNU Make, Docker, WSL, or a GPU.

## Mandatory tests

At minimum:

- unit tests for config validation, overlay precedence, error codes, redaction, manifest hashing and CLI rendering;
- property tests for deterministic overlays, canonical hash stability and secret redaction idempotence;
- integration test for clean wheel install outside repository;
- golden JSON tests for doctor/config/evidence errors;
- tests that imports have no external side effects;
- tests that GPU absence is healthy;
- tests that the review pack refuses 21 files;
- tests that hash mismatch fails;
- tests that a raw secret value in config is rejected.

## Mandatory acceptance commands

Codex may add equivalent wrapper commands, but these capabilities must actually run:

```text
uv sync --all-groups --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy src/dmf_pulse
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing
uv run dmf --version
uv run dmf doctor --json
uv run dmf config validate --environment test --config-root config
uv run dmf config show --environment test --config-root config --json
uv build
uv run python scripts/verify_wheel.py
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
uv run dmf review-pack build --ticket FND-001 --output review_pack/FND-001
```

The implementation must also run the installed `dmf --version` and `dmf doctor --json` from a fresh temporary virtual environment outside the repository.

## Completion evidence

Write under `evidence/tickets/FND-001/`:

- baseline manifest;
- executed plan;
- exact commands and exit codes;
- test and coverage summary;
- dependency report;
- build/package report;
- repository validation report;
- acceptance matrix;
- `codex_result.json`;
- human-readable `ACCEPTANCE.md`.

Do not mark COMPLETE when any mandatory command was skipped, simulated, or inferred from a different command.
