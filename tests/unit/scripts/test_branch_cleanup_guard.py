"""Ordinary atomic deletion is restricted to exact reviewed advertised tips."""

import pytest

from tests.unit.scripts.script_support import load_script

guard = load_script("branch_cleanup_guard")


def manifest():
    return {
        "schema_version": "branch-delete-guard-v1",
        "remote_name": "origin",
        "remote_url": "owned-remote",
        "refs": {"refs/heads/old-one": "a" * 40, "refs/heads/old-two": "b" * 40},
    }


def payload():
    return f"(delete) {guard.ZERO} refs/heads/old-one {'a' * 40}\n(delete) {guard.ZERO} refs/heads/old-two {'b' * 40}\n"


def test_exact_complete_deletion_is_admitted_without_any_ref_mutation():
    approved = manifest()
    guard.verify_deletions(approved, "origin", "owned-remote", payload())
    assert approved == manifest()


@pytest.mark.parametrize(
    "change", ["stale", "missing", "extra", "duplicate", "update", "malformed", "other_remote"]
)
def test_unreviewed_updates_are_refused(change):
    value = payload()
    url = "owned-remote"
    if change == "stale":
        value = value.replace("a" * 40, "c" * 40)
    elif change == "missing":
        value = value.splitlines()[0]
    elif change == "extra":
        value += f"(delete) {guard.ZERO} refs/heads/unknown {'d' * 40}\n"
    elif change == "duplicate":
        value += value.splitlines()[0]
    elif change == "update":
        value = value.replace(f"(delete) {guard.ZERO}", f"refs/heads/local {'e' * 40}")
    elif change == "malformed":
        value = "malformed"
    else:
        url = "different-remote"
    with pytest.raises(ValueError):
        guard.verify_deletions(manifest(), "origin", url, value)


@pytest.mark.parametrize("name", [*sorted(guard.PROTECTED), "refs/tags/accepted-release"])
def test_protected_refs_and_tags_cannot_be_manifest_deletions(name):
    value = manifest()
    value["refs"] = {name: "a" * 40}
    with pytest.raises(ValueError, match="non-protected"):
        guard.verify_deletions(
            value, "origin", "owned-remote", f"(delete) {guard.ZERO} {name} {'a' * 40}\n"
        )
