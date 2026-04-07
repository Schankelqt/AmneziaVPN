from datetime import datetime
from pydantic import BaseModel, Field


class CreateClientRequest(BaseModel):
    telegram_user_id: int = Field(..., gt=0)
    plan_days: int = Field(default=30, ge=1, le=3650)
    remark: str = Field(default="")


class RenewClientRequest(BaseModel):
    add_days: int = Field(default=30, ge=1, le=3650)


class ClientResponse(BaseModel):
    client_id: str
    telegram_user_id: int
    active: bool
    expires_at: datetime
    config: str
    provider_ref: str
