# CLI acceptance

The same `EvaluationService` powers `build-folds`, `benchmark`, `projections`, `policy`, `leakage`
and `report`. All six commands passed from the canonical wheel installed outside the source tree
with `PYTHONPATH` removed, and the packaged default config loaded successfully. The clean control
returned canonical JSON with exit 0; the future-data canary returned a blocking report and exit 3.
