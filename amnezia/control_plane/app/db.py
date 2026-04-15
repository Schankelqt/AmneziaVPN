import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./control_plane.db").strip()

connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "clients" in table_names:
        columns = {col["name"] for col in inspector.get_columns("clients")}
        if "user_name" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clients ADD COLUMN user_name VARCHAR(128)"))
        with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_active_telegram_user_id "
                        "ON clients (telegram_user_id) WHERE active = true"
                    )
                )
            else:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_active_telegram_user_id "
                        "ON clients (telegram_user_id) WHERE active = 1"
                    )
                )

    if "traffic_samples" in table_names:
        traffic_columns = {col["name"] for col in inspector.get_columns("traffic_samples")}
        with engine.begin() as conn:
            if "raw_rx_bytes" not in traffic_columns:
                conn.execute(text("ALTER TABLE traffic_samples ADD COLUMN raw_rx_bytes BIGINT DEFAULT 0"))
            if "raw_tx_bytes" not in traffic_columns:
                conn.execute(text("ALTER TABLE traffic_samples ADD COLUMN raw_tx_bytes BIGINT DEFAULT 0"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
