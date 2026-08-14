# Applying the GCS-008 implementation artifact

## Preconditions

- Use a clean clone of `sebgreenhalgh/dmf-pulse`.
- Confirm the required parent exists locally:

  ```powershell
  git cat-file -e a5a0b66afd6e9645f971976d723e238824bee6a8^{commit}
  ```

- Do not apply the artifact to `main`.
- Ensure the worktree is clean before extraction.

## Create the implementation branch

```powershell
$Parent = "a5a0b66afd6e9645f971976d723e238824bee6a8"
$Branch = "stage/A8/GCS-008-goal-clean-sheet-distributions"

git switch --detach $Parent
git switch -c $Branch
```

Extract the ZIP into the repository root, preserving all repository-relative paths and allowing the artifact files to overlay the accepted parent.

## Apply the governed PLANS.md update

The ZIP contains an append-only helper patch because replacing the complete historical `PLANS.md` inside an overlay would be unsafe. Apply it against the exact required parent, then delete the helper so it cannot enter the commit:

```powershell
git apply --check PLANS_GCS008_APPEND.patch
git apply PLANS_GCS008_APPEND.patch
Remove-Item -LiteralPath PLANS_GCS008_APPEND.patch
```

POSIX equivalent:

```sh
git apply --check PLANS_GCS008_APPEND.patch
git apply PLANS_GCS008_APPEND.patch
rm PLANS_GCS008_APPEND.patch
```

## Verify the overlay before execution

```powershell
if ((git merge-base HEAD $Parent) -ne $Parent) {
    throw "The implementation branch is not based on the required parent."
}

if ((git rev-parse HEAD) -ne $Parent) {
    throw "The branch must still point to the required parent before commit."
}

uv run python scripts/validate_gcs008_scope.py
git diff --check
```

The artifact does not alter Stage-7 source, migrations, dependency locks, or `main`. `IMPLEMENTATION_PLAN.md` records the reconciled implementation contract and `PLANS.md` receives the concise repository execution-plan entry through the patch above.

## Validate

Run every command in `ACCEPTANCE_COMMANDS.ps1` from the repository root. Do not treat generated documentation or isolated overlay results as proof that clean-checkout CI passed.

## Commit and publish

After all acceptance commands pass:

```powershell
git status --short
git add --all
git commit -m "feat(events): implement GCS-008 score distributions"
git push --set-upstream origin stage/A8/GCS-008-goal-clean-sheet-distributions
```

Open a draft pull request against the repository’s intended integration branch. Keep independent review, human acceptance, and merge separate from implementation-generated assurance.

## Conflict handling

Stop rather than overwrite when:

- the parent SHA differs;
- `git apply --check` rejects the append-only `PLANS.md` patch;
- any frozen Stage-7, migration, dependency-lock, or unrelated path is already modified;
- a public schema or packaged resource differs from the accepted parent for reasons not represented in this artifact;
- the scope validator identifies an unapproved path.
