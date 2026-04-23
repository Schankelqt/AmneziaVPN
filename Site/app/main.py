import os
import secrets
import sqlite3
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .db import conn, create_user, init_db, now_iso
from .google_oauth import exchange_code_and_get_profile, google_authorization_url
from .security import hash_password, session_secret, verify_password
from .telegram_auth import verify_telegram_login_widget
from .vless_xui import is_configured as vless_configured, provision_vless_access, revoke_vless_access

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="HorizonNetVPN Site", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    same_site="lax",
    https_only=False,
)
init_db()


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _bot_url() -> str:
    username = _env("SITE_BOT_USERNAME", "").lstrip("@")
    if username:
        return f"https://t.me/{username}"
    return _env("SITE_BOT_URL", "https://t.me/horizonnetvpn_bot")


def _ctx(request: Request, extra: dict | None = None) -> dict:
    uid = request.session.get("uid")
    user = None
    if uid:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (int(uid),)).fetchone()
    data = {
        "request": request,
        "domain": _env("SITE_DOMAIN", "horizonnetvpn.ru"),
        "admin_domain": _env("ADMIN_DOMAIN", "admin.horizonnetvpn.ru"),
        "bot_url": _bot_url(),
        "support_tg": _env("SITE_SUPPORT_TG", "@horizonnetvpn_support"),
        "price_month": _env("SITE_PRICE_MONTH", "299"),
        "price_quarter": _env("SITE_PRICE_QUARTER", "799"),
        "price_year": _env("SITE_PRICE_YEAR", "2490"),
        "logged_in": bool(user),
        "user": user,
        "tg_login_enabled": bool(_env("SITE_TELEGRAM_LOGIN_ENABLED", "false").lower() in {"1", "true", "yes"}),
        "google_enabled": bool(_env("GOOGLE_CLIENT_ID")),
        "flash_error": request.session.pop("flash_error", None),
        "flash_ok": request.session.pop("flash_ok", None),
        "supported_protocols": _supported_protocols(),
    }
    if extra:
        data.update(extra)
    return data


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _set_flash(request: Request, *, err: str | None = None, ok: str | None = None) -> None:
    if err:
        request.session["flash_error"] = err
    if ok:
        request.session["flash_ok"] = ok


def _bot_api_headers() -> dict[str, str]:
    token = _env("SITE_BOT_API_TOKEN")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _control_plane_url() -> str:
    return _env("CONTROL_PLANE_INTERNAL_URL", "http://control-plane:8090").rstrip("/")


def _integration_user_id(user) -> int:
    tg_id = (user["tg_id"] or "").strip() if "tg_id" in user.keys() else ""
    if tg_id:
        try:
            return int(tg_id)
        except ValueError:
            pass
    return int(user["id"])


def _wireguard_user_id(user) -> int | None:
    tg_id = (user["tg_id"] or "").strip() if "tg_id" in user.keys() else ""
    if not tg_id:
        return None
    try:
        return int(tg_id)
    except ValueError:
        return None


def _protocol_backend(protocol: str) -> tuple[str, dict[str, str]]:
    if protocol == "wireguard":
        return _control_plane_url(), _bot_api_headers()
    return "", {}


def _supported_protocols() -> list[str]:
    protocols = ["wireguard"]
    if vless_configured():
        protocols.append("vless")
    return protocols


def _default_protocol_for_user(user) -> str:
    raw = (user["selected_protocol"] or "").strip().lower() if "selected_protocol" in user.keys() else ""
    return raw if raw in {"wireguard", "vless"} else "wireguard"


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _revoke_wireguard_for_user(tg_id: int) -> bool:
    base_url, headers = _protocol_backend("wireguard")
    if not base_url or not headers:
        return False
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{base_url}/v1/bot/users/{tg_id}/revoke", headers=headers)
            return resp.status_code in {200, 404}
    except httpx.HTTPError:
        return False


async def _process_due_protocol_switch_revoke(user) -> None:
    protocol = (user["pending_revoke_protocol"] or "").strip().lower()
    when = _parse_iso(user["pending_revoke_at"])
    if protocol not in {"wireguard", "vless"} or not when:
        return
    if when > datetime.now(timezone.utc):
        return

    ok = False
    ref = (user["pending_revoke_ref"] or "").strip()
    if protocol == "vless" and ref:
        ok = await revoke_vless_access(ref)
    elif protocol == "wireguard":
        tg_id = _wireguard_user_id(user)
        if tg_id is not None:
            ok = await _revoke_wireguard_for_user(tg_id)
    if ok:
        conn.execute(
            "UPDATE users SET pending_revoke_protocol = NULL, pending_revoke_ref = NULL, pending_revoke_at = NULL WHERE id = ?",
            (user["id"],),
        )
        conn.commit()


