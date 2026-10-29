# Independent Windows performance attribution

Status: **inherited local 100ms budget failure reproduced on accepted parent**.
The local performance gate remains failed. No source or test fix is supported by
the GC hypothesis, and this report does not waive the acceptance requirement.

The predeclared experiment ran exactly one full `-m performance` selection for
accepted parent `02576a563179e0a8d3311fc5e82c770905975f61` and current source,
then one isolated profile for each. No repeat-until-pass, prewarming, GC disable,
threshold change or tracked edit occurred. All transport/DNS was blocked.

| Unprofiled full selection | Thirty cold calls | GC in timed window | Result |
|---|---:|---:|---|
| Accepted parent | 140.331ms | 2.560ms | 1 failed / 3 passed |
| Current | 133.560ms | 1.715ms | 1 failed / 3 passed |

Both windows contained only four generation0 collections, collecting zero objects.
Neither had a generation1/2 collection. Removing observed GC diagnostically would
still leave 137.771ms and 131.845ms. A proposed `gc.collect()` before the cold cache
clear cannot explain this failure and was not run as a remediation experiment.

The test, adapter, model and numerical kernel hashes are identical. Both use the
same Windows host, Anaconda CPython3.13.9, Pydantic2.13.4/core2.46.4 and pytest9.1.1.
Each cell proves the expected cold-cache behavior: one validation miss,29 hits.
No introduced numerical/model/dependency change is demonstrated by these results.

The current attribution profile took138.320ms, including1.655ms GC. Approximately
59ms was spent serializing the complete artifact30 times,41ms in the one cold
authenticated parse, with the remaining time in context/registry validation,
fixture sealing and rate construction. These are the existing authentication paths;
skipping validation or weakening the immutable-content cache is not a valid fix.

The parent profile took312.540ms because profiling triggered an181.375ms generation2
collection. That event was absent from both raw failures. It is an instrumentation
effect, not evidence that pytest collection garbage caused the original failures.
Profile timings are attribution only and are not a replacement benchmark.

The first harness setup mistakenly cleared pytest addopts, removing required
`--import-mode=importlib`; collection aborted before any benchmark. The error is
retained as `performance-parent-collection-importmode-error.json`. Keeping the
repository's pytest options fixed collection. This was setup remediation, not a
timing retry. Parent pytest-cache write warnings are also preserved in its log.

Bounded machine evidence is `accel002-performance-audit.json`; four raw/profile
artifacts contain event timestamps, source hashes, selected tests, outcomes,
unchanged threshold and cache statistics. Corresponding `.log` files retain test
failures. The harness is `accel002_perf_audit.py`; the summary writer performs no
model run (`accel002_perf_finalize.py`).

Recommendation: retain the local failure and investigate a real performance change
that preserves exact authentication/tamper guarantees, or obtain an explicit
governed benchmark-method decision. Do not use a GC-isolation edit or silently
weaken100ms to make this run green. The sample is deliberately small and fixed;
it establishes neither a speedup nor broad statistical equivalence.
