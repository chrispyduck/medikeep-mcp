"""MCP server exposing the MediKeep API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx
import mcp.types as types
from mcp.server.lowlevel import Server

from . import __version__
from .catalog import Catalog, Operation
from .client import ApiResponse, MediKeepClient, MediKeepError
from .config import Settings
from .skills_loader import Skill, load_skills

log = logging.getLogger("medikeep_mcp")

INSTRUCTIONS = """\
MediKeep is a self-hosted personal medical records system (medications, conditions,
allergies, lab results with per-test components, vitals, encounters/visits,
procedures, treatments, immunizations, symptoms, injuries, family history,
insurance, practitioners, files, reports and more).

Start with `medikeep_whoami` to learn the signed-in user and the active patient.
`medikeep_patient_overview` gives a broad snapshot in one call. Every MediKeep REST
endpoint is reachable: find it with `medikeep_list_operations`, inspect it with
`medikeep_describe_operation`, then run it with `medikeep_call`.

Read `medikeep_guide` (or the MCP prompts/resources of the same names) for task
playbooks: health summaries, lab trend analysis, medication review, entering
records from documents, symptom tracking, family history, reports & sharing.

This is real, private health data. Never invent values, cite the record a fact
came from, ask before creating/changing/deleting records, and do not present
analysis as medical advice."""

# Sections fetched by medikeep_patient_overview: name -> (method, path, query)
OVERVIEW_SECTIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "patient": ("/patient-management/{pid}", {}),
    "active_medications": ("/medications/patient/{pid}", {"active_only": True, "limit": 200}),
    "active_conditions": ("/conditions/patient/{pid}/active", {}),
    "active_allergies": ("/allergies/patient/{pid}/active", {}),
    "active_treatments": ("/treatments/patient/{pid}/active", {}),
    "active_injuries": ("/injuries/patient/{pid}/active", {}),
    "latest_vitals": ("/vitals/patient/{pid}/latest", {}),
    "vitals_stats": ("/vitals/patient/{pid}/stats", {}),
    "recent_encounters": ("/encounters/patient/{pid}/recent", {"days": "{days}"}),
    "recent_procedures": ("/procedures/patient/{pid}/recent", {"days": "{days}"}),
    "recent_immunizations": ("/immunizations/patient/{pid}/recent", {"days": "{days}"}),
    "recent_lab_results": ("/lab-results/patient/{pid}", {"limit": 25}),
    "abnormal_lab_components": ("/lab-test-components/components/abnormal", {"patient_id": "{pid}", "limit": 100}),
    "symptoms": ("/symptoms/", {"patient_id": "{pid}", "limit": 100}),
    "family_members": ("/family-members/", {"patient_id": "{pid}", "limit": 100}),
    "insurance": ("/insurances/", {"patient_id": "{pid}", "active_only": True}),
    "primary_emergency_contact": ("/emergency-contacts/patient/{pid}/primary", {}),
    "active_equipment": ("/medical-equipment/active", {"patient_id": "{pid}"}),
}
DEFAULT_OVERVIEW = [
    "patient",
    "active_medications",
    "active_conditions",
    "active_allergies",
    "active_treatments",
    "latest_vitals",
    "recent_encounters",
    "recent_lab_results",
    "abnormal_lab_components",
]


def _json(data: Any) -> str:
    return json.dumps(data, indent=1, default=str, ensure_ascii=False)


def strip_nulls(data: Any) -> Any:
    """Drop null/empty values recursively; MediKeep records are sparse."""
    if isinstance(data, dict):
        return {k: strip_nulls(v) for k, v in data.items() if v is not None and v != [] and v != ""}
    if isinstance(data, list):
        return [strip_nulls(v) for v in data]
    return data


def _text(text: str, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text=text)], isError=error)


class MediKeepMCP:
    def __init__(self, settings: Settings, catalog: Catalog):
        self.settings = settings
        self.catalog = catalog
        self.client = MediKeepClient(settings)
        self.skills: dict[str, Skill] = load_skills()
        self.ops: list[Operation] = catalog.filtered(settings.include_tags, settings.exclude_tags)
        self.op_names = {op.name for op in self.ops}
        self._active_patient: int | None = None

    # ================================================================= tools
    def helper_tools(self) -> list[types.Tool]:
        ro = types.ToolAnnotations(readOnlyHint=True, openWorldHint=False)
        skill_names = sorted(self.skills)
        return [
            types.Tool(
                name="medikeep_guide",
                title="MediKeep usage guides",
                description=(
                    "Playbooks for working with MediKeep data. Call with no topic to list them, "
                    "or with a topic to read one. Read the relevant guide before multi-step tasks "
                    "(health summaries, lab trends, medication review, adding records, etc.)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"topic": {"type": "string", "enum": skill_names}},
                },
                annotations=ro,
            ),
            types.Tool(
                name="medikeep_whoami",
                title="Current user and active patient",
                description=(
                    "Return the signed-in MediKeep user, the active patient (whose records most "
                    "endpoints default to), all patients this user can access, and server version."
                ),
                inputSchema={"type": "object", "properties": {}},
                annotations=ro,
            ),
            types.Tool(
                name="medikeep_list_operations",
                title="List MediKeep API operations",
                description=(
                    "Discover MediKeep API operations. With no arguments: list categories (tags) "
                    "with operation counts. With `tag` and/or `search`: list matching operations "
                    "as `name  METHOD /path  summary`. Use the name with medikeep_describe_operation "
                    "and medikeep_call."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string", "description": "Category, e.g. 'medications', 'lab-results'"},
                        "search": {"type": "string", "description": "Keywords, e.g. 'lab trend' or 'booster'"},
                        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                    },
                },
                annotations=ro,
            ),
            types.Tool(
                name="medikeep_describe_operation",
                title="Describe a MediKeep API operation",
                description=(
                    "Show an operation's path/query parameters, request body schema (with required "
                    "fields), and response shape. Accepts an operation name, operationId, or "
                    "'METHOD /path'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"operation": {"type": "string"}},
                    "required": ["operation"],
                },
                annotations=ro,
            ),
            types.Tool(
                name="medikeep_call",
                title="Call any MediKeep API operation",
                description=(
                    "Execute any MediKeep API operation. `operation` is a name from "
                    "medikeep_list_operations (or 'METHOD /api/v1/path'). If a `patient_id` path "
                    "parameter is omitted the active patient is used. DELETE operations need "
                    "`confirm: true`. File uploads take local paths in `files`; file downloads are "
                    "saved locally and the path is returned."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string"},
                        "path_params": {"type": "object", "description": "Values for {placeholders} in the path"},
                        "query": {"type": "object", "description": "Query string parameters"},
                        "body": {"description": "JSON request body (object or array)"},
                        "form": {"type": "object", "description": "Form fields for multipart/form endpoints"},
                        "files": {
                            "type": "object",
                            "description": "Multipart file fields: {field: local_path | [local_paths]}",
                        },
                        "raw_file": {
                            "type": "string",
                            "description": "Local file sent as the raw request body (e.g. imaging import)",
                        },
                        "save_to": {"type": "string", "description": "Where to save a downloaded file"},
                        "confirm": {"type": "boolean", "description": "Required (true) for DELETE operations"},
                    },
                    "required": ["operation"],
                },
                annotations=types.ToolAnnotations(destructiveHint=True, openWorldHint=False),
            ),
            types.Tool(
                name="medikeep_patient_overview",
                title="Patient health snapshot",
                description=(
                    "Fetch a broad snapshot of a patient's record in one call (defaults to the "
                    "active patient). Sections: " + ", ".join(OVERVIEW_SECTIONS) + ". Default: "
                    + ", ".join(DEFAULT_OVERVIEW) + ". Pass sections=['all'] for everything."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "patient_id": {"type": "integer"},
                        "sections": {"type": "array", "items": {"type": "string"}},
                        "days": {
                            "type": "integer",
                            "description": "Look-back window for recent_* sections (default 365)",
                        },
                    },
                },
                annotations=ro,
            ),
            types.Tool(
                name="medikeep_search_records",
                title="Search medical records",
                description=(
                    "Full-text search across a patient's records (medications, conditions, labs, "
                    "procedures, encounters, ...). Omit `q` to list everything; filter by `types` "
                    "and ISO dates."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "types": {"type": "array", "items": {"type": "string"}},
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "sort": {"type": "string", "enum": ["relevance", "date_desc", "date_asc", "title"]},
                        "limit": {"type": "integer", "description": "Results per type (max 100)"},
                        "skip": {"type": "integer"},
                        "patient_id": {"type": "integer"},
                    },
                },
                annotations=ro,
            ),
            types.Tool(
                name="medikeep_lab_trend",
                title="Lab test trend",
                description=(
                    "Time series of one lab test component (e.g. 'Hemoglobin A1c', 'LDL "
                    "Cholesterol') for a patient, with values, units, reference ranges and status. "
                    "Use medikeep_call get_component_catalog to see which test names exist."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "test_name": {"type": "string"},
                        "patient_id": {"type": "integer"},
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "unit": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["test_name"],
                },
                annotations=ro,
            ),
        ]

    def operation_tools(self) -> list[types.Tool]:
        tools = []
        for op in self.ops:
            desc = op.summary or op.name
            if op.description and op.description != op.summary:
                desc += "\n\n" + op.description
            desc = f"[{op.tag}] {op.method} {op.path}\n{desc}"
            tools.append(
                types.Tool(
                    name=op.name,
                    description=desc[:1500],
                    inputSchema=self.catalog.tool_input_schema(op),
                    annotations=types.ToolAnnotations(
                        readOnlyHint=op.is_read_only,
                        destructiveHint=op.is_destructive,
                        openWorldHint=False,
                    ),
                )
            )
        return tools

    def list_tools(self) -> list[types.Tool]:
        tools = self.helper_tools()
        if self.settings.tool_mode == "full":
            tools += self.operation_tools()
        return tools

    async def call_tool(self, name: str, args: dict[str, Any]) -> types.CallToolResult:
        try:
            if name == "medikeep_guide":
                return self.tool_guide(args.get("topic"))
            if name == "medikeep_whoami":
                return await self.tool_whoami()
            if name == "medikeep_list_operations":
                return self.tool_list_operations(args.get("tag"), args.get("search"), args.get("method"))
            if name == "medikeep_describe_operation":
                return self.tool_describe(args.get("operation", ""))
            if name == "medikeep_call":
                op = self._lookup(args.get("operation", ""))
                if isinstance(op, types.CallToolResult):
                    return op
                return await self.execute(
                    op,
                    path_params=args.get("path_params") or {},
                    query=args.get("query") or {},
                    body=args.get("body"),
                    form=args.get("form"),
                    files=args.get("files"),
                    save_to=args.get("save_to"),
                    raw_file=args.get("raw_file"),
                    confirm=bool(args.get("confirm")),
                )
            if name == "medikeep_patient_overview":
                return await self.tool_overview(args)
            if name == "medikeep_search_records":
                return await self.tool_search(args)
            if name == "medikeep_lab_trend":
                return await self.tool_lab_trend(args)
            if self.settings.tool_mode == "full" and name in self.op_names:
                return await self._execute_tool_args(self.catalog.operations[name], args)
            return _text(f"Unknown tool: {name}", error=True)
        except MediKeepError as e:
            msg = str(e)
            if e.detail is not None:
                msg += "\n" + _json(e.detail)
            return _text(msg, error=True)
        except httpx.HTTPError as e:
            return _text(
                f"Could not reach MediKeep at {self.settings.url}: {type(e).__name__}: {e}", error=True
            )

    # ---------------------------------------------------------- tool bodies
    def tool_guide(self, topic: str | None) -> types.CallToolResult:
        if not topic:
            lines = ["Available MediKeep guides (call medikeep_guide with topic=<name>):", ""]
            lines += [f"- {s.name}: {s.description}" for s in self.skills.values()]
            return _text("\n".join(lines))
        skill = self.skills.get(topic)
        if not skill:
            return _text(f"No guide named '{topic}'. Options: {', '.join(self.skills)}", error=True)
        return _text(skill.body)

    async def tool_whoami(self) -> types.CallToolResult:
        user = await self.client.get_json("/users/me")
        out: dict[str, Any] = {
            "server": self.settings.url,
            "user": strip_nulls(user),
        }
        try:
            active = await self.client.get_json("/patient-management/active/current")
            out["active_patient"] = strip_nulls(active)
            if isinstance(active, dict) and active.get("id"):
                self._active_patient = int(active["id"])
        except MediKeepError as e:
            out["active_patient"] = f"unavailable ({e.status})"
        try:
            patients = await self.client.get_json("/patient-management/")
            out["accessible_patients"] = strip_nulls(patients)
        except MediKeepError:
            pass
        try:
            out["medikeep_version"] = await self.client.get_json("/system/version")
        except MediKeepError:
            pass
        if self.client.must_change_password:
            out["warning"] = "MediKeep requires this account to change its password."
        out["mcp"] = {
            "version": __version__,
            "api_spec": f"{self.catalog.source} (MediKeep {self.catalog.api_version})",
            "tool_mode": self.settings.tool_mode,
            "read_only": self.settings.read_only,
        }
        return _text(_json(out))

    def tool_list_operations(self, tag: str | None, search: str | None, method: str | None) -> types.CallToolResult:
        ops = self.ops
        if not tag and not search and not method:
            tags = self.catalog.tags(ops)
            lines = [f"{len(ops)} operations in {len(tags)} categories. Filter with tag= or search=.", ""]
            lines += [f"{t} ({n})" for t, n in tags.items()]
            return _text("\n".join(lines))
        if tag:
            ops = [o for o in ops if o.tag == tag or o.tag == tag.lower()]
        if method:
            ops = [o for o in ops if o.method == method.upper()]
        if search:
            ops = self.catalog.search(search, ops)
        if not ops:
            return _text("No matching operations. Call with no arguments to see categories.")
        lines = [f"{o.name}  {o.method} {o.path}  {o.short_description()}" for o in ops[:150]]
        if len(ops) > 150:
            lines.append(f"... {len(ops) - 150} more; narrow the search.")
        return _text("\n".join(lines))

    def tool_describe(self, ref: str) -> types.CallToolResult:
        op = self._lookup(ref)
        if isinstance(op, types.CallToolResult):
            return op
        return _text(_json(self.catalog.describe(op)))

    async def tool_overview(self, args: dict[str, Any]) -> types.CallToolResult:
        pid = args.get("patient_id") or await self.active_patient_id()
        days = int(args.get("days") or 365)
        sections = args.get("sections") or DEFAULT_OVERVIEW
        if "all" in sections:
            sections = list(OVERVIEW_SECTIONS)
        unknown = [s for s in sections if s not in OVERVIEW_SECTIONS]
        if unknown:
            return _text(f"Unknown sections {unknown}. Valid: {list(OVERVIEW_SECTIONS)}", error=True)

        async def fetch(section: str) -> tuple[str, Any]:
            path, query = OVERVIEW_SECTIONS[section]
            q = {k: (v.format(pid=pid, days=days) if isinstance(v, str) else v) for k, v in query.items()}
            resp = await self.client.request("GET", path.format(pid=pid), query=q)
            if resp.ok:
                return section, strip_nulls(resp.data)
            if resp.status == 404:
                return section, None
            return section, {"error": resp.status, "detail": resp.data}

        results = await asyncio.gather(*(fetch(s) for s in sections))
        out = {"patient_id": pid, "recent_window_days": days}
        out.update(dict(results))
        return self._format(out)

    async def tool_search(self, args: dict[str, Any]) -> types.CallToolResult:
        query = {k: v for k, v in args.items() if v not in (None, "", [])}
        resp = await self.client.request("GET", "/search/", query=query)
        return self._result(resp)

    async def tool_lab_trend(self, args: dict[str, Any]) -> types.CallToolResult:
        pid = args.get("patient_id") or await self.active_patient_id()
        query = {k: args.get(k) for k in ("test_name", "date_from", "date_to", "unit", "limit")}
        resp = await self.client.request("GET", f"/lab-test-components/patient/{pid}/trends", query=query)
        return self._result(resp)

    # -------------------------------------------------------------- execute
    def _lookup(self, ref: str) -> Operation | types.CallToolResult:
        op = self.catalog.find(ref or "")
        if op is None:
            hits = self.catalog.search(ref, self.ops)[:10] if ref else []
            hint = ("\nDid you mean: " + ", ".join(h.name for h in hits)) if hits else ""
            return _text(f"Unknown operation '{ref}'. Use medikeep_list_operations.{hint}", error=True)
        if op.name not in self.op_names:
            return _text(f"Operation '{op.name}' is disabled by MEDIKEEP_INCLUDE/EXCLUDE_TAGS.", error=True)
        return op

    async def _execute_tool_args(self, op: Operation, args: dict[str, Any]) -> types.CallToolResult:
        path_params = {p.name: args[p.name] for p in op.path_params if p.name in args}
        query = {p.name: args[p.name] for p in op.query_params if p.name in args}
        files = {f: args[f] for f in op.file_fields if args.get(f)}
        return await self.execute(
            op,
            path_params=path_params,
            query=query,
            body=args.get("body"),
            form=args.get("form"),
            files=files or None,
            save_to=args.get("save_to"),
            raw_file=args.get("raw_file"),
            confirm=bool(args.get("confirm")),
        )

    async def execute(
        self,
        op: Operation,
        *,
        path_params: dict[str, Any],
        query: dict[str, Any],
        body: Any = None,
        form: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        save_to: str | None = None,
        raw_file: str | None = None,
        confirm: bool = False,
    ) -> types.CallToolResult:
        if self.settings.read_only and not op.is_read_only:
            return _text(
                f"{op.signature()} modifies data, but this server runs with MEDIKEEP_READ_ONLY=true.",
                error=True,
            )
        if op.is_destructive and self.settings.require_confirm and not confirm:
            return _text(
                f"{op.signature()} is destructive. Confirm with the user, then repeat the call "
                "with confirm=true.",
                error=True,
            )

        path = op.path
        for p in op.path_params:
            value = path_params.get(p.name)
            if value is None and p.name in query:
                value = query.pop(p.name)
            if value is None and p.name == "patient_id":
                value = await self.active_patient_id()
            if value is None:
                return _text(
                    f"Missing path parameter '{p.name}' for {op.signature()}.", error=True
                )
            path = path.replace("{" + p.name + "}", quote(str(value), safe=""))
        leftover = re.findall(r"{(\w+)}", path)
        if leftover:
            return _text(f"Unresolved path parameters: {leftover}", error=True)

        if op.body_content_type in ("multipart", "form") and body and not form and isinstance(body, dict):
            form = body
            body = None
        if op.body_content_type == "multipart" and form and not files:
            # Allow file paths to be passed inside `form` under the file field names.
            files = {f: form.pop(f) for f in list(form) if f in op.file_fields}
        if op.body_content_type in ("multipart", "form") and form is None and files is None:
            form = {}

        resp = await self.client.request(
            op.method,
            path,
            query=query,
            json_body=body if op.body_content_type == "json" or op.body_content_type is None else None,
            form=form if op.body_content_type in ("multipart", "form") else None,
            files=files or None,
            save_to=save_to,
            raw_file=raw_file,
            auth=not (op.tag == "authentication" and op.name in {"login", "register", "get_registration_status"}),
        )
        return self._result(resp)

    async def active_patient_id(self) -> int:
        if self._active_patient is None:
            active = await self.client.get_json("/patient-management/active/current")
            if not isinstance(active, dict) or not active.get("id"):
                raise MediKeepError(
                    "No active patient. Create one (create_my_patient_record) or switch "
                    "(switch_active_patient), or pass patient_id explicitly."
                )
            self._active_patient = int(active["id"])
        return self._active_patient

    def _result(self, resp: ApiResponse) -> types.CallToolResult:
        if resp.file_path is not None:
            return _text(
                _json(
                    {
                        "status": resp.status,
                        "saved_to": str(resp.file_path),
                        "content_type": resp.content_type,
                        "bytes": resp.size,
                    }
                )
            )
        if not resp.ok:
            return _text(f"HTTP {resp.status}\n" + (_json(resp.data) if resp.data is not None else ""), error=True)
        if resp.data is None:
            return _text(f"HTTP {resp.status} (no content)")
        # Track patient switches so the default patient stays correct.
        if isinstance(resp.data, dict) and "active_patient_id" in resp.data:
            self._active_patient = resp.data.get("active_patient_id") or None
        return self._format(strip_nulls(resp.data) if not isinstance(resp.data, str) else resp.data)

    def _format(self, data: Any) -> types.CallToolResult:
        text = data if isinstance(data, str) else _json(data)
        limit = self.settings.max_response_chars
        if len(text) > limit:
            text = (
                text[:limit]
                + f"\n\n[truncated: response was {len(text)} characters. Use skip/limit, date filters, "
                "or a narrower endpoint.]"
            )
        return _text(text)

    # ================================================== prompts / resources
    def list_prompts(self) -> list[types.Prompt]:
        return [
            types.Prompt(
                name=s.name,
                description=s.description,
                arguments=[
                    types.PromptArgument(
                        name="request", description="What you want to do (optional)", required=False
                    )
                ],
            )
            for s in self.skills.values()
        ]

    def get_prompt(self, name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
        skill = self.skills.get(name)
        if not skill:
            raise ValueError(f"Unknown prompt: {name}")
        text = skill.body
        request = (arguments or {}).get("request")
        if request:
            text += f"\n\n---\n\nTask: {request}"
        return types.GetPromptResult(
            description=skill.description,
            messages=[types.PromptMessage(role="user", content=types.TextContent(text=text))],
        )

    def list_resources(self) -> list[types.Resource]:
        res = [
            types.Resource(
                name=s.name,
                uri=f"medikeep://skills/{s.name}",
                description=s.description,
                mimeType="text/markdown",
            )
            for s in self.skills.values()
        ]
        res.append(
            types.Resource(
                name="operations",
                uri="medikeep://operations",
                description="Index of every MediKeep API operation (name, method, path, summary)",
                mimeType="text/plain",
            )
        )
        return res

    def read_resource(self, uri: str) -> types.ReadResourceResult:
        if uri == "medikeep://operations":
            text = "\n".join(f"{o.tag}\t{o.name}\t{o.method} {o.path}\t{o.short_description()}" for o in self.ops)
            return types.ReadResourceResult(
                contents=[types.TextResourceContents(uri=uri, mimeType="text/plain", text=text)]
            )
        m = re.fullmatch(r"medikeep://skills/(.+)", uri)
        if m and m.group(1) in self.skills:
            return types.ReadResourceResult(
                contents=[
                    types.TextResourceContents(uri=uri, mimeType="text/markdown", text=self.skills[m.group(1)].text)
                ]
            )
        raise ValueError(f"Unknown resource: {uri}")


async def load_catalog(settings: Settings) -> Catalog:
    if settings.openapi_source in ("auto", "live"):
        try:
            async with httpx.AsyncClient(verify=settings.verify_ssl, timeout=15) as http:
                resp = await http.get(f"{settings.url}/api/v1/openapi.json")
            if resp.status_code == 200:
                return Catalog(resp.json(), source="live")
            if settings.openapi_source == "live":
                raise RuntimeError(
                    f"Live OpenAPI unavailable (HTTP {resp.status_code}); set ENABLE_API_DOCS=true on MediKeep"
                )
        except httpx.HTTPError as e:
            if settings.openapi_source == "live":
                raise RuntimeError(f"Could not fetch live OpenAPI: {e}") from e
            log.info("Live OpenAPI not reachable (%s); using bundled spec", e)
    return Catalog.bundled()


def build_server(app: MediKeepMCP) -> Server:
    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=app.list_tools())

    async def on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        return await app.call_tool(params.name, params.arguments or {})

    async def on_list_prompts(ctx, params) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=app.list_prompts())

    async def on_get_prompt(ctx, params: types.GetPromptRequestParams) -> types.GetPromptResult:
        return app.get_prompt(params.name, params.arguments)

    async def on_list_resources(ctx, params) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=app.list_resources())

    async def on_read_resource(ctx, params: types.ReadResourceRequestParams) -> types.ReadResourceResult:
        return app.read_resource(str(params.uri))

    return Server(
        "medikeep",
        version=__version__,
        title="MediKeep",
        instructions=INSTRUCTIONS,
        website_url="https://github.com/chrispyduck/medikeep-mcp",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_prompts=on_list_prompts,
        on_get_prompt=on_get_prompt,
        on_list_resources=on_list_resources,
        on_read_resource=on_read_resource,
    )