def _plan_price(plan_days: int) -> int:
    if plan_days == 30:
        return int(_env("SITE_PRICE_MONTH", "299"))
    if plan_days == 90:
        return int(_env("SITE_PRICE_QUARTER", "799"))
    if plan_days == 365:
        return int(_env("SITE_PRICE_YEAR", "2490"))
    raise ValueError("Unsupported plan")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", _ctx(request))


@app.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request):
    return templates.TemplateResponse("pricing.html", _ctx(request))


@app.get("/faq", response_class=HTMLResponse)
def faq(request: Request):
    return templates.TemplateResponse("faq.html", _ctx(request))


@app.get("/contact", response_class=HTMLResponse)
def contact(request: Request):
    return templates.TemplateResponse("contact.html", _ctx(request))


@app.get("/buy")
def buy() -> RedirectResponse:
    return RedirectResponse(url=_bot_url(), status_code=302)


@app.get("/register", response_class=HTMLResponse)
def register_get(request: Request):
    if request.session.get("uid"):
        return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("register.html", _ctx(request))


@app.post("/register")
def register_post(
    request: Request,
    login: str = Form(default=""),
    password: str = Form(default=""),
    password2: str = Form(default=""),
):
    if request.session.get("uid"):
        return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)
    login = login.strip().lower()
    if len(login) < 3:
        _set_flash(request, err="Логин должен быть минимум 3 символа.")
        return RedirectResponse(url="/register", status_code=status.HTTP_303_SEE_OTHER)
    if len(password) < 8:
        _set_flash(request, err="Пароль должен быть минимум 8 символов.")
        return RedirectResponse(url="/register", status_code=status.HTTP_303_SEE_OTHER)
    if password != password2:
        _set_flash(request, err="Пароли не совпадают.")
        return RedirectResponse(url="/register", status_code=status.HTTP_303_SEE_OTHER)
    existing = conn.execute("SELECT id FROM users WHERE login = ?", (login,)).fetchone()
    if existing:
        _set_flash(request, err="Этот логин уже занят.")
        return RedirectResponse(url="/register", status_code=status.HTTP_303_SEE_OTHER)
    user = create_user(login=login, email=None, password_hash=hash_password(password))
    request.session["uid"] = user["id"]
    _set_flash(request, ok=f"Регистрация успешна. Ваш ID: {user['public_id']}")
    return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    if request.session.get("uid"):
        return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("login.html", _ctx(request))


