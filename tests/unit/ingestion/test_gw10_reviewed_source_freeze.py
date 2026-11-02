"""Finite source-policy extensions preserve all historical freeze boundaries."""

import ast
import hashlib
import json
import subprocess
from functools import cache

import pytest

from tests.gw10_reviewed_source_freeze_support import (
    GW10_REVIEWED_SOURCE_SHA256,
    OPR_REVIEWED_SOURCE_SHA256,
    historical_gw10_source_bytes,
    is_exact_gw10_reviewed_source,
)

pytestmark = pytest.mark.unit
PARENT = "df16ed960142086e9eab3b89a94ac08ed8900f4b"
PARENT_SHA256 = {
    "ingestion/odds/client.py": "996f134785a8f70a369688aa977cae764cadc632131f1750a4b222130efca803",
    "ingestion/odds/current.py": "f8e131d2413bcccc2b78959779f0dae0618800f188b524fd2ea5b5299c47e5a9",
    "ingestion/odds/identity.py": "0c4fd04c32bade5a447d151208d464727854cdc717b81170c94c0cbcaaa5ae2b",
    "ingestion/odds/transient.py": "e73d0b95d9f11ec47ec81e2ee05448002db2c2a276a21b1a7a2e369a04347086",
    "markets/current.py": "5e018a571ebf0bf0a33da7b8e87894f7bb31eb14b93b5b31102d586ba9924b17",
    "private_v1/horizon_markets.py": "0696abaf10f73f24d56db6e18fc52fe473b046a00708244d5fd0342e5ada6554",
}
REVIEWED_CHANGED_FUNCTIONS = {
    "ingestion/odds/client.py": {"OddsClient._unsafe_fetch"},
    "ingestion/odds/current.py": {"build_current_odds_input"},
    "ingestion/odds/identity.py": {"_require_source_rights"},
    "ingestion/odds/transient.py": {"CurrentOddsTransientService.acquire"},
    "markets/current.py": {
        "CurrentMarketCanonicalIdentityView.validate_view",
        "build_transient_current_market_identity_view",
        "current_odds_rights_sha256",
        "_require_accepted_odds_rights",
        "_identity_sets_are_exact",
        "CurrentMarketCanonicalIdentityRepository.resolve",
    },
    "private_v1/horizon_markets.py": {"_identity_view", "build_future_market_evidence"},
}
FUNCTION_COUNTS = {
    "ingestion/odds/client.py": 80,
    "ingestion/odds/current.py": 27,
    "ingestion/odds/identity.py": 34,
    "ingestion/odds/transient.py": 2,
    "markets/current.py": 56,
    "private_v1/horizon_markets.py": 12,
}


@cache
def _parent_bytes(root, relative):
    body = subprocess.check_output(
        ["git", "show", f"{PARENT}:src/dmf_pulse/{relative}"], cwd=root, timeout=30
    )
    assert hashlib.sha256(body).hexdigest() == PARENT_SHA256[relative]
    return body


def _function_nodes(module):
    result = {}

    class Functions(ast.NodeVisitor):
        def __init__(self):
            self.context = []

        def visit_ClassDef(self, node):
            self.context.append(node.name)
            self.generic_visit(node)
            self.context.pop()

        def visit_FunctionDef(self, node):
            name = ".".join([*self.context, node.name])
            assert name not in result
            result[name] = node
            self.context.append(node.name)
            self.generic_visit(node)
            self.context.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

    Functions().visit(module)
    return result


def _functions(module):
    return {
        name: ast.dump(node, include_attributes=False)
        for name, node in _function_nodes(module).items()
    }


