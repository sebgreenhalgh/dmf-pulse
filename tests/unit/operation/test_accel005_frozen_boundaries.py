"""The exact reviewed quota, new-purpose and permission seams preserve retained code."""

import ast
import copy
import hashlib
import subprocess
from functools import cache
from pathlib import Path

import pytest

from tests.accel005_legacy_freeze_support import without_accel005_permission

pytestmark = pytest.mark.unit

ROOT = Path.cwd()
FROZEN = "1e2e9d4dbf5c6af39e0c02cbd12ea487fee9e7b8"
PARENT = "f07c063b4f6e4cb8451b9189771a0410329f23f0"
IMPORT = "from dmf_pulse.ingestion.odds.private_operator import PRIVATE_OPERATOR_PROFILE_ID, require_private_operator_quota"
CLIENT_HEAD = """private_operator = self._profile.rights_profile_id == PRIVATE_OPERATOR_PROFILE_ID
if private_operator:
    if self._maximum_attempts != 1:
        raise IngestionError("RIGHTS_BLOCKED", "new-purpose Odds acquisition is single-attempt")
    require_private_operator_quota(self._profile, quota, checked_at=self._clock())
"""
CLIENT_SEND = """if private_operator:
    require_private_operator_quota(self._profile, quota, checked_at=started_at)
"""
TRANSIENT_HEAD = """if profile.rights_profile_id not in {ODDS_PRIVATE_PROFILE_ID, PRIVATE_OPERATOR_PROFILE_ID}:
    raise IngestionError("RIGHTS_BLOCKED", "unsupported current Odds source profile")
if profile.rights_profile_id == PRIVATE_OPERATOR_PROFILE_ID:
    if self._maximum_attempts != 1 or not self._require_known_quota:
        raise IngestionError("RIGHTS_BLOCKED", "new-purpose Odds requires bounded account use")
    require_private_operator_quota(profile, self._quota, checked_at=self._clock())
"""


@cache
def git_bytes(commit, name):
    return subprocess.check_output(
        [
            "git",
            "-c",
            "safe.directory=" + str(ROOT),
            "show",
            f"{commit}:src/dmf_pulse/ingestion/odds/{name}.py",
        ],
        cwd=ROOT,
        timeout=30,
    )


def dump(node):
    return ast.dump(node, include_attributes=False)


def nodes(text):
    return ast.parse(text).body


def method(tree, name):
    clsname = "OddsClient" if name == "client" else "CurrentOddsTransientService"
    cls = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == clsname]
    assert len(cls) == 1
    found = [
        node
        for node in cls[0].body
        if isinstance(node, ast.FunctionDef)
        and node.name == ("_unsafe_fetch" if name == "client" else "acquire")
    ]
    assert len(found) == 1
    return found[0]


