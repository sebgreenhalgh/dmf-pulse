"""Strict safe-subset YAML loader for governed rule authoring."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from yaml.constructor import ConstructorError  # type: ignore[import-untyped]
from yaml.nodes import MappingNode, ScalarNode  # type: ignore[import-untyped]
from yaml.tokens import (  # type: ignore[import-untyped]
    AliasToken,
    AnchorToken,
    ScalarToken,
    TagToken,
)

from dmf_pulse.rules.errors import RulesValidationError

IMPLICIT_STRING_BOOLEANS = {"yes", "no", "on", "off"}
DECIMAL_LIKE = re.compile(r"^[+-]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?$")


class StrictRulesLoader(yaml.SafeLoader):  # type: ignore[misc]
    """Safe loader with duplicate keys and complex mapping keys disabled."""


def _construct_mapping(
    loader: StrictRulesLoader, node: MappingNode, deep: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        if not isinstance(key_node, ScalarNode):
            raise ConstructorError(None, None, "mapping keys must be strings", key_node.start_mark)
        if key_node.tag != "tag:yaml.org,2002:str":
            raise ConstructorError(None, None, "mapping keys must be strings", key_node.start_mark)
        key = key_node.value
        if key == "<<":
            raise ConstructorError(
                None, None, "YAML merge keys are prohibited", key_node.start_mark
            )
        if key in result:
            raise ConstructorError(None, None, "duplicate mapping key", key_node.start_mark)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictRulesLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _validate_scalar_tree(value: object, path: str = "$") -> None:
    if isinstance(value, float):
        raise RulesValidationError(
            "RULESET_YAML_FLOAT", "binary floating-point values are prohibited"
        )
    if isinstance(value, (dt.date, dt.datetime)):
        raise RulesValidationError(
            "RULESET_YAML_TIMESTAMP", "timestamps must be quoted RFC 3339 strings"
        )
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RulesValidationError("RULESET_YAML_KEY", "mapping keys must be strings")
            _validate_scalar_tree(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_scalar_tree(item, f"{path}[{index}]")
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise RulesValidationError("RULESET_YAML_SCALAR", f"unsupported YAML scalar at {path}")


def load_rules_yaml_bytes(raw: bytes) -> dict[str, Any]:
    """Parse exact source bytes under the bounded strict authoring subset."""

    if len(raw) > 1024 * 1024:
        raise RulesValidationError("RULESET_FILE_TOO_LARGE", "a rules YAML file exceeds 1 MiB")
    try:
        text = raw.decode("utf-8")
        for token in yaml.scan(text):
            if isinstance(token, (AnchorToken, AliasToken)):
                raise RulesValidationError(
                    "RULESET_YAML_ALIAS", "YAML anchors and aliases are prohibited"
                )
            if isinstance(token, TagToken):
                raise RulesValidationError("RULESET_YAML_TAG", "explicit YAML tags are prohibited")
            if isinstance(token, ScalarToken) and token.style is None:
                if token.value.casefold() in IMPLICIT_STRING_BOOLEANS:
                    raise RulesValidationError(
                        "RULESET_YAML_IMPLICIT_BOOLEAN",
                        "yes/no/on/off string values must be quoted",
                    )
                if DECIMAL_LIKE.fullmatch(token.value):
                    raise RulesValidationError(
                        "RULESET_YAML_FLOAT", "decimal rule values must be quoted strings"
                    )
        value = yaml.load(text, Loader=StrictRulesLoader)
    except RulesValidationError:
        raise
    except (UnicodeError, yaml.YAMLError) as exc:
        raise RulesValidationError(
            "RULESET_YAML_INVALID", "rules YAML failed the safe-subset parser"
        ) from exc
    if not isinstance(value, dict):
        raise RulesValidationError(
            "RULESET_YAML_MAPPING", "each rules YAML file must contain a mapping"
        )
    _validate_scalar_tree(value)
    return value


def load_rules_yaml(path: Path) -> dict[str, Any]:
    """Read one bounded UTF-8 YAML mapping under the strict authoring subset."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RulesValidationError(
            "RULESET_FILE_UNAVAILABLE", "a required rules file is unavailable"
        ) from exc
    return load_rules_yaml_bytes(raw)
