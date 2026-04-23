# Telegram Bot Integration Playbook

This playbook describes how to integrate an external Telegram bot with HorizonNetVPN `control_plane` for WireGuard lifecycle operations.

## 1) Integration Prerequisites

- `control_plane` is deployed and reachable from bot server.
- `BOT_API_TOKEN` is configured in `control_plane`.
- Bot sends:

```http
Authorization: Bearer <BOT_API_TOKEN>
```

- Base URL example:
  - Internal: `http://127.0.0.1:8090`
  - Through domain/reverse proxy: `https://admin.horizonnetvpn.ru`

## 2) Core Endpoint Set

- `GET /v1/bot/users/{telegram_user_id}/active-access`
- `POST /v1/bot/users/{telegram_user_id}/provision`
- `POST /v1/bot/users/{telegram_user_id}/renew`
- `POST /v1/bot/users/{telegram_user_id}/revoke`
- `GET /v1/bot/users/{telegram_user_id}/qrcode.svg`

Support:

- `GET /health`
- `GET /v1/db/health`
- `GET /v1/time`

## 3) Canonical Bot Scenarios

## 3.1 Purchase WG access (first provision)

### Trigger

- Payment was confirmed successfully in bot billing flow.

### Steps

1. Call `POST /provision` with `recreate_if_exists=false`.
2. If success, send config and optionally QR.
3. Save returned `client_id` and `provider_ref` in bot DB.

### Request

```json
{
  "user_name": "kirill",
  "plan_days": 30,
  "remark": "tg-purchase-<order-id>",
  "recreate_if_exists": false
}
```

### Expected behavior

- New user: creates fresh WG access.
- Existing active user: idempotently returns existing active access.

## 3.2 Renew existing WG access

### Trigger

- Payment for extension confirmed.

### Steps

1. Call `POST /renew` with `add_days`.
2. Update local bot subscription metadata.

### Request

```json
{ "add_days": 30 }
```

### Fallback behavior

- If `404 Active client not found`, decide policy:
  - either call `provision`,
  - or show error and ask user to recreate profile.

## 3.3 Revoke WG access

### Trigger

- Subscription ended/cancelled/manual revoke.

### Steps

1. Call `POST /revoke`.
2. Mark WG access inactive in bot DB.

If service returns `404`, treat as idempotent revoke (already inactive).

## 3.4 Get active config for "My Keys"

### Steps

1. Call `GET /active-access`.
2. Show config in Telegram message or file.
3. Optional QR button -> call `/qrcode.svg`.

## 3.5 QR flow

### Steps

1. Call `GET /qrcode.svg`.
2. Receive SVG body (`image/svg+xml`).
3. Send to user as image/document in Telegram.

Note: endpoint returns raw SVG text, not JSON.

## 4) VLESS <-> WireGuard Switching Strategy (Bot-side Orchestration)

This service is WireGuard-only. Protocol switching is orchestrated by your bot/service layer.

Recommended switch flow:

1. Validate active paid subscription in bot DB.
2. Provision target protocol first.
3. If target success -> revoke previous protocol.
4. Commit local state (`selected_protocol`) only after successful target provision.

### 4.1 VLESS -> WG

1. `POST /v1/bot/users/{id}/provision` (`recreate_if_exists=false`)
2. On success: deactivate/revoke VLESS key in 3x-ui
3. Persist `selected_protocol=wireguard`

### 4.2 WG -> VLESS

1. Provision VLESS in 3x-ui
2. On success: `POST /v1/bot/users/{id}/revoke`
3. Persist `selected_protocol=vless`

## 5) Error Handling Contract

## 5.1 Authentication

- `401` -> wrong/missing bearer token
- `503` on bot endpoints -> `BOT_API_TOKEN` missing in control plane

Bot action: alert ops + retry only after config fix.

## 5.2 Resource state

- `404 Active client not found`
  - in renew/revoke/get active/qr
  - treat as "no active WG currently"

## 5.3 Provider failures

- `502` -> upstream wg-easy failure/network/auth mismatch.

Bot action:

- retry with backoff,
- if still failing, mark operation pending/manual review.

## 5.4 Validation errors

- `422` invalid payload/query format.

Bot action:

- bug in caller; do not retry blindly.

## 6) Retry and Idempotency Policy

Recommended default:

- Timeout per request: `5-10s`
- Retry: `2-3` attempts for `502/timeout`
- Backoff: `0.5s`, `1s`, `2s`

Idempotent-safe operations:

- `provision` with `recreate_if_exists=false`
- `revoke` (treat `404` as already revoked)

Potentially non-idempotent:

- `provision` with `recreate_if_exists=true` (intentionally rotates key)

## 7) Suggested Bot DB Fields (minimum)

- `telegram_user_id`
- `selected_protocol` (`vless|wireguard`)
- `wg_client_id` (control-plane `client_id`)
- `wg_provider_ref` (wg-easy reference)
- `wg_active` (bool)
- `wg_expires_at`
- `last_sync_at`
- `last_sync_error`

## 8) Observability and Health Checks

Bot-side periodic checks:

1. `GET /health`
2. `GET /v1/db/health`
3. `GET /v1/time`

If any fail:

- disable protocol switch actions temporarily,
- surface maintenance message to users,
- notify operator.

## 9) Security Operational Practices

- Rotate `BOT_API_TOKEN` on leakage suspicion.
- Never log full bearer token in bot logs.
- Keep control-plane behind TLS when called over public network.
- Prefer IP allowlist between bot server and VPN server if possible.

## 10) Minimal Smoke Test Script (Operator)

```bash
export API="http://127.0.0.1:8090"
export TOKEN="REDACTED"
export UID="775766895"

curl -sS "$API/health"
curl -sS "$API/v1/db/health"

curl -sS -H "Authorization: Bearer $TOKEN" \
  "$API/v1/bot/users/$UID/active-access"

curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan_days":30,"remark":"bot-smoke","recreate_if_exists":false}' \
  "$API/v1/bot/users/$UID/provision"

curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"add_days":7}' \
  "$API/v1/bot/users/$UID/renew"

curl -i -H "Authorization: Bearer $TOKEN" \
  "$API/v1/bot/users/$UID/qrcode.svg"
```

## 11) Rollout Plan

1. Enable feature flag in bot for WireGuard on internal users only.
2. Run dual-mode support (`vless` + `wireguard`) for a pilot cohort.
3. Monitor support incidents, provider errors, and retry rates.
4. Expand rollout gradually.
