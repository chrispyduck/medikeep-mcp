"""Operation catalog built from MediKeep's OpenAPI description.

Every MediKeep REST endpoint becomes an :class:`Operation` with a short, stable,
MCP-safe name (e.g. ``read_medications`` or ``list_links__conditions_encounters``),
its parameters, and a fully-inlined JSON schema for its request body.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

HTTP_METHODS = ("get", "post", "put", "patch", "delete")
MAX_TOOL_NAME = 64
_SUFFIX_RE = re.compile(r"_api_v1_.*$")


@dataclass
class Param:
    name: str
    location: str  # "path" | "query"
    required: bool
    schema: dict[str, Any]
    description: str = ""


@dataclass
class Operation:
    name: str
    method: str
    path: str
    tag: str
    summary: str
    description: str
    operation_id: str
    params: list[Param] = field(default_factory=list)
    body_content_type: str | None = None  # json | multipart | form
    body_schema: dict[str, Any] | None = None
    body_required: bool = False
    file_fields: list[str] = field(default_factory=list)
    file_fields_multi: list[str] = field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    binary_response: bool = False
    raw_body: bool = False  # endpoint reads the raw request body (e.g. DICOM/ZIP import)

    @property
    def path_params(self) -> list[Param]:
        return [p for p in self.params if p.location == "path"]

    @property
    def query_params(self) -> list[Param]:
        return [p for p in self.params if p.location == "query"]

    @property
    def is_read_only(self) -> bool:
        return self.method == "GET"

    @property
    def is_destructive(self) -> bool:
        return self.method == "DELETE"

    def short_description(self) -> str:
        return self.summary or self.operation_id

    def signature(self) -> str:
        return f"{self.method} {self.path}"


class SchemaResolver:
    """Inline ``$ref``s and simplify FastAPI/Pydantic schemas for LLM consumption."""

    def __init__(self, components: dict[str, Any]):
        self.components = components

    def resolve(self, schema: Any, depth: int = 0, max_depth: int = 6, seen: tuple = ()) -> Any:
        if isinstance(schema, list):
            return [self.resolve(s, depth, max_depth, seen) for s in schema]
        if not isinstance(schema, dict):
            return schema
        if "$ref" in schema:
            ref_name = schema["$ref"].split("/")[-1]
            if ref_name in seen or depth >= max_depth:
                return {"type": "object", "description": f"{ref_name} (nested; see API docs)"}
            target = self.components.get(ref_name, {})
            resolved = self.resolve(target, depth + 1, max_depth, seen + (ref_name,))
            extra = {k: v for k, v in schema.items() if k != "$ref"}
            if extra:
                resolved = {**resolved, **self.resolve(extra, depth, max_depth, seen)}
            return resolved
        out: dict[str, Any] = {}
        for key, value in schema.items():
            if key == "title":
                continue
            if key in ("properties", "patternProperties", "$defs", "definitions") and isinstance(value, dict):
                out[key] = {k: self.resolve(v, depth, max_depth, seen) for k, v in value.items()}
            elif isinstance(value, (dict, list)):
                out[key] = self.resolve(value, depth, max_depth, seen)
            else:
                out[key] = value
        return _collapse_nullable(out)


def _collapse_nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Turn ``anyOf: [X, {type: null}]`` into ``X`` (+ nullable note) to save tokens."""
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        non_null = [s for s in any_of if not (isinstance(s, dict) and s.get("type") == "null")]
        if len(non_null) == 1 and len(non_null) != len(any_of):
            merged = {**non_null[0], **{k: v for k, v in schema.items() if k != "anyOf"}}
            return merged
    return schema


def _safe_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    name = re.sub(r"_{3,}", "__", name).strip("_")
    if len(name) > MAX_TOOL_NAME:
        digest = hashlib.sha1(name.encode()).hexdigest()[:6]
        name = name[: MAX_TOOL_NAME - 7] + "_" + digest
    return name


def _literal_segments(path: str) -> list[str]:
    segs = [s for s in path.split("/") if s and not s.startswith("{")]
    return [s for s in segs if s not in ("api", "v1")]


