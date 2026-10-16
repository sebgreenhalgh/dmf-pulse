# A02 acceptance matrix

All automated source cases are synthetic and offline. No real labels or model-performance metrics are used to select or alter the implementation. Original P01/A01 artifacts are read-only; their complete file inventories are retained in evidence.

| Gate | Required proof |
| --- | --- |
| T01 | Original forecast semantic/byte pins; before/after execution authentication; no-generation guard on strict frozen scoring view |
| T02 | Exactly ten frozen IDs; missing/extra/duplicate rejection; no partial score |
| T03 | Exact oriented canonical club aliases and fixture registrations; reversed/unknown/ambiguous identities fail |
| T04 | OpenLigaDB league 5996, pl, 2026, Premier League, matchday 6; wrong source/season/league fails |
| T05 | Finished=true and unique After90Minutes result with global/league type agreement; half-time/extra-time/penalties/exceptional results fail |
| T06 | Actual date from explicit provider UTC timestamp; frozen date separate; no naive/pre-freeze/future played time |
| T07 | Unique provider match/result IDs; one-to-one canonical/provider club mapping |
| T08 | Amendment/context sealed before metrics; immutable fixed OpenLigaDB policy; reviewed file-byte gate; persistent one-attempt marker |
| T09 | Exact already-qualified rights-profile SHA checked before any transport; capability change fails with zero calls |
| T10 | Strict integer scores in governed support; no bool/string/float/null/negative labels |
| T11 | All ten D+2 eligible, UTC midnight boundary tested; no partial metrics |
| T12 | All result/mapping/provenance/rights/timestamp tampering fails semantic authentication |
| T13 | Exclusive content-addressed publication; reauthentication after persistence; collisions refused |
| T14 | Distinct score/report schemas retain PUBLIC_FALLBACK_OUTCOME_SOURCE and A02 context through CLI/store/replay |
| T15 | Exact equality across all 49 metrics, all 30 fixture/product rows; original whole-envelope oracle reproduced independently from accepted parent |
| T16 | Original protocol, A01/clarification, A02 amendment/context, original forecast/cohort and rights identities remain bound |
| T17 | No product/source/model selection, tuning, promotion or activation function; descriptive classification and research draw policy retained |
| T18 | Future authenticated OpenFootball comparison of ten identities/dates/oriented scores; append-only reconciliation/dispute; rehashed false claims rejected |
| T19 | Only three fixed OpenLigaDB TLS routes; no redirects/retries/credential headers; bounded response/deadline; forbidden URLs fail offline |
| T20 | Focused/evaluation/source/rights and legacy regression, Ruff format/lint, strict mypy, frozen sync, build, both installed-wheel paths, manifests, repository validation, secret scan, diff check, full exact-SHA CI before live execution |

Literal local commands are recorded with start/end UTC, exit status and byte-hashed raw stdout/stderr in evidence/tickets/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A02/COMMAND-*.json and COMMAND-*.log. Windows AppControl prevents native Ruff/mypy entry-point launchers, so the identical installed tools run via Python -m. Pytest uses an isolated workspace basetemp after the host temporary-directory ACL refused access. No test or failure gate is disabled; focused coverage is partial-source evidence, and the full aggregate 90% branch-aware gate is enforced by exact-SHA CI.

Publication creates only the requested branch commit. No PR, merge or tag. CI verification and real acquisition/score evidence are subsequent immutable external records bound to the exact implementation commit. Actual source labels and reports remain in private ignored artifacts, never published to Git.
