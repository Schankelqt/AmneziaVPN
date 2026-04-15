from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import ClientRecord
from app.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_admin_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_AUTH_USER", raising=False)
    monkeypatch.delenv("ADMIN_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("BOT_API_TOKEN", raising=False)
    db = SessionLocal()
    try:
        db.query(ClientRecord).delete()
        db.commit()
    finally:
        db.close()


def test_frontend_and_health() -> None:
    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert "HorizonNetVPN" in root_resp.text

    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"

    db_health_resp = client.get("/v1/db/health")
    assert db_health_resp.status_code == 200
    assert db_health_resp.json()["status"] == "ok"

    stats_resp = client.get("/v1/stats/traffic")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert "totals" in stats
    assert "per_user" in stats
    assert "series_24h" in stats


def test_site_requires_basic_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_AUTH_USER", "admin")
    monkeypatch.setenv("ADMIN_AUTH_PASSWORD", "secret")
    assert client.get("/").status_code == 401
    ok = client.get("/", auth=("admin", "secret"))
    assert ok.status_code == 200
    assert client.get("/health").status_code == 200


def test_client_lifecycle() -> None:
    create_resp = client.post(
        "/v1/clients",
        json={"telegram_user_id": 123456789, "plan_days": 30, "remark": "pilot-user"},
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["active"] is True
    assert "mock-" in created["provider_ref"]
    assert "[Interface]" in created["config"]

    client_id = created["client_id"]

    renew_resp = client.post(f"/v1/clients/{client_id}/renew", json={"add_days": 7})
    assert renew_resp.status_code == 200
    renewed = renew_resp.json()
    assert renewed["client_id"] == client_id
    assert renewed["active"] is True

    config_resp = client.get(f"/v1/clients/{client_id}/config")
    assert config_resp.status_code == 200
    assert config_resp.json()["client_id"] == client_id

    qrcode_resp = client.get(f"/v1/clients/{client_id}/qrcode.svg")
    assert qrcode_resp.status_code == 200
    assert "svg" in qrcode_resp.text.lower()

    list_resp = client.get("/v1/clients")
    assert list_resp.status_code == 200
    assert any(item["client_id"] == client_id for item in list_resp.json())

    stats_resp = client.get("/v1/stats/traffic")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["totals"]["total_bytes"] >= 0
    assert any(item["client_id"] == client_id for item in stats["per_user"])
    assert len(stats["series_24h"]) == 24

    revoke_resp = client.post(f"/v1/clients/{client_id}/revoke")
    assert revoke_resp.status_code == 200
    revoked = revoke_resp.json()
    assert revoked["active"] is False

    renew_after_revoke = client.post(f"/v1/clients/{client_id}/renew", json={"add_days": 1})
    assert renew_after_revoke.status_code == 409


def test_admin_reboot_disabled_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_AUTH_USER", raising=False)
    monkeypatch.delenv("ADMIN_AUTH_PASSWORD", raising=False)
    resp = client.post("/v1/admin/reboot")
    assert resp.status_code == 503


def test_admin_reboot_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_AUTH_USER", "admin")
    monkeypatch.setenv("ADMIN_AUTH_PASSWORD", "correct")
    resp = client.post("/v1/admin/reboot", auth=("admin", "wrong"))
    assert resp.status_code == 401


def test_bot_endpoints_require_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_API_TOKEN", "bot-secret")
    no_auth = client.get("/v1/bot/users/123/active-access")
    assert no_auth.status_code == 401
    wrong_auth = client.get(
        "/v1/bot/users/123/active-access",
        headers={"Authorization": "Bearer wrong"},
    )
    assert wrong_auth.status_code == 401


def test_bot_wireguard_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_API_TOKEN", "bot-secret")
    headers = {"Authorization": "Bearer bot-secret"}

    provision_resp = client.post(
        "/v1/bot/users/555/provision",
        headers=headers,
        json={"plan_days": 30, "remark": "tg-bot", "recreate_if_exists": False},
    )
    assert provision_resp.status_code == 200
    provisioned = provision_resp.json()
    assert provisioned["telegram_user_id"] == 555
    client_id = provisioned["client_id"]

    get_active_resp = client.get("/v1/bot/users/555/active-access", headers=headers)
    assert get_active_resp.status_code == 200
    assert get_active_resp.json()["client_id"] == client_id

    provision_again_resp = client.post(
        "/v1/bot/users/555/provision",
        headers=headers,
        json={"plan_days": 30, "remark": "tg-bot", "recreate_if_exists": False},
    )
    assert provision_again_resp.status_code == 200
    assert provision_again_resp.json()["client_id"] == client_id

    renew_resp = client.post("/v1/bot/users/555/renew", headers=headers, json={"add_days": 3})
    assert renew_resp.status_code == 200
    assert renew_resp.json()["client_id"] == client_id

    qr_resp = client.get("/v1/bot/users/555/qrcode.svg", headers=headers)
    assert qr_resp.status_code == 200
    assert "svg" in qr_resp.text.lower()

    revoke_resp = client.post("/v1/bot/users/555/revoke", headers=headers)
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["active"] is False

    missing_active_resp = client.get("/v1/bot/users/555/active-access", headers=headers)
    assert missing_active_resp.status_code == 404


@patch("app.main.subprocess.run")
def test_admin_reboot_schedules(
    mock_run: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_AUTH_USER", "admin")
    monkeypatch.setenv("ADMIN_AUTH_PASSWORD", "secret")
    resp = client.post("/v1/admin/reboot", auth=("admin", "secret"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "scheduled"
    assert data["delay_minutes"] == 1
    assert mock_run.called
