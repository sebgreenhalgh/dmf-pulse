# Stage 9 ruleset readiness

## Target 2026/27 state

- Ruleset ID: `fpl-2026-27`
- Version: `0.1.0-prelaunch.1`
- Status: `CAPTURED_UNVERIFIED`
- Production eligible: `false`
- Human approval / activation: absent
- Partial compiler result hash:
  `ef99df946ef82d880021b2be5bb8a431e90b9f66b37c068eef76d434aec63b5a`
- Partial source-bundle semantic hash:
  `302f019f3d9351c1ae95c0ea8728ee1e3310323f65f6759f60a7228f75a848ec`

Those hashes identify the current partial capture; they do not make it complete,
approved, active, or production eligible. PTS-009 does not modify RUL-002.

## Reference TEST/REPLAY rules

The frozen reference artifact is a real accepted compiler output loaded through
`AcceptedRulesAdapter`:

- ID: `fpl-reference-2025-26`
- Version: `1.0.0`
- Embedded ruleset hash:
  `12271ab0b32a461baa3778f2e914f45744ccf9d5302c37c4a5f2ffb89e0c1139`
- Artifact file SHA-256:
  `f4fb6a5458b3956cb300b822539772904e61036f7571aba7c04284458680f271`
- Status: `REFERENCE_ONLY`
- Production eligible: `false`

It is permitted only for explicit offline TEST/REPLAY fixtures and goldens. Test
support does not duplicate scoring arithmetic; expected outputs are produced and
independently recomputed by the accepted rules engine.

## Mode behavior

TEST/REPLAY accepts an explicitly complete reference/verified rules artifact, binds
the exact ID/version/hash into request and result, and scores only through the
accepted transform.

PRODUCTION requires all of the following: status `ACTIVE`, production eligibility,
no unresolved blockers, and a matching human approval record binding the same
ID/version/hash. Otherwise projection fails closed. The installed-wheel production
probe exits 4 with `RULESET_NOT_ACTIVE` on the current reference artifact.

## Readiness conclusion

The Stage 9 rules boundary is implemented and testable. Production 2026/27 player
points remain **BLOCKED** solely on the independent target-season rules verification,
approval, and activation process plus later model calibration—not on an attempt to
carry reference values into production.
