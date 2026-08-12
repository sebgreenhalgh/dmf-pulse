# MIN-007H v1.4 result

The corrected v1.4 assurance contract was executed against parent
`1599e8fae8156e19da078cba0dffb9afb47ddc49`.

The earlier 77.78% result was the focused whole-availability inventory while
the repository-wide `fail_under=90` setting was active. It was not the final
repository gate. The corrected focused command uses `--cov-fail-under=0` and
the exhaustive validator enforces reachable mathematical-core coverage.

Full suite: 1385 passed, 0 skipped; 92.54% total coverage; exit 0.
Integration migration/availability/markets: 112 passed, 0 skipped. Contract,
golden and property tests: 96 passed, 0 skipped. Alembic head is
`20260807_0006`; migration matrix and wheel/security gates pass.

Raw and reachable core figures are recorded in `math_core_manifest.json` and
`coverage_summary.json`. H cannot self-accept Stage 7; the review archive
requires fresh independent review of every exact waiver.
