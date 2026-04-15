# Amnezia Integration (Isolated from 3-x-ui)

This folder contains a new, standalone control-plane for issuing and revoking VPN access for a Telegram bot workflow, without changing anything in `3-x-ui/`.

## What is implemented

- `control_plane/` - FastAPI service with endpoints:
  - `GET /` - lightweight frontend UI
  - `POST /v1/clients` - create client + issue config
  - `POST /v1/clients/{client_id}/renew` - extend access
  - `POST /v1/clients/{client_id}/revoke` - revoke access
  - `GET /v1/clients/{client_id}/config` - return current config
  - `GET /v1/clients` - list clients for admin UI
  - `GET /v1/stats/traffic` - protocol totals + per-user traffic + 24h series
- Provider abstraction for VPN backend integration.
- `MockProvider` for safe local testing before wiring to production VPN backend.
- API tests (`pytest`) for basic lifecycle.

## Server sizing guidance

Based on Amnezia docs for self-hosted:

- Minimum: 1 vCPU, 1 GB RAM, 10 GB SSD, public IPv4.
- Recommended for 10+ simultaneous users: 2 vCPU, 2 GB RAM.

Your current VPS (`1 vCPU / 1 GB RAM / 15 GB SSD`) fits **minimum** and is enough for pilot/testing and a small number of active users.

## Amnezia licensing/pricing summary

- For self-hosted mode, Amnezia docs state the app is free and users pay for VPS rental.
- You do not need a separate paid Amnezia API plan for this self-hosted setup.
- Paid plans on Amnezia website refer to their service offerings, not a mandatory fee for running your own server.

## Quick start (local)

```bash
cd amnezia/control_plane
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload --port 8090
```

Open `http://127.0.0.1:8090` for the web UI.

## Traffic statistics

The admin UI includes traffic metrics and charts:

- Total inbound/outbound traffic for the protocol.
- Per-user traffic usage.
- 24-hour chart and top-user chart.

Current implementation uses deterministic mock traffic in `MockProvider` mode by default.
You can switch to real WireGuard backend via `VPN_PROVIDER=wgeasy` and `WG_EASY_*` env variables.

## Deploy

See `DEPLOY.md` for GitHub -> VPS deployment with systemd + nginx.

## WireGuard backend (wg-easy)

See `docs/WG_BACKEND.md` — Docker + wg-easy, firewall, и план интеграции с `VpnProvider` вместо `MockProvider`.

## Next production step

Switch provider in `amnezia/control_plane/.env`:

- `VPN_PROVIDER=mock` for safe local testing.
- `VPN_PROVIDER=wgeasy` for real backend integration (`WG_EASY_BASE_URL`, `WG_EASY_USERNAME`, `WG_EASY_PASSWORD` required).

The service API contract stays unchanged for the Telegram bot.
