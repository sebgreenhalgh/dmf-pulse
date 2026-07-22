# Ruleset Schema Contract

A source directory contains exactly these required authoring files unless a future schema version changes the manifest:

- `season_manifest.yaml`
- `positions.yaml`
- `scoring.yaml`
- `assists.yaml`
- `bonus.yaml`
- `squad.yaml`
- `lineup.yaml`
- `transfers.yaml`
- `prices.yaml`
- `chips.yaml`
- `deadlines.yaml`
- `special_events.yaml`
- `source_manifest.yaml`

Unknown extra YAML files are rejected unless explicitly listed as extension files in the season manifest and supported by the schema version.

## Authoring safeguards

- YAML safe subset only.
- Reject duplicate mapping keys at every nesting level.
- Reject anchors, aliases and merge keys.
- Reject custom tags.
- Reject non-string mapping keys.
- Reject timestamps/dates coerced into Python date types; authoring timestamps must be quoted RFC 3339 strings.
- Reject implicit booleans such as unquoted `yes/no/on/off` where a string is required.
- No binary floating-point rule values. Integer, boolean, string, explicit decimal-as-string or typed unknown wrapper only.

## Typed unknown

A required value may be absent only in a non-production draft using an object equivalent to:

```yaml
verification_status: "UNKNOWN"
value: null
source_refs: []
```

The field’s schema must explicitly permit this state. `null` alone is invalid. UNKNOWN/CONFLICTED required values block VERIFIED/ACTIVE status.

## Canonical output

The compiler emits one JSON object with:
- schema and ruleset versions;
- exact source file hashes;
- status and production eligibility;
- normalized typed rule values;
- rule IDs and source IDs;
- deterministic UTF-8 JSON representation;
- SHA-256 computed over the canonical representation excluding only the self-hash field;
- compiler version and source-bundle hash.

Map keys are sorted. Lists retain declared semantic order. Strings use Unicode NFC. Newlines and authoring comments do not affect the compiled hash. Two semantically different rule sets must not share a hash.

## Lifecycle

- `REFERENCE_ONLY`: may compile and score research/synthetic scenarios; cannot publish target decisions.
- `CAPTURED_UNVERIFIED`: may validate, compile, show and diff; scoring may be blocked when required values unknown; activation always fails.
- `VERIFIED`: all blocking values verified and tests/source bundle complete; not yet active.
- `ACTIVE`: requires exact approval record and immutable artifact publication.
- Active artifacts cannot be overwritten at the same ID/version/path. A change requires a new version/hash.
