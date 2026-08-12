from pathlib import Path

SOURCE = Path(__file__).parents[3] / "src" / "dmf_pulse" / "availability" / "persistence.py"


def test_final_publication_does_not_change_all_constraint_modes() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "SET CONSTRAINTS ALL IMMEDIATE" not in source
    assert "SET CONSTRAINTS football.trg_min007f_final_output_complete IMMEDIATE" in source
    assert "SET CONSTRAINTS football.trg_min007f_final_output_complete DEFERRED" in source
