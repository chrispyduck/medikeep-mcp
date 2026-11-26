#!/usr/bin/env python3
"""Refresh the bundled MediKeep OpenAPI snapshot.

Usage:
  # From a running MediKeep started with ENABLE_API_DOCS=true
  python scripts/update_openapi.py --url http://localhost:8005

  # From a MediKeep source checkout (run with an interpreter that has MediKeep's
  # requirements installed)
  /path/to/medikeep-venv/bin/python scripts/update_openapi.py --source ../MediKeep
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "medikeep_mcp" / "data" / "openapi.json"


def from_url(url: str) -> dict:
    with urllib.request.urlopen(url.rstrip("/") + "/api/v1/openapi.json", timeout=30) as resp:
        return json.load(resp)


def from_source(src: Path) -> dict:
    tmp = tempfile.mkdtemp(prefix="medikeep-openapi-")
    os.environ.update(
        {
            "ENABLE_API_DOCS": "true",
            "DATABASE_URL": f"sqlite:///{tmp}/schema.db",
            "SECRET_KEY": "schema-export-only",
            "LOG_DIR": tmp,
            "UPLOAD_DIR": f"{tmp}/uploads",
        }
    )
    os.chdir(src)
    sys.path.insert(0, str(src))
    from app.main import app  # type: ignore

    return app.openapi()


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url")
    group.add_argument("--source", type=Path)
    args = parser.parse_args()
    spec = from_url(args.url) if args.url else from_source(args.source.resolve())
    OUT.write_text(json.dumps(spec, separators=(",", ":")), "utf-8")
    ops = sum(
        1 for item in spec["paths"].values() for m in item if m in ("get", "post", "put", "patch", "delete")
    )
    print(f"Wrote {OUT} - MediKeep {spec['info'].get('version')}, {ops} operations")


if __name__ == "__main__":
    main()