def test_reviewed_extension_has_six_fixed_paths_and_twelve_policy_functions():
    assert (
        set(GW10_REVIEWED_SOURCE_SHA256)
        == set(PARENT_SHA256)
        == set(REVIEWED_CHANGED_FUNCTIONS)
        == set(FUNCTION_COUNTS)
    )
    assert len(GW10_REVIEWED_SOURCE_SHA256) == 6
    assert sum(map(len, REVIEWED_CHANGED_FUNCTIONS.values())) == 12
    assert sum(FUNCTION_COUNTS.values()) == 211
    assert sum(FUNCTION_COUNTS.values()) - sum(map(len, REVIEWED_CHANGED_FUNCTIONS.values())) == 199
    assert (
        hashlib.sha256(
            json.dumps(GW10_REVIEWED_SOURCE_SHA256, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == "abc829cbb5592e593b820a3add28243402fd3608b2d9b933a2a7a561780e9663"
    )


def test_all_six_historical_freeze_maps_remain_exact(repository_root):
    historical = {}
    for filename, names in (
        (
            "test_horizon_probe.py",
            ("_R8A_UNMODIFIED_SOURCE_HASHES", "_ACCEL005_QUOTA_ANNOTATION"),
        ),
        (
            "test_horizon_rights_approval.py",
            (
                "_R8B_UNMODIFIED_EXECUTABLE_HASHES",
                "_ACCEL003_REVIEWED_EXECUTABLE_EXCEPTIONS",
                "_ACCEL004_REVIEWED_EXECUTABLE_EXCEPTIONS",
                "_ACCEL005_REVIEWED_EXECUTABLE_EXCEPTIONS",
            ),
        ),
    ):
        tree = ast.parse((repository_root / "tests/unit/ingestion" / filename).read_bytes())
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in names
            ):
                assert node.targets[0].id not in historical
                historical[node.targets[0].id] = ast.literal_eval(node.value)
    assert len(historical) == 6
    assert (
        hashlib.sha256(
            json.dumps(historical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == "050ff96763ea50f51c922aea647c23c11f44866472e58a122131a826d1fb5279"
    )


@pytest.mark.parametrize("relative", tuple(PARENT_SHA256))
def test_exact_reviewed_bytes_only_and_all_legacy_function_bodies_preserved(
    repository_root, relative
):
    current = (repository_root / "src/dmf_pulse" / relative).read_bytes()
    assert is_exact_gw10_reviewed_source(relative, current)
    historical = historical_gw10_source_bytes(relative, current)
    assert historical is not None
    before = _functions(ast.parse(_parent_bytes(repository_root, relative)))
    after = _functions(ast.parse(historical))
    assert set(before) == set(after)
    assert len(before) == FUNCTION_COUNTS[relative]
    changed = {name for name in before if before[name] != after[name]}
    assert changed == REVIEWED_CHANGED_FUNCTIONS[relative]
    for name in set(before) - REVIEWED_CHANGED_FUNCTIONS[relative]:
        assert before[name] == after[name]


@pytest.mark.parametrize("relative", tuple(PARENT_SHA256))
@pytest.mark.parametrize("attack", ["comment", "extra_call", "changed_source_policy", "byte_flip"])
def test_exact_extension_rejects_mutated_bytes(repository_root, relative, attack):
    current = (repository_root / "src/dmf_pulse" / relative).read_bytes()
    assert is_exact_gw10_reviewed_source(relative, current)
    if attack == "comment":
        altered = current + b"\n# Unreviewed source edit.\n"
    elif attack == "extra_call":
        altered = current + b"\nunreviewed_source_call()\n"
    elif attack == "changed_source_policy":
        assert b"private_operator" in current
        altered = current.replace(b"private_operator", b"unreviewed_operator", 1)
    else:
        altered = current[:-1] + bytes([current[-1] ^ 1])
    assert altered != current
    assert not is_exact_gw10_reviewed_source(relative, altered)


@pytest.mark.parametrize("relative", tuple(PARENT_SHA256))
def test_mutated_reviewed_digest_rejects_even_unchanged_source(
    repository_root, relative, monkeypatch
):
    current = (repository_root / "src/dmf_pulse" / relative).read_bytes()
    assert is_exact_gw10_reviewed_source(relative, current)
    monkeypatch.setitem(GW10_REVIEWED_SOURCE_SHA256, relative, "0" * 64)
    assert not is_exact_gw10_reviewed_source(relative, current)


@pytest.mark.parametrize("relative", tuple(PARENT_SHA256))
@pytest.mark.parametrize(
    "attack", ["extra_import", "function_swap", "moved_statement", "legacy_call"]
)
def test_legacy_function_and_module_mutations_never_qualify(repository_root, relative, attack):
    current = (repository_root / "src/dmf_pulse" / relative).read_bytes()
    tree = ast.parse(current)
    functions = _function_nodes(tree)
    legacy = sorted(set(functions) - REVIEWED_CHANGED_FUNCTIONS[relative])
    target = next(functions[name] for name in legacy if len(functions[name].body) > 1)
    before = _functions(tree)
    if attack == "extra_import":
        tree.body.append(ast.parse("import unreviewed_source_adapter").body[0])
    elif attack == "function_swap":
        other = next(node for node in functions.values() if node is not target)
        target.body, other.body = other.body, target.body
    elif attack == "moved_statement":
        target.body.append(target.body.pop(0))
    else:
        target.body.append(ast.parse("unreviewed_legacy_call()").body[0])
    altered = ast.unparse(tree).encode()
    assert not is_exact_gw10_reviewed_source(relative, altered)
    if attack != "extra_import":
        after = _functions(tree)
        assert any(before[name] != after[name] for name in legacy)


@pytest.mark.parametrize("relative", tuple(PARENT_SHA256))
def test_exact_extension_cannot_authorize_another_path(repository_root, relative):
    current = (repository_root / "src/dmf_pulse" / relative).read_bytes()
    assert not is_exact_gw10_reviewed_source("unreviewed/" + relative, current)
    assert not is_exact_gw10_reviewed_source("../" + relative, current)
    for other in set(PARENT_SHA256) - {relative}:
        assert not is_exact_gw10_reviewed_source(other, current)


@pytest.mark.parametrize(
    "relative",
    [
        "ingestion/odds/parser.py",
        "ingestion/current_state.py",
        "ingestion/odds/automatic_mapping.py",
        "private_v1/rolling_models.py",
        "private_v1/one_command.py",
        "private_v1/rolling.py",
    ],
)
def test_exact_extension_never_covers_unchanged_or_intentionally_evolving_other_modules(
    repository_root, relative
):
    assert not is_exact_gw10_reviewed_source(
        relative, (repository_root / "src/dmf_pulse" / relative).read_bytes()
    )


def test_opr_extension_has_one_fixed_path_and_exact_four_line_inverse(repository_root):
    assert OPR_REVIEWED_SOURCE_SHA256 == {
        "ingestion/odds/client.py": "8b3d3193ffb142bc678f4730299eebd82d3134efdf92dcfe761fa788d7c44a76"
    }
    assert (
        hashlib.sha256(
            json.dumps(OPR_REVIEWED_SOURCE_SHA256, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == "37d2e81184e17a1582458d2864ae7a3d434e845f35dd66095dede718355edda0"
    )
    current = (repository_root / "src/dmf_pulse/ingestion/odds/client.py").read_bytes()
    additions = (
        b"        on_response_headers: Callable[[int, Mapping[str, str]], None] | None = None,\n",
        b"        self._on_response_headers = on_response_headers\n",
        b"            if self._on_response_headers is not None:\n",
        b"                self._on_response_headers(response.status, headers)\n",
    )
    expected = current
    for line in additions:
        assert expected.count(line) == 1
        expected = expected.replace(line, b"", 1)
    assert (
        hashlib.sha256(expected).hexdigest()
        == GW10_REVIEWED_SOURCE_SHA256["ingestion/odds/client.py"]
    )
    assert historical_gw10_source_bytes("ingestion/odds/client.py", current) == expected
    assert historical_gw10_source_bytes("ingestion/odds/client.py", expected) == expected
    before, after = _functions(ast.parse(expected)), _functions(ast.parse(current))
    assert set(before) == set(after)
    assert {name for name in before if before[name] != after[name]} == {
        "HttpClientOddsTransport.__init__",
        "HttpClientOddsTransport._unsafe_send",
    }


@pytest.mark.parametrize(
    "digest", ["0" * 64, "8b3d3193ffb142bc678f4730299eebd82d3134efdf92dcfe761fa788d7c44a76"]
)
def test_historical_map_cannot_be_relabelled_to_authorize_opr(repository_root, monkeypatch, digest):
    current = (repository_root / "src/dmf_pulse/ingestion/odds/client.py").read_bytes()
    monkeypatch.setitem(GW10_REVIEWED_SOURCE_SHA256, "ingestion/odds/client.py", digest)
    assert not is_exact_gw10_reviewed_source("ingestion/odds/client.py", current)
    assert historical_gw10_source_bytes("ingestion/odds/client.py", current) is None


@pytest.mark.parametrize(
    "attack",
    [
        "removed",
        "duplicate",
        "argument_order",
        "always_call",
        "changed_default",
        "moved_after_body",
        "other_method",
        "extra_import",
        "extra_call",
    ],
)
def test_opr_exact_inverse_rejects_every_unreviewed_hook_change(
    repository_root, monkeypatch, attack
):
    relative = "ingestion/odds/client.py"
    current = (repository_root / "src/dmf_pulse" / relative).read_bytes()
    condition = b"            if self._on_response_headers is not None:\n"
    call = b"                self._on_response_headers(response.status, headers)\n"
    guard = condition + call
    assert current.count(guard) == 1
    if attack == "removed":
        altered = current.replace(guard, b"", 1)
    elif attack == "duplicate":
        altered = current.replace(guard, guard + guard, 1)
    elif attack == "argument_order":
        altered = current.replace(
            call, b"                self._on_response_headers(headers, response.status)\n", 1
        )
    elif attack == "always_call":
        altered = current.replace(condition, b"            if True:\n", 1)
    elif attack == "changed_default":
        altered = current.replace(b"None] | None = None,", b"None] | None = True,", 1)
    elif attack == "moved_after_body":
        altered = current.replace(guard, b"", 1)
        anchor = b"            result = OddsHttpResponse(\n"
        assert altered.count(anchor) == 1
        altered = altered.replace(anchor, guard + anchor, 1)
    elif attack == "other_method":
        altered = current.replace(guard, b"", 1)
        anchor = b"        limit = load_provider_config().max_response_bytes\n"
        method = altered.index(
            b"    def _read_body(\n", altered.index(b"class HttpClientOddsTransport:")
        )
        position = altered.index(anchor, method) + len(anchor)
        moved = (
            b"        if self._on_response_headers is not None:\n"
            b"            self._on_response_headers(response.status, headers)\n"
        )
        altered = altered[:position] + moved + altered[position:]
    elif attack == "extra_import":
        altered = current + b"\nimport unreviewed_response_adapter\n"
    else:
        altered = current + b"\nunreviewed_response_call()\n"
    assert altered != current
    assert not is_exact_gw10_reviewed_source(relative, altered)
    assert historical_gw10_source_bytes(relative, altered) is None
    # Even a mistakenly updated extension-map digest cannot turn an unreviewed
    # hook position/body into the frozen historical GW10 state.
    monkeypatch.setitem(OPR_REVIEWED_SOURCE_SHA256, relative, hashlib.sha256(altered).hexdigest())
    assert not is_exact_gw10_reviewed_source(relative, altered)
    assert historical_gw10_source_bytes(relative, altered) is None


def test_opr_map_cannot_expand_to_another_path_or_digest(repository_root, monkeypatch):
    relative = "ingestion/odds/client.py"
    current = (repository_root / "src/dmf_pulse" / relative).read_bytes()
    monkeypatch.setitem(OPR_REVIEWED_SOURCE_SHA256, relative, "0" * 64)
    assert not is_exact_gw10_reviewed_source(relative, current)
    monkeypatch.setitem(OPR_REVIEWED_SOURCE_SHA256, relative, hashlib.sha256(current).hexdigest())
    monkeypatch.setitem(
        OPR_REVIEWED_SOURCE_SHA256, "unreviewed/client.py", hashlib.sha256(current).hexdigest()
    )
    assert not is_exact_gw10_reviewed_source(relative, current)
    assert not is_exact_gw10_reviewed_source("unreviewed/client.py", current)
