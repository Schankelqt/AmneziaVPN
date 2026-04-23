# HorizonNetVPN Control Plane API Spec

This document describes the HTTP API of `amnezia/control_plane` (FastAPI), including admin endpoints, bot integration endpoints, and traffic analytics.

## Base URL

- Local/container: `http://127.0.0.1:8090`
- Public admin/API access through reverse proxy: `https://admin.horizonnetvpn.ru`

## Authentication

There are two auth modes:

- **Admin HTTP Basic** (`ADMIN_AUTH_USER`, `ADMIN_AUTH_PASSWORD`)
  - Protects UI and non-bot endpoints.
  - Excludes `/health`.
- **Bot Bearer Token** (`BOT_API_TOKEN`)
  - Required for `/v1/bot/*`.
  - Header: `Authorization: Bearer <BOT_API_TOKEN>`

## Timezone and Date Semantics

- Service timezone: `Europe/Moscow`.
- API datetime fields are serialized as ISO-8601 with timezone offset.
- Traffic filters use date-only values (`YYYY-MM-DD`) in Moscow timezone.

## Data Models

### ClientResponse

```json
{
  "client_id": "uuid",
  "telegram_user_id": 775766895,
  "user_name": "kirill",
  "active": true,
  "expires_at": "2026-05-20T12:00:00+03:00",
  "config": "[Interface] ...",
  "provider_ref": "1"
}
```

## Health and Diagnostics

### `GET /health`

- Purpose: liveness check.
- Auth: none.
- Response:

```json
{ "status": "ok" }
```

### `GET /v1/db/health`

- Purpose: database connectivity check (`SELECT 1`).
- Auth: admin basic (if configured).
- Response:

```json
{ "status": "ok" }
```

### `GET /v1/time`

- Purpose: current backend time in Moscow and UTC.
- Auth: admin basic (if configured).
- Response:

```json
{
  "timezone": "Europe/Moscow",
  "backend_time_moscow": "2026-04-15T16:40:00+03:00",
  "backend_time_utc": "2026-04-15T13:40:00+00:00"
}
```

### `GET /v1/logs/traffic?limit=100`

- Purpose: recent traffic journal samples.
- Auth: admin basic (if configured).
- Query params:
  - `limit`: `1..500` (default `100`)
- Response:

```json
{
  "items": [
    {
      "sample_at": "2026-04-15T16:40:00+03:00",
      "client_id": "uuid",
      "telegram_user_id": 775766895,
      "user_name": "kirill",
      "raw_rx_bytes": 1048576,
      "raw_tx_bytes": 524288,
      "rx_bytes": 1024,
      "tx_bytes": 512,
      "total_bytes": 1536
    }
  ],
  "note": "WireGuard does not expose destination services/domains without DPI."
}
```

## Admin UI Endpoint

### `GET /admin`

- Returns static admin UI page.
- Auth: admin basic (if configured).

## Client Management (General)

### `GET /v1/clients`

- List all clients.
- Auth: admin basic (if configured).
- Response: `ClientResponse[]`.

### `POST /v1/clients`

- Create a client.
- Auth: admin basic (if configured).
- Request:

```json
{
  "telegram_user_id": 775766895,
  "user_name": "kirill",
  "plan_days": 30,
  "remark": "pilot-user"
}
```

- Response: `ClientResponse`.
- Possible errors:
  - `502` provider failure
  - `409` active client already exists for this Telegram user

### `POST /v1/clients/{client_id}/renew`

- Extend expiry by `add_days`.
- Auth: admin basic (if configured).
- Request:

```json
{ "add_days": 30 }
```

- Response: `ClientResponse`.
- Errors:
  - `404` client not found
  - `409` client revoked

### `POST /v1/clients/{client_id}/revoke`

- Revoke client access in provider and mark inactive.
- Auth: admin basic (if configured).
- Response: `ClientResponse`.

### `GET /v1/clients/{client_id}/config`