class Catalog:
    def __init__(self, spec: dict[str, Any], source: str = "bundled"):
        self.spec = spec
        self.source = source
        self.resolver = SchemaResolver(spec.get("components", {}).get("schemas", {}))
        self.operations: dict[str, Operation] = {}
        self._by_signature: dict[str, Operation] = {}
        self._by_operation_id: dict[str, Operation] = {}
        self._build()

    # ------------------------------------------------------------------ loading
    @classmethod
    def bundled(cls) -> "Catalog":
        text = resources.files("medikeep_mcp").joinpath("data/openapi.json").read_text("utf-8")
        return cls(json.loads(text), source="bundled")

    @property
    def api_version(self) -> str:
        return str(self.spec.get("info", {}).get("version", "unknown"))

    # ---------------------------------------------------------------- building
    def _build(self) -> None:
        raw: list[tuple[str, str, dict[str, Any]]] = []
        for path, item in self.spec.get("paths", {}).items():
            for method, op in item.items():
                if method in HTTP_METHODS:
                    raw.append((path, method, op))

        shorts = Counter(_SUFFIX_RE.sub("", op.get("operationId", "")) or "op" for _, _, op in raw)
        for path, method, op in raw:
            short = _SUFFIX_RE.sub("", op.get("operationId", "")) or "op"
            if shorts[short] > 1:
                short = f"{short}__{'_'.join(_literal_segments(path))}"
            name = _safe_name(short)
            base, n = name, 2
            while name in self.operations:
                name = _safe_name(f"{base}_{n}")
                n += 1
            operation = self._make_operation(name, path, method, op)
            self.operations[name] = operation
            self._by_signature[operation.signature()] = operation
            self._by_operation_id[operation.operation_id] = operation

    def _make_operation(self, name: str, path: str, method: str, op: dict[str, Any]) -> Operation:
        tags = op.get("tags") or ["general"]
        params: list[Param] = []
        for p in op.get("parameters", []):
            if p.get("in") not in ("path", "query"):
                continue
            # Internal FastAPI dependency plumbing, never meant to be set by callers.
            if p["name"] == "required_permission":
                continue
            params.append(
                Param(
                    name=p["name"],
                    location=p["in"],
                    required=bool(p.get("required", False)),
                    schema=self.resolver.resolve(p.get("schema", {}), max_depth=3),
                    description=p.get("description") or p.get("schema", {}).get("description", ""),
                )
            )

        operation = Operation(
            name=name,
            method=method.upper(),
            path=path,
            tag=tags[0],
            summary=(op.get("summary") or "").strip(),
            description=(op.get("description") or "").strip(),
            operation_id=op.get("operationId", name),
            params=params,
        )

        operation.raw_body = "raw request body" in operation.description.lower()

        body = op.get("requestBody") or {}
        content = body.get("content") or {}
        if content:
            operation.body_required = bool(body.get("required", False))
            if "application/json" in content:
                operation.body_content_type = "json"
                schema = content["application/json"].get("schema", {})
            elif "multipart/form-data" in content:
                operation.body_content_type = "multipart"
                schema = content["multipart/form-data"].get("schema", {})
            elif "application/x-www-form-urlencoded" in content:
                operation.body_content_type = "form"
                schema = content["application/x-www-form-urlencoded"].get("schema", {})
            else:
                operation.body_content_type = "json"
                schema = next(iter(content.values())).get("schema", {})
            resolved = self.resolver.resolve(schema)
            operation.body_schema = resolved
            if operation.body_content_type == "multipart":
                for fname, fschema in (resolved.get("properties") or {}).items():
                    if _is_binary(fschema):
                        operation.file_fields.append(fname)
                    elif fschema.get("type") == "array" and _is_binary(fschema.get("items", {})):
                        operation.file_fields.append(fname)
                        operation.file_fields_multi.append(fname)

        ok = op.get("responses", {}).get("200") or op.get("responses", {}).get("201") or {}
        rcontent = ok.get("content") or {}
        if "application/json" in rcontent:
            operation.response_schema = rcontent["application/json"].get("schema")
        elif rcontent:
            operation.binary_response = True
        return operation

    # ----------------------------------------------------------------- queries
    def filtered(self, include_tags: list[str], exclude_tags: list[str]) -> list[Operation]:
        ops = list(self.operations.values())
        if include_tags:
            ops = [o for o in ops if o.tag in include_tags]
        if exclude_tags:
            ops = [o for o in ops if o.tag not in exclude_tags]
        return ops

    def tags(self, ops: list[Operation] | None = None) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for op in ops if ops is not None else self.operations.values():
            counts[op.tag] += 1
        return dict(sorted(counts.items()))

    def find(self, ref: str) -> Operation | None:
        """Look an operation up by tool name, operationId, or ``"METHOD /path"``."""
        ref = ref.strip()
        if ref in self.operations:
            return self.operations[ref]
        if ref in self._by_operation_id:
            return self._by_operation_id[ref]
        parts = ref.split(None, 1)
        if len(parts) == 2:
            method, path = parts[0].upper(), parts[1].strip()
            if not path.startswith("/api/"):
                path = "/api/v1" + (path if path.startswith("/") else "/" + path)
            for candidate in (path, path.rstrip("/"), path.rstrip("/") + "/"):
                op = self._by_signature.get(f"{method} {candidate}")
                if op:
                    return op
            # Match a concrete path (e.g. /api/v1/medications/12) against templates.
            for op in self.operations.values():
                if op.method == method and _template_matches(op.path, path):
                    return op
        return None

    def search(self, query: str, ops: list[Operation]) -> list[Operation]:
        terms = [t for t in re.split(r"[\s_/-]+", query.lower()) if t]
        scored = []
        for op in ops:
            hay = " ".join([op.name, op.path, op.tag, op.summary, op.description]).lower()
            score = sum(hay.count(t) for t in terms)
            if all(t in hay for t in terms):
                scored.append((score, op))
        scored.sort(key=lambda x: (-x[0], x[1].path))
        return [op for _, op in scored]

    # ------------------------------------------------------- schema rendering
    def describe(self, op: Operation) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": op.name,
            "method": op.method,
            "path": op.path,
            "tag": op.tag,
            "summary": op.summary,
        }
        if op.description:
            out["description"] = op.description
        if op.path_params:
            out["path_params"] = {p.name: _param_doc(p) for p in op.path_params}
        if op.query_params:
            out["query"] = {p.name: _param_doc(p) for p in op.query_params}
        if op.body_schema is not None:
            out["body"] = {
                "content_type": op.body_content_type,
                "required": op.body_required,
                "schema": op.body_schema,
            }
            if op.file_fields:
                out["body"]["file_fields"] = op.file_fields
                out["body"]["note"] = (
                    "Pass local file path(s) via `files` ({field: path or [paths]}); "
                    "other fields go in `form`."
                )
        if op.raw_body:
            out["raw_body"] = "Send a local file as the raw request body via `raw_file`."
        if op.binary_response:
            out["response"] = "binary file (saved to the download directory)"
        elif op.response_schema is not None:
            out["response_schema"] = self.resolver.resolve(op.response_schema, max_depth=2)
        return out

    def tool_input_schema(self, op: Operation) -> dict[str, Any]:
        """Input schema for the per-operation tool exposed in ``full`` mode."""
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in op.params:
            schema = copy.deepcopy(p.schema)
            if p.description and "description" not in schema:
                schema["description"] = p.description
            if p.location == "path" and p.name == "patient_id":
                schema["description"] = (
                    schema.get("description", "Patient ID")
                    + " (defaults to the active patient if omitted)"
                )
            elif p.required:
                required.append(p.name)
            props[p.name] = schema
        if op.body_content_type == "json" and op.body_schema is not None:
            props["body"] = {**op.body_schema, "description": "JSON request body"}
            if op.body_required:
                required.append("body")
        elif op.body_content_type in ("multipart", "form") and op.body_schema is not None:
            form_props = {
                k: v for k, v in (op.body_schema.get("properties") or {}).items() if k not in op.file_fields
            }
            if form_props:
                props["form"] = {
                    "type": "object",
                    "properties": form_props,
                    "description": "Form fields",
                }
            for f in op.file_fields:
                if f in op.file_fields_multi:
                    props[f] = {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Local file paths to upload",
                    }
                else:
                    props[f] = {"type": "string", "description": "Local file path to upload"}
                if f in (op.body_schema.get("required") or []):
                    required.append(f)
        if op.raw_body:
            props["raw_file"] = {"type": "string", "description": "Local file sent as the raw request body"}
            required.append("raw_file")
        if op.binary_response:
            props["save_to"] = {
                "type": "string",
                "description": "Optional local path to save the downloaded file",
            }
        if op.is_destructive:
            props["confirm"] = {
                "type": "boolean",
                "description": "Must be true to perform this destructive operation",
            }
        schema: dict[str, Any] = {"type": "object", "properties": props}
        if required:
            schema["required"] = required
        return schema


def _is_binary(schema: dict[str, Any]) -> bool:
    return schema.get("type") == "string" and (
        schema.get("format") == "binary" or schema.get("contentMediaType") == "application/octet-stream"
    )


def _template_matches(template: str, path: str) -> bool:
    t_parts = template.strip("/").split("/")
    p_parts = path.strip("/").split("/")
    if len(t_parts) != len(p_parts):
        return False
    return all(t.startswith("{") or t == p for t, p in zip(t_parts, p_parts))


def _param_doc(p: Param) -> dict[str, Any]:
    doc = dict(p.schema)
    if p.description and "description" not in doc:
        doc["description"] = p.description
    if p.required:
        doc["required"] = True
    return doc
