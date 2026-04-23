#!/usr/bin/env bash
set -euo pipefail

PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-horizonnetvpn.ru}"
ADMIN_DOMAIN="${ADMIN_DOMAIN:-admin.horizonnetvpn.ru}"
BOT_TOKEN="${BOT_API_TOKEN:-}"
TEST_UID="${TEST_UID:-775766895}"

echo "== Local health checks =="
curl -fsS http://127.0.0.1:8088/health
curl -fsS http://127.0.0.1:8090/health

echo "== Host-header checks before/after nginx reload =="
curl -fsS -H "Host: ${PUBLIC_DOMAIN}" http://127.0.0.1:8088/ >/dev/null
curl -fsS -H "Host: ${ADMIN_DOMAIN}" http://127.0.0.1:8090/health >/dev/null

echo "== HTTPS checks after DNS/TLS =="
curl -fsS "https://${PUBLIC_DOMAIN}/health"
curl -fsS "https://${ADMIN_DOMAIN}/health"

if [[ -n "${BOT_TOKEN}" ]]; then
  echo "== Bot API check =="
  curl -fsS -H "Authorization: Bearer ${BOT_TOKEN}" \
    "https://${ADMIN_DOMAIN}/v1/bot/users/${TEST_UID}/active-access" || true
else
  echo "BOT_API_TOKEN not set; skip bot endpoint smoke check."
fi

echo "Smoke checks completed."
