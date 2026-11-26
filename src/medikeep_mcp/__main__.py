"""Entry point: ``medikeep-mcp`` (stdio by default, ``--http`` for streamable HTTP)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import __version__
from .config import Settings
from .server import MediKeepMCP, build_server, load_catalog


def main() -> None:
    parser = argparse.ArgumentParser(prog="medikeep-mcp", description="MCP server for MediKeep")
    parser.add_argument("--version", action="version", version=f"medikeep-mcp {__version__}")
    parser.add_argument("--http", action="store_true", help="Serve streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()

    # stdout is the MCP channel in stdio mode; log to stderr only.
    logging.basicConfig(stream=sys.stderr, level=args.log_level.upper())

    settings = Settings.from_env()
    if settings.tool_mode not in ("compact", "full"):
        parser.error("MEDIKEEP_TOOL_MODE must be 'compact' or 'full'")
    catalog = asyncio.run(load_catalog(settings))
    app = MediKeepMCP(settings, catalog)
    server = build_server(app)

    if args.http:
        import uvicorn

        uvicorn.run(server.streamable_http_app(), host=args.host, port=args.port, log_level="warning")
        return

    from mcp.server.stdio import stdio_server

    async def run_stdio() -> None:
        try:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())
        finally:
            await app.client.aclose()

    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
