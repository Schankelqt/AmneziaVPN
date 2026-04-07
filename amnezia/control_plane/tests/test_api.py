from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_frontend_and_health() -> None:
    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert "HorizonNetVPN Control Plane" in root_resp.text

    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"

    stats_resp = client.get("/v1/stats/traffic")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert "totals" in stats
    assert "per_user" in stats
    assert "series_24h" in stats


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
