# Artifact assurance

Stage 13 composes accepted Stage-12 canonical JSON, semantic sealing, detached SHA-256,
content-addressing, write-once collision detection and path confinement. Projection lineage binds
one semantic hash per source observation plus explicit model, calibration, price-path,
configuration and ruleset identities. Nested Stage-12 calibrator seals are independently verified.

Tests cover round-trip persistence, exact idempotency, tamper detection, nested tampering,
noncanonical lineage, contradictory cycles/decisions/paths and inherited collision/confinement.
Active artifacts are never resolved through a mutable `latest` alias.
