"""Strict installed specification and authority-manifest validation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA256 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^\d+\.\d+(?:\.\d+)?(?:\s|$)")
APPROVED_DMFP04 = "DMFP-04_DATA_SOURCES_MARKETS_APIS_AND_LICENSING_ZERO_COST_v1.0.txt"
FPL004_FROZEN_INPUTS = {
    "fixtures/manifest.json": "a59443aae90ff6f030a39c02d14fc90e3ee2f64b5eb1e2a8cb527224c48f278b",
    "public_contracts/provider_snapshot_result.schema.json": (
        "53ab2f4e350d06c9b36c4e450447c907efcd4dcff3b9eb8707bd3c13794839de"
    ),
    "public_contracts/quality_report.schema.json": (
        "b8110e58a28cf562d21ae6674c95d52398b200191d145ca9d7ef0bf48ae8cd5e"
    ),
    "public_contracts/rights_decision.schema.json": (
        "dffa2b0dd6dbbdc7a280b91e8753274bcc58c9fcc2e63421e5864409ac8ac33c"
    ),
    "public_contracts/source_bundle_summary.schema.json": (
        "aec43210bee973712b21b45244db0bf4d2d00812b08b74e05a4000f395bfe679"
    ),
}
ODD005_FROZEN_INPUTS = {
    "fixtures/odds/ODD-005/manifest.json": (
        "b02bb6d02d6454fb39cb79170cc63b5e21e19a639623151a3d11edf3fe564f96"
    ),
    "public_contracts/market_observation.schema.json": (
        "be1e753ad192368fbd8a2b82383cd86e07be2104ba5595e1ea81b5581144f217"
    ),
    "public_contracts/market_query_result.schema.json": (
        "24b5268c4e22a2b99ac7eefc4073045f2f95a71071556c74e3394a7472aafa46"
    ),
    "public_contracts/odds_ingestion_result.schema.json": (
        "4b64765a95b3ce05ec4f0170baa069f871aec98c170232c1e97a6d029f7014d3"
    ),
    "public_contracts/provider_failure.schema.json": (
        "3e6cc5975ed408e3fc027887f1b0aff834b2ccbae381679798e957f56856854b"
    ),
    "public_contracts/quota_state.schema.json": (
        "d4510bda339b0cb8992305daff9794f681735f281840623175a7b96739df79c9"
    ),
    "tickets/ODD-005/ACCEPTANCE.md": (
        "5dd3700f0fe2ee8b1c02aa4668ee8a1154166b13a0f84c7564d59e0aa48399d0"
    ),
    "tickets/ODD-005/ticket.yaml": (
        "2f21febe234cb36cf5e031c56ff0a52b665f564a3239a0ed6c258a803590243c"
    ),
    "fixtures/odds/ODD-005/expected_outputs/as_of_2026-08-20T12-05-00Z.json": (
        "015a3180323a06aa9a09e99ffb90c00a1e411d819a3c51d1ac927843086ede73"
    ),
    "fixtures/odds/ODD-005/expected_outputs/changed_quote.json": (
        "09408d93ee5051899bf2b5ab9b3d6e230e4100ca577edca516385ff35105b3a6"
    ),
    "fixtures/odds/ODD-005/expected_outputs/controlled_live_refusal.json": (
        "4ad725025a2c88f66a8b3e60d9ed82167af3f0a68892769f26d3811d0b17286a"
    ),
    "fixtures/odds/ODD-005/expected_outputs/happy_path.json": (
        "05d16722d6027822d3e03bff3cdeb56bcf475600b033c18820e4d1f027b619d7"
    ),
    "fixtures/odds/ODD-005/expected_outputs/incomplete_book.json": (
        "584e2a60ccaf4876f979510b7866a37ee27357e487f8fc48c87f6a181bf6ca37"
    ),
}
NRM006_FROZEN_INPUTS = {
    "tickets/NRM-006/ticket.yaml": (
        "932cc44fe23c92b3ac01d027b9eb1d768fe7797cf1b2a0cf8148575e9bc16f0a",
        3363,
    ),
    "tickets/NRM-006/ACCEPTANCE.md": (
        "3b15b46472b9b2ee73abbb69f5ce481ec51132c96ae56435ed1f9f05aa8656f8",
        10572,
    ),
    "public_contracts/probability.schema.json": (
        "6a0dcfb79f5e8939dd54f889b61236783d8c4e05a4bd0272eae25599c2373f9b",
        338,
    ),
    "public_contracts/normalised_operator_market.schema.json": (
        "c2851ca0c051c61aaa404fb290f6974640b2b1453f8c5a43e8d89502d0ee21fb",
        5197,
    ),
    "public_contracts/market_consensus.schema.json": (
        "60e59a14cb5c3a9abdbac5c7b4c929c9a38993a07a0b71cdc80704517fc56ad4",
        4764,
    ),
    "public_contracts/market_normalisation_result.schema.json": (
        "b9a39f8f2a612645ddde141f8e9c8df340d65d1b1a8a4e01b42bb2f64a1eb789",
        3046,
    ),
    "fixtures/odds/NRM-006/manifest.json": (
        "a63bd28ef7fcea90c56697ee0e77dc28ec10f63b53bdd794d21aa84815d85d23",
        3518,
    ),
    "fixtures/odds/NRM-006/expected_outputs/balanced_book.json": (
        "148a7d2d8af16d62f87fe72d37c557ebe21c8bde85d4a7a8d07a8d320daf058e",
        1144,
    ),
    "fixtures/odds/NRM-006/expected_outputs/duplicate_outcome_same_payload.json": (
        "18afaec209296e018fa63ece08c6201fb5c2c9666135c2f99cc7f09c92b13dfd",
        101,
    ),
    "fixtures/odds/NRM-006/expected_outputs/future_mapping_canaries.json": (
        "ac17153205e345694b883e1d9dfe7e80351299a3bfe5c457bd3935aa714cfc89",
        165,
    ),
    "fixtures/odds/NRM-006/expected_outputs/happy_path_consensus.json": (
        "7b26a39f14b497d2d68a4e063be5feba1dd8e974214251c2136745ef148a7a31",
        3127,
    ),
    "fixtures/odds/NRM-006/expected_outputs/heavy_favourite.json": (
        "36a15135519b9223a04fb6df84df8950005fe32cf61c7839e3e7aa55e549237c",
        1147,
    ),
    "fixtures/odds/NRM-006/expected_outputs/high_overround.json": (
        "159261037ef45b93fc54743572dee28ace007b223df162782d66a1c9cf1128b8",
        1145,
    ),
    "fixtures/odds/NRM-006/expected_outputs/incomplete_book.json": (
        "804eec074eab35e3da8eed245508b5a306948eb2ca98791f03b60c53d6ee5640",
        473,
    ),
    "fixtures/odds/NRM-006/expected_outputs/processing_crosses_cutoff.json": (
        "638f01644ec20302cfab2749fff4df5d22179174d7f6e7aedbb554f0f4290f9a",
        337,
    ),
    "fixtures/odds/NRM-006/expected_outputs/rate_limit_retry.json": (
        "72431b449f943b3980cea059a98201c92e38b4f9f315de245b3aa1bcd0291fd6",
        130,
    ),
    "fixtures/odds/NRM-006/expected_outputs/same_value_reobservation.json": (
        "e78f4a350c511137b74df1e06806e6ff79ceeb82557b298d304fcbdf85393d95",
        145,
    ),
    "fixtures/odds/NRM-006/expected_outputs/stale_mixed_books.json": (
        "abeaa6958631527a6323ad7ad0f12ed4695bcefe1ae115aeece417aee1e28315",
        2303,
    ),
}
NRM006_FIXTURE_ENTRIES = {
    "fixtures/odds/NRM-006/balanced_book.json": (
        "c04738977d654f1a9a62f2d9b225d1690feaef54f0ae80324ccec6bdcda6d600",
        236,
    ),
    "fixtures/odds/NRM-006/duplicate_outcome_same_payload.json": (
        "ba9891d639e728a8b9de258798b1aae947ae48b4e71fdbeb8949fdc210f0378d",
        453,
    ),
    "fixtures/odds/NRM-006/future_mapping_canaries.json": (
        "471dd13ac95f27f0e34b6352e50253ea5139bdbc1b202ba4c43278282f217b7c",
        425,
    ),
    "fixtures/odds/NRM-006/happy_path_market_query.json": (
        "ec556ddd6edf2f57f1489fb1c7641fb4cca244c88438c879e353e84dc761eafa",
        4434,
    ),
    "fixtures/odds/NRM-006/heavy_favourite.json": (
        "568426cc222f4ab9ab259786e861f4d4f54d23787a17c8b127e595a6e17da63f",
        239,
    ),
    "fixtures/odds/NRM-006/high_overround.json": (
        "f21e20f565703a212f5580df584a8c57b26bbd384d75ea222ada84e40d320d1e",
        237,
    ),
    "fixtures/odds/NRM-006/incomplete_book.json": (
        "20f22c958c19949a786a009d17386687abf737e08c288081c76461b8d2d263f9",
        218,
    ),
    "fixtures/odds/NRM-006/normalisation_policy.json": (
        "201a3450482287b6e9a7929bc25f2c97375d1eccf67b239462644ae983242f18",
        1186,
    ),
    "fixtures/odds/NRM-006/processing_crosses_cutoff.json": (
        "e70a03b0d1d3195ae83a97ce2671d94abb15b4765e34bb210a5cbb33a8aba715",
        340,
    ),
    "fixtures/odds/NRM-006/rate_limit_retry.json": (
        "f5e85faa12fd1655f70b405c3ddd0cc801edca27c1b0607c5838af6bdeeb68e6",
        540,
    ),
    "fixtures/odds/NRM-006/same_value_reobservation.json": (
        "b92d987a289a0ac91b97be2e108c6f97b104c7b836f4d2b88686f8cde9702283",
        449,
    ),
    "fixtures/odds/NRM-006/stale_mixed_books.json": (
        "935fef14f59f47cd8a547db4a5773c0f13bf1c8178f11f06d4d09e1820ada4c7",
        4434,
    ),
}
NRM006_ORACLE_PATHS = (
    "expected_outputs/balanced_book.json",
    "expected_outputs/duplicate_outcome_same_payload.json",
    "expected_outputs/future_mapping_canaries.json",
    "expected_outputs/happy_path_consensus.json",
    "expected_outputs/heavy_favourite.json",
    "expected_outputs/high_overround.json",
    "expected_outputs/incomplete_book.json",
    "expected_outputs/processing_crosses_cutoff.json",
    "expected_outputs/rate_limit_retry.json",
    "expected_outputs/same_value_reobservation.json",
    "expected_outputs/stale_mixed_books.json",
)


class SpecValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("installed specification manifests are invalid")
        self.errors = tuple(errors)

    def as_error_object(self) -> dict[str, object]:
        return {
            "error": {
                "code": "SPEC_MANIFEST_INVALID",
                "details": list(self.errors),
                "message": str(self),
            },
            "ok": False,
        }


class FrozenInputValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("FPL-004 frozen inputs are invalid")
        self.errors = tuple(errors)


class OddFrozenInputValidationError(FrozenInputValidationError):
    def __init__(self, errors: list[str]) -> None:
        ValueError.__init__(self, "ODD-005 frozen inputs are invalid")
        self.errors = tuple(errors)


class NrmFrozenInputValidationError(FrozenInputValidationError):
    def __init__(self, errors: list[str]) -> None:
        ValueError.__init__(self, "NRM-006 frozen inputs are invalid")
        self.errors = tuple(errors)


def validate_fpl004_frozen_inputs(root: Path) -> dict[str, object]:
    """Verify pack-derived fixtures and public contracts against pinned digests."""

    root = root.resolve()
    errors: list[str] = []
    actual: dict[str, str] = {}
    for relative, expected in FPL004_FROZEN_INPUTS.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            errors.append(f"{relative}: missing or non-regular frozen input")
            continue
        digest = _digest(path)
        actual[relative] = digest
        if digest != expected:
            errors.append(f"{relative}: frozen SHA-256 mismatch")
    if errors:
        raise FrozenInputValidationError(errors)
    return {
        "file_count": len(actual),
        "files": dict(sorted(actual.items())),
        "ok": True,
    }


def validate_odd005_frozen_inputs(root: Path) -> dict[str, object]:
    """Verify every Pack 1.1 fixture, schema, and ticket input pinned by ODD-005."""

    root = root.resolve()
    errors: list[str] = []
    actual: dict[str, str] = {}
    for relative, expected in ODD005_FROZEN_INPUTS.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            errors.append(f"{relative}: missing or non-regular frozen input")
            continue
        digest = _digest(path)
        actual[relative] = digest
        if digest != expected:
            errors.append(f"{relative}: frozen SHA-256 mismatch")
    fixture_actual: dict[str, str] = {}
    manifest_path = root / "fixtures/odds/ODD-005/manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"fixtures/odds/ODD-005/manifest.json: invalid: {type(exc).__name__}")
        manifest = {}
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or manifest.get("manifest_version") != "1.0.0"
        or manifest.get("pack_id") != "ODD-005"
        or manifest.get("fixture_count") != 13
        or not isinstance(entries, list)
        or len(entries) != 13
    ):
        errors.append("fixtures/odds/ODD-005/manifest.json: invalid frozen envelope")
        entries = []
    seen_paths: set[str] = set()
    required_entry_keys = {
        "bytes",
        "path",
        "purpose",
        "rights_profile",
        "sha256",
        "synthetic",
    }
    fixture_root = (root / "fixtures/odds/ODD-005").resolve()
    for index, entry in enumerate(entries):
        label = f"fixtures/odds/ODD-005/manifest.json entry {index + 1}"
        if not isinstance(entry, dict) or set(entry) != required_entry_keys:
            errors.append(f"{label}: invalid keys")
            continue
        raw_relative = entry.get("path")
        expected_sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if (
            not isinstance(raw_relative, str)
            or not raw_relative.startswith("fixtures/odds/ODD-005/")
            or "\\" in raw_relative
            or raw_relative.startswith("/")
            or ".." in Path(raw_relative).parts
            or raw_relative in seen_paths
            or not isinstance(expected_sha, str)
            or SHA256.fullmatch(expected_sha) is None
            or isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
            or entry.get("synthetic") is not True
            or entry.get("rights_profile") != "synthetic_the_odds_api_v1"
            or entry.get("purpose") != "ODD-005 deterministic synthetic provider-shaped fixture"
        ):
            errors.append(f"{label}: invalid frozen entry")
            continue
        relative = raw_relative
        seen_paths.add(relative)
        candidate = root / relative
        try:
            candidate.resolve().relative_to(fixture_root)
        except ValueError:
            errors.append(f"{relative}: fixture path escapes its frozen root")
            continue
        if candidate.is_symlink() or not candidate.is_file():
            errors.append(f"{relative}: missing or non-regular frozen fixture")
            continue
        digest = _digest(candidate)
        fixture_actual[relative] = digest
        if candidate.stat().st_size != expected_bytes:
            errors.append(f"{relative}: frozen byte-size mismatch")
        if digest != expected_sha:
            errors.append(f"{relative}: frozen SHA-256 mismatch")
    discovered = {
        path.relative_to(root).as_posix()
        for path in fixture_root.rglob("*")
        if path.is_file()
        and path.name != "manifest.json"
        and "expected_outputs" not in path.relative_to(fixture_root).parts
    }
    if discovered != seen_paths:
        errors.append("fixtures/odds/ODD-005/manifest.json: fixture inventory mismatch")
    if errors:
        raise OddFrozenInputValidationError(errors)
    return {
        "file_count": len(actual),
        "files": dict(sorted(actual.items())),
        "fixture_entry_count": len(fixture_actual),
        "fixture_files": dict(sorted(fixture_actual.items())),
        "ok": True,
    }


def validate_nrm006_frozen_inputs(root: Path) -> dict[str, object]:
    """Verify every installed Pack 1.1 NRM fixture, oracle, schema, and ticket byte."""

    root = root.resolve()
    errors: list[str] = []
    actual: dict[str, str] = {}
    for relative, (expected_digest, expected_bytes) in NRM006_FROZEN_INPUTS.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            errors.append(f"{relative}: missing or non-regular frozen input")
            continue
        try:
            size = path.stat().st_size
            digest = _digest(path)
        except OSError:
            errors.append(f"{relative}: unavailable frozen input")
            continue
        actual[relative] = digest
        if size != expected_bytes:
            errors.append(f"{relative}: frozen byte-size mismatch")
        if digest != expected_digest:
            errors.append(f"{relative}: frozen SHA-256 mismatch")

    fixture_root = (root / "fixtures/odds/NRM-006").resolve()
    manifest_path = fixture_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"fixtures/odds/NRM-006/manifest.json: invalid: {type(exc).__name__}")
        manifest = {}
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    oracles = manifest.get("oracles") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {"entries", "fixture_manifest_version", "generated_at", "oracles", "ticket"}
        or manifest.get("fixture_manifest_version") != "nrm-006-fixtures-v1.1"
        or manifest.get("ticket") != "NRM-006"
        or manifest.get("generated_at") != "2026-08-06T14:15:00Z"
        or not isinstance(entries, list)
        or len(entries) != len(NRM006_FIXTURE_ENTRIES)
        or not isinstance(oracles, list)
        or oracles != list(NRM006_ORACLE_PATHS)
    ):
        errors.append("fixtures/odds/NRM-006/manifest.json: invalid frozen envelope")
        entries = []
        oracles = []

    fixture_actual: dict[str, str] = {}
    seen_paths: set[str] = set()
    required_entry_keys = {"path", "rights_classification", "sha256", "synthetic"}
    for index, entry in enumerate(entries):
        label = f"fixtures/odds/NRM-006/manifest.json entry {index + 1}"
        if not isinstance(entry, dict) or set(entry) != required_entry_keys:
            errors.append(f"{label}: invalid keys")
            continue
        raw_relative = entry.get("path")
        expected = (
            NRM006_FIXTURE_ENTRIES.get(raw_relative) if isinstance(raw_relative, str) else None
        )
        if (
            not isinstance(raw_relative, str)
            or not raw_relative.startswith("fixtures/odds/NRM-006/")
            or "\\" in raw_relative
            or raw_relative.startswith("/")
            or ".." in Path(raw_relative).parts
            or raw_relative in seen_paths
            or expected is None
            or entry.get("sha256") != expected[0]
            or entry.get("synthetic") is not True
            or entry.get("rights_classification") != "SYNTHETIC_TEST"
        ):
            errors.append(f"{label}: invalid frozen entry")
            continue
        seen_paths.add(raw_relative)
        candidate = root / raw_relative
        try:
            candidate.resolve().relative_to(fixture_root)
        except (OSError, ValueError):
            errors.append(f"{raw_relative}: fixture path escapes its frozen root")
            continue
        if candidate.is_symlink() or not candidate.is_file():
            errors.append(f"{raw_relative}: missing or non-regular frozen fixture")
            continue
        try:
            size = candidate.stat().st_size
            digest = _digest(candidate)
        except OSError:
            errors.append(f"{raw_relative}: unavailable frozen fixture")
            continue
        fixture_actual[raw_relative] = digest
        if size != expected[1]:
            errors.append(f"{raw_relative}: frozen byte-size mismatch")
        if digest != expected[0]:
            errors.append(f"{raw_relative}: frozen SHA-256 mismatch")
    if seen_paths != set(NRM006_FIXTURE_ENTRIES):
        errors.append("fixtures/odds/NRM-006/manifest.json: fixture entry inventory mismatch")

    try:
        discovered_fixtures = {
            path.relative_to(root).as_posix()
            for path in fixture_root.rglob("*")
            if path.is_file()
            and path.name != "manifest.json"
            and "expected_outputs" not in path.relative_to(fixture_root).parts
        }
        discovered_oracles = {
            path.relative_to(fixture_root).as_posix()
            for path in (fixture_root / "expected_outputs").rglob("*")
            if path.is_file()
        }
    except OSError:
        discovered_fixtures = set()
        discovered_oracles = set()
        errors.append("fixtures/odds/NRM-006: frozen inventory is unavailable")
    if discovered_fixtures != set(NRM006_FIXTURE_ENTRIES):
        errors.append("fixtures/odds/NRM-006/manifest.json: fixture inventory mismatch")
    if discovered_oracles != set(NRM006_ORACLE_PATHS):
        errors.append("fixtures/odds/NRM-006/manifest.json: oracle inventory mismatch")

    if errors:
        raise NrmFrozenInputValidationError(errors)
    return {
        "file_count": len(actual),
        "files": dict(sorted(actual.items())),
        "fixture_entry_count": len(fixture_actual),
        "fixture_files": dict(sorted(fixture_actual.items())),
        "ok": True,
        "oracle_count": len(oracles),
    }


def _object(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path.as_posix()}: malformed or unavailable: {type(exc).__name__}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.as_posix()}: root must be an object")
        return {}
    return value


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def validate_specifications(root: Path) -> dict[str, object]:
    """Validate installed document bytes, decisions, and every authority reference."""

    root = root.resolve()
    manifests = root / "specs" / "manifests"
    errors: list[str] = []
    documents = _object(manifests / "document_manifest.json", errors)
    decisions = _object(manifests / "decision_manifest.json", errors)
    authority = _object(manifests / "authority_manifest.json", errors)
    stages = _object(manifests / "stage_authority_requirements.json", errors)

    document_ids: set[str] = set()
    filenames: set[str] = set()
    raw_documents = documents.get("documents")
    if not isinstance(raw_documents, list):
        errors.append("document_manifest.documents: must be an array")
        raw_documents = []
    for index, item in enumerate(raw_documents):
        label = f"document_manifest.documents[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        document_id = item.get("document_id")
        filename = item.get("filename")
        if not isinstance(document_id, str) or not document_id:
            errors.append(f"{label}: invalid document_id")
            continue
        if document_id in document_ids:
            errors.append(f"{label}: duplicate document_id {document_id}")
        document_ids.add(document_id)
        if not isinstance(filename, str) or Path(filename).name != filename:
            errors.append(f"{label}: invalid filename")
            continue
        if filename in filenames:
            errors.append(f"{label}: duplicate filename {filename}")
        filenames.add(filename)
        if document_id == "DMFP-04" and filename != APPROVED_DMFP04:
            errors.append(f"{label}: paid or obsolete DMFP-04 is forbidden")
        version = item.get("version")
        status = item.get("status")
        if not isinstance(version, str) or VERSION.match(version) is None:
            errors.append(f"{label}: malformed version")
        if not isinstance(status, str) or not status.strip():
            errors.append(f"{label}: malformed status")
        path = (
            root / "docs" / "implementation" / filename
            if document_id == "DMF-PULSE-CODEX-PLAYBOOK"
            else root / "specs" / "approved" / filename
        )
        try:
            size = path.stat().st_size
            digest = _digest(path)
        except OSError:
            errors.append(f"{label}: installed file is missing")
            continue
        if item.get("bytes") != size:
            errors.append(f"{label}: byte count mismatch")
        expected = item.get("sha256")
        if not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
            errors.append(f"{label}: malformed SHA-256")
        elif expected != digest:
            errors.append(f"{label}: SHA-256 mismatch")

    decision_ids: set[str] = set()
    raw_decisions = decisions.get("decisions")
    if not isinstance(raw_decisions, list):
        errors.append("decision_manifest.decisions: must be an array")
        raw_decisions = []
    for index, item in enumerate(raw_decisions):
        label = f"decision_manifest.decisions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        decision_id = item.get("id")
        if not isinstance(decision_id, str) or not decision_id:
            errors.append(f"{label}: invalid decision ID")
            continue
        if decision_id in decision_ids:
            errors.append(f"{label}: duplicate decision ID {decision_id}")
        decision_ids.add(decision_id)
        status = item.get("status")
        if status not in {"ACCEPTED", "ACTIVE", "PROVISIONAL", "SUPERSEDED", "REJECTED"}:
            errors.append(f"{label}: malformed status")
        source = item.get("source")
        if not isinstance(source, dict):
            errors.append(f"{label}: source must be an object")
            continue
        source_path = source.get("path")
        source_hash = source.get("document_sha256")
        if not isinstance(source_path, str) or not (root / source_path).is_file():
            errors.append(f"{label}: stale source path")
        elif not isinstance(source_hash, str) or _digest(root / source_path) != source_hash:
            errors.append(f"{label}: stale source hash")

    scope_map: dict[str, tuple[set[str], set[str]]] = {}
    raw_scopes = authority.get("scopes")
    if not isinstance(raw_scopes, list):
        errors.append("authority_manifest.scopes: must be an array")
        raw_scopes = []
    for index, item in enumerate(raw_scopes):
        label = f"authority_manifest.scopes[{index}]"
        if not isinstance(item, dict) or not isinstance(item.get("scope"), str):
            errors.append(f"{label}: malformed scope")
            continue
        scope = str(item["scope"])
        if scope in scope_map:
            errors.append(f"{label}: duplicate scope {scope}")
        scope_documents = item.get("documents")
        scope_decisions = item.get("decisions")
        if not isinstance(scope_documents, list) or not all(
            isinstance(value, str) for value in scope_documents
        ):
            errors.append(f"{label}: documents must be string IDs")
            scope_documents = []
        if not isinstance(scope_decisions, list) or not all(
            isinstance(value, str) for value in scope_decisions
        ):
            errors.append(f"{label}: decisions must be string IDs")
            scope_decisions = []
        missing_documents = set(scope_documents) - document_ids
        missing_decisions = set(scope_decisions) - decision_ids
        if missing_documents:
            errors.append(f"{label}: stale documents {sorted(missing_documents)}")
        if missing_decisions:
            errors.append(f"{label}: stale decisions {sorted(missing_decisions)}")
        scope_map[scope] = (set(scope_documents), set(scope_decisions))

    stage_map = stages.get("required_scopes")
    if not isinstance(stage_map, dict):
        errors.append("stage_authority_requirements.stages: must be an object")
    else:
        for scope, requirements in stage_map.items():
            if scope not in scope_map or not isinstance(requirements, dict):
                errors.append(f"stage_authority_requirements: stale scope {scope}")
                continue
            expected_documents, expected_decisions = scope_map[scope]
            if set(requirements.get("documents", [])) != expected_documents:
                errors.append(f"stage_authority_requirements: {scope} document mismatch")
            if set(requirements.get("decisions", [])) != expected_decisions:
                errors.append(f"stage_authority_requirements: {scope} decision mismatch")

    if "A4-FPL-ingestion" not in scope_map:
        errors.append("authority_manifest: A4-FPL-ingestion scope is missing")
    if (
        root / "tickets/ODD-005/ticket.yaml"
    ).is_file() and "A5-odds-manual-import" not in scope_map:
        errors.append("authority_manifest: A5-odds-manual-import scope is missing")
    if (root / "tickets/NRM-006/ticket.yaml").is_file() and "A6-normalisation" not in scope_map:
        errors.append("authority_manifest: A6-normalisation scope is missing")
    if errors:
        raise SpecValidationError(errors)
    return {
        "decision_count": len(decision_ids),
        "document_count": len(document_ids),
        "ok": True,
        "scope_count": len(scope_map),
    }


__all__ = [
    "FPL004_FROZEN_INPUTS",
    "NRM006_FIXTURE_ENTRIES",
    "NRM006_FROZEN_INPUTS",
    "NRM006_ORACLE_PATHS",
    "ODD005_FROZEN_INPUTS",
    "FrozenInputValidationError",
    "NrmFrozenInputValidationError",
    "OddFrozenInputValidationError",
    "SpecValidationError",
    "validate_fpl004_frozen_inputs",
    "validate_nrm006_frozen_inputs",
    "validate_odd005_frozen_inputs",
    "validate_specifications",
]
