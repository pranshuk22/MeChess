"""TypeScript types from the API's OpenAPI schema (the contract), without extra dependencies.
Usage: PYTHONPATH=. python tools/gen_ts_types.py frontend/src/api/schema.ts   (a unit test fails when the checked-in file is out of date)"""
import json
import sys
import tempfile
from pathlib import Path

from chessme.app.config import AppConfig
from chessme.app.main import create_app


def ts(s: dict) -> str:
    if "$ref" in s:
        return s["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in s or "oneOf" in s:
        parts = [ts(x) for x in s.get("anyOf") or s.get("oneOf")]
        return " | ".join(dict.fromkeys(parts))
    t = s.get("type")
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        inner = ts(s.get("items", {}))
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if t == "object":
        return "Record<string, unknown>"
    return "unknown"


def render(spec: dict) -> str:
    out = ["// Generated from the API's OpenAPI schema by tools/gen_ts_types.py: do not edit.", ""]
    for name, s in sorted(spec["components"]["schemas"].items()):
        if name in ("HTTPValidationError", "ValidationError"):
            continue
        req = set(s.get("required", []))
        out.append(f"export interface {name} {{")
        for k, v in s.get("properties", {}).items():
            out.append(f"  {k}{'' if k in req else '?'}: {ts(v)};")
        out.append("}\n")
    return "\n".join(out)


def build() -> str:
    return render(create_app(AppConfig(data_dir=tempfile.mkdtemp()), static=False).openapi())


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(build())
    print("wrote", sys.argv[1])
