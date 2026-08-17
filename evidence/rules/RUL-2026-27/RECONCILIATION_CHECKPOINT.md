# RUL-2026-27 Reconciliation Checkpoint

## Scope

This checkpoint records repository identity, governing specification digests, and fresh official 2026/27 source evidence before target-rule authoring changes. It does **not** mark the ruleset active, approved, or production ready.

## Immutable implementation identity

- Repository: `sebgreenhalgh/dmf-pulse`
- Immutable parent: `4f1274ccef419a7c0bde335c48bd4070e248b2e6`
- Dedicated branch: `readiness/RUL-2026-27-full-season-activation`
- Remote `main` at start and recheck: the immutable parent SHA
- Stage-12-or-later modelling changes incorporated: **no**

## Fresh source result

Official source payloads were captured at `2026-08-17T20:14:21Z` through a hash-recording GitHub Actions run. The live bootstrap supplies all 38 deadlines, squad/formation constants, transfer caps and selling fee, and split chip inventory windows. Official 2026/27 announcements close the chip, finality, BPS and defensive-contribution changes.

A material stale-source conflict was found: the Help index still exposes 2025/26 AFCON FAQ text, while the later 2026/27 changes announcement says no AFCON transfer grant applies. The claim register treats the season-specific announcement as controlling and retains an adversarial stale-source gate.

## Existing accepted implementation

The accepted `PLAYER_POINTS` implementation and `INT-FPL-2026-BONUS-TIES-001` interpretation remain authoritative. No existing human approval is broadened. Repository review identified the following implementation gaps to close without redesigning accepted architecture:

1. target schema/status authoring cannot yet represent a complete verified target ruleset;
2. chip effects are blanket-blocked rather than validated/executed through controlled operations;
3. the official 20-transfer cap conflicts with a current squad-size cap assumption;
4. inherited capabilities incorrectly reject a valid interpretation scoped to `PLAYER_POINTS`;
5. schema-1.1 activation lacks evidence-bound source freshness, capability, differential, and reconciliation gates;
6. review-bundle reproduction and assurance are not yet implemented.

## Activation conclusion

No completed 2026/27 Premier League/FPL match exists at this checkpoint. Representative official-game reconciliation is therefore `TEMPORALLY_UNAVAILABLE`. DMFP-02 makes that reconciliation a normative production-activation requirement, so production activation remains blocked even after the technical ruleset is completed. The final branch will retain a pending human approval artifact and test activation failure closed.
