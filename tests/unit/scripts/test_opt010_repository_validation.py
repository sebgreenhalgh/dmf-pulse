from pathlib import Path


def test_opt010_manifest_is_preferred_by_repository_validation() -> None:
    source = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    assert 'evidence/tickets/OPT-010/current_manifest.json' in source
    assert "opt010_path.is_file()" in source
