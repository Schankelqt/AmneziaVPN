import base64
import os
import secrets
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy.orm import Session

from .db import get_db, init_db
from .models import ClientRecord, TrafficSample
from .provider.base import VpnProvider
from .provider.mock import MockProvider
from .provider.wgeasy import WgEasyConfig, WgEasyProvider
from .schemas import (
    BotProvisionRequest,
    BotRenewRequest,
    ClientResponse,
    CreateClientRequest,
    RenewClientRequest,
)

app = FastAPI(title="HorizonNetVPN Amnezia Control Plane", version="0.1.0")
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
init_db()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _host_without_port(host: str | None) -> str:
    if not host:
        return ""
    return host.split(":")[0].strip().lower()


def _csv_env_set(name: str) -> set[str]:
    raw = os.environ.get(name, "")
    result: set[str] = set()
    for item in raw.split(","):
        val = _host_without_port(item)
        if val:
            result.add(val)
    return result


def _build_provider() -> tuple[str, VpnProvider]:
    provider_name = os.environ.get("VPN_PROVIDER", "mock").strip().lower()
    if provider_name == "mock":
        return "mock", MockProvider()

    if provider_name == "wgeasy":
        base_url = os.environ.get("WG_EASY_BASE_URL", "").strip()
        auth_mode = os.environ.get("WG_EASY_AUTH_MODE", "basic").strip().lower()
        username = os.environ.get("WG_EASY_USERNAME", "").strip()
        password = os.environ.get("WG_EASY_PASSWORD", "").strip()
        timeout_raw = os.environ.get("WG_EASY_TIMEOUT_SECONDS", "10").strip()
        if not base_url:
            raise RuntimeError("VPN_PROVIDER=wgeasy requires WG_EASY_BASE_URL")
        if auth_mode not in {"basic", "none"}:
            raise RuntimeError("WG_EASY_AUTH_MODE must be one of: basic, none")
        if auth_mode == "basic" and (not username or not password):
            raise RuntimeError(
                "WG_EASY_AUTH_MODE=basic requires WG_EASY_USERNAME and WG_EASY_PASSWORD"
            )
        return "wgeasy", WgEasyProvider(
            WgEasyConfig(
                base_url=base_url,
                username=username,
                password=password,
                auth_mode=auth_mode,
                verify_tls=_env_bool("WG_EASY_VERIFY_TLS", True),
                timeout_seconds=float(timeout_raw or "10"),
            )
        )

    raise RuntimeError(f"Unsupported VPN_PROVIDER: {provider_name}")


provider_kind, provider = _build_provider()
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

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
    if request.url.path.startswith("/v1/bot/"):
        return await call_next(request)
    if not _authorization_header_allows_access(request.headers.get("Authorization")):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="HorizonNetVPN Admin"'},
        )
    return await call_next(request)


@app.middleware("http")
async def enforce_admin_domain(request: Request, call_next):
    """
    Keep admin UI/API off the public customer domain.
    Bot API and health endpoints stay reachable as service endpoints.
    """
    path = request.url.path
    if path == "/health" or path.startswith("/v1/bot/"):
        return await call_next(request)

    # If not configured, keep backwards-compatible behavior.
    admin_hosts = _csv_env_set("ADMIN_ALLOWED_HOSTS")
    if not admin_hosts:
        return await call_next(request)

    host = _host_without_port(request.headers.get("host"))
    if host in admin_hosts:
        return await call_next(request)

    return Response(status_code=404, content="Not Found")


def _build_response(client: ClientRecord) -> ClientResponse:
    return ClientResponse(
        client_id=client.client_id,
        telegram_user_id=client.telegram_user_id,
        user_name=client.user_name,
        active=client.active,
        expires_at=_to_moscow(client.expires_at),
        config=client.config,
        provider_ref=client.provider_ref,
    )


def _now_moscow() -> datetime:
    return datetime.now(tz=MOSCOW_TZ)


def _to_moscow(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MOSCOW_TZ)


def _active_client_for_telegram_user(db: Session, telegram_user_id: int) -> ClientRecord | None:
    return (
        db.query(ClientRecord)
        .filter(
            ClientRecord.telegram_user_id == telegram_user_id,
            ClientRecord.active.is_(True),
        )
        .order_by(ClientRecord.expires_at.desc(), ClientRecord.created_at.desc())
        .first()
    )


