"""Build and verify the post-push PRC-013 independent-review archive."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
BASE_SHA = "ce7fe8f4354d95a477afcf6eed45f63cf0ab772e"
BASE_BRANCH = "main"
BRANCH = "stage/A13/PRC-013-price-prediction"
REMOTE_REF = f"refs/remotes/origin/{BRANCH}"
ZIP_PATH = ROOT / "DMF_PULSE_STAGE13_SOL_REVIEW.zip"
SHA_PATH = ROOT / "DMF_PULSE_STAGE13_SOL_REVIEW.sha256"
FIXED_TIMESTAMP = (2026, 8, 18, 12, 0, 0)


def _git(*arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _text(value: str) -> bytes:
    return (value.rstrip() + "\n").encode("utf-8")


def _review_instructions(head: str) -> bytes:
    return _text(
        f"""# Independent Sol review instructions

Review branch `{BRANCH}` at `{head}` against immutable base `{BASE_SHA}`.

Prioritize temporal leakage, immutable identity, Decimal probability reconciliation, recurrent
path completeness, exact Stage-11 selling/affordability reuse, Stage-12 metric/calibration reuse,
ACT/WAIT complete utility, configuration ownership of model policy, rights gating and activation
fail-closed behavior. Report P0/P1/P2 findings explicitly. Run the focused Stage-13 suite and then
the deferred full repository suite. Do not treat this pack or engineering status as human
acceptance, production activation or permission to merge/tag.
"""
    )


def _collect_members(head: str, remote_head: str) -> dict[str, bytes]:
    patch = _git("diff", "--binary", f"{BASE_SHA}..{head}").encode("utf-8")
    if not patch:
        raise RuntimeError("Stage-13 patch is empty")
    changed = tuple(
        line
        for line in _git(
            "diff", "--name-only", "--diff-filter=ACMRT", f"{BASE_SHA}..{head}"
        ).splitlines()
        if line
    )
    if not changed:
        raise RuntimeError("Stage-13 changed-file inventory is empty")
    members: dict[str, bytes] = {
        "REPO.txt": _text("dmf-pulse"),
        "BASE_BRANCH.txt": _text(BASE_BRANCH),
        "BASE_SHA.txt": _text(BASE_SHA),
        "STAGE13_BRANCH.txt": _text(BRANCH),
        "WORKTREE_HEAD.txt": _text(head),
        "REMOTE_HEAD.txt": _text(remote_head),
        "STAGE13.patch": patch,
        "PATCH_STATS.txt": _git("diff", "--stat", f"{BASE_SHA}..{head}").encode("utf-8"),
        "CHANGED_FILES.txt": _text("\n".join(changed)),
        "SOL_REVIEW_INSTRUCTIONS.md": _review_instructions(head),
    }
    root_evidence = {
        "IMPLEMENTATION_RESULT.md": "evidence/tickets/PRC-013/IMPLEMENTATION_RESULT.md",
        "KNOWN_LIMITATIONS.md": "evidence/tickets/PRC-013/KNOWN_LIMITATIONS.md",
        "TEST_RESULTS.md": "evidence/tickets/PRC-013/TEST_RESULTS.md",
        "VALIDATION_STATUS.md": "evidence/tickets/PRC-013/VALIDATION_STATUS.md",
    }
    for member, relative in root_evidence.items():
        members[member] = (ROOT / relative).read_bytes()
    for relative in changed:
        path = ROOT / relative
        if path.is_file():
            members[f"repository/{PurePosixPath(relative).as_posix()}"] = path.read_bytes()
    authority_files = (
        "specs/manifests/authority_manifest.json",
        "specs/approved/DMFP-11_PRICE_CHANGE_AND_TEAM_VALUE_MODEL.txt",
        "specs/approved/DMFP-19_CODEX_IMPLEMENTATION_ROADMAP_AND_ACCEPTANCE_TESTS.txt",
        "specs/approved/DMFP-20_ASSUMPTIONS_DECISIONS_AND_OPEN_QUESTIONS.txt",
    )
    for relative in authority_files:
        members[f"authority/{relative}"] = (ROOT / relative).read_bytes()
    return members


def _write_archive(members: dict[str, bytes]) -> None:
    if ZIP_PATH.exists() or SHA_PATH.exists():
        raise RuntimeError("refusing to overwrite an existing Stage-13 review ZIP or SHA file")
    manifest = "".join(
        f"{_sha256(data)}  {name}\n" for name, data in sorted(members.items())
    ).encode("utf-8")
    complete = {**members, "PACK_FILE_SHA256.txt": manifest}
    with zipfile.ZipFile(
        ZIP_PATH,
        mode="x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name, data in sorted(complete.items()):
            if not _safe_member(name):
                raise RuntimeError(f"unsafe review member path: {name}")
            info = zipfile.ZipInfo(name, FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    digest = _sha256(ZIP_PATH.read_bytes())
    SHA_PATH.write_text(f"{digest}  {ZIP_PATH.name}\n", encoding="ascii", newline="\n")


def _verify_archive() -> dict[str, object]:
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        names = tuple(archive.namelist())
        if archive.testzip() is not None:
            raise RuntimeError("ZIP CRC integrity failed")
        if len(names) != len(set(names)) or any(not _safe_member(name) for name in names):
            raise RuntimeError("ZIP contains duplicate or unsafe member paths")
        manifest_lines = archive.read("PACK_FILE_SHA256.txt").decode("utf-8").splitlines()
        expected: dict[str, str] = {}
        for line in manifest_lines:
            digest, name = line.split("  ", maxsplit=1)
            expected[name] = digest
        actual_names = set(names) - {"PACK_FILE_SHA256.txt"}
        if set(expected) != actual_names:
            raise RuntimeError("PACK_FILE_SHA256 inventory differs from ZIP members")
        for name, digest in expected.items():
            if _sha256(archive.read(name)) != digest:
                raise RuntimeError(f"review member hash mismatch: {name}")
        required = {
            "STAGE13.patch",
            "IMPLEMENTATION_RESULT.md",
            "KNOWN_LIMITATIONS.md",
            "TEST_RESULTS.md",
            "VALIDATION_STATUS.md",
        }
        if not required <= set(names) or not archive.read("STAGE13.patch"):
            raise RuntimeError("required review material is absent or empty")
        prefixes = (
            "repository/src/dmf_pulse/prices/",
            "repository/tests/unit/prices/",
            "repository/fixtures/prices/",
            "repository/evidence/tickets/PRC-013/",
        )
        if any(not any(name.startswith(prefix) for name in names) for prefix in prefixes):
            raise RuntimeError("review archive omits production, test, fixture or evidence content")
    declared = SHA_PATH.read_text(encoding="ascii").split()[0]
    actual = _sha256(ZIP_PATH.read_bytes())
    if declared != actual:
        raise RuntimeError("detached ZIP SHA-256 does not match")
    return {
        "integrity": "PASS",
        "member_count": len(names),
        "sha256": actual,
        "size_bytes": ZIP_PATH.stat().st_size,
        "zip": str(ZIP_PATH),
        "sha_file": str(SHA_PATH),
    }


def main() -> None:
    branch = _git("branch", "--show-current").strip()
    head = _git("rev-parse", "HEAD").strip()
    remote_head = _git("rev-parse", REMOTE_REF).strip()
    parents = _git("rev-list", "--parents", "-n", "1", "HEAD").split()
    if branch != BRANCH or head != remote_head:
        raise RuntimeError("review pack requires the pushed Stage-13 branch with remote equality")
    if len(parents) != 2 or parents[1] != BASE_SHA:
        raise RuntimeError("Stage-13 commit must be directly parented by the immutable base")
    if _git("status", "--porcelain", "--untracked-files=all").strip():
        raise RuntimeError("review pack requires a clean tracked/untracked worktree")
    members = _collect_members(head, remote_head)
    _write_archive(members)
    print(json.dumps(_verify_archive(), sort_keys=True))


if __name__ == "__main__":
    main()
