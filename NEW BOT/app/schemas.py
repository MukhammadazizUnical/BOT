from pydantic import BaseModel, Field


class SendMessageDTO(BaseModel):
    to: str = Field(min_length=1)
    message: str = Field(min_length=1)
    user_id: int | None = None
    telegram_account_id: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    role: str
