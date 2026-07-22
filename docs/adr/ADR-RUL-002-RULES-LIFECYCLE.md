# ADR-RUL-002: Explicit hashed rulesets and fail-closed activation

Status: accepted for RUL-002 implementation.

Rules are authored as strict split YAML and compiled to canonical, self-hashed JSON. Runtime callers identify a concrete path/hash; no mutable `latest` lookup exists. Reference-only rules may score bounded research scenarios. Target drafts with unknown/conflicted values may be inspected and diffed but cannot score or activate. Activation requires VERIFIED, production-eligible, source-complete rules plus an exact approval identity/hash/provenance record, and publishes atomically to an immutable ID/version path.

This realizes `ADR-GOV-003`, `ADR-GOV-004`, `ADR-PTS-001`, `ADR-PTS-002`, and the RUL-002 lifecycle contracts without treating ticket text as higher authority.
