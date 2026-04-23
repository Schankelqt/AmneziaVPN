# Deploy to VPS via GitHub

This guide deploys `amnezia/control_plane` to your server while leaving `3-x-ui` untouched.

## 1) Push project to GitHub

From your local machine:

```bash
cd "/Users/schankel/Desktop/Projects/For Cursor/VPN"
git init
git add .
git commit -m "Add Amnezia control plane and frontend"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

If this repo already exists, just commit and push your current branch.

## 2) Prepare server

On VPS (Ubuntu/Debian):

```bash
apt update
apt install -y git python3 python3-venv python3-pip nginx openssh-client
```

## 2.5) Deploy key (SSH) for GitHub

Use a **deploy key** so the server can `git clone` / `git pull` without your personal password or token. The key lives only on the VPS; you add the **public** half in GitHub.

### Generate a dedicated key on the VPS

Run as the same user that will own the repo (often `root` for `/opt/...`):

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -C "horizonnetvpn-deploy" -f ~/.ssh/github_horizonnetvpn_deploy -N ""
chmod 600 ~/.ssh/github_horizonnetvpn_deploy
```

Show the **public** key and copy it:

```bash
cat ~/.ssh/github_horizonnetvpn_deploy.pub
```

### Add the key in GitHub

1. Open the repository on GitHub → **Settings** → **Deploy keys** → **Add deploy key**.
2. **Title:** e.g. `VPS NL production`.
3. **Key:** paste the contents of `github_horizonnetvpn_deploy.pub`.
4. Enable **Allow write access** only if this server must push to the repo (usually leave **unchecked** = read-only for `pull`).

### Tell SSH to use this key for `github.com`

Create or edit `~/.ssh/config`:

```
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/github_horizonnetvpn_deploy
    IdentitiesOnly yes
```

```bash
chmod 600 ~/.ssh/config
```

### Verify

```bash
ssh -T git@github.com
```

You should see a message that GitHub authenticated you (often “Hi … You’ve successfully authenticated…”).

### Clone URL

Use the SSH form:

`git@github.com:<OWNER>/<REPO>.git`

Example:

```bash
git clone git@github.com:myorg/horizonnetvpn.git app
```

## 3) Clone repo

```bash
mkdir -p /opt/horizonnetvpn
cd /opt/horizonnetvpn
git clone git@github.com:<OWNER>/<REPO>.git app
cd app/amnezia
cp .env.prod.example .env.prod
```

Fill real values in `/opt/horizonnetvpn/app/amnezia/.env.prod`:

- `POSTGRES_PASSWORD`
- `ADMIN_AUTH_PASSWORD`
- `BOT_API_TOKEN` (for Telegram bot -> control-plane API)
- `WG_EASY_PASSWORD`
- `WG_EASY_INIT_PASSWORD`
- `WG_EASY_INIT_HOST` (your public server IP or DNS)
- `SITE_SESSION_SECRET` (long random string for website sessions)
- `SITE_PUBLIC_BASE_URL` (e.g. `https://horizonnetvpn.ru`)

Important for Docker mode:

- Do **not** set `DATABASE_URL` to `127.0.0.1` in `.env.prod`.
- `control-plane` connects to Postgres via Docker service name `postgres`.
- The compose file injects the correct `DATABASE_URL` automatically.

Optional auth providers for website:

- Google OAuth:
  - `GOOGLE_CLIENT_ID`
  - `GOOGLE_CLIENT_SECRET`
- Telegram login widget:
  - `SITE_TELEGRAM_LOGIN_ENABLED=true`
  - `SITE_BOT_TOKEN=<telegram_bot_token>`
  - `SITE_TELEGRAM_LOGIN_MAX_AGE_SECONDS=600`

VLESS on website uses the same 3x-ui model as Telegram bot:

- `XUI_BASE_URL`
- `XUI_USERNAME`
- `XUI_PASSWORD`
- `XUI_INBOUND_ID_REALITY`
- `VLESS_REALITY_SERVER_NAME`
- `VLESS_REALITY_PORT`
- `VLESS_REALITY_PUBLIC_KEY`
- `VLESS_REALITY_SHORT_ID`
- `VLESS_REALITY_SNI`
- `VLESS_REALITY_FINGERPRINT`

External Telegram bot integration with WireGuard control-plane:

- in bot `.env` set `WG_ENABLED=true`
- set `WG_CP_BASE_URL=https://admin.horizonnetvpn.ru`
- set `WG_CP_BOT_API_TOKEN` equal to `BOT_API_TOKEN` from `amnezia/.env.prod`

## 4) Start full Docker stack (site + control-plane + postgres + wg-easy)

```bash
cd /opt/horizonnetvpn/app/amnezia
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

Health checks:

```bash
curl -sS http://127.0.0.1:8090/health
curl -sS http://127.0.0.1:8088/health
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=100 control-plane
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=100 site
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=100 wg-easy
```

## 5) Nginx reverse proxy (host)

Nginx stays on host and splits traffic:

- `horizonnetvpn.ru` / `www.horizonnetvpn.ru` -> `127.0.0.1:8088` (public customer site)
- `admin.horizonnetvpn.ru` -> `127.0.0.1:8090` (control-plane admin/API)

Use the ready template from repo:

- `deploy/nginx.horizonnetvpn.conf`

Create `/etc/nginx/sites-available/horizonnetvpn`:

```nginx
server {
    listen 80;
    server_name horizonnetvpn.ru www.horizonnetvpn.ru;

    location / {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name admin.horizonnetvpn.ru;

    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and reload:

```bash
ln -s /etc/nginx/sites-available/horizonnetvpn /etc/nginx/sites-enabled/horizonnetvpn
nginx -t
systemctl reload nginx
```

## 6) Update flow (next releases)

```bash
cd /opt/horizonnetvpn/app
git pull
cd amnezia
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

## 7) Optional HTTPS

After domain points to your VPS:

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d horizonnetvpn.ru -d www.horizonnetvpn.ru -d admin.horizonnetvpn.ru
```

## 8) Cutover without downtime

1. Deploy Docker stack first (`docker compose ... up -d --build`) and verify both local health endpoints.
2. Keep old nginx mapping active while validating site on loopback:
   - `curl -H "Host: horizonnetvpn.ru" http://127.0.0.1:8088/`
   - `curl -H "Host: admin.horizonnetvpn.ru" http://127.0.0.1:8090/health`
3. Update `/etc/nginx/sites-available/horizonnetvpn` with both server blocks above.
4. Run `nginx -t` and `systemctl reload nginx`.
5. Smoke test after switch:
   - `https://horizonnetvpn.ru/` serves customer website.
   - `https://horizonnetvpn.ru/register` and `/login` work.
   - website account can buy/renew and receives VPN key in `/account`.
   - `https://admin.horizonnetvpn.ru/admin` opens admin UI.
   - Telegram bot still calls `https://admin.horizonnetvpn.ru/v1/bot/*` with `BOT_API_TOKEN`.

Optional helper script:

```bash
cd /opt/horizonnetvpn/app/amnezia
PUBLIC_DOMAIN=horizonnetvpn.ru ADMIN_DOMAIN=admin.horizonnetvpn.ru BOT_API_TOKEN=<token> ./deploy/cutover_smoke_checks.sh
```
