# Reproducible Stage-11 benchmark

Commands from the repository root, Python 3.13.9 on Windows x86-64:

```text
python scripts/benchmark_stage11_policy.py --incoming 12 --tactical surrogate --output review_pack/r2/benchmark-final-12.json
python scripts/benchmark_stage11_policy.py --incoming 3 --tactical exact --scenarios 1 --output review_pack/r2/benchmark-exact-3.json
```

The benchmark executes the retained generic enumerator and then the explicit accelerated path
against identical requests and separately initialized tactical evaluators. Both precompute the
same root squads *outside* the timed policy solve, matching the live blocker's boundary. It
asserts complete exhaustion and full candidate dataclass equality, including all retained root
policies, Decimal utility triples, action/tie choices, tactical hashes and full ownership history.

## STANDARD-scale structural result

The fixture has a 15-player legal squad, 12 retained incoming players (three per position),
FT=2, bank=0, three Gameweeks, identical future shortlist/prices, no chips and zero terminal.
All 12 incoming players are purchasable and reachable. Four incumbents (one per position) cost
50 tenths, other incumbents 40, and incoming players 50. Club and position constraints apply.
This intentionally tractable synthetic economy does not represent every live price profile.
No transfer combination or future action is removed beyond canonical legality. The unchanged
root set has 1 hold, 12 one-transfer and 54 two-transfer actions. The declared STANDARD mode
retains up to four distinct metric-selected players per position before boundary ties; 12 is
in the same broad range. This fixture uses a controlled exact tactical surrogate solely to
isolate structural Stage-11 work; production/private runtime always uses exact Stage 10.

| Measurement | Generic | Accelerated |
|---|---:|---:|
| Stage-11 wall time | 329.285223 s | 12.577433 s |
| Continuation state expansions / memo entries | 3,410 | 389 |
| Continuation memo hits | 0 | 3,021 |
| Policy/action candidates generated | 141,483 | 17,022 |
| Canonical transition applications | 1,833,609 | 20,043 |
| Unique node/squad tactical evaluations | 579 | 579 |
| Future individual tactical calls | 512 | 0 |
| Future node batch calls | 0 | 32 |
| Retained root candidates | 67 | 67 |
| Peak continuation Pareto size | 1 | 1 |

Speedup: **26.180638835844757x**. Exact full candidate equality: PASS.
The target of at least 10x is met on this reproducible synthetic workload.

Original decomposition: canonical transition/validation consumes 294.574466 s of the
329.285223 s solve. Action enumeration consumes 253.246771 s, including its transition work;
these are overlapping/inclusive timers, not additive categories. Pareto construction is
0.513433 s and tactical request time 0.866939 s. Thus structural transition validation and
repeated economically equivalent continuations, not Pareto operations, dominate this fixture.
Depth-2 full fingerprints number 3,343, while economic keys number only 322. No duplicate in
this fixture differs *only* by closed spells; active spell provenance also differs.

After the change, action enumeration is 8.326679 s, transition work 8.228203 s, and Pareto
construction 0.064628 s. The exact budget/club precheck rejects 188,082 combinations without
full transition construction; they still count against the original per-state combination cap.
The first measured version (economic memo, transition reuse, batching; no early economic
precheck) took 34.300763 s versus 326.017485 s, a 9.50x speedup. Profiling that version motivated
the additional lossless precheck, not any shortlist or horizon reduction.

## Real exact tactical check

The smaller 15-player/three-incoming fixture uses the actual Stage-10 adapter and one complete,
coherent all-appearance scenario per node. It is a separate tactical-path proof, not the
STANDARD-scale acceptance workload or a representation of live Stage-9 diversity.

- Generic: 28.026534 s; accelerated: 8.110473 s; speedup: 3.455598087961426x.
- Exactly 357 unique node/squad tactical evaluations on both paths.
- Future individual calls: 288 to zero; all future misses use lazy exact batches.
- Full candidate and canonical tactical/ownership hash equality: PASS.
- The inherited 001L batching regression additionally exercises mixed appearance masks,
  nonuniform weights, autosubs, captain fallback and tied optima.

Timings are elapsed wall time on this workstation, with other local acceptance work possible.
They are not a latency promise for a private entry, arbitrary hardware, large Pareto families,
or the unbounded production problem. The exploratory 32-scenario run was stopped and is not
used as acceptance evidence. No real credentials or private FPL data were read for benchmarks.
