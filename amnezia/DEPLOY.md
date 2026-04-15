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
- `WG_EASY_PASSWORD`
- `WG_EASY_INIT_PASSWORD`
- `WG_EASY_INIT_HOST` (your public server IP or DNS)

## 4) Start full Docker stack (control-plane + postgres + wg-easy)

```bash
cd /opt/horizonnetvpn/app/amnezia
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

Health checks:

```bash
curl -sS http://127.0.0.1:8090/health
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=100 control-plane
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=100 wg-easy
```

## 5) Nginx reverse proxy (host)

Nginx stays on host and proxies to `127.0.0.1:8090` (control-plane container).

Create `/etc/nginx/sites-available/horizonnetvpn-control-plane`:

```nginx
server {
    listen 80;
    server_name <YOUR_DOMAIN_OR_IP>;

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
ln -s /etc/nginx/sites-available/horizonnetvpn-control-plane /etc/nginx/sites-enabled/horizonnetvpn-control-plane
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
certbot --nginx -d <YOUR_DOMAIN>
```
