from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from .base import VpnProvider


@dataclass(frozen=True)
class WgEasyConfig:
    base_url: str
    username: str
    password: str
    verify_tls: bool = True
    timeout_seconds: float = 10.0


class WgEasyProvider(VpnProvider):
    """WireGuard Easy v15 adapter via HTTP API."""

    def __init__(self, config: WgEasyConfig) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._auth = (config.username, config.password)
        self._verify_tls = config.verify_tls
        self._timeout = config.timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        expected_status: set[int] | None = None,
    ) -> httpx.Response:
        try:
            with httpx.Client(
                base_url=self._base_url,
                auth=self._auth,
                verify=self._verify_tls,
                timeout=self._timeout,
            ) as client:
                response = client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"wg-easy request failed: {exc}") from exc

        if expected_status and response.status_code not in expected_status:
            raise RuntimeError(
                f"wg-easy returned unexpected status {response.status_code} for {method} {path}: "
                f"{response.text[:500]}"
            )

        return response

    def create_client(self, client_id: str, remark: str) -> tuple[str, str]:
        # wg-easy requires unique human-readable name.
        display_name = (remark or "horizonnetvpn-client").strip()[:48]
        unique_name = f"{display_name}-{client_id[:8]}"
        # Some wg-easy v15 builds require expiresAt in create payload.
        # Access period is currently enforced by control_plane logic, so we set
        # a long horizon in backend and revoke explicitly via API when needed.
        expires_at = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()

        created = self._request(
            "POST",
            "/api/client",
            json={"name": unique_name, "expiresAt": expires_at},
            expected_status={200, 201},
        ).json()

        provider_ref = str(created.get("clientId", "")).strip()
        if not provider_ref:
            raise RuntimeError(f"wg-easy create_client missing clientId in response: {created}")

        config = self.get_config(provider_ref)
        return provider_ref, config

    def revoke_client(self, provider_ref: str) -> None:
        response = self._request("DELETE", f"/api/client/{provider_ref}")
        if response.status_code == 404:
            raise KeyError(f"Unknown provider_ref: {provider_ref}")
        if response.status_code not in {200, 204}:
            raise RuntimeError(
                f"wg-easy revoke_client unexpected status {response.status_code}: {response.text[:500]}"
            )

    def get_config(self, provider_ref: str) -> str:
        response = self._request("GET", f"/api/client/{provider_ref}/configuration")
        if response.status_code == 404:
            raise KeyError(f"Unknown provider_ref: {provider_ref}")
        if response.status_code != 200:
            raise RuntimeError(
                f"wg-easy get_config unexpected status {response.status_code}: {response.text[:500]}"
            )
        return response.text

    def get_qr_svg(self, provider_ref: str) -> str:
        response = self._request("GET", f"/api/client/{provider_ref}/qrcode.svg")
        if response.status_code == 404:
            raise KeyError(f"Unknown provider_ref: {provider_ref}")
        if response.status_code != 200:
            raise RuntimeError(
                f"wg-easy get_qr_svg unexpected status {response.status_code}: {response.text[:500]}"
            )
        return response.text
