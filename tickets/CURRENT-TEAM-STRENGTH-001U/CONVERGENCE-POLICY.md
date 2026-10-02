# Predeclared convergence acceptance

Before measuring/selecting a count, evaluate deterministic nested prefixes
64, 128, 256, 512, 1024 and 2048 against an 8192-draw reference, with independent
counter seeds 23 and 71. Use representative synthetic strong/weak/balanced
fixtures, including identical market-backed and prior-only Stage-8 requests.
Measure both lambda means, exact-score L1/max movement, 1X2, each accepted
total-goal line, clean sheets, lambda/predictive variances and Stage-8 outputs.

For an operational research count, every fixture and seed must preserve all
published six-place Stage-8 goal means against both the high reference and the
next count, and probability differences must not exceed the existing Stage-8
tail tolerance (1e-10). This deliberately conservative rule uses existing
representation/tail boundaries, not an invented model accuracy tolerance.
The last candidate cannot pass without a higher next candidate. All comparison
metrics remain visible even when this rule fails.

Any later downstream player/decision gate must also satisfy governed 0.15 xp/GW
and 0.50 horizon utility materiality limits; Stage-8 stability alone cannot prove
that gate. No operational count is selected unless all relevant gates pass.
Absent stability, explicit caller-selected counts remain RESEARCH_ONLY; no
default draw count, live mixture mode, accuracy claim or activation is added.
