# Artifact assurance

Stage 13 composes the accepted Stage-12 canonical JSON, semantic sealing, detached SHA-256,
content-addressing, write-once collision detection and path-confinement infrastructure. Tests cover
round-trip persistence, exact idempotency, tamper detection and inherited collision/confinement.
Active artifacts are never resolved through a mutable `latest` alias.