def _create_client_record(
    db: Session, telegram_user_id: int, user_name: str | None, plan_days: int, remark: str
) -> ClientRecord:
    client_id = str(uuid4())
    try:
        provider_ref, config = provider.create_client(client_id=client_id, remark=remark)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    expires_at = _now_moscow() + timedelta(days=plan_days)

    record = ClientRecord(
        client_id=client_id,
        telegram_user_id=telegram_user_id,
        user_name=(user_name or "").strip() or None,
        provider_ref=provider_ref,
        config=config,
        expires_at=expires_at,
        created_at=_now_moscow(),
        revoked_at=None,
        active=True,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Keep provider/backend consistent when DB rejects duplicate active entry.
        try:
            provider.revoke_client(provider_ref)
        except Exception:
            pass
        raise HTTPException(
            status_code=409,
            detail="Active client already exists for this telegram_user_id",
        ) from exc
    db.refresh(record)
    return record


def _parse_user_id_filter(raw: str | None) -> set[int]:
    if not raw:
        return set()
    result: set[int] = set()
    for chunk in raw.split(","):
        value = chunk.strip()
        if not value:
            continue
        try:
            parsed = int(value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid user_ids value: {value}. Use comma-separated positive integers.",
            ) from None
        if parsed > 0:
            result.add(parsed)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid user_ids value: {value}. Use positive integers.",
            )
    return result


def _series_window(
    now: datetime, scale: Literal["day", "week", "month"], date_from: date | None, date_to: date | None
) -> tuple[datetime, datetime, timedelta]:
    if date_from or date_to:
        today = now.date()
        from_date = date_from or today
        to_date = date_to or from_date
        if to_date < from_date:
            from_date, to_date = to_date, from_date
        start = datetime.combine(from_date, time.min, tzinfo=MOSCOW_TZ)
        end = datetime.combine(to_date, time.max, tzinfo=MOSCOW_TZ)
        span_days = (to_date - from_date).days + 1
        bucket = timedelta(hours=1) if span_days <= 2 else timedelta(days=1)
        return start, end, bucket
    if scale == "week":
        return now - timedelta(days=7), now, timedelta(days=1)
    if scale == "month":
        return now - timedelta(days=30), now, timedelta(days=1)
    return now - timedelta(hours=24), now, timedelta(hours=1)


def _rate_for_client(record: ClientRecord) -> tuple[int, int]:
    seed = int(record.telegram_user_id) % 100
    rx_rate = 200 + (seed * 3)
    tx_rate = 120 + (seed * 2)
    return rx_rate, tx_rate


def _traffic_until(record: ClientRecord, at_time: datetime) -> tuple[int, int]:
    start = record.created_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    stop = record.revoked_at or at_time
    if stop.tzinfo is None:
        stop = stop.replace(tzinfo=timezone.utc)
    end = min(stop, at_time)
    if end <= start:
        return 0, 0
    seconds = int((end - start).total_seconds())
    rx_rate, tx_rate = _rate_for_client(record)
    return seconds * rx_rate, seconds * tx_rate


def _store_traffic_samples(
    db: Session, now: datetime, records: list[ClientRecord], snapshot: dict[str, dict[str, int]]
) -> None:
    for item in records:
        traffic = snapshot.get(item.provider_ref) or snapshot.get(str(item.provider_ref)) or {}
        raw_rx = int(traffic.get("rx_bytes") or 0)
        raw_tx = int(traffic.get("tx_bytes") or 0)
        previous = (
            db.query(TrafficSample)
            .filter(TrafficSample.client_id == item.client_id)
            .order_by(TrafficSample.sample_at.desc())
            .first()
        )
        if previous:
            prev_raw_rx = int(previous.raw_rx_bytes or previous.rx_bytes or 0)
            prev_raw_tx = int(previous.raw_tx_bytes or previous.tx_bytes or 0)
            delta_rx = max(0, raw_rx - prev_raw_rx)
            delta_tx = max(0, raw_tx - prev_raw_tx)
        else:
            delta_rx = 0
            delta_tx = 0
        sample = TrafficSample(
            sample_at=now,
            client_id=item.client_id,
            telegram_user_id=item.telegram_user_id,
            user_name=item.user_name,
            raw_rx_bytes=raw_rx,
            raw_tx_bytes=raw_tx,
            rx_bytes=delta_rx,
            tx_bytes=delta_tx,
            total_bytes=delta_rx + delta_tx,
        )
        db.add(sample)
    db.commit()


