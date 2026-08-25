# CURRENT-FPL-STATE-001A independent-review remediation

Reviewed deficient head: `140100fa49bea1d3d0493cb68f186af564fa1380`

Architectural parent: `2bc2783adc37d0956962d7574f73cbb6af711e28`

Branch: `integration/current-fpl/CURRENT-FPL-STATE-001A-manual-transient`

This record preserves findings from the subsequent independent review. It does not rewrite the
original same-agent review, perform a new independent re-review, or claim human acceptance.

## CFSA-REV-001 — material P2

Reproduction at the reviewed head showed that `finished=None`, a target with
`is_previous=True`/`is_current=True`, and target state fields that were `None` in otherwise accepted
tuples could compile. An individual non-target event with multiple true state flags was not always
rejected.

Remediation requires the target to have `finished is False`, `is_previous is False`, and exactly
one complete explicit tuple: current `(False, True, False)` or next `(False, False, True)`. Every
event is also rejected when more than one previous/current/next flag is true; unique current and
next identities remain required.

Regression coverage includes explicit valid current/next states and rejects finished true/null,
previous+current, previous+next, current+next, every target flag null, neither current nor next,
two current, two next, and contradictory non-target flags. Focused GREEN: 76 passed.

Disposition: **CLOSED by remediation; independent re-review pending**.

## CFSA-REV-002 — material P2

Reproduction at the reviewed head confirmed an `lstat(path)` followed by a separate pathname open,
and hard-linked bootstrap/fixtures objects were not rejected as `USAGE_INVALID` before parsing. The
reviewed implementation had no low-level descriptor boundary on which the deterministic
substitution regression could interpose.

Remediation performs pre-open `os.lstat`, rejects symlink/non-regular paths, opens once with
read-only/binary/close-on-exec and `O_NOFOLLOW` flags where the platform exposes them, validates the
opened object with `os.fstat`, compares pre/open and post/open identity with `os.path.samestat`, and
reads at most the configured limit plus one byte from that descriptor. An `ExitStack` holds both
verified descriptors concurrently so actual opened-object identity, including hard links, must
differ before either payload is parsed. Every descriptor is closed in the context-manager cleanup.

Deterministic regressions substitute a different regular-file descriptor after pre-open validation,
substitute post-open pathname metadata, supply a non-regular `fstat`, and verify failed descriptors
are closed. Existing missing/directory/symlink/same-path checks remain; resolved aliases, hard links,
both oversize positions, ordinary files, and available `O_NOFOLLOW` use are covered. Error messages
do not disclose source paths or attacker bytes.

The claim is limited to this stdlib descriptor/path boundary. It is not an absolute claim against
arbitrary kernel or filesystem control.

Disposition: **CLOSED by remediation; independent re-review pending**.

## RED/GREEN chronology

- RED focused command at reviewed behavior: 8 failed, 10 passed, 46 deselected. Failures exposed
  accepted target null/contradiction states, non-target contradictory state, hard-link aliasing, and
  the missing descriptor-open boundary.
- GREEN complete focused command after remediation: 76 passed, 0 failed.
- Branch-aware ticket-owned coverage: 91%, with descriptor-validation failure branches included.

## Scope and status

No network, database, persistence, manager state, FPL-to-Odds identity, availability/minutes,
projection, optimisation, or orchestration dependency was added. Local gates passed: 30 hostile
cases; 205 non-database plus 68 PostgreSQL 18.4 inherited tests; frozen sync; diff; format; lint;
module-invoked mypy over 248 source files; build; all three wheel verifiers; repository/secret gates;
and the isolated installed-wheel synthetic GW2 command. The direct Windows `mypy` launcher was
blocked before execution by host Application Control and therefore requires the final Linux CI
proof. Exact-SHA CI is recorded only externally after the immutable push. The permitted clean
status is `CURRENT_FPL_STATE_001A_REMEDIATED_PENDING_INDEPENDENT_REREVIEW`.
