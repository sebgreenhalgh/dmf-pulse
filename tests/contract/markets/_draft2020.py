"""Small offline Draft 2020-12 validator for the frozen NRM contract fixtures."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID


class SchemaValidationError(ValueError):
    """A JSON instance does not satisfy a frozen Draft 2020-12 schema."""


def _type_matches(instance: object, schema_type: str) -> bool:
    if schema_type == "null":
        return instance is None
    if schema_type == "object":
        return isinstance(instance, Mapping)
    if schema_type == "array":
        return isinstance(instance, list)
    if schema_type == "string":
        return isinstance(instance, str)
    if schema_type == "boolean":
        return isinstance(instance, bool)
    if schema_type == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if schema_type == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    raise SchemaValidationError(f"unsupported schema type: {schema_type}")


def _format_valid(instance: object, format_name: str) -> bool:
    if not isinstance(instance, str):
        return True
    if format_name == "uuid":
        try:
            UUID(instance)
        except ValueError:
            return False
        return True
    if format_name == "date-time":
        try:
            parsed = datetime.fromisoformat(
                instance[:-1] + "+00:00" if instance.endswith("Z") else instance
            )
        except ValueError:
            return False
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    raise SchemaValidationError(f"unsupported schema format: {format_name}")


def validate_instance(
    instance: object,
    schema: object,
    *,
    registry: Mapping[str, object],
    path: str = "$",
) -> None:
    """Validate the frozen schemas' Draft 2020-12 subset, including references."""

    if schema is True:
        return
    if schema is False:
        raise SchemaValidationError(f"{path}: false schema")
    if not isinstance(schema, Mapping):
        raise SchemaValidationError(f"{path}: schema must be a mapping or boolean")

    if "$ref" in schema:
        reference = str(schema["$ref"]).rsplit("/", 1)[-1]
        try:
            target = registry[reference]
        except KeyError as exc:
            raise SchemaValidationError(f"{path}: unknown reference {reference}") from exc
        validate_instance(instance, target, registry=registry, path=path)
        return

    if "const" in schema and instance != schema["const"]:
        raise SchemaValidationError(f"{path}: const mismatch")
    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaValidationError(f"{path}: enum mismatch")

    if "anyOf" in schema:
        errors: list[SchemaValidationError] = []
        for candidate in schema["anyOf"]:
            try:
                validate_instance(instance, candidate, registry=registry, path=path)
                break
            except SchemaValidationError as exc:
                errors.append(exc)
        else:
            raise SchemaValidationError(f"{path}: anyOf failed") from errors[-1]

    for candidate in schema.get("allOf", ()):
        validate_instance(instance, candidate, registry=registry, path=path)

    condition = schema.get("if")
    if condition is not None:
        try:
            validate_instance(instance, condition, registry=registry, path=path)
        except SchemaValidationError:
            pass
        else:
            if "then" in schema:
                validate_instance(instance, schema["then"], registry=registry, path=path)

    schema_type = schema.get("type")
    if schema_type is not None:
        accepted_types = (schema_type,) if isinstance(schema_type, str) else tuple(schema_type)
        if not any(_type_matches(instance, item) for item in accepted_types):
            raise SchemaValidationError(f"{path}: type mismatch")

    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            raise SchemaValidationError(f"{path}: minLength")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(str(pattern), instance) is None:
            raise SchemaValidationError(f"{path}: pattern")
        if "format" in schema and not _format_valid(instance, str(schema["format"])):
            raise SchemaValidationError(f"{path}: format")

    if isinstance(instance, Mapping):
        required = schema.get("required", ())
        for name in required:
            if name not in instance:
                raise SchemaValidationError(f"{path}: required {name}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        if additional is False:
            unknown = set(instance) - set(properties)
            if unknown:
                raise SchemaValidationError(f"{path}: additional properties {sorted(unknown)}")
        for name, child_schema in properties.items():
            if name in instance:
                validate_instance(
                    instance[name], child_schema, registry=registry, path=f"{path}.{name}"
                )

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0) or len(instance) > schema.get(
            "maxItems", len(instance)
        ):
            raise SchemaValidationError(f"{path}: item count")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in instance]
            if len(set(encoded)) != len(encoded):
                raise SchemaValidationError(f"{path}: duplicate items")
        prefix_items = schema.get("prefixItems", ())
        for index, child_schema in enumerate(prefix_items):
            if index < len(instance):
                validate_instance(
                    instance[index], child_schema, registry=registry, path=f"{path}[{index}]"
                )
        items = schema.get("items")
        if items is False and len(instance) > len(prefix_items):
            raise SchemaValidationError(f"{path}: items beyond prefixItems")
        if isinstance(items, Mapping):
            for index in range(len(prefix_items), len(instance)):
                validate_instance(
                    instance[index], items, registry=registry, path=f"{path}[{index}]"
                )