def _build_series_from_samples(
    start: datetime,
    end: datetime,
    bucket: timedelta,
    samples: list[dict[str, int | datetime]],
) -> list[dict[str, int | str]]:
    series = []
    cursor = start
    while cursor <= end:
        next_cursor = cursor + bucket
        rx_sum = 0
        tx_sum = 0
        for sample in samples:
            sample_at = sample["sample_at"]
            if isinstance(sample_at, datetime) and cursor <= sample_at < next_cursor:
                rx_sum += int(sample.get("delta_rx", 0))
                tx_sum += int(sample.get("delta_tx", 0))
        series.append(
            {
                "ts": cursor.isoformat(),
                "rx_bytes": rx_sum,
                "tx_bytes": tx_sum,
                "total_bytes": rx_sum + tx_sum,
            }
        )
        cursor = next_cursor
    return series


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/db/health")
def db_health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database is unavailable: {exc}") from exc
    return {"status": "ok"}


@app.get("/v1/time")
def current_time() -> dict[str, str]:
    now_moscow = _now_moscow()
    now_utc = now_moscow.astimezone(timezone.utc)
    return {
        "timezone": "Europe/Moscow",
        "backend_time_moscow": now_moscow.isoformat(),
        "backend_time_utc": now_utc.isoformat(),
    }


@app.get("/v1/logs/traffic")
def traffic_logs(limit: int = 100, db: Session = Depends(get_db)) -> dict:
    bounded_limit = max(1, min(limit, 500))
    rows = (
        db.query(TrafficSample)
        .order_by(TrafficSample.sample_at.desc())
        .limit(bounded_limit)
        .all()
    )
    items = [
        {
            "sample_at": _to_moscow(row.sample_at),
            "client_id": row.client_id,
            "telegram_user_id": row.telegram_user_id,
            "user_name": row.user_name,
            "raw_rx_bytes": row.raw_rx_bytes,
            "raw_tx_bytes": row.raw_tx_bytes,
            "rx_bytes": row.rx_bytes,
            "tx_bytes": row.tx_bytes,
            "total_bytes": row.total_bytes,
        }
        for row in rows
    ]
    return {"items": items, "note": "WireGuard does not expose destination services/domains without DPI."}


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


def _bot_api_token() -> str:
    return os.environ.get("BOT_API_TOKEN", "").strip()


def require_bot_token(request: Request) -> None:
    expected_token = _bot_api_token()
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="Bot API is disabled. Set BOT_API_TOKEN.",
        )
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = auth_header[7:].strip()
    if not token or not secrets.compare_digest(token, expected_token):
        raise HTTPException(status_code=401, detail="Invalid bot token")


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


@app.get("/admin")
def frontend() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "horizonnetvpn-control-plane",
        "admin_ui": "/admin",
        "health": "/health",
    }


@app.get("/v1/clients", response_model=list[ClientResponse])
def list_clients(db: Session = Depends(get_db)) -> list[ClientResponse]:
    records = (
        db.query(ClientRecord)
        .filter(ClientRecord.active.is_(True))
        .order_by(ClientRecord.expires_at.desc())
        .all()
    )
    return [_build_response(item) for item in records]


