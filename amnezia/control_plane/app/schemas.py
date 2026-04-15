from datetime import datetime
from pydantic import BaseModel, Field


class CreateClientRequest(BaseModel):
    telegram_user_id: int = Field(..., gt=0)
    user_name: str | None = Field(default=None, max_length=128)
    plan_days: int = Field(default=30, ge=1, le=3650)
    remark: str = Field(default="")


class RenewClientRequest(BaseModel):
    add_days: int = Field(default=30, ge=1, le=3650)


class BotProvisionRequest(BaseModel):
    user_name: str | None = Field(default=None, max_length=128)
    plan_days: int = Field(default=30, ge=1, le=3650)
    remark: str = Field(default="")
    recreate_if_exists: bool = Field(default=False)


class BotRenewRequest(BaseModel):
    add_days: int = Field(default=30, ge=1, le=3650)


class ClientResponse(BaseModel):
    client_id: str
    telegram_user_id: int
    user_name: str | None = None
    active: bool
    expires_at: datetime
    config: str
    provider_ref: str
