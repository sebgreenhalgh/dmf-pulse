# GW1 Checkpoint 1.4A Focused Validation

- Workflow run — `32285050335`
- Validated commit — `3bf950c67b3c3a6d3da48e18b65718281f643461`
- Branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Commit subject — `checkpoint(gw1): stage exact fixture identity publication`
- Overall — `FAIL`
- PostgreSQL — `NOT_EXECUTED` (transient/DB-free identity architecture).
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.
- Checkpoint 1.5 work — `NOT_EXECUTED`.

## Exit codes

- `install_uv` — `PASS` (exit `0`)
- `frozen_sync` — `PASS` (exit `0`)
- `focused_pytest` — `PASS` (exit `0`)
- `ruff_format` — `FAIL` (exit `1`)
- `ruff_format_diff` — `FAIL` (exit `1`)
- `ruff_lint` — `PASS` (exit `0`)
- `strict_mypy` — `FAIL` (exit `1`)
- `build` — `PASS` (exit `0`)
- `secret_scan` — `PASS` (exit `0`)
- `diff_check` — `FAIL` (exit `2`)

## focused_pytest

```text
........................................................................ [ 57%]
......................................................                   [100%]
126 passed in 2.66s
```

## ruff_format

```text
Would reformat: src/dmf_pulse/ingestion/odds/identity.py
Would reformat: src/dmf_pulse/ingestion/odds/mapping.py
Would reformat: tests/unit/ingestion/test_fpl_odds_team_identity.py
3 files would be reformatted
```

## ruff_format_diff

```text
--- src/dmf_pulse/ingestion/odds/identity.py
+++ src/dmf_pulse/ingestion/odds/identity.py
@@ -85,9 +85,7 @@
     odds_identity_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
     team_alias_plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
     team_alias_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
-    mapping_algorithm_version: Literal["gw1-fpl-odds-exact-v1"] = (
-        "gw1-fpl-odds-exact-v1"
-    )
+    mapping_algorithm_version: Literal["gw1-fpl-odds-exact-v1"] = "gw1-fpl-odds-exact-v1"
     team_mappings: tuple[ResolvedCurrentTeam, ...] = Field(min_length=2)
     semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
 
@@ -317,8 +315,7 @@
     if any(mapping.approved_at > decided_at for mapping in plan.team_mappings):
         raise IngestionError("POST_CUTOFF", "team alias was approved after the mapping decision")
     fpl_rights = {
-        str(decision.capability): decision.decision
-        for decision in fpl_input.rights.decisions
+        str(decision.capability): decision.decision for decision in fpl_input.rights.decisions
     }
     if (
         fpl_rights.get("manual_import") != "ALLOW"
@@ -343,8 +340,7 @@
         if (
             team.provider_team_id in by_id
             or team.identity.canonical_lookup_sha256 in identity_hashes
-            or team.source_semantic_sha256
-            != fpl_input.provenance.bootstrap_semantic_sha256
+            or team.source_semantic_sha256 != fpl_input.provenance.bootstrap_semantic_sha256
         ):
             raise IngestionError("MAPPING_CONFLICT", "official FPL team identity is duplicated")
         by_id[team.provider_team_id] = team

--- src/dmf_pulse/ingestion/odds/mapping.py
+++ src/dmf_pulse/ingestion/odds/mapping.py
@@ -201,14 +201,10 @@
 class CurrentTeamAliasPlan(_FrozenCurrentMapping):
     """Operator-supplied, reviewed team alias authority for current use."""
 
-    contract_version: Literal["gw1-fpl-odds-team-alias-plan-v1"] = (
-        "gw1-fpl-odds-team-alias-plan-v1"
-    )
+    contract_version: Literal["gw1-fpl-odds-team-alias-plan-v1"] = "gw1-fpl-odds-team-alias-plan-v1"
     plan_id: str = Field(min_length=1, max_length=160)
     plan_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
-    mapping_algorithm_version: Literal["gw1-fpl-odds-exact-v1"] = (
-        "gw1-fpl-odds-exact-v1"
-    )
+    mapping_algorithm_version: Literal["gw1-fpl-odds-exact-v1"] = "gw1-fpl-odds-exact-v1"
     approved_at: datetime
     evidence_class: CurrentMappingEvidenceClass
     reviewer: str = Field(min_length=1, max_length=160)

--- tests/unit/ingestion/test_fpl_odds_team_identity.py
+++ tests/unit/ingestion/test_fpl_odds_team_identity.py
@@ -69,9 +69,7 @@
 
 def _odds_value(repository_root: Path) -> list[dict[str, Any]]:
     value = json.loads(
-        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(
-            encoding="utf-8"
-        )
+        (repository_root / "fixtures/odds/ODD-005/happy_path.json").read_text(encoding="utf-8")
     )
     assert isinstance(value, list)
     return value

3 files would be reformatted
```

## ruff_lint

```text
All checks passed!
```

## strict_mypy

```text
src/dmf_pulse/ingestion/odds/identity.py:158: error: Argument "key" to "sorted" has incompatible type "Callable[[dict[str, object]], object]"; expected "Callable[[dict[str, object]], SupportsDunderLT[Any] | SupportsDunderGT[Any]]"  [arg-type]
src/dmf_pulse/ingestion/odds/identity.py:158: error: Incompatible return value type (got "object", expected "SupportsDunderLT[Any] | SupportsDunderGT[Any]")  [return-value]
src/dmf_pulse/ingestion/odds/identity.py:177: error: Argument "key" to "sorted" has incompatible type "Callable[[dict[str, int | dict[str, Any] | str | None]], int | dict[str, Any] | str | None]"; expected "Callable[[dict[str, int | dict[str, Any] | str | None]], SupportsDunderLT[Any] | SupportsDunderGT[Any]]"  [arg-type]
src/dmf_pulse/ingestion/odds/identity.py:177: error: Incompatible return value type (got "int | dict[str, Any] | str | None", expected "SupportsDunderLT[Any] | SupportsDunderGT[Any]")  [return-value]
Found 4 errors in 1 file (checked 2 source files)
```

## build

```text
Building source distribution...
Building wheel from source distribution...
Successfully built dist/dmf_pulse-0.2.0.tar.gz
Successfully built dist/dmf_pulse-0.2.0-py3-none-any.whl
```

## secret_scan

```text
{
  "finding_count": 0,
  "findings": [],
  "status": "PASS"
}
```

## diff_check

```text
evidence/readiness/GW1_SESSION1_VALIDATION_1_4A.md:57: trailing whitespace.
+ 
evidence/readiness/GW1_SESSION1_VALIDATION_1_4A.md:84: trailing whitespace.
+ 
evidence/readiness/GW1_SESSION1_VALIDATION_1_4A.md:102: trailing whitespace.
+ 
```
