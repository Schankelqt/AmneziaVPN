from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class ClientRecord(Base):
    __tablename__ = "clients"
    __table_args__ = (
        Index(
            "uq_clients_active_telegram_user_id",
            "telegram_user_id",
            unique=True,
            sqlite_where=text("active = 1"),
            postgresql_where=text("active = true"),
        ),
    )

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider_ref: Mapped[str] = mapped_column(String(128), index=True)
    config: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class TrafficSample(Base):
    __tablename__ = "traffic_samples"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sample_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    raw_rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    raw_tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
