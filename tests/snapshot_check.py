#!/usr/bin/env python3
"""Holding a feed snapshot to schemas/feed.v1.json, with no package beyond Python.

A minimal JSON Schema 2020-12 checker for exactly the keywords the schema uses
(type, const, pattern, required, properties, additionalProperties: false,
items, prefixItems, minItems, maxItems, maxLength, minimum, maximum, anyOf and
local $ref), and the scan for what must never be in a snapshot (FEED-0003).

A keyword the checker does not know is an error rather than ignored, so a schema
that grows a keyword cannot pass unchecked. The smoke imports it; on its own it
checks the files it is given:

    python3 tests/snapshot_check.py build/public/feeds/*.json
"""

import json
import re
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "feed.v1.json"

KNOWN = {"$schema", "$id", "$defs", "$ref", "title", "description", "type", "const", "pattern", "required",
         "properties", "additionalProperties", "items", "prefixItems", "minItems", "maxItems", "maxLength",
         "minimum", "maximum", "anyOf"}


def _is_type(value, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool) or (
            isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    raise ValueError(f"unknown type {name}")


def _resolve(root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"only local references are read: {ref}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def errors(value, schema, root: dict = None, where: str = "$") -> list:
    """What is wrong with `value` against `schema`, one line per problem."""
    root = root if root is not None else schema
    if schema is True:
        return []
    if schema is False:
        return [f"{where}: nothing is allowed here"]
    unknown = set(schema) - KNOWN
    if unknown:
        return [f"{where}: the checker does not know {sorted(unknown)}"]
    out = []
    if "$ref" in schema:
        out += errors(value, _resolve(root, schema["$ref"]), root, where)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, n) for n in names):
            return out + [f"{where}: {json.dumps(value)[:60]} is not {names}"]
    if "const" in schema and (value != schema["const"] or type(value) is not type(schema["const"])):
        out.append(f"{where}: {value!r} is not {schema['const']!r}")
    if "anyOf" in schema and not any(not errors(value, s, root, where) for s in schema["anyOf"]):
        out.append(f"{where}: {value!r} matches none of anyOf")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{where}: {value!r} does not match {schema['pattern']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{where}: longer than {schema['maxLength']}")
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where}: {value} is below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where}: {value} is above {schema['maximum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{where}: {key} is missing")
        properties = schema.get("properties", {})
        for key, member in value.items():
            if key in properties:
                out += errors(member, properties[key], root, f"{where}.{key}")
            elif schema.get("additionalProperties", True) is False:
                out.append(f"{where}: {key} is not allowed")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{where}: more than {schema['maxItems']} items")
        prefix = schema.get("prefixItems", [])
        for i, item in enumerate(value):
            if i < len(prefix):
                out += errors(item, prefix[i], root, f"{where}[{i}]")
            elif "items" in schema:
                out += errors(item, schema["items"], root, f"{where}[{i}]")
    return out


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def check(text: str, forbidden=()) -> list:
    """Everything wrong with one snapshot's text: not JSON, against the schema,
    or holding one of the forbidden strings (ids, addresses, tokens)."""
    try:
        value = json.loads(text)
    except ValueError as error:
        return [f"not JSON: {error}"]
    problems = errors(value, load_schema())
    for needle in forbidden:
        if needle and needle in text:
            problems.append(f"holds {needle!r}, which must never leave the installation")
    return problems


def main(paths: list) -> int:
    failed = 0
    for path in paths:
        problems = check(Path(path).read_text(encoding="utf-8"))
        for problem in problems:
            print(f"{path}: {problem}")
        failed += bool(problems)
    if not failed:
        print(f"{len(paths)} snapshot(s) hold to {SCHEMA_PATH.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
