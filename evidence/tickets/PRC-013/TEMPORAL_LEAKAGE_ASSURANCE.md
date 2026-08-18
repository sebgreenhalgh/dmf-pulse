# Temporal leakage assurance

Price and external predictor observations retain UTC `observed_at`, `received_at`, and `usable_at`;
Stage-12 eligibility requires all applicable system times by the information cutoff. Inference now
also proves model and calibrator training cutoffs do not follow the forecast cutoff. Model/config,
feature-schema and recurrent-state versions are exact-lineage bound.

Physical regressions cover post-midnight, future-event, late-received, external-future,
not-yet-available field, outer-fold calibration, future-trained model/calibrator, repeated-snapshot
timing and same-valid-time source-correction canaries. No post-cutoff information path remains in
the reviewed Stage-13 boundary.
