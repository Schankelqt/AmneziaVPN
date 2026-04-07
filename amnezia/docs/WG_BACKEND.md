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
nano .env   # WG_HOST=ваш публичный IP или домен, WG_EASY_PASSWORD=сильный пароль
docker compose up -d
docker compose ps
```

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

## Часть C — связка с control_plane (следующий этап разработки)

Сейчас в коде используется `MockProvider`. Нужно реализовать, например, **`WgEasyProvider`**:

1. Вызовы HTTP API wg-easy (или чтение/запись через официально поддерживаемый механизм версии 15 — смотреть документацию wg-easy для вашего тега образа).
2. `create_client` → создать peer, вернуть **текст конфига** для пользователя.
3. `revoke_client` → удалить peer.
4. `get_config` → отдать актуальный конфиг.

Переключение провайдера — через переменные окружения в `.env` control_plane (например `VPN_PROVIDER=wgeasy` + URL + токен/пароль для API).

### Про Amnezia-клиент

Стандартный **WireGuard** конфиг из wg-easy обычно импортируется в клиенты WG. **AmneziaWG** — отдельный протокол с обфускацией; если вам критично именно AWG, уточните совместимость или используйте стек Amnezia для AWG отдельно. Для массовых продаж часто достаточно классического WG и обычных клиентов; Amnezia можно оставить как опцию для «сложных» регионов.

---

## Порядок работ (чеклист)

1. systemd для control plane — готово по инструкции выше.
2. nginx + HTTPS для админки/API — по `DEPLOY.md`.
3. wg-easy поднят, UDP 51820 открыт, UI проверен через туннель.
4. Реализовать `WgEasyProvider` и переключить `app/main.py` с `MockProvider`.
5. Подключить Telegram-бот к API control_plane с секретом в заголовке.
