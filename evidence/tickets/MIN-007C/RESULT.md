# MIN-007C result

- Ticket: `MIN-007C`; branch: `stage/A7/MIN-007-basic-minutes-model`.
- Accepted parent: `d54eae162386901f9710d7212b5dfb89174cfa31`.
- Commit: pending the required exact-message commit (`MIN-007C add regularised role baseline`).
- Pack validation: Pack 007C `21` manifest entries valid; frozen role oracle passed.
- Acceptance ledger: `13/13` literal commands passed; all availability tests passed with zero skips.

## Contract canaries

- Role artifact semantic SHA-256: `baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96`.
- Accepted MIN-007B training semantic SHA-256: `1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3`.
- Accepted MIN-007B canonical history SHA-256: `23cc133b26beba0455ca50e66cbd4fca5bde8b1b38a4b946b197d53039982096`.
- Eight canonical role canaries and the mixed old-manager/PRESEASON/different-team weighting canary match exactly.
- Hard ineligibility returns internal `START=0`, `BENCH=0`, `OUT=1`, confidence `B`; cold start returns confidence `D` with `NO_TARGET_TEAM_COMPETITIVE_HISTORY`; new-manager and promoted-team early regimes cap at `C`.

## Scope and risks

- Changed only the internal availability role model, synthetic MIN-007C policy/canary fixtures, focused A7 availability tests, plans and MIN-007C evidence.
- Internal `role_utilities` are sampling weights only and are not exposed as public coherent `p_start`, `p_bench` or `p_out_of_squad` values.
- No PMF, coherent sampler, persistence/migration, CLI, evaluation/calibration claim, dependency, network/provider request or credential was added. No unresolved risks; repository validation and secret scanning passed with zero findings.
