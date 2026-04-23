import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("SITE_DB_PATH", "/app/data/site.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


conn = _connect()


def init_db() -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_id TEXT NOT NULL UNIQUE,
            login TEXT UNIQUE,
            email TEXT UNIQUE,
            password_hash TEXT,
            google_sub TEXT UNIQUE,
            tg_id TEXT UNIQUE,
            selected_protocol TEXT NOT NULL DEFAULT 'wireguard',
            pending_revoke_protocol TEXT,
            pending_revoke_ref TEXT,
            pending_revoke_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            integration_user_id INTEGER NOT NULL,
            protocol TEXT NOT NULL,
            plan_days INTEGER NOT NULL,
            amount_rub INTEGER NOT NULL,
            status TEXT NOT NULL,
            client_id TEXT,
            provider_ref TEXT,
            config TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            direction TEXT NOT NULL,
            body TEXT NOT NULL,
            tg_message_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(purchases)").fetchall()}
    if "integration_user_id" not in existing_columns:
        conn.execute("ALTER TABLE purchases ADD COLUMN integration_user_id INTEGER DEFAULT 0")
    if "protocol" not in existing_columns:
        conn.execute("ALTER TABLE purchases ADD COLUMN protocol TEXT DEFAULT 'wireguard'")
    existing_user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "selected_protocol" not in existing_user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN selected_protocol TEXT DEFAULT 'wireguard'")
    if "pending_revoke_protocol" not in existing_user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN pending_revoke_protocol TEXT")
    if "pending_revoke_ref" not in existing_user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN pending_revoke_ref TEXT")
    if "pending_revoke_at" not in existing_user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN pending_revoke_at TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email_lower ON users(lower(email)) WHERE email IS NOT NULL"
    )
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_user(
    *,
    login: str | None,
    email: str | None,
    password_hash: str | None,
    google_sub: str | None = None,
    tg_id: str | None = None,
) -> sqlite3.Row:
    public_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO users (public_id, login, email, password_hash, google_sub, tg_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (public_id, login, email, password_hash, google_sub, tg_id, now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE public_id = ?", (public_id,)).fetchone()
    if row is None:
        raise RuntimeError("Failed to create user")
    return row
