# Private analysis warehouse: schema v1

Permanent Windows path: `%LOCALAPPDATA%\DMFPulse\analysis\dmf_pulse.sqlite`.
The file belongs to the Windows owner. Read it locally using SQLite URI mode=ro,
or the installed `dmf analysis` commands. No dashboard, token or provider call is
needed. The warehouse is not an authorization, budget or consumption database.
PostgreSQL retains those responsibilities and its original identity and history.
On POSIX the analytical path is `$XDG_DATA_HOME/dmf-pulse/analysis/dmf_pulse.sqlite`,
or `~/.local/share/dmf-pulse/analysis/dmf_pulse.sqlite` when unset. A first launch
does not require Windows process APIs. Reopening an existing listener requires
native Windows owner/process/listener proof; unsupported proofs fail closed.

```powershell
$deskRoot = Join-Path $env:LOCALAPPDATA 'DMFPulse/operator'
$deskRelease = (Get-Content -LiteralPath (Join-Path $deskRoot 'active-release.json') -Raw | ConvertFrom-Json).manifest.wheel_sha256
$analysisPython = Join-Path $deskRoot "releases/$deskRelease/venv/Scripts/python.exe"
& $analysisPython -I -B -c "from dmf_pulse.cli.app import main; main()" analysis query "SELECT run_id,gameweek,generated_at,provenance_class FROM runs"
& $analysisPython -I -B -c "from dmf_pulse.cli.app import main; main()" analysis query "SELECT name,expected_points,p10,median,p90,expected_minutes FROM player_forecasts ORDER BY expected_points DESC" --csv
& $analysisPython -I -B -c "from dmf_pulse.cli.app import main; main()" analysis export
```

The fixed `operator/dmf.cmd` is the signed **start-only** launcher. Analytical
commands use the active installed wheel's Python CLI entrypoint above, or SQLite directly below. This avoids unsigned console wrappers blocked by Windows Application Control. These
read-only commands do not confer permission to run operational commands directly.

```python
import sqlite3
from pathlib import Path
import os
path = Path(os.environ["LOCALAPPDATA"]) / "DMFPulse/analysis/dmf_pulse.sqlite"
with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
    db.execute("PRAGMA query_only=ON")
    rows = db.execute("SELECT name, expected_points FROM player_forecasts").fetchall()
```

`analysis query` restricts SQLite to reads, disables extensions, caps SQL at16KiB,
results at10,000rows/16MiB and execution at5seconds, with streaming output and bounded SQLite value size. `--database` selects an explicit
read-only local file for inspection. `--csv` prints query results. `analysis export`
prints complete rights-permitted derived JSON, optionally `--run-id ID`. Redirect
these outputs only to a private destination. Neither command uploads anything.
Cloud AI access requires the owner to supply an export explicitly.
Snapshots and SQLite values have a separate 32 MiB capacity (plus bounded row
overhead), accommodating the measured full 760-player optimizer output. History
lists contain metadata only. Complete private JSON exports use the snapshot path;
SQL output remains capped at 16 MiB, so query large evidence by selected fields.

