from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


@dataclass
class VlessAccess:
    outline_id: str
    access_url: str


def is_configured() -> bool:
    return bool(_env("XUI_BASE_URL") and _env("XUI_USERNAME") and _env("XUI_PASSWORD"))


def _build_vless_reality_link(client_uuid: str, name: str) -> str:
    host = _env("VLESS_REALITY_SERVER_NAME")
    if not host and _env("XUI_BASE_URL"):
        parsed = urlparse(_env("XUI_BASE_URL"))
        host = (parsed.hostname or "").strip()
    if not host:
        raise RuntimeError("VLESS_REALITY_SERVER_NAME or XUI_BASE_URL host is required")

    port = int(_env("VLESS_REALITY_PORT", "443"))
    pbk = _env("VLESS_REALITY_PUBLIC_KEY")
    sid = _env("VLESS_REALITY_SHORT_ID")
    sni = _env("VLESS_REALITY_SNI")
    fp = _env("VLESS_REALITY_FINGERPRINT", "random")

    return (
        f"vless://{client_uuid}@{host}:{port}"
        f"?type=tcp"
        f"&security=reality"
        f"&encryption=none"
        f"&pbk={pbk}"
        f"&sni={sni}"
        f"&sid={sid}"
        f"&fp={fp}"
        f"&spx=%2F"
        f"#{name}"
    )


async def provision_vless_access(name: str) -> VlessAccess:
    if not is_configured():
        raise RuntimeError("XUI_BASE_URL/XUI_USERNAME/XUI_PASSWORD are not configured")

    base_url = _env("XUI_BASE_URL").rstrip("/")
    username = _env("XUI_USERNAME")
    password = _env("XUI_PASSWORD")
    inbound_id = int(_env("XUI_INBOUND_ID_REALITY", "0"))
    if inbound_id <= 0:
        raise RuntimeError("XUI_INBOUND_ID_REALITY must be set")

    client_uuid = str(uuid4())
    settings_str = json.dumps(
        {
            "clients": [
                {
                    "id": client_uuid,
                    "email": name,
                    "enable": True,
                    "flow": "",
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": 0,
                    "tgId": "",
                    "subId": "",
                }
            ]
        },
        separators=(",", ":"),
    )

    async with httpx.AsyncClient(base_url=base_url, timeout=20.0, verify=True) as client:
        login_res = await client.post("/login", json={"username": username, "password": password})
        login_res.raise_for_status()

        add_res = await client.post(
            "/panel/api/inbounds/addClient",
            json={
                "id": inbound_id,
                "settings": settings_str,
                "totalGB": 0,
                "expiryTime": 0,
            },
        )
        add_res.raise_for_status()
        payload = add_res.json()
        if isinstance(payload, dict) and payload.get("success") is False:
            raise RuntimeError(f"3X-UI addClient failed: {payload.get('msg') or payload}")

    access_url = _build_vless_reality_link(client_uuid, name)
    return VlessAccess(outline_id=client_uuid, access_url=access_url)


async def revoke_vless_access(outline_id: str) -> bool:
    if not is_configured():
        return False
    base_url = _env("XUI_BASE_URL").rstrip("/")
    username = _env("XUI_USERNAME")
    password = _env("XUI_PASSWORD")
    inbound_id = int(_env("XUI_INBOUND_ID_REALITY", "0"))
    if inbound_id <= 0:
        return False

    async with httpx.AsyncClient(base_url=base_url, timeout=20.0, verify=True) as client:
        login_res = await client.post("/login", json={"username": username, "password": password})
        login_res.raise_for_status()
        del_res = await client.post(f"/panel/api/inbounds/{inbound_id}/delClient/{outline_id}", json={})
        if not del_res.is_success:
            return False
        try:
            payload = del_res.json()
        except Exception:
            return True
        if isinstance(payload, dict) and payload.get("success") is False:
            return False
        return True
