# D6 capacity policy

The repository-owned L6-shaped workload has 13 root incoming candidates, a normal
15-player squad, two root transfers, and a node-specific bounded-horizon terminal
screen. It produces the exact L6 root upper bound of 8,386 and the exact observed
maximum of 1,032 position-compatible action combinations. Its 12,887 reachable
non-root states dominate historical L6's 9,249 without using private rows.

The immutable parent repeats the complete no-transfer baseline search. D6 removes
that lossless duplicate. The final stress case measures 520,651 cumulative legal
actions in the primary exact solve. Although this is 3,637 below 524,288, 0.7%
headroom is not an operational envelope. The governed cumulative cap is therefore
786,432, leaving 265,781 actions (51.0%) above the measured complete workload.

The same probe also demonstrates that the former 250,000 policy-candidate cap is
independently insufficient after cumulative discovery completes. This is not hidden
or overloaded into another unit: `max_policy_candidates` is separately raised to
786,432. The per-state action, state-expansion and returned-root base caps remain
5,000, 25,000 and 1,000; the private request may still raise the first and last to
the authenticated exact-space bounds (17,000 and 8,386 in L6).

Peak memory is not asserted. Portable Python in the locked Windows environment has
no approved non-perturbing peak-RSS facility, and adding a dependency or enabling
allocation tracing for the measured solve would change the workload. Wall and CPU
times are retained as nonsemantic benchmark observations.