| Relation | Grain and content |
| --- | --- |
| snapshots | One immutable typed derived JSON payload and semantic digest per run ID. Includes unconfirmed staged data, explicitly not a publication. |
| publications | Immutable confirmation: exact snapshot digest, canonical PostgreSQL publication SHA, confirmation UTC. |
| runs | Confirmed snapshots only: GW, generated/cutoff/source capture times, provenance, validation, policy/implementation/wheel fingerprints, full manager decision, source vintages and last-observed quota JSON. |
| player_forecasts | Run/official FPL player ID; canonical ID, name/team/position/price in GBP 0.1; xPts, median/p10/p90/stddev/MC mean SE, expected minutes, start and60+ probabilities, confidence, fallback and full derived row JSON. Probabilities are fractions; minutes/probabilities preserve original decimal strings. Null means unavailable, never zero. |
| manager_squad | Run/original squad slot and player ID, bank and FPL team value in GBP 0.1. |
| fixture_projections | Run/official fixture ID; full available derived fixture summaries, minute distributions, warnings, exact kickoff and projection hashes. Empty for historical imports without retained fixture objects. |
| gameweek_projections | Run/GW derived summaries including distributions/components, uncertainty and Monte Carlo diagnostics when available. |
| optimizer_evidence | Full success-only derived optimization result, selected/conservative/upside/root-counterfactual plans and move attribution. Hashes bind it to the exact manager decision and worker envelope. Required for new normal standing publications; null for older evidence that did not retain it. |
| transfer_plans | Run/evaluated transfer count; complete actual frontier JSON including moves, legal/action constraints, hits, future free-transfer state, bank, gain PMF and uncertainty. This is the engine's evaluated frontier, not invented additional alternatives. |
| tactics | Selected and hold XI, formation derivable from positions, ordered bench, captain/vice, and paired plan comparison JSON. |
| captaincy_evidence | Actual selected/hold tactics and objective disclosure; captain-only counterfactual/joint-outcome fields null when absent. No post-hoc explanation. |
| acquisition_evidence | Run/request: closed diagnostic admission/invocation/HTTP completion metadata; no response bodies or credentials. |
| analysis_attempts | COMPLETE, PENDING_UNCONFIRMED or FAILED; failed attempts never replace latest successful history. |
| failed_attempts | Separate immutable attempt identity, UTC and closed error code. |
| failure_evidence | Immutable closed diagnostic and last observed charge/credit receipt, with explicit normal/owned provenance; unavailable evidence stays null. |
| run_player_changes | Old/new run and player ID, numerical xPts delta. Observable differences only; not causal attribution or evidence of improved skill. |

Canonical typed JSON schema is `AnalysisSnapshot` (analysis-snapshot-v1). The
`view` is the unchanged engine DeskView/decision. Optional `presentation` retains
all available typed catalogue, fixture and Gameweek derived projections. It
excludes original provider bodies, execution inputs and source scenario matrices.
`diagnostics` contains only the existing closed DiagnosticReport model. Engine
lineage hashes remain unchanged. A source Git commit may be null if not carried
by the signed runtime; the exact implementation and signed private wheel remain
pinned. Do not confuse a package-content fingerprint with a Git commit.

Optimizer evidence includes the unchanged engine's evaluated tactical plans and
scenario-level manager outcome scores: counted player IDs, autosubs, effective
captain and aggregate manager points. It excludes raw per-player joint scenario
matrices and execution requests. These retained selected-plan outcomes do not
provide a captain-only counterfactual or explain why Palmer beat Haaland; that
specific explanation remains explicitly unavailable where not produced.

All forecasts remain UNVALIDATED. Provenance is NORMAL_STANDING,
GW10_DIAGNOSTIC or OWNED_SYNTHETIC, with explicit permission origin and private
retention restrictions. GW10 is REAL-DATA-DERIVED, DIAGNOSTIC and HISTORICAL_AS_OF.
Its original timestamps and670player outputs are preserved; unavailable fixture
objects or captaincy counterfactuals remain null/unavailable. Selecting history
never enrolls a new event or changes the consumed GW10 slot.

Generated time, information cutoff, source captured time and actual request
chronology are distinct. Last-observed Odds headers are historical observations,
not a live balance. Original decision replay-retention wording describes the
original transient execution; this warehouse's narrow derived retention does not
authorize raw replay/training datasets or change supplier permission provenance.

Schema migrations use transactional DDL and PRAGMA user_version. Unsupported
versions and unknown pre-existing v0 schemas refuse. SQLite synchronous=FULL and
atomic transactions preserve durable writes; immutable UPDATE/DELETE triggers
protect history. Latest is computed from confirmed run timestamps; it is not an
editable pointer. Stage first, append canonical digest-bound publication second,
confirm third. Startup reconciles exact canonical publications idempotently.
Unconfirmed orphan snapshots remain excluded. Installer and rollback never delete,
move, initialize over, or include this separate analytical directory in releases.
Back up the closed database using SQLite backup API or a consistent file copy;
restore to an owner-only directory and retain original hashes/provenance.

Historical browser verification preserves every installed-byte, signature and
withdrawal guard. An expired acquisition policy can still display already
authorized retained data; strict require_policy remains mandatory before every
quota/discovery/acquisition/enrollment boundary. No future-before-acceptance
policy is admitted. Browser reload and SQL/history access never renew authority.
