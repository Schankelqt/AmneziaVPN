from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import ClientRecord, TrafficSample

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_AUTH_USER", raising=False)
    monkeypatch.delenv("ADMIN_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("BOT_API_TOKEN", raising=False)
    db = SessionLocal()
    try:
        db.query(TrafficSample).delete()
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

    time_resp = client.get("/v1/time")
    assert time_resp.status_code == 200
    assert time_resp.json()["timezone"] == "Europe/Moscow"


def test_site_requires_basic_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_AUTH_USER", "admin")
    monkeypatch.setenv("ADMIN_AUTH_PASSWORD", "secret")
    assert client.get("/").status_code == 401
    ok = client.get("/", auth=("admin", "secret"))
    assert ok.status_code == 200
    assert client.get("/health").status_code == 200


def test_client_lifecycle_with_user_name_and_stats_filters() -> None:
    create_resp = client.post(
        "/v1/clients",
        json={
            "telegram_user_id": 123456789,
            "user_name": "kirill",
            "plan_days": 30,
            "remark": "pilot-user",
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["active"] is True
    assert created["user_name"] == "kirill"

    client_id = created["client_id"]

    renew_resp = client.post(f"/v1/clients/{client_id}/renew", json={"add_days": 7})
    assert renew_resp.status_code == 200

    config_resp = client.get(f"/v1/clients/{client_id}/config")
    assert config_resp.status_code == 200

    qrcode_resp = client.get(f"/v1/clients/{client_id}/qrcode.svg")
    assert qrcode_resp.status_code == 200
    assert "svg" in qrcode_resp.text.lower()

    list_resp = client.get("/v1/clients")
    assert list_resp.status_code == 200
    assert any(item["user_name"] == "kirill" for item in list_resp.json())

    stats_resp = client.get("/v1/stats/traffic?scale=day&user_ids=123456789")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert "totals" in stats
    assert "per_user" in stats
    assert "series_24h" in stats

    logs_resp = client.get("/v1/logs/traffic?limit=10")
    assert logs_resp.status_code == 200
    assert "items" in logs_resp.json()

    bad_user_filter = client.get("/v1/stats/traffic?user_ids=abc")
    assert bad_user_filter.status_code == 422

    bad_date = client.get("/v1/stats/traffic?date_from=2026-99-99")
    assert bad_date.status_code == 422

    revoke_resp = client.post(f"/v1/clients/{client_id}/revoke")
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["active"] is False

    renew_after_revoke = client.post(f"/v1/clients/{client_id}/renew", json={"add_days": 1})
    assert renew_after_revoke.status_code == 409


def test_admin_reboot_disabled_without_credentials() -> None:
    resp = client.post("/v1/admin/reboot")
    assert resp.status_code == 503


def test_admin_reboot_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_AUTH_USER", "admin")
    monkeypatch.setenv("ADMIN_AUTH_PASSWORD", "correct")
    resp = client.post("/v1/admin/reboot", auth=("admin", "wrong"))
    assert resp.status_code == 401


def test_bot_endpoints_require_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_API_TOKEN", "bot-secret")
    assert client.get("/v1/bot/users/123/active-access").status_code == 401
    assert (
        client.get(
            "/v1/bot/users/123/active-access",
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )


def test_bot_wireguard_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_API_TOKEN", "bot-secret")
    headers = {"Authorization": "Bearer bot-secret"}

    provision_resp = client.post(
        "/v1/bot/users/555/provision",
        headers=headers,
        json={"plan_days": 30, "user_name": "kirill", "remark": "tg-bot", "recreate_if_exists": False},
    )
    assert provision_resp.status_code == 200
    provisioned = provision_resp.json()
    assert provisioned["telegram_user_id"] == 555
    assert provisioned["user_name"] == "kirill"
    client_id = provisioned["client_id"]

    assert client.get("/v1/bot/users/555/active-access", headers=headers).status_code == 200

    provision_again_resp = client.post(
        "/v1/bot/users/555/provision",
        headers=headers,
        json={"plan_days": 30, "remark": "tg-bot", "recreate_if_exists": False},
    )
    assert provision_again_resp.status_code == 200
    assert provision_again_resp.json()["client_id"] == client_id

    renew_resp = client.post("/v1/bot/users/555/renew", headers=headers, json={"add_days": 3})
    assert renew_resp.status_code == 200

    qr_resp = client.get("/v1/bot/users/555/qrcode.svg", headers=headers)
    assert qr_resp.status_code == 200
    assert "svg" in qr_resp.text.lower()

    revoke_resp = client.post("/v1/bot/users/555/revoke", headers=headers)
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["active"] is False

    assert client.get("/v1/bot/users/555/active-access", headers=headers).status_code == 404


def test_bot_provision_recreate_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_API_TOKEN", "bot-secret")
    headers = {"Authorization": "Bearer bot-secret"}

    first = client.post(
        "/v1/bot/users/777/provision",
        headers=headers,
        json={"plan_days": 30, "remark": "one", "recreate_if_exists": False},
    )
    assert first.status_code == 200
    first_id = first.json()["client_id"]

    second = client.post(
        "/v1/bot/users/777/provision",
        headers=headers,
        json={"plan_days": 30, "remark": "two", "recreate_if_exists": True},
    )
    assert second.status_code == 200
    assert second.json()["client_id"] != first_id


@patch("app.main.subprocess.run")
def test_admin_reboot_schedules(mock_run: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_AUTH_USER", "admin")
    monkeypatch.setenv("ADMIN_AUTH_PASSWORD", "secret")
    resp = client.post("/v1/admin/reboot", auth=("admin", "secret"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "scheduled"
    assert data["delay_minutes"] == 1
    assert mock_run.called
