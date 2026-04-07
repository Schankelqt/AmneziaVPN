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

Current implementation uses deterministic mock traffic in `MockProvider` mode.
After switching to a real provider adapter, these numbers should be replaced with real WireGuard/AmneziaWG counters.

## Deploy

See `DEPLOY.md` for GitHub -> VPS deployment with systemd + nginx.

## Next production step

Replace `MockProvider` with a real backend adapter:

- Preferred: managed WireGuard backend with stable API.
- Fallback: controlled SSH automation on the VPN host.

The service API contract stays unchanged for the Telegram bot.
