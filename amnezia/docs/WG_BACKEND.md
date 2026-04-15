# WireGuard backend (wg-easy) + дальнейшие шаги

Вы идёте по варианту **B**: отдельный WG backend с API/UI, а `control_plane` вызывает его из `VpnProvider`.

## Часть A — control plane через systemd

На сервере (пути как у вас: `/opt/horizonnetvpn/app`).

### 1) Убедиться, что venv и зависимости стоят

```bash
cd /opt/horizonnetvpn/app/amnezia/control_plane
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

### 2) Скопировать unit из репозитория

С Mac (или с сервера, если репо уже склонирован):

Файл в репо: `amnezia/deploy/horizonnetvpn-control-plane.service`

На сервере:

```bash
sudo cp /opt/horizonnetvpn/app/amnezia/deploy/horizonnetvpn-control-plane.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now horizonnetvpn-control-plane
sudo systemctl status horizonnetvpn-control-plane
```

Сервис слушает **только** `127.0.0.1:8090` — снаружи открывайте через **nginx** (см. `DEPLOY.md` §5).

### 3) Проверка локально на сервере

```bash
curl -sS http://127.0.0.1:8090/health
```

---

## Часть B — Docker + wg-easy

### 1) Установить Docker (Ubuntu 24.04)

```bash
apt update
apt install -y ca-certificates curl
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker compose version
```

### 2) Конфиг и запуск

```bash
cd /opt/horizonnetvpn/app/amnezia/wg_backend
cp .env.example .env
nano .env   # заполните INIT_* (логин/пароль/host/port) для wg-easy v15
docker compose up -d
docker compose ps
```

Важно для `wg-easy:15`:

- v15 не использует legacy переменные `PASSWORD`/`PASSWORD_HASH` из v14.
- Используйте setup wizard в UI или unattended setup через `INIT_*`.
- Для API control plane (`WG_EASY_USERNAME`/`WG_EASY_PASSWORD`) используйте
  обычный пароль (plain), который вы задали в `INIT_PASSWORD`/UI.

### 3) Firewall

Открыть **UDP 51820** (WireGuard). Пример UFW:

```bash
ufw allow 51820/udp
ufw allow OpenSSH
ufw status
```

В панели хостинга (security group) тоже должен быть разрешён **UDP 51820** на публичный IP.

### 4) Web UI wg-easy

В `docker-compose.yml` порт **51821** проброшен только на **127.0.0.1**. Зайти можно так:

**SSH-туннель с Mac:**

```bash
ssh -L 51821:127.0.0.1:51821 root@ВАШ_IP
```

В браузере Mac: `http://127.0.0.1:51821`

Либо позже повесить nginx с Basic Auth на `51821` — не оставляйте панель без пароля в открытом интернете.

---

## Часть C — связка с control_plane

`WgEasyProvider` уже реализован в `control_plane`.

Переключение:

```env
VPN_PROVIDER=wgeasy
WG_EASY_BASE_URL=http://127.0.0.1:51821
WG_EASY_USERNAME=admin
WG_EASY_PASSWORD=<plain password from wg-easy login>
WG_EASY_VERIFY_TLS=false
WG_EASY_TIMEOUT_SECONDS=10
```

Проверка API wg-easy с сервера:

```bash
curl -u 'admin:<plain password>' http://127.0.0.1:51821/api/client
```

### Про Amnezia-клиент

Стандартный **WireGuard** конфиг из wg-easy обычно импортируется в клиенты WG. **AmneziaWG** — отдельный протокол с обфускацией; если вам критично именно AWG, уточните совместимость или используйте стек Amnezia для AWG отдельно. Для массовых продаж часто достаточно классического WG и обычных клиентов; Amnezia можно оставить как опцию для «сложных» регионов.

---

## Порядок работ (чеклист)

1. systemd для control plane — готово по инструкции выше.
2. nginx + HTTPS для админки/API — по `DEPLOY.md`.
3. wg-easy поднят, UDP 51820 открыт, UI проверен через туннель.
4. Переключить `control_plane/.env` на `VPN_PROVIDER=wgeasy` и проверить `GET /v1/stats/traffic` (`protocol=wireguard-wgeasy`).
5. Подключить Telegram-бот к API control_plane с секретом в заголовке.
