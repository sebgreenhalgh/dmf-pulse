# OPT-011 known limitations

1. **Production is fail-closed.** The dependency-free bounded exact enumerator is authorised only
   for explicit TEST/REPLAY state spaces. There is no unrestricted production MILP/backend in
   this delivery.
2. **Terminal value is intentionally zero.** `ZERO_FLEXIBILITY_BASELINE_V1` is versioned,
   disabled and has zero coefficients. No uncalibrated flexibility bonus is hidden in the
   objective.
3. **Future points/value state is supplied.** Stage 11 consumes node-specific tactical values,
   availability, fixtures and prices; it does not forecast prices or injuries.
4. **No chips, rank/EO or account execution.** These remain later-stage concerns.
5. **Grandfathered club-quota repair is not modelled.** A starting squad that exceeds a club
   quota is rejected rather than granted an inferred transition exception. No target-season
   exception was authorised for this stage.
6. **Future club membership is not node-specific.** Candidate club identity is fixed over the
   declared bounded horizon. Requests needing a future real-world club change must fail closed or
   be rebuilt after observation; Stage 11 does not infer transfer timing.
7. **Bounded search caps are explicit.** Exceeding a configured cap returns a typed resource
   status; it never silently prunes and calls the result optimal.
8. **Wall-clock runtime is evidence only.** Runtime is excluded from deterministic result hashes;
   external benchmark evidence records host timing.