@app.post("/login")
def login_post(request: Request, login: str = Form(...), password: str = Form(...)):
    login = login.strip().lower()
    user = conn.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        _set_flash(request, err="Неверный логин или пароль.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    request.session["uid"] = user["id"]
    return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/auth/google")
def auth_google_start(request: Request):
    if not _env("GOOGLE_CLIENT_ID"):
        _set_flash(request, err="Google login не настроен.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(url=google_authorization_url(state), status_code=302)


@app.get("/auth/google/callback")
async def auth_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error or not code:
        _set_flash(request, err="Ошибка Google OAuth.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if state != request.session.get("oauth_state"):
        _set_flash(request, err="OAuth state не совпал. Повторите вход.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    request.session.pop("oauth_state", None)

    profile = await exchange_code_and_get_profile(code)
    if not profile:
        _set_flash(request, err="Не удалось получить профиль Google.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    google_sub = str(profile.get("sub") or "")
    email = (profile.get("email") or "").strip().lower() or None
    if not google_sub:
        _set_flash(request, err="Профиль Google некорректен.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    user = conn.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
    current_uid = request.session.get("uid")
    if not user and current_uid:
        current_user = conn.execute("SELECT * FROM users WHERE id = ?", (int(current_uid),)).fetchone()
        if current_user:
            taken = conn.execute("SELECT id FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
            if taken and int(taken["id"]) != int(current_user["id"]):
                _set_flash(request, err="Этот Google-аккаунт уже привязан к другому пользователю.")
                return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)
            try:
                conn.execute(
                    "UPDATE users SET google_sub = ?, email = COALESCE(email, ?) WHERE id = ?",
                    (google_sub, email, current_user["id"]),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # race-safe fallback
                pass
            user = conn.execute("SELECT * FROM users WHERE id = ?", (current_user["id"],)).fetchone()
    if not user and email:
        user = conn.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email,)).fetchone()
        if user:
            try:
                conn.execute("UPDATE users SET google_sub = ? WHERE id = ?", (google_sub, user["id"]))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not user:
        try:
            user = create_user(login=None, email=email, password_hash=None, google_sub=google_sub)
        except sqlite3.IntegrityError:
            user = conn.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
            if not user and email:
                user = conn.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email,)).fetchone()
    if not user:
        _set_flash(request, err="Не удалось завершить вход через Google.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    request.session["uid"] = user["id"]
    _set_flash(request, ok=f"Вход через Google успешен. Ваш ID: {user['public_id']}")
    return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/auth/telegram")
async def auth_telegram(request: Request):
    if _env("SITE_TELEGRAM_LOGIN_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        _set_flash(request, err="Вход через Telegram отключен.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    form = dict(await request.form())
    if not form:
        # fallback parse path
        _set_flash(request, err="Пустые данные Telegram.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    bot_token = _env("SITE_BOT_TOKEN")
    try:
        max_age = int(_env("SITE_TELEGRAM_LOGIN_MAX_AGE_SECONDS", "600"))
    except ValueError:
        max_age = 600
    if not verify_telegram_login_widget(form, bot_token, max_age_seconds=max_age):
        _set_flash(request, err="Неверная подпись Telegram Login.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    tg_id = str(form.get("id") or "")
    if not tg_id:
        _set_flash(request, err="Telegram ID не найден.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    current_uid = request.session.get("uid")
    user = conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    if not user and current_uid:
        current_user = conn.execute("SELECT * FROM users WHERE id = ?", (int(current_uid),)).fetchone()
        if current_user:
            try:
                conn.execute("UPDATE users SET tg_id = ? WHERE id = ?", (tg_id, current_user["id"]))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            user = conn.execute("SELECT * FROM users WHERE id = ?", (current_user["id"],)).fetchone()
    if not user:
        try:
            user = create_user(login=None, email=None, password_hash=None, tg_id=tg_id)
        except sqlite3.IntegrityError:
            user = conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    if not user:
        _set_flash(request, err="Не удалось завершить вход через Telegram.")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    request.session["uid"] = user["id"]
    _set_flash(request, ok=f"Вход через Telegram успешен. Ваш ID: {user['public_id']}")
    return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/account", response_class=HTMLResponse)
async def account(request: Request):
    uid = request.session.get("uid")
    if not uid:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (int(uid),)).fetchone()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    await _process_due_protocol_switch_revoke(user)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (int(uid),)).fetchone()
    purchases = conn.execute(
        "SELECT * FROM purchases WHERE user_id = ? ORDER BY id DESC LIMIT 20", (user["id"],)
    ).fetchall()
    return templates.TemplateResponse(
        "account.html",
        _ctx(
            request,
            {
                "purchases": purchases,
                "default_protocol": _default_protocol_for_user(user),
            },
        ),
    )


@app.post("/account/buy")
async def account_buy(request: Request, plan: str = Form(...), protocol: str = Form(...)):
    uid = request.session.get("uid")
    if not uid:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (int(uid),)).fetchone()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    await _process_due_protocol_switch_revoke(user)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (int(uid),)).fetchone()

    plan_map = {"month": 30, "quarter": 90, "year": 365}
    if plan not in plan_map:
        _set_flash(request, err="Неизвестный тариф.")
        return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)
    plan_days = plan_map[plan]
    amount = _plan_price(plan_days)

    if protocol not in _supported_protocols():
        _set_flash(request, err="Выбранный протокол сейчас недоступен.")
        return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)

    ext_user_id = _integration_user_id(user)
    payload: dict = {}
    old_protocol = _default_protocol_for_user(user)
    old_ref = None
    if old_protocol == "vless":
        old_active = conn.execute(
            """
            SELECT * FROM purchases
            WHERE integration_user_id = ? AND protocol = 'vless'
              AND status = 'paid' AND expires_at IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            (ext_user_id,),
        ).fetchone()
        if old_active:
            old_ref = old_active["provider_ref"]

    if protocol == "wireguard":
        wg_user_id = _wireguard_user_id(user)
        if wg_user_id is None:
            _set_flash(
                request,
                err="Для WireGuard-покупки привяжите Telegram-аккаунт (чтобы продление шло в тот же профиль, как в боте).",
            )
            return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)
        base_url, headers = _protocol_backend(protocol)
        if not base_url or not headers:
            _set_flash(request, err="Не задан SITE_BOT_API_TOKEN для выдачи WireGuard ключей.")
            return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)
        op_resp = None
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                for attempt in range(3):
                    try:
                        # Bot-like flow: try renew first, fallback to provision.
                        renew_resp = await client.post(
                            f"{base_url}/v1/bot/users/{wg_user_id}/renew",
                            headers=headers,
                            json={"add_days": plan_days},
                        )
                        if renew_resp.status_code == 404:
                            op_resp = await client.post(
                                f"{base_url}/v1/bot/users/{wg_user_id}/provision",
                                headers=headers,
                                json={
                                    "user_name": user["login"] or user["email"] or user["public_id"],
                                    "plan_days": plan_days,
                                    "remark": f"site-{protocol}-{plan}-{user['public_id']}",
                                    "recreate_if_exists": False,
                                },
                            )
                        else:
                            op_resp = renew_resp
                        if op_resp.status_code in {200, 201}:
                            break
                    except httpx.HTTPError:
                        op_resp = None
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
        except httpx.HTTPError:
            op_resp = None

        if op_resp is None or op_resp.status_code not in {200, 201}:
            _set_flash(request, err="Не удалось выдать/продлить WireGuard ключ.")
            return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)

        async with httpx.AsyncClient(timeout=20.0) as client:
            latest_resp = await client.get(
                f"{base_url}/v1/bot/users/{wg_user_id}/active-access",
                headers=headers,
            )
            if latest_resp.status_code != 200:
                _set_flash(request, err="Операция прошла, но не удалось подтвердить актуальный WireGuard ключ.")
                return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)
            payload = latest_resp.json()
        ext_user_id = wg_user_id

    elif protocol == "vless":
        # Same business semantics as bot: if active key exists, keep key and extend expiry.
        active = conn.execute(
            """
            SELECT * FROM purchases
            WHERE integration_user_id = ? AND protocol = 'vless'
              AND status = 'paid' AND expires_at IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            (ext_user_id,),
        ).fetchone()
        now = datetime.now(timezone.utc)
        current_exp = None
        if active and active["expires_at"]:
            try:
                current_exp = datetime.fromisoformat(str(active["expires_at"]).replace("Z", "+00:00"))
            except ValueError:
                current_exp = None
        if current_exp and current_exp > now:
            new_exp = current_exp + timedelta(days=plan_days)
            payload = {
                "client_id": active["client_id"],
                "provider_ref": active["provider_ref"],
                "config": active["config"],
                "expires_at": new_exp.isoformat(),
            }
        else:
            try:
                created = await provision_vless_access(user["login"] or user["email"] or user["public_id"])
            except Exception:
                _set_flash(request, err="Не удалось выдать VLESS ключ (3x-ui).")
                return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)
            payload = {
                "client_id": created.outline_id,
                "provider_ref": created.outline_id,
                "config": created.access_url,
                "expires_at": (now + timedelta(days=plan_days)).isoformat(),
            }

    if not payload.get("config") or not payload.get("client_id"):
        _set_flash(request, err="Не удалось получить валидный ключ после операции оплаты.")
        return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)

    conn.execute("UPDATE users SET selected_protocol = ? WHERE id = ?", (protocol, user["id"]))
    if old_protocol != protocol:
        # Bot-like graceful switch: provision target first, revoke old protocol after delay.
        pending_revoke_ref = old_ref if old_protocol == "vless" else None
        conn.execute(
            """
            UPDATE users
            SET pending_revoke_protocol = ?, pending_revoke_ref = ?, pending_revoke_at = ?
            WHERE id = ?
            """,
            (
                old_protocol,
                pending_revoke_ref,
                (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                user["id"],
            ),
        )

    conn.execute(
        """
        INSERT INTO purchases (user_id, integration_user_id, protocol, plan_days, amount_rub, status, client_id, provider_ref, config, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user["id"],
            ext_user_id,
            protocol,
            plan_days,
            amount,
            "paid",
            payload.get("client_id"),
            payload.get("provider_ref"),
            payload.get("config"),
            payload.get("expires_at"),
            now_iso(),
        ),
    )
    conn.commit()
    _set_flash(request, ok=f"Тариф успешно активирован ({protocol}). Ключ обновлен/продлен.")
    return RedirectResponse(url="/account", status_code=status.HTTP_303_SEE_OTHER)