def expected_overlay(name):
    # Build the complete expected module from immutable Wave005 bytes. Nothing
    # in the live module is removed, rewritten or accepted by a generic rule.
    frozen = git_bytes(FROZEN, name)
    assert (
        hashlib.sha256(frozen).hexdigest()
        == {
            "client": "996f134785a8f70a369688aa977cae764cadc632131f1750a4b222130efca803",
            "transient": "e73d0b95d9f11ec47ec81e2ee05448002db2c2a276a21b1a7a2e369a04347086",
        }[name]
    )
    tree = ast.parse(frozen)
    index = [
        i
        for i, node in enumerate(tree.body)
        if isinstance(node, ast.ImportFrom) and node.module == "dmf_pulse.ingestion.rights"
    ]
    assert len(index) == 1 and dump(tree.body[index[0]]) == dump(
        nodes("from dmf_pulse.ingestion.rights import require_rights")[0]
    )
    tree.body[index[0] : index[0]] = nodes(IMPORT)
    target = method(tree, name)
    if name == "client":
        assert [dump(node) for node in target.body[:2]] == [
            dump(node)
            for node in nodes(
                "config = load_provider_config()\nrequire_rights(self._profile, RightsCapability.AUTOMATED_ACCESS, checked_at=self._clock())"
            )
        ]
        loops = [node for node in target.body if isinstance(node, ast.For)]
        assert len(loops) == 1
        loop = loops[0]
        assert dump(loop.target) == dump(ast.Name(id="attempt", ctx=ast.Store()))
        assert dump(loop.iter) == dump(
            ast.parse("range(1, maximum_attempts + 1)", mode="eval").body
        )
        assert dump(loop.body[1]) == dump(nodes("started_at = self._clock()")[0])
        assert dump(loop.body[2]) == dump(
            nodes("""if started_at.tzinfo is None or started_at.utcoffset() is None:
    raise IngestionError("INTERNAL_INVARIANT", "odds client clock must be timezone-aware")
""")[0]
        )
        assert dump(loop.body[3]) == dump(nodes("self.transport_call_count += 1")[0])
        assert dump(loop.body[4]) == dump(
            nodes("response, safe_error = _send_transport(transport, attempt_request, credential)")[
                0
            ]
        )
        loop.body[3:3] = nodes(CLIENT_SEND)
        target.body[2:2] = nodes(CLIENT_HEAD)
        # OPR-001 adds only a safe response-header receipt hook. Preserve the
        # entire retained transport, including request, retry and parsing code.
        transport = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "HttpClientOddsTransport"
        )
        initializer = next(
            node
            for node in transport.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        assert [arg.arg for arg in initializer.args.kwonlyargs] == [
            "connection_factory",
            "ssl_context_factory",
            "monotonic",
        ]
        parameter = ast.parse(
            "def owned(*, on_response_headers: Callable[[int, Mapping[str, str]], None] | None = None):\n    return None\n"
        ).body[0]
        initializer.args.kwonlyargs.append(parameter.args.kwonlyargs[0])
        initializer.args.kw_defaults.append(ast.Constant(value=None))
        initializer.body.extend(nodes("self._on_response_headers = on_response_headers"))
        sender = next(
            node
            for node in transport.body
            if isinstance(node, ast.FunctionDef) and node.name == "_unsafe_send"
        )
        block = next(node for node in sender.body if isinstance(node, ast.Try))
        anchor = nodes(
            "headers = _safe_header_pairs([(name, value) for name, value in raw_headers])"
        )[0]
        positions = [i for i, node in enumerate(block.body) if dump(node) == dump(anchor)]
        assert len(positions) == 1
        block.body[positions[0] + 1 : positions[0] + 1] = nodes(
            "if self._on_response_headers is not None:\n    self._on_response_headers(response.status, headers)"
        )
    else:
        assert dump(target.body[7]) == dump(
            nodes("profile = self._profile or load_rights_profiles()[ODDS_PRIVATE_PROFILE_ID]")[0]
        )
        assert [dump(node) for node in target.body[8:10]] == [
            dump(node)
            for node in nodes(
                "require_rights(profile, RightsCapability.AUTOMATED_ACCESS, checked_at=self._clock())\nrequire_rights(profile, RightsCapability.TRANSIENT_PROCESSING, checked_at=self._clock())"
            )
        ]
        target.body[8:8] = nodes(TRANSIENT_HEAD)
    return tree


@pytest.mark.parametrize("name", ["client", "transient"])
def test_new_purpose_overlay_is_exact_complete_module(name):
    assert dump(expected_overlay(name)) == dump(
        ast.parse((ROOT / f"src/dmf_pulse/ingestion/odds/{name}.py").read_bytes())
    )


@pytest.mark.parametrize("name", ["client", "transient"])
@pytest.mark.parametrize(
    "attack",
    [
        "extra_call",
        "extra_import",
        "alias_in_reviewed_import",
        "moved_import",
        "duplicate_import",
        "altered_guard",
        "altered_quota_argument",
        "altered_error",
        "extra_call_inside_guard",
        "moved_guard",
        "duplicate_guard",
        "wrong_method",
        "altered_legacy_return",
    ],
)
def test_new_purpose_overlay_cannot_hide_unreviewed_changes(name, attack):
    wanted = expected_overlay(name)
    changed = copy.deepcopy(wanted)
    target = method(changed, name)
    index = next(
        i
        for i, node in enumerate(changed.body)
        if isinstance(node, ast.ImportFrom)
        and node.module == "dmf_pulse.ingestion.odds.private_operator"
    )
    guard_index = 3 if name == "client" else 9
    if attack == "extra_call":
        target.body.append(nodes("unreviewed_runtime_call()")[0])
    elif attack == "extra_import":
        changed.body.append(nodes("import unreviewed_module")[0])
    elif attack == "alias_in_reviewed_import":
        changed.body[index].names.append(ast.alias(name="unreviewed_alias"))
    elif attack == "moved_import":
        changed.body.insert(1, changed.body.pop(index))
    elif attack == "duplicate_import":
        changed.body.insert(index, copy.deepcopy(changed.body[index]))
    elif attack == "altered_guard":
        target.body[guard_index].test = ast.Constant(value=True)
    elif attack == "altered_quota_argument":
        calls = [
            node
            for node in ast.walk(target.body[guard_index])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "require_private_operator_quota"
        ]
        assert len(calls) == 1
        calls[0].args[1] = ast.Constant(value=None)
    elif attack == "altered_error":
        calls = [
            node
            for node in ast.walk(target.body[guard_index])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "IngestionError"
        ]
        assert len(calls) == 1
        calls[0].args[0] = ast.Constant(value="UNREVIEWED_ERROR")
    elif attack == "extra_call_inside_guard":
        target.body[guard_index].body.append(nodes("unreviewed_runtime_call()")[0])
    elif attack == "moved_guard":
        target.body.append(target.body.pop(guard_index))
    elif attack == "duplicate_guard":
        target.body.append(copy.deepcopy(target.body[guard_index]))
    elif attack == "wrong_method":
        cls = next(
            node for node in changed.body if isinstance(node, ast.ClassDef) and target in node.body
        )
        other = next(
            node for node in cls.body if isinstance(node, ast.FunctionDef) and node is not target
        )
        other.body.append(target.body.pop(guard_index))
    else:
        returns = [node for node in ast.walk(target) if isinstance(node, ast.Return)]
        assert returns
        returns[0].value = ast.Constant(value=None)
    assert dump(changed) != dump(wanted)


@pytest.mark.parametrize("attack", ["moved_after_send", "duplicate", "altered_clock", "removed"])
def test_new_purpose_pretransport_recheck_has_one_exact_location(attack):
    wanted = expected_overlay("client")
    changed = copy.deepcopy(wanted)
    loop = next(node for node in method(changed, "client").body if isinstance(node, ast.For))
    assert dump(loop.body[3]) == dump(nodes(CLIENT_SEND)[0])
    if attack == "moved_after_send":
        loop.body.insert(5, loop.body.pop(3))
    elif attack == "duplicate":
        loop.body.insert(3, copy.deepcopy(loop.body[3]))
    elif attack == "altered_clock":
        loop.body[3].body[0].value.keywords[0].value = ast.Constant(value=None)
    else:
        loop.body.pop(3)
    assert dump(changed) != dump(wanted)


@pytest.mark.parametrize("name,unions", [("client", 3), ("transient", 1)])
def test_quota_addition_is_import_and_input_annotations_only(name, unions):
    path = f"src/dmf_pulse/ingestion/odds/{name}.py"
    original = subprocess.check_output(["git", "show", f"{PARENT}:{path}"], text=True, timeout=30)

    class RemoveReviewedQuota(ast.NodeTransformer):
        def __init__(self):
            self.imports = 0
            self.unions = 0

        def visit_ImportFrom(self, node):
            if node.module == "dmf_pulse.ingestion.odds.models":
                self.imports += sum(alias.name == "QualifiedOperatorQuota" for alias in node.names)
                node.names = [
                    alias for alias in node.names if alias.name != "QualifiedOperatorQuota"
                ]
            return node

        def visit_arg(self, node):
            annotation = node.annotation
            if (
                node.arg == "quota"
                and isinstance(annotation, ast.BinOp)
                and isinstance(annotation.op, ast.BitOr)
                and isinstance(annotation.right, ast.Constant)
                and annotation.right.value is None
                and isinstance(annotation.left, ast.BinOp)
                and isinstance(annotation.left.op, ast.BitOr)
                and isinstance(annotation.left.left, ast.Name)
                and annotation.left.left.id == "QuotaState"
                and isinstance(annotation.left.right, ast.Name)
                and annotation.left.right.id == "QualifiedOperatorQuota"
            ):
                self.unions += 1
                node.annotation = ast.BinOp(
                    left=annotation.left.left, op=ast.BitOr(), right=annotation.right
                )
            return node

    visitor = RemoveReviewedQuota()
    frozen_source = git_bytes(FROZEN, name).decode("utf-8")
    current = visitor.visit(ast.parse(frozen_source))
    assert (visitor.imports, visitor.unions) == (1, unions)
    assert ast.dump(current) == ast.dump(ast.parse(original))
    moved = frozen_source.replace(
        "quota: QuotaState | QualifiedOperatorQuota | None", "quota: QuotaState | None", 1
    )
    moved += "\ndef unreviewed_runtime_union(value):\n    return value | QualifiedOperatorQuota\n"
    altered = visitor.visit(ast.parse(moved))
    assert ast.dump(altered) != ast.dump(ast.parse(original))


@pytest.mark.parametrize("name", ["team_strength_live", "team_strength_live_network"])
def test_native_permission_seam_normalizer_cannot_hide_other_changes(name):
    path = f"src/dmf_pulse/private_v1/{name}.py"
    source = Path(path).read_text(encoding="utf-8")
    original = subprocess.check_output(["git", "show", f"{PARENT}:{path}"], text=True, timeout=30)
    assert without_accel005_permission(source, path) == original
    assert without_accel005_permission(source + "\nUNREVIEWED_CONTROL = True\n", path) != original
    with pytest.raises(ValueError, match="seam changed"):
        without_accel005_permission(
            source.replace("requires_supplier_permission", "unreviewed_permission")
            if name.endswith("network")
            else source.replace("self._fpl_transport is None", "True"),
            path,
        )
