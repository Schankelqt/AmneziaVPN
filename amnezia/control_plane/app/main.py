import base64
import os
import secrets
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response

from .provider.base import VpnProvider
from .provider.mock import MockProvider
from .provider.wgeasy import WgEasyConfig, WgEasyProvider
from .schemas import (
    ClientResponse,
    CreateClientRequest,
    RenewClientRequest,
)

app = FastAPI(title="HorizonNetVPN Amnezia Control Plane", version="0.1.0")
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

clients: dict[str, dict] = {}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_provider() -> tuple[str, VpnProvider]:
    provider_name = os.environ.get("VPN_PROVIDER", "mock").strip().lower()
    if provider_name == "mock":
        return "mock", MockProvider()

    if provider_name == "wgeasy":
        base_url = os.environ.get("WG_EASY_BASE_URL", "").strip()
        username = os.environ.get("WG_EASY_USERNAME", "").strip()
        password = os.environ.get("WG_EASY_PASSWORD", "").strip()
        timeout_raw = os.environ.get("WG_EASY_TIMEOUT_SECONDS", "10").strip()
        if not base_url or not username or not password:
            raise RuntimeError(
                "VPN_PROVIDER=wgeasy requires WG_EASY_BASE_URL, WG_EASY_USERNAME, WG_EASY_PASSWORD"
            )
        return "wgeasy", WgEasyProvider(
            WgEasyConfig(
                base_url=base_url,
                username=username,
                password=password,
                verify_tls=_env_bool("WG_EASY_VERIFY_TLS", True),
                timeout_seconds=float(timeout_raw or "10"),
            )
        )

    raise RuntimeError(f"Unsupported VPN_PROVIDER: {provider_name}")


provider_kind, provider = _build_provider()

_http_basic = HTTPBasic(auto_error=False)


def _admin_basic_credentials() -> tuple[str, str]:
    user = os.environ.get("ADMIN_AUTH_USER", "").strip()
    password = os.environ.get("ADMIN_AUTH_PASSWORD", "").strip()
    return user, password


def _admin_basic_configured() -> bool:
    user, password = _admin_basic_credentials()
    return bool(user and password)


def _credentials_tuple_valid(username: str, password: str) -> bool:
    expected_user, expected_password = _admin_basic_credentials()
    if not expected_user or not expected_password:
        return False
    return secrets.compare_digest(username, expected_user) and secrets.compare_digest(
        password, expected_password
    )


def _parse_basic_authorization(header: str | None) -> tuple[str, str] | None:
    if not header or not header.startswith("Basic "):
        return None
    try:
        raw = base64.b64decode(header[6:].strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    idx = raw.find(":")
    if idx == -1:
        return None
    return raw[:idx], raw[idx + 1 :]


def _authorization_header_allows_access(header: str | None) -> bool:
    parsed = _parse_basic_authorization(header)
    if not parsed:
        return False
    u, p = parsed
    return _credentials_tuple_valid(u, p)


@app.middleware("http")
async def enforce_admin_site_auth(request: Request, call_next):
    """When ADMIN_AUTH_* are set, require HTTP Basic for all routes except /health."""
    if not _admin_basic_configured():
        return await call_next(request)
    if request.url.path == "/health":
        return await call_next(request)
    if not _authorization_header_allows_access(request.headers.get("Authorization")):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="HorizonNetVPN Admin"'},
        )
    return await call_next(request)


def _build_response(client: dict) -> ClientResponse:
    return ClientResponse(
        client_id=client["client_id"],
        telegram_user_id=client["telegram_user_id"],
        active=client["active"],
        expires_at=client["expires_at"],
        config=client["config"],
        provider_ref=client["provider_ref"],
    )


def _rate_for_client(record: dict) -> tuple[int, int]:
    seed = int(record["telegram_user_id"]) % 100
    rx_rate = 200 + (seed * 3)
    tx_rate = 120 + (seed * 2)
    return rx_rate, tx_rate


def _traffic_until(record: dict, at_time: datetime) -> tuple[int, int]:
    start = record["created_at"]
    stop = record["revoked_at"] or at_time
    end = min(stop, at_time)
    if end <= start:
        return 0, 0
    seconds = int((end - start).total_seconds())
    rx_rate, tx_rate = _rate_for_client(record)
    return seconds * rx_rate, seconds * tx_rate


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def require_admin_basic(
    credentials: HTTPBasicCredentials | None = Depends(_http_basic),
) -> None:
    """HTTP Basic for reboot; same credentials as site-wide auth when configured."""
    if not _admin_basic_configured():
        raise HTTPException(
            status_code=503,
            detail="Admin reboot is disabled. Set ADMIN_AUTH_USER and ADMIN_AUTH_PASSWORD.",
        )
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    if not _credentials_tuple_valid(credentials.username, credentials.password):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.post("/v1/admin/reboot")
def admin_reboot(_auth=Depends(require_admin_basic)) -> dict[str, str | int]:
    """Schedule OS reboot in 1 minute. Requires HTTP Basic (ADMIN_AUTH_* in .env)."""
    try:
        subprocess.run(
            ["/sbin/shutdown", "-r", "+1", "HorizonNetVPN control-plane admin reboot"],
            check=True,
            timeout=15,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="shutdown binary not found (expected /sbin/shutdown on Linux).",
        ) from None
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=f"shutdown failed: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=500, detail=f"shutdown timed out: {exc}") from exc
    return {
        "status": "scheduled",
        "delay_minutes": 1,
        "message": "System reboot is scheduled in 1 minute.",
    }


