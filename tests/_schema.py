"""A minimal JSON Schema validator for the tests, and the packaged catalog schema.

Only the keywords the committed catalog schema uses, so the tests need no new
dependency; test_schema_uses_only_supported_keywords (tests/test_catalog.py)
keeps it honest. Shared by the catalog and lifecycle tests.
"""

import json
import re

from skilldeck.catalog import catalog_schema_text

SUPPORTED_KEYWORDS = {
    "$schema",
    "title",
    "description",
    "$defs",
    "$ref",
    "type",
    "const",
    "required",
    "properties",
    "additionalProperties",
    "oneOf",
    "items",
    "pattern",
    "minLength",
    "maxLength",
    "minItems",
    "uniqueItems",
}
_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "null": lambda v: v is None,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def catalog_schema():
    return json.loads(catalog_schema_text())


def schema_errors(instance, schema=None, *, exact=False):
    """Every way ``instance`` breaks ``schema``; with ``exact``, also any
    object property the schema does not describe."""
    root = schema or catalog_schema()

    def check(value, node, path, exact):
        errors: list[str] = []
        if "$ref" in node:
            # the schema's $ref siblings are only annotations, so merging the
            # target in is exact here (and lets ``exact`` see its properties)
            target = root["$defs"][node["$ref"].removeprefix("#/$defs/")]
            node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        if "type" in node:
            types = node["type"] if isinstance(node["type"], list) else [node["type"]]
            if not any(_TYPES[t](value) for t in types):
                return [f"{path}: {value!r} is not of type {types}"]
        if "const" in node and (
            value != node["const"] or type(value) is not type(node["const"])
        ):
            errors.append(f"{path}: {value!r} is not {node['const']!r}")
        if "oneOf" in node:
            # branches only constrain; ``exact`` is the enclosing node's job
            matches = [
                not check(value, branch, path, False) for branch in node["oneOf"]
            ]
            if matches.count(True) != 1:
                errors.append(f"{path}: matches {matches.count(True)} of oneOf")
        if isinstance(value, str):
            if len(value) < node.get("minLength", 0):
                errors.append(f"{path}: too short")
            if len(value) > node.get("maxLength", len(value)):
                errors.append(f"{path}: too long")
            if "pattern" in node and not re.search(node["pattern"], value):
                errors.append(f"{path}: {value!r} does not match {node['pattern']}")
        if isinstance(value, list):
            if len(value) < node.get("minItems", 0):
                errors.append(f"{path}: too few items")
            if node.get("uniqueItems") and len(set(map(json.dumps, value))) != len(
                value
            ):
                errors.append(f"{path}: items are not unique")
            if "items" in node:
                for index, item in enumerate(value):
                    errors += check(item, node["items"], f"{path}[{index}]", exact)
        if isinstance(value, dict):
            for key in node.get("required", []):
                if key not in value:
                    errors.append(f"{path}: missing {key}")
            properties = node.get("properties", {})
            for key, item in value.items():
                if key in properties:
                    errors += check(item, properties[key], f"{path}.{key}", exact)
                elif "additionalProperties" in node:
                    extra = node["additionalProperties"]
                    errors += check(item, extra, f"{path}.{key}", exact)
                elif exact:
                    errors.append(f"{path}: undocumented property {key}")
        return errors

    return check(instance, root, "$", exact)


def schema_nodes(node, *, branches=True):
    """``node`` and every schema below it; ``branches``: including oneOf's."""
    yield node
    children = [
        *node.get("properties", {}).values(),
        *node.get("$defs", {}).values(),
    ]
    for key in ("items", "additionalProperties"):
        if isinstance(node.get(key), dict):
            children.append(node[key])
    if branches:
        children += node.get("oneOf", [])
    for child in children:
        yield from schema_nodes(child, branches=branches)
