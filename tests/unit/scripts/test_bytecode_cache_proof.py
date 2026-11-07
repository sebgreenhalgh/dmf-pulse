"""Cache removal can preserve unique source work without trusting an installed RECORD."""

import importlib.util
import marshal
import os
import sys

import pytest

from tests.unit.scripts.script_support import load_script

proof = load_script("bytecode_cache_proof")


def owned_cache(tmp_path, optimize=0):
    source = tmp_path / "owned.py"
    source.write_text("raise RuntimeError('must never execute')\n", encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    tag = str(sys.implementation.cache_tag) + (f".opt-{optimize}" if optimize else "")
    path = cache / f"owned.{tag}.pyc"
    code = compile(source.read_bytes(), str(source), "exec", dont_inherit=True, optimize=optimize)
    path.write_bytes(importlib.util.MAGIC_NUMBER + b"\0" * 12 + marshal.dumps(code))
    return source, cache, path


@pytest.mark.parametrize("optimize", [0, 1, 2])
def test_exact_recreation_is_read_only_and_does_not_execute_source(tmp_path, optimize):
    source, cache, path = owned_cache(tmp_path, optimize)
    before = source.read_bytes(), path.read_bytes()
    value = proof.prove_cache(cache)
    assert value["status"] == "PROVEN_RECREATABLE_CACHE"
    assert value["source_executed_or_bytecode_loaded"] is False
    assert value["files"][0]["optimization"] == optimize
    assert (source.read_bytes(), path.read_bytes()) == before


@pytest.mark.parametrize(
    "failure",
    [
        "source_changed",
        "trailing_body",
        "magic",
        "flags",
        "extra_file",
        "directory",
        "hardlink",
        "source_link",
    ],
)
def test_unreproducible_or_shared_or_ambiguous_cache_is_held(tmp_path, monkeypatch, failure):
    source, cache, path = owned_cache(tmp_path)
    if failure == "source_changed":
        source.write_text("changed = True\n", encoding="utf-8")
    elif failure == "trailing_body":
        path.write_bytes(path.read_bytes() + b"extra")
    elif failure == "magic":
        path.write_bytes(b"BAD!" + path.read_bytes()[4:])
    elif failure == "flags":
        path.write_bytes(path.read_bytes()[:4] + (7).to_bytes(4, "little") + path.read_bytes()[8:])
    elif failure == "extra_file":
        (cache / "unknown.txt").write_text("unique work")
    elif failure == "directory":
        (cache / "nested").mkdir()
    elif failure == "hardlink":
        os.link(path, tmp_path / "shared.pyc")
    else:
        original = proof.Path.is_symlink
        monkeypatch.setattr(
            proof.Path, "is_symlink", lambda candidate: candidate == source or original(candidate)
        )
    with pytest.raises(ValueError):
        proof.prove_cache(cache)


def test_literal_relocation_verifies_bytes_identity_and_retained_source(tmp_path):
    source, cache, _ = owned_cache(tmp_path)
    receipt = proof.prove_cache(cache)
    assert isinstance(receipt["files"][0]["device"], str)
    destination = tmp_path / "archived-cache"
    cache.rename(destination)
    proof.verify_relocated_cache(receipt, destination)
    source.write_text("changed = True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="RETAINED_SOURCE_CHANGED"):
        proof.verify_relocated_cache(receipt, destination)


def test_extra_archived_file_fails_verification(tmp_path):
    _, cache, _ = owned_cache(tmp_path)
    receipt = proof.prove_cache(cache)
    (cache / "unexpected.txt").write_text("unique")
    with pytest.raises(ValueError, match="RELOCATED_MEMBERSHIP_CHANGED"):
        proof.verify_relocated_cache(receipt, cache)
