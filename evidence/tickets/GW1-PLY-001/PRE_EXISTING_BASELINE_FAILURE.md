# Inherited general-CI baseline—outside GW1-PLY-001

Canonical general CI run `32433733490` was already failing in the PostgreSQL
integration gate at:

```text
tests/integration/ingestion/odds/test_live_provider_current_input.py::
test_live_provider_native_input_persists_governed_evidence_without_mapping
```

The recorded inherited condition is `QUOTA_REQUEST_COST_MISMATCH`; the same
general workflow had already failed on market-primary readiness SHA
`3ef25343725aeef1ebb3546a78e63a2ff72ea2e8` in run `32399775030`.

GW1-PLY-001 does not modify Odds request-cost semantics, Stage-6 totals,
PostgreSQL Odds persistence, or this inherited test. Its dedicated offline
workflow is therefore the ticket acceptance gate. A material change to this
baseline is an investigation stop, not a reason to alter this candidate.
