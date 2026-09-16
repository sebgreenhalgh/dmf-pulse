# R9C-D2 acceptance

The blocked probe result is schema `r9c-shadow-probe-diagnostics-v2`. It may disclose
only finite `DirectFplResource` values per transport attempt, the last logical resource,
whether that logical fetch returned bytes, and its transport-attempt count. It must not
disclose identifiers, URLs, HTTP details, bodies, credentials or exception information.

The wrapper is probe-local. It does not retry or alter the direct FPL client, request
order, transport policy, rights, model, persistence boundary, Odds path, active
recommendation path or Stage 7--11 execution.
