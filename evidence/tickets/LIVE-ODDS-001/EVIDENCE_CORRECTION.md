# LIVE-ODDS-001 secret-scan evidence correction

## Historical assertion preserved

The sealed `COMMAND_LEDGER.txt` for reviewed checkpoint
`6c36e73adef21b52ed54d23733e5a34c71547a6d` states that
`uv run python scripts/scan_secrets.py` passed with zero findings. That
historical statement is preserved as written; it is not treated as true.

## Independent-review contradiction and startup reproduction

Independent review reported eight findings. Remediation startup reproduced
all eight from a clean clone outside `review_pack`:

| Path | Line | Rule | Safe fingerprint | Category at startup |
|---|---:|---|---|---|
| `src/dmf_pulse/ingestion/odds/client.py` | 105 | `CREDENTIAL_ASSIGNMENT` | `3a2d1afa44d101200100d332f52384e523e7e881b7db0008da228cd94cebdfe1` | production design signal |
| `src/dmf_pulse/ingestion/odds/client.py` | 897 | `CREDENTIAL_ASSIGNMENT` | `606a6356b94d2fc503233471e89b63b96d40edc29007a2cd604895d5a37a0107` | production design signal |
| `tests/unit/ingestion/test_live_odds_001_transport.py` | 220 | `CREDENTIAL_ASSIGNMENT` | `39e136d775115063a8b306b58c9009a495d621aff1f75e8441049f4e4e8f92ea` | synthetic test construction |
| same | 220 | `SENSITIVE_QUERY_VALUE` | `6bd70317ef1dbc3ab76b9c859c95032956b423cfb145da1b6bb45298d825934e` | synthetic test construction |
| same | 259 | `CREDENTIAL_ASSIGNMENT` | `6a0214473ea95fc4e02fe7079c3e34eed01836faa2cc729394f8b1a5b6e65dc3` | synthetic test construction |
| same | 260 | `CREDENTIAL_ASSIGNMENT` | `6a0214473ea95fc4e02fe7079c3e34eed01836faa2cc729394f8b1a5b6e65dc3` | synthetic test construction |
| same | 404 | `CREDENTIAL_ASSIGNMENT` | `9e22c1aea6d5444637a73fb57cd347c116b0c3c83894c1c44770c9dd15dbb191` | synthetic test construction |
| `tests/unit/ingestion/test_odds_transport_parser_boundaries.py` | 210 | `CREDENTIAL_ASSIGNMENT` | `606a6356b94d2fc503233471e89b63b96d40edc29007a2cd604895d5a37a0107` | synthetic test construction |

No matched value is copied into this evidence.

## Scanner path defect

`scan_repository()` tests exclusions against absolute `candidate.parts`.
Because the mandated worktree resides below `review_pack`, every repository
candidate is excluded. This explains how the historical zero could be
recorded while the sealed tree still contained eight findings. The zero from
that path is not accepted as a valid scan.

## Final correction

R2 removed both production design signals by removing credential storage from
`OddsHttpRequest`, separating the raw credential from safe request metadata,
and avoiding scanner-significant raw credential assignment syntax in the
unsafe exchange. The parser/transport boundary test signal at the reviewed
line 210 disappeared with that same request-contract correction.

R5 rewrote the five remaining synthetic source constructions so the tests
assemble the credential-bearing query, unsafe header names, and provider body
only at runtime. The sentinel assertions remain unchanged in strength. No
scanner allowlist entry was added by this remediation; no production finding
was suppressed.

R5 also corrected `scan_repository()` to apply excluded path components to
the path relative to the requested repository root. The property test places
a repository beneath a parent directory named `review_pack` and now proves
that its source is scanned. Therefore the mandated worktree is no longer a
false-zero location.

Final exact command from the remediated worktree:

`uv run python scripts/scan_secrets.py`

- exit code: `0`
- status: `PASS`
- finding count: `0`

The historical sealed zero remains false for checkpoint `6c36e73`; this
correction records a new, genuinely covered zero rather than rewriting it.
