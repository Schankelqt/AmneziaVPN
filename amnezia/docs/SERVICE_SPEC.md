# HorizonNetVPN WireGuard Control Plane Service Spec

This file describes the service architecture, runtime model, storage, security model, and operational flows for `amnezia/control_plane`.

## 1. Service Purpose

`control_plane` is a management API and admin UI for WireGuard users with:

- client provisioning/revocation/renewal,
- traffic analytics,
- Telegram bot integration endpoints,
- optional host-level administrative action (reboot).

It is intentionally limited to WireGuard backend orchestration and does not include payment logic.

## 2. High-Level Architecture

- **API/UI Layer:** FastAPI app (`app/main.py`)
- **Provider Layer:** abstraction + implementation (`provider/base.py`, `provider/wgeasy.py`)
- **Persistence Layer:** SQLAlchemy ORM + PostgreSQL/SQLite fallback (`app/db.py`, `app/models.py`)
- **Frontend:** static HTML/CSS/JS served by FastAPI (`app/static/*`)
- **Deployment:** Docker Compose (`amnezia/docker-compose.prod.yml`)

## 3. Runtime Components

### 3.1 `control-plane` container

- Exposes `127.0.0.1:8090` on host.
- Uses env-driven provider selection:
  - `VPN_PROVIDER=mock|wgeasy`
- For production:
  - `VPN_PROVIDER=wgeasy`
  - `WG_EASY_BASE_URL`, `WG_EASY_USERNAME`, `WG_EASY_PASSWORD`
  - `BOT_API_TOKEN`
  - `ADMIN_AUTH_USER`, `ADMIN_AUTH_PASSWORD`

### 3.2 `postgres` container

- Stores clients and traffic samples.
- DB URL is injected in compose using service DNS (`postgres`), not localhost.

### 3.3 `wg-easy` container

- WireGuard backend and API.
- `control-plane` uses basic auth against `wg-easy` API.

### 3.4 Host nginx

- TLS termination and routing remain host-managed.
- Proxies to `127.0.0.1:8090`.
- Existing external stacks (e.g., 3x-ui/panel) are isolated by design.

## 4. Data Model

## 4.1 `clients`

Core managed entity:

- `client_id` (UUID string, PK)
- `telegram_user_id`
- `user_name` (optional Telegram username/display name)
- `provider_ref` (backend client identifier)
- `config` (wireguard config text)
- `expires_at`, `created_at`, `revoked_at`
- `active` (bool)

Invariant:

- At most one active client per `telegram_user_id` (partial unique index).

## 4.2 `traffic_samples`

Traffic journal rows, periodically appended when stats endpoint is called:

- key fields: `sample_at`, `client_id`, `telegram_user_id`, `user_name`
- counters:
  - `raw_rx_bytes`, `raw_tx_bytes` (absolute provider counters),
  - `rx_bytes`, `tx_bytes`, `total_bytes` (delta for interval analytics).

## 5. Authentication and Access Control

Two independent auth channels:

- **Admin Basic auth**
  - protects UI and standard admin API when configured.
- **Bot Bearer auth**
  - required for `/v1/bot/*`.
  - configured via `BOT_API_TOKEN`.

This split allows bot traffic without sharing admin credentials.

## 6. Time and Timezone Policy

- Logical service timezone: `Europe/Moscow`.
- API responses and UI display are aligned to Moscow time.
- Date-range filters are interpreted in Moscow timezone.
- Containers set `TZ=Europe/Moscow` for operational consistency.

## 7. Core Flows

## 7.1 Admin create client

1. Receive create payload (`telegram_user_id`, `user_name`, `plan_days`, `remark`).
2. Create client via provider API.
3. Persist in DB.
4. Return full client response.

Concurrency safety:

- if duplicate active user insert happens, DB unique constraint rejects insert,
- service rolls back and attempts backend cleanup (revoke created provider record),
- returns conflict (`409`).

## 7.2 Bot provision (idempotent)

1. Validate bearer token.
2. Check active client for `telegram_user_id`.
3. If active exists and `recreate_if_exists=false`, return existing.
4. If `recreate_if_exists=true`, revoke existing and create new.

## 7.3 Renew and revoke

- `renew` extends `expires_at`.
- `revoke` calls provider revoke and marks record inactive.

## 7.4 Traffic analytics

1. Pull current per-client counters from provider.
2. Write traffic samples into DB (raw + delta).
3. Build aggregate/top/series from DB samples with requested filters.

## 8. Observability

Available built-in diagnostics:

- `/health`
- `/v1/db/health`
- `/v1/time`
- `/v1/logs/traffic`

Current limitation:

- no structured logging framework/trace IDs yet.

## 9. Known Boundaries and Explicit Non-Goals

- No deep packet inspection (DPI).
- No destination-domain/service logging from WireGuard tunnel contents.
- No payment/billing logic in this service.
- No multi-protocol switch orchestration here (handled by external bot/business layer).

## 10. Reliability and Safety Decisions

- DB-level uniqueness for active user access.
- Provider cleanup on DB conflict to avoid orphaned backend clients.
- Constant-time token/credential comparison.
- Bounded traffic log endpoint.
- Strict request validation for date/user filters.

## 11. Deployment Contract

Required env keys for production (`wgeasy`):

- `VPN_PROVIDER=wgeasy`
- `WG_EASY_BASE_URL`
- `WG_EASY_USERNAME`
- `WG_EASY_PASSWORD`
- `BOT_API_TOKEN`
- `POSTGRES_*` and DB URL (compose injects correct internal URL)
- optional `ADMIN_AUTH_USER/ADMIN_AUTH_PASSWORD`

## 12. Suggested Next Improvements

- Add OpenAPI examples for bot endpoints.
- Add retry/backoff policy around wg-easy calls.
- Add Alembic-based migrations (instead of lightweight startup migrations).
- Add rate limiting for bot endpoints.
- Add audit trail for bot actions (`provision/renew/revoke`) with caller metadata.
