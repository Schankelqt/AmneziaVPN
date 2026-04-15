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
    if "clients" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("clients")}
        if "user_name" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clients ADD COLUMN user_name VARCHAR(128)"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