- Fetch latest WireGuard config from provider.
- Auth: admin basic (if configured).
- Response: `ClientResponse`.

### `GET /v1/clients/{client_id}/qrcode.svg`

- Returns SVG QR code for selected client.
- Auth: admin basic (if configured).
- Content-Type: `image/svg+xml`.

## Traffic Analytics

### `GET /v1/stats/traffic`

- Purpose: summary, top users, and time series.
- Auth: admin basic (if configured).
- Query params:
  - `scale`: `day | week | month` (default `day`)
  - `date_from`: `YYYY-MM-DD` (optional)
  - `date_to`: `YYYY-MM-DD` (optional)
  - `user_ids`: comma-separated positive Telegram IDs (optional)

If `date_from/date_to` are provided, they override scale window.

- Response:

```json
{
  "protocol": "wireguard-wgeasy",
  "updated_at": "2026-04-15T16:40:00+03:00",
  "scale": "week",
  "date_from": "2026-04-08",
  "date_to": "2026-04-15",
  "selected_user_ids": [775766895],
  "totals": {
    "rx_bytes": 100000,
    "tx_bytes": 50000,
    "total_bytes": 150000
  },
  "per_user": [
    {
      "telegram_user_id": 775766895,
      "user_name": "kirill",
      "rx_bytes": 100000,
      "tx_bytes": 50000,
      "total_bytes": 150000,
      "client_id": "uuid",
      "active": true,
      "expires_at": "2026-05-20T12:00:00+03:00"
    }
  ],
  "series_24h": [
    {
      "ts": "2026-04-15T00:00:00+03:00",
      "rx_bytes": 1024,
      "tx_bytes": 512,
      "total_bytes": 1536
    }
  ],
  "available_users": [
    {
      "telegram_user_id": 775766895,
      "user_name": "kirill",
      "active": true
    }
  ]
}
```

- Errors:
  - `422` invalid `user_ids` or date format
  - `502` provider API failure

## Bot Integration Endpoints

All endpoints below require:

```http
Authorization: Bearer <BOT_API_TOKEN>
```

### `GET /v1/bot/users/{telegram_user_id}/active-access`

- Returns current active client for user.
- Response: `ClientResponse`.
- Errors:
  - `404` active client not found

### `POST /v1/bot/users/{telegram_user_id}/provision`

- Create active client if none exists.
- Idempotent when `recreate_if_exists=false`.
- Request:

```json
{
  "user_name": "kirill",
  "plan_days": 30,
  "remark": "tg-bot",
  "recreate_if_exists": false
}
```

- Behavior:
  - if active exists and `recreate_if_exists=false`: return existing
  - if active exists and `recreate_if_exists=true`: revoke existing, create new
- Response: `ClientResponse`.

### `POST /v1/bot/users/{telegram_user_id}/renew`

- Extend active client expiry.
- Request:

```json
{ "add_days": 30 }
```

- Response: `ClientResponse`.
- Error: `404` if no active client.

### `POST /v1/bot/users/{telegram_user_id}/revoke`

- Revoke active client.
- Response: `ClientResponse`.
- Error: `404` if no active client.

### `GET /v1/bot/users/{telegram_user_id}/qrcode.svg`

- Returns SVG QR code for active client.
- Content-Type: `image/svg+xml`.
- Error: `404` if no active client.

## Admin Server Control

### `POST /v1/admin/reboot`

- Schedules OS reboot in one minute.
- Requires admin basic auth configured.
- Response:

```json
{
  "status": "scheduled",
  "delay_minutes": 1,
  "message": "System reboot is scheduled in 1 minute."
}
```

## Error Format

FastAPI standard:

```json
{ "detail": "message" }
```

## Practical Integration Notes

- Bot should treat `404 active-access` as "no active WG yet".
- Bot should treat `409` from provision as recoverable/idempotent race and retry `active-access`.
- For QR, consume raw SVG (`image/svg+xml`) rather than expecting JSON.
