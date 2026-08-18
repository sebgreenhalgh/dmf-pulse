# Temporal leakage assurance

Price and external predictor observations retain UTC `observed_at`, `received_at`, and `usable_at`.
All three must be at or before the information cutoff. Strict mode raises a typed Stage-12 leakage
failure; audit mode excludes the violating observations. P1 rejects labels unavailable at its
training cutoff. Price calibration rejects future labels and Stage-12 blocks outer-origin reuse.

Physical regressions cover post-midnight, future-event, late-received, external-future,
not-yet-available field and outer-fold calibration canaries.