@app.get("/")
def frontend() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/v1/clients", response_model=list[ClientResponse])
def list_clients() -> list[ClientResponse]:
    records = sorted(clients.values(), key=lambda item: item["expires_at"], reverse=True)
    return [_build_response(item) for item in records]


@app.get("/v1/stats/traffic")
def traffic_stats() -> dict:
    now = datetime.now(tz=timezone.utc)
    protocol = "wireguard-wgeasy" if provider_kind == "wgeasy" else "amneziawg-mock"

    per_user = []
    total_rx = 0
    total_tx = 0
    for item in clients.values():
        rx_bytes, tx_bytes = _traffic_until(item, now)
        total_rx += rx_bytes
        total_tx += tx_bytes
        per_user.append(
            {
                "client_id": item["client_id"],
                "telegram_user_id": item["telegram_user_id"],
                "active": item["active"],
                "expires_at": item["expires_at"],
                "rx_bytes": rx_bytes,
                "tx_bytes": tx_bytes,
                "total_bytes": rx_bytes + tx_bytes,
            }
        )

    per_user.sort(key=lambda user: user["total_bytes"], reverse=True)

    series = []
    for offset in range(23, -1, -1):
        point_time = now - timedelta(hours=offset)
        rx_point = 0
        tx_point = 0
        for item in clients.values():
            rx_bytes, tx_bytes = _traffic_until(item, point_time)
            rx_point += rx_bytes
            tx_point += tx_bytes
        series.append(
            {
                "ts": point_time.isoformat(),
                "rx_bytes": rx_point,
                "tx_bytes": tx_point,
                "total_bytes": rx_point + tx_point,
            }
        )

    return {
        "protocol": protocol,
        "updated_at": now.isoformat(),
        "totals": {
            "rx_bytes": total_rx,
            "tx_bytes": total_tx,
            "total_bytes": total_rx + total_tx,
        },
        "per_user": per_user,
        "series_24h": series,
    }


@app.post("/v1/clients", response_model=ClientResponse)
def create_client(payload: CreateClientRequest) -> ClientResponse:
    client_id = str(uuid4())
    try:
        provider_ref, config = provider.create_client(client_id=client_id, remark=payload.remark)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    expires_at = datetime.now(tz=timezone.utc) + timedelta(days=payload.plan_days)

    record = {
        "client_id": client_id,
        "telegram_user_id": payload.telegram_user_id,
        "provider_ref": provider_ref,
        "config": config,
        "expires_at": expires_at,
        "created_at": datetime.now(tz=timezone.utc),
        "revoked_at": None,
        "active": True,
    }
    clients[client_id] = record
    return _build_response(record)


@app.post("/v1/clients/{client_id}/renew", response_model=ClientResponse)
def renew_client(client_id: str, payload: RenewClientRequest) -> ClientResponse:
    record = clients.get(client_id)
    if not record:
        raise HTTPException(status_code=404, detail="Client not found")
    if not record["active"]:
        raise HTTPException(status_code=409, detail="Client is revoked")

    record["expires_at"] = record["expires_at"] + timedelta(days=payload.add_days)
    return _build_response(record)


@app.post("/v1/clients/{client_id}/revoke", response_model=ClientResponse)
def revoke_client(client_id: str) -> ClientResponse:
    record = clients.get(client_id)
    if not record:
        raise HTTPException(status_code=404, detail="Client not found")
    if not record["active"]:
        return _build_response(record)

    try:
        provider.revoke_client(record["provider_ref"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record["revoked_at"] = datetime.now(tz=timezone.utc)
    record["active"] = False
    return _build_response(record)


@app.get("/v1/clients/{client_id}/config", response_model=ClientResponse)
def get_client_config(client_id: str) -> ClientResponse:
    record = clients.get(client_id)
    if not record:
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        record["config"] = provider.get_config(record["provider_ref"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _build_response(record)


@app.get("/v1/clients/{client_id}/qrcode.svg")
def get_client_qr_svg(client_id: str) -> Response:
    record = clients.get(client_id)
    if not record:
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        qr_svg = provider.get_qr_svg(record["provider_ref"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=qr_svg, media_type="image/svg+xml")
