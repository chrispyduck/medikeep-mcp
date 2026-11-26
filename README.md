# medikeep-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server for
[MediKeep](https://github.com/afairgiant/MediKeep), the self-hosted personal medical
records manager. It lets Claude (or any MCP client) read and manage everything in
your MediKeep instance, and ships with **skills** that teach the model how to use
that information well: health summaries, lab trends, medication review, record
entry, symptom/vitals tracking, family history and sharing, reports, and admin.

- **Every MediKeep API operation** (584 in MediKeep 0.75) is available, generated from MediKeep's OpenAPI schema.
- **Two tool modes:** a compact set of 8 tools (default, light on context), or one tool per operation.
- **Automatic login** with username/password, TOTP two-factor support, and re-login when sessions expire.
- **File uploads and downloads** (lab PDFs, attachments, imaging, exports, PDF reports).
- **Guardrails:** read-only mode, `confirm: true` required for deletes, tag allow/deny lists.
- **Skills** in Claude Code skill format, also served as MCP prompts and resources for other clients.

## Install

Requires [uv](https://docs.astral.sh/uv/) (or pip) and Python 3.11+.

### Claude Code plugin (server + skills)

```bash
claude plugin marketplace add chrispyduck/medikeep-mcp
```

```bash
claude plugin install medikeep@medikeep-mcp
```

The plugin reads `MEDIKEEP_URL`, `MEDIKEEP_USERNAME`, `MEDIKEEP_PASSWORD` (and the
other settings below) from your environment.

### Any MCP client (Claude Desktop, Cursor, ...)

```json
{
  "mcpServers": {
    "medikeep": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/chrispyduck/medikeep-mcp", "medikeep-mcp"],
      "env": {
        "MEDIKEEP_URL": "https://medikeep.example.com",
        "MEDIKEEP_USERNAME": "me",
        "MEDIKEEP_PASSWORD": "..."
      }
    }
  }
}
```

Or with Claude Code directly:

```bash
claude mcp add medikeep -e MEDIKEEP_URL=http://localhost:8005 -e MEDIKEEP_USERNAME=me -e MEDIKEEP_PASSWORD=secret -- uvx --from git+https://github.com/chrispyduck/medikeep-mcp medikeep-mcp
```

To use the skills in Claude Code without the plugin, copy `skills/*` into
`~/.claude/skills/`. Other clients get the same content as MCP prompts
(`medikeep-health-summary`, ...), as resources (`medikeep://skills/<name>`), and via
the `medikeep_guide` tool.

`medikeep-mcp --http --port 8765` serves streamable HTTP instead of stdio.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MEDIKEEP_URL` | `http://localhost:8005` | MediKeep base URL |
| `MEDIKEEP_USERNAME` / `MEDIKEEP_PASSWORD` | | Account to act as |
| `MEDIKEEP_TOTP_SECRET` | | Base32 TOTP secret if the account uses two-factor auth |
| `MEDIKEEP_TOKEN` | | Pre-issued JWT instead of a password (expires with the session) |
| `MEDIKEEP_TOOL_MODE` | `compact` | `compact` or `full` (see below) |
| `MEDIKEEP_INCLUDE_TAGS` / `MEDIKEEP_EXCLUDE_TAGS` | | Comma-separated API categories to allow / hide, e.g. `admin,sso,frontend-logs` |
| `MEDIKEEP_OPENAPI_SOURCE` | `auto` | `auto` uses the server's live schema when `ENABLE_API_DOCS=true`, otherwise the bundled one; `live`; `bundled` |
| `MEDIKEEP_READ_ONLY` | `false` | Refuse all non-GET calls |
| `MEDIKEEP_REQUIRE_CONFIRM` | `true` | DELETE calls need `confirm: true` |
| `MEDIKEEP_DOWNLOAD_DIR` | `~/Downloads/medikeep-mcp` | Where downloaded files and exports are saved |
| `MEDIKEEP_VERIFY_SSL` | `true` | Set `false` for self-signed certificates |
| `MEDIKEEP_TIMEOUT` | `60` | HTTP timeout (seconds) |
| `MEDIKEEP_MAX_RESPONSE_CHARS` | `60000` | Truncate very large responses |

Create a dedicated MediKeep user for the MCP if you want to limit what it can see,
and share only the patients it should access with that user.

With two-factor auth on, MediKeep rejects a code that was already used, so a login
that lands in the same 30-second window as a previous one waits for the next code.

## Tools

### Compact mode (default)

| Tool | What it does |
|---|---|
| `medikeep_whoami` | Signed-in user, active patient, accessible patients, server version |
| `medikeep_patient_overview` | Snapshot of a patient across up to 18 sections in one call |
| `medikeep_search_records` | Full-text search across records |
| `medikeep_lab_trend` | Time series for one lab component |
| `medikeep_list_operations` | Browse/search all API operations by category or keyword |
| `medikeep_describe_operation` | Parameters, body schema and response of an operation |
| `medikeep_call` | Execute any operation (JSON bodies, multipart uploads, raw uploads, downloads) |
| `medikeep_guide` | Read the bundled skills/playbooks |

Example: `medikeep_call {"operation": "create_medication", "body": {"medication_name": "Atorvastatin", "dosage": "20 mg", "frequency": "daily", "status": "active", "patient_id": 2}}`.
Operations can also be referenced as `"GET /api/v1/medications/12"`. A `patient_id`
path parameter defaults to the active patient.

### Full mode

`MEDIKEEP_TOOL_MODE=full` additionally registers every operation as its own tool
(`read_medications`, `create_lab_test_components_bulk`, `get_lab_test_component_trends`, ...)
with a typed input schema and read-only/destructive annotations. That is ~590 tools
(~450 KB of schemas), so pair it with `MEDIKEEP_INCLUDE_TAGS` / `MEDIKEEP_EXCLUDE_TAGS`
unless your client handles large tool sets well.

## Skills

| Skill | Use it for |
|---|---|
| `medikeep-basics` | Data model, patient context, finding/calling operations, safety rules |
| `medikeep-health-summary` | Health summaries, visit prep, provider handoffs |
| `medikeep-lab-analysis` | Lab panels, components, trends, abnormal values, entering labs |
| `medikeep-medication-review` | Medication lists, reconciliation, allergy checks, changes, reminders |
| `medikeep-record-entry` | Adding records from notes/documents, linking, attachments, imports |
| `medikeep-symptoms-and-vitals` | Symptom episodes, vitals trends, injuries |
| `medikeep-family-and-sharing` | Family history, multiple patients, sharing and invitations |
| `medikeep-reports-and-export` | PDF reports, exports, file downloads |
| `medikeep-admin` | Backups, users, trash, audit log, integrations, notifications, 2FA |

## Development

```bash
uv sync --extra dev
```

```bash
uv run pytest
```

The tests check that every operation is cataloged, tool names are valid, and every
operation name mentioned in the skills exists.

The bundled schema (`src/medikeep_mcp/data/openapi.json`) is MediKeep 0.75.0. To
refresh it after a MediKeep upgrade, start MediKeep with `ENABLE_API_DOCS=true` and run:

```bash
uv run python scripts/update_openapi.py --url http://localhost:8005
```

Health data is sensitive: this server talks only to the MediKeep URL you configure,
and the skills instruct the model not to invent values, to ask before changing
records, and not to present analysis as medical advice.

## License

Apache-2.0, matching MediKeep. Not affiliated with the MediKeep project.
