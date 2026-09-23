# CURRENT-TEAM-STRENGTH-001P-L2-D2 offline acceptance

## Scope and source

- Immutable parent: `c11f4fee160043aafcb4008d4deb0ffa3ef709eb`
- Execution mode: `OFFLINE_ONLY`
- Live FPL requests: `0`
- Live Odds requests: `0`
- Live OpenFootball requests: `0`
- Credential inspection: `0`
- Live retry: `false`
- New live authority: `false`
- Private persistence: `false`
- Production activation: `false`

Provider-shaped tests use only in-memory fake transports and generated inputs. No
provider request, credential, DNS lookup, or socket connection was performed.

## Historical L2

The consumed attempt reported:

```text
CURRENT_TEAM_STRENGTH_001P_L2_LIVE_EXECUTION_NOT_COMPLETED
RUN_TWO_WORLD_COMPARISON
TWO_WORLD_COMPARISON_FAILED
FPL requests = 12
Odds acquisitions = 1
Odds requests = 1
private_attempt_consumed = true
persistence = false
production_activation = false
```

The result proves an untyped/fallback terminal path was used. It does not identify
which wrapper assertion failed, and D2 makes no historical root-cause claim.

## Wrapper audit

The exact parent combined these conditions under one coarse failure:

- post-comparison provider counters changed;
- comparison returned a value of the wrong type;
- an untyped invocation error escaped the D1 typed diagnostic contract;
- safe D1 diagnostic validation/serialization failed and fell back to the current
  generic stage/reason.

D2 assigns closed stages/reasons to invocation, counter reconciliation, type
validation, diagnostic serialization, and success-summary construction. Safe state
includes invocation-started/invocation-returned markers and, on divergence, named
nonnegative deltas for all seven governed counters.

An offline reproduction proves `DENIED_SENDS` can increase even when comparison
code returns normally: code calls the closed-gate audit hook, the gate increments
`denied` and raises, and the caller catches/suppresses that exception. Network access
remains denied. This mechanism is possible; it is not asserted as historical L2's
cause. Actual send deltas and denied-send deltas occupy distinct named fields.

## Tests and quality gates

- D2 direct A-G/adversarial wrapper population: `16 passed`.
- L1/L2 authority and D1 diagnostic population: `156 passed`.
- Real generated provider-shaped one-command vertical slice: `1 passed`.
- Five 001P cases plus comparison/contracts/markets/controls: `65 passed`.
- Public readiness, Stage 8/9/10/11, rolling, one-command, and ordinary CLI:
  `116 passed`.
- Frozen offline dependency sync: `40 packages`, pass.
- Repository-wide Ruff format: `898 files already formatted`.
- Repository-wide Ruff check: pass.
- Strict mypy: `312 source files`, pass.
- Wheel and sdist build: pass (`dmf_pulse-0.2.0`).
- Clean installed-wheel smoke outside source tree: pass; both authorities consumed,
  provider calls `0`, production activation `false`.
- First-party secret scan: `0 findings`.
- Differential coverage against the immutable parent for the two changed production
  modules: `85/85` added executable statements and `12/12` added branches (`100%`
  statement and branch coverage). Direct D2 tests exercise every requested A-G path
  plus counter shape/type/backward movement, pre-invocation capture, and outer typed
  terminal dispatch. Full repository CI retains the configured `>=90%` global
  branch-coverage gate; no exclusion was added.

The comparison kernel, diagnostics model, network gate, ordinary service,
ScorePriorRequest, team-strength model, and Stage 8-11 implementation files are
byte-identical to the immutable parent. The real success slice confirms the same
requests, projections, worlds, decisions, utilities, candidate screens, and
materiality outputs; D2 adds only safe wrapper state/container fields.

Canonical PRC-013 and D2 manifests each contain `1520` governed files. Repository
validation passed with `0` errors, the first-party secret scan passed with `0`
findings, and the capped D2 review pack built with `18` entries. Exact-SHA CI and
final remote equality are post-commit publication gates.
