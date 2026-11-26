"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    url: str = "http://localhost:8005"
    username: str | None = None
    password: str | None = None
    totp_secret: str | None = None
    token: str | None = None
    verify_ssl: bool = True
    timeout: float = 60.0

    # "compact": a handful of generic tools that can reach every endpoint.
    # "full": additionally expose one MCP tool per MediKeep API operation.
    tool_mode: str = "compact"
    # Where to load the OpenAPI description from: "auto" (live, then bundled),
    # "live" (server must have ENABLE_API_DOCS=true) or "bundled".
    openapi_source: str = "auto"
    include_tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)

    read_only: bool = False
    require_confirm: bool = True
    download_dir: Path = Path.home() / "Downloads" / "medikeep-mcp"
    max_response_chars: int = 60000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            url=os.getenv("MEDIKEEP_URL", cls.url).rstrip("/"),
            username=os.getenv("MEDIKEEP_USERNAME") or None,
            password=os.getenv("MEDIKEEP_PASSWORD") or None,
            totp_secret=os.getenv("MEDIKEEP_TOTP_SECRET") or None,
            token=os.getenv("MEDIKEEP_TOKEN") or None,
            verify_ssl=_bool("MEDIKEEP_VERIFY_SSL", True),
            timeout=float(os.getenv("MEDIKEEP_TIMEOUT", "60")),
            tool_mode=os.getenv("MEDIKEEP_TOOL_MODE", "compact").strip().lower(),
            openapi_source=os.getenv("MEDIKEEP_OPENAPI_SOURCE", "auto").strip().lower(),
            include_tags=_list("MEDIKEEP_INCLUDE_TAGS"),
            exclude_tags=_list("MEDIKEEP_EXCLUDE_TAGS"),
            read_only=_bool("MEDIKEEP_READ_ONLY", False),
            require_confirm=_bool("MEDIKEEP_REQUIRE_CONFIRM", True),
            download_dir=Path(
                os.path.expanduser(
                    os.getenv("MEDIKEEP_DOWNLOAD_DIR", str(cls.download_dir))
                )
            ),
            max_response_chars=int(os.getenv("MEDIKEEP_MAX_RESPONSE_CHARS", "60000")),
        )
