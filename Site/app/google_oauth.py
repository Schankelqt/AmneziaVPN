from urllib.parse import urlencode
import os

import httpx


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def google_authorization_url(state: str) -> str:
    web_base = _env("SITE_PUBLIC_BASE_URL", "https://horizonnetvpn.ru").rstrip("/")
    params = {
        "client_id": _env("GOOGLE_CLIENT_ID"),
        "redirect_uri": f"{web_base}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


async def exchange_code_and_get_profile(code: str) -> dict | None:
    client_id = _env("GOOGLE_CLIENT_ID")
    client_secret = _env("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    web_base = _env("SITE_PUBLIC_BASE_URL", "https://horizonnetvpn.ru").rstrip("/")
    redirect_uri = f"{web_base}/auth/google/callback"
    async with httpx.AsyncClient(timeout=20.0) as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code != 200:
            return None
        access_token = token_res.json().get("access_token")
        if not access_token:
            return None
        profile_res = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_res.status_code != 200:
            return None
        return profile_res.json()
