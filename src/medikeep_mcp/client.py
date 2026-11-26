"""Async HTTP client for the MediKeep REST API with automatic authentication."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pyotp

from .config import Settings

API_PREFIX = "/api/v1"


class MediKeepError(Exception):
    def __init__(self, message: str, status: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


@dataclass
class ApiResponse:
    status: int
    content_type: str
    data: Any = None  # parsed JSON or text
    file_path: Path | None = None
    size: int | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class MediKeepClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._token: str | None = settings.token
        self._login_lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            base_url=settings.url,
            timeout=settings.timeout,
            verify=settings.verify_ssl,
            follow_redirects=True,
            headers={"User-Agent": "medikeep-mcp"},
        )
        self._last_totp_step: int | None = None
        self.user: dict[str, Any] | None = None
        self.must_change_password = False

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ auth
    @property
    def can_login(self) -> bool:
        return bool(self.settings.username and self.settings.password)

    async def login(self) -> None:
        if not self.can_login:
            raise MediKeepError(
                "No MediKeep credentials configured. Set MEDIKEEP_USERNAME and "
                "MEDIKEEP_PASSWORD (and MEDIKEEP_TOTP_SECRET if two-factor is on), "
                "or MEDIKEEP_TOKEN."
            )
        resp = await self._http.post(
            f"{API_PREFIX}/auth/login",
            data={"username": self.settings.username, "password": self.settings.password},
        )
        if resp.status_code >= 400:
            raise MediKeepError(
                f"MediKeep login failed ({resp.status_code}): {_error_text(resp)}",
                resp.status_code,
            )
        payload = resp.json()
        if payload.get("mfa_required"):
            payload = await self._complete_mfa(payload)
        token = payload.get("access_token")
        if not token:
            raise MediKeepError(f"MediKeep login returned no access token: {payload}")
        self._token = token
        self.must_change_password = bool(payload.get("must_change_password"))

    async def _complete_mfa(self, challenge: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.totp_secret:
            raise MediKeepError(
                "This MediKeep account requires two-factor authentication. Set "
                "MEDIKEEP_TOTP_SECRET to the account's TOTP secret (base32), or supply "
                "a pre-issued MEDIKEEP_TOKEN."
            )
        if "totp" not in (challenge.get("methods") or ["totp"]):
            raise MediKeepError(f"Unsupported two-factor methods: {challenge.get('methods')}")
        totp = pyotp.TOTP(self.settings.totp_secret.replace(" ", ""))
        for attempt in range(2):
            # MediKeep refuses a code that was already used, so never send the same
            # 30-second step twice (e.g. a quick re-login after a session timeout).
            step = int(time.time()) // totp.interval
            if attempt or step == self._last_totp_step:
                await asyncio.sleep(totp.interval - time.time() % totp.interval + 0.5)
                step = int(time.time()) // totp.interval
            self._last_totp_step = step
            resp = await self._http.post(
                f"{API_PREFIX}/auth/two-factor/verify",
                json={
                    "mfa_ticket": challenge["mfa_ticket"],
                    "code": totp.now(),
                    "method": "totp",
                    # Lets later re-logins in this process skip the second step.
                    "remember_device": bool(challenge.get("remember_device_days")),
                },
            )
            if resp.status_code < 400 or "already used" not in _error_text(resp).lower():
                break
        if resp.status_code >= 400:
            raise MediKeepError(
                f"MediKeep two-factor verification failed ({resp.status_code}): {_error_text(resp)}",
                resp.status_code,
            )
        return resp.json()

    async def _ensure_token(self) -> None:
        if self._token:
            return
        async with self._login_lock:
            if not self._token:
                await self.login()

    # --------------------------------------------------------------- requests
    async def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: Any = None,
        form: dict[str, Any] | None = None,
        files: dict[str, str | list[str]] | None = None,
        save_to: str | None = None,
        raw_file: str | None = None,
        auth: bool = True,
    ) -> ApiResponse:
        if not path.startswith("/"):
            path = "/" + path
        if not path.startswith("/api/") and path not in ("/", "/health"):
            path = API_PREFIX + path
        query = {k: v for k, v in (query or {}).items() if v is not None}

        attempts = 2 if auth else 1
        for attempt in range(attempts):
            if auth:
                await self._ensure_token()
            headers = {"Authorization": f"Bearer {self._token}"} if auth and self._token else {}
            with ExitStack() as stack:
                upload = _open_files(files, stack) if files else None
                kwargs: dict[str, Any] = {"params": query, "headers": headers}
                if raw_file:
                    raw_path = Path(raw_file).expanduser()
                    if not raw_path.is_file():
                        raise MediKeepError(f"File not found for upload: {raw_path}")
                    kwargs["content"] = raw_path.read_bytes()
                    kwargs["headers"] = {
                        **headers,
                        "Content-Type": mimetypes.guess_type(raw_path.name)[0] or "application/octet-stream",
                    }
                elif upload is not None:
                    kwargs["files"] = upload
                    if form:
                        kwargs["data"] = _stringify_form(form)
                elif form is not None:
                    kwargs["data"] = _stringify_form(form)
                elif json_body is not None:
                    kwargs["json"] = json_body
                resp = await self._http.request(method.upper(), path, **kwargs)
            if resp.status_code == 401 and auth and attempt == 0 and self.can_login:
                # Token expired (MediKeep sessions time out); log in again and retry once.
                self._token = None
                continue
            return await self._to_response(resp, save_to)
        raise AssertionError("unreachable")

    async def get_json(self, path: str, **query: Any) -> Any:
        resp = await self.request("GET", path, query=query)
        if not resp.ok:
            raise MediKeepError(f"GET {path} failed ({resp.status})", resp.status, resp.data)
        return resp.data

    async def _to_response(self, resp: httpx.Response, save_to: str | None) -> ApiResponse:
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if resp.status_code == 204 or not resp.content:
            return ApiResponse(resp.status_code, ctype, data=None)
        if ctype == "application/json" or ctype.endswith("+json"):
            try:
                return ApiResponse(resp.status_code, ctype, data=resp.json())
            except json.JSONDecodeError:
                return ApiResponse(resp.status_code, ctype, data=resp.text)
        if resp.status_code >= 400 or ctype.startswith("text/") and not _is_attachment(resp):
            return ApiResponse(resp.status_code, ctype, data=resp.text)
        target = self._download_target(resp, save_to)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(resp.content)
        return ApiResponse(resp.status_code, ctype, file_path=target, size=len(resp.content))

    def _download_target(self, resp: httpx.Response, save_to: str | None) -> Path:
        if save_to:
            target = Path(save_to).expanduser()
            if target.is_dir():
                target = target / _filename(resp)
            return target
        target = self.settings.download_dir / _filename(resp)
        stem, suffix, n = target.stem, target.suffix, 1
        while target.exists():
            target = target.with_name(f"{stem}_{n}{suffix}")
            n += 1
        return target


def _is_attachment(resp: httpx.Response) -> bool:
    return "attachment" in resp.headers.get("content-disposition", "").lower()


def _filename(resp: httpx.Response) -> str:
    cd = resp.headers.get("content-disposition", "")
    match = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I) or re.search(
        r'filename="?([^";]+)"?', cd, re.I
    )
    if match:
        name = Path(httpx.URL("http://x/" + match.group(1).strip()).path).name
        if name:
            return name
    tail = Path(resp.request.url.path).name or "download"
    ext = mimetypes.guess_extension(resp.headers.get("content-type", "").split(";")[0].strip()) or ""
    return tail if "." in tail else tail + ext


def _open_files(files: dict[str, str | list[str]], stack: ExitStack) -> list[tuple[str, tuple]]:
    out: list[tuple[str, tuple]] = []
    for field_name, paths in files.items():
        for raw in [paths] if isinstance(paths, str) else paths:
            p = Path(raw).expanduser()
            if not p.is_file():
                raise MediKeepError(f"File not found for upload: {p}")
            mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            out.append((field_name, (p.name, stack.enter_context(p.open("rb")), mime)))
    return out


def _stringify_form(form: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in form.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, dict) or (
            isinstance(v, list) and not all(isinstance(i, (str, int, float)) for i in v)
        ):
            out[k] = json.dumps(v)
        else:
            out[k] = v
    return out


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:500]
    if isinstance(data, dict):
        return str(data.get("detail") or data.get("message") or data)
    return str(data)
