# U.01 authority closure

The human instruction for 001U attests that L8's one-shot was consumed.
Only authority consumption is persisted here; no terminal JSON, squad, action,
player identifiers, market payloads, or reconstructed private inputs are stored.

L1-L8 are in the immutable consumed-reference set. Current approval and
attestation are both None. Historical aliases remain solely for compatibility;
they cannot authorize a provider attempt. Unknown pairs fail closed. No L9 exists.

Offline verification before publication:

```text
PYTHONPATH=src python -m pytest tests/unit/private_v1/test_team_strength_u_closure.py tests/unit/private_v1/test_team_strength_l2.py -q
87 passed in 6.63s
python -m ruff check <three changed Python files>
All checks passed!
python -m ruff format --check <three changed Python files>
3 files already formatted
git diff --check
PASS
```

These commands used the existing workspace Python environment, with this
worktree's src selected explicitly. Frozen sync is pending: the first offline
attempt found no cached locked Ruff wheel in the task-local cache.