@app.get("/v1/stats/traffic")
def traffic_stats(
    scale: Literal["day", "week", "month"] = "day",
    date_from: date | None = None,
    date_to: date | None = None,
    user_ids: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    now = _now_moscow()
    protocol = "wireguard-wgeasy" if provider_kind == "wgeasy" else "amneziawg-mock"
    records = db.query(ClientRecord).all()
    selected_user_ids = _parse_user_id_filter(user_ids)
    if selected_user_ids:
        records = [item for item in records if int(item.telegram_user_id) in selected_user_ids]

    if provider_kind == "wgeasy":
        if not isinstance(provider, WgEasyProvider):
            raise HTTPException(status_code=500, detail="Provider mismatch for wgeasy stats")
        try:
            snapshot = provider.get_traffic_snapshot()
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        # Journal traffic samples so we can filter by date/range later.
        _store_traffic_samples(db, now, records, snapshot)
        start, end, bucket = _series_window(now, scale, date_from, date_to)
        sample_query = (
            db.query(TrafficSample)
            .filter(TrafficSample.sample_at >= start, TrafficSample.sample_at <= end)
            .order_by(TrafficSample.sample_at.asc())
        )
        if selected_user_ids:
            sample_query = sample_query.filter(TrafficSample.telegram_user_id.in_(selected_user_ids))
        sample_rows = sample_query.all()

        sample_dicts: list[dict[str, int | datetime]] = []
        for row in sample_rows:
            sample_dicts.append(
                {
                    "sample_at": _to_moscow(row.sample_at),
                    "telegram_user_id": int(row.telegram_user_id),
                    "delta_rx": int(row.rx_bytes),
                    "delta_tx": int(row.tx_bytes),
                }
            )
        series = _build_series_from_samples(start, end, bucket, sample_dicts)

        per_user = []
        total_rx = 0
        total_tx = 0
        for record in records:
            traffic = snapshot.get(record.provider_ref) or snapshot.get(str(record.provider_ref)) or {}
            rx = int(traffic.get("rx_bytes") or 0)
            tx = int(traffic.get("tx_bytes") or 0)
            total_rx += rx
            total_tx += tx
            per_user.append(
                {
                    "telegram_user_id": record.telegram_user_id,
                    "user_name": record.user_name,
                    "rx_bytes": rx,
                    "tx_bytes": tx,
                    "total_bytes": rx + tx,
                    "client_id": record.client_id,
                    "active": record.active,
                    "expires_at": _to_moscow(record.expires_at),
                }
            )

        per_user.sort(key=lambda user: int(user["total_bytes"]), reverse=True)
        available_users = [
            {
                "telegram_user_id": item.telegram_user_id,
                "user_name": item.user_name,
                "active": item.active,
            }
            for item in db.query(ClientRecord).order_by(ClientRecord.telegram_user_id.asc()).all()
        ]
        return {
            "protocol": protocol,
            "updated_at": now.isoformat(),
            "scale": scale,
            "date_from": start.date().isoformat(),
            "date_to": end.date().isoformat(),
            "selected_user_ids": sorted(selected_user_ids),
            "totals": {
                "rx_bytes": total_rx,
                "tx_bytes": total_tx,
                "total_bytes": total_rx + total_tx,
            },
            "per_user": per_user,
            "series_24h": series,
            "available_users": available_users,
        }

    per_user = []
    total_rx = 0
    total_tx = 0
    for item in records:
        rx_bytes, tx_bytes = _traffic_until(item, now)
        total_rx += rx_bytes
        total_tx += tx_bytes
        per_user.append(
            {
                "client_id": item.client_id,
                "telegram_user_id": item.telegram_user_id,
                "active": item.active,
                "expires_at": _to_moscow(item.expires_at),
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
        for item in records:
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
        "scale": scale,
        "date_from": now.date().isoformat(),
        "date_to": now.date().isoformat(),
        "selected_user_ids": sorted(selected_user_ids),
        "totals": {
            "rx_bytes": total_rx,
            "tx_bytes": total_tx,
            "total_bytes": total_rx + total_tx,
        },
        "per_user": per_user,
        "series_24h": series,
        "available_users": [
            {
                "telegram_user_id": item.telegram_user_id,
                "user_name": item.user_name,
                "active": item.active,
            }
            for item in records
        ],
    }


@app.post("/v1/clients", response_model=ClientResponse)
def create_client(payload: CreateClientRequest, db: Session = Depends(get_db)) -> ClientResponse:
    record = _create_client_record(
        db=db,
        telegram_user_id=payload.telegram_user_id,
        user_name=payload.user_name,
        plan_days=payload.plan_days,
        remark=payload.remark,
    )
    return _build_response(record)


@app.post("/v1/clients/{client_id}/renew", response_model=ClientResponse)
def renew_client(
    client_id: str, payload: RenewClientRequest, db: Session = Depends(get_db)
) -> ClientResponse:
    record = db.get(ClientRecord, client_id)
    if not record:
        raise HTTPException(status_code=404, detail="Client not found")
    if not record.active:
        raise HTTPException(status_code=409, detail="Client is revoked")

    record.expires_at = record.expires_at + timedelta(days=payload.add_days)
    db.commit()
    db.refresh(record)
    return _build_response(record)


@app.post("/v1/clients/{client_id}/revoke", response_model=ClientResponse)
def revoke_client(client_id: str, db: Session = Depends(get_db)) -> ClientResponse:
    record = db.get(ClientRecord, client_id)
    if not record:
        raise HTTPException(status_code=404, detail="Client not found")
    if not record.active:
        return _build_response(record)

    try:
        provider.revoke_client(record.provider_ref)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record.revoked_at = _now_moscow()
    record.active = False
    db.commit()
    db.refresh(record)
    return _build_response(record)


@app.get("/v1/clients/{client_id}/config", response_model=ClientResponse)
def get_client_config(client_id: str, db: Session = Depends(get_db)) -> ClientResponse:
    record = db.get(ClientRecord, client_id)
    if not record:
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        record.config = provider.get_config(record.provider_ref)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.commit()
    db.refresh(record)
    return _build_response(record)


@app.get("/v1/clients/{client_id}/qrcode.svg")
def get_client_qr_svg(client_id: str, db: Session = Depends(get_db)) -> Response:
    record = db.get(ClientRecord, client_id)
    if not record:
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        qr_svg = provider.get_qr_svg(record.provider_ref)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=qr_svg, media_type="image/svg+xml")


@app.get("/v1/bot/users/{telegram_user_id}/active-access", response_model=ClientResponse)
def bot_get_active_access(
    telegram_user_id: int,
    _auth: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
) -> ClientResponse:
    record = _active_client_for_telegram_user(db, telegram_user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Active client not found")
    return _build_response(record)


@app.post("/v1/bot/users/{telegram_user_id}/provision", response_model=ClientResponse)
def bot_provision_access(
    telegram_user_id: int,
    payload: BotProvisionRequest,
    _auth: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
) -> ClientResponse:
    active = _active_client_for_telegram_user(db, telegram_user_id)
    if active and not payload.recreate_if_exists:
        if payload.user_name and active.user_name != payload.user_name:
            active.user_name = payload.user_name
            db.commit()
            db.refresh(active)
        return _build_response(active)
    if active and payload.recreate_if_exists:
        try:
            provider.revoke_client(active.provider_ref)
        except KeyError:
            pass
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        active.revoked_at = _now_moscow()
        active.active = False
        db.commit()
    try:
        record = _create_client_record(
            db=db,
            telegram_user_id=telegram_user_id,
            user_name=payload.user_name,
            plan_days=payload.plan_days,
            remark=payload.remark,
        )
        return _build_response(record)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        latest = _active_client_for_telegram_user(db, telegram_user_id)
        if latest:
            return _build_response(latest)
        raise


@app.post("/v1/bot/users/{telegram_user_id}/renew", response_model=ClientResponse)
def bot_renew_active_access(
    telegram_user_id: int,
    payload: BotRenewRequest,
    _auth: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
) -> ClientResponse:
    record = _active_client_for_telegram_user(db, telegram_user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Active client not found")
    record.expires_at = record.expires_at + timedelta(days=payload.add_days)
    db.commit()
    db.refresh(record)
    return _build_response(record)


@app.post("/v1/bot/users/{telegram_user_id}/revoke", response_model=ClientResponse)
def bot_revoke_active_access(
    telegram_user_id: int,
    _auth: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
) -> ClientResponse:
    record = _active_client_for_telegram_user(db, telegram_user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Active client not found")
    try:
        provider.revoke_client(record.provider_ref)
    except KeyError:
        pass
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record.revoked_at = _now_moscow()
    record.active = False
    db.commit()
    db.refresh(record)
    return _build_response(record)


@app.get("/v1/bot/users/{telegram_user_id}/qrcode.svg")
def bot_get_active_qr_svg(
    telegram_user_id: int,
    _auth: None = Depends(require_bot_token),
    db: Session = Depends(get_db),
) -> Response:
    record = _active_client_for_telegram_user(db, telegram_user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Active client not found")
    try:
        qr_svg = provider.get_qr_svg(record.provider_ref)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=qr_svg, media_type="image/svg+xml")
