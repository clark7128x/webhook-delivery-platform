from pydantic import BaseModel, HttpUrl, EmailStr, ConfigDict
from typing import Any, Optional
import uuid
from datetime import datetime

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str = "owner"

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: Optional[str] = None
    role: Optional[str] = None

class EndpointCreate(BaseModel):
    url: HttpUrl

class EndpointResponse(BaseModel):
    id: uuid.UUID
    url: str
    secret: str
    model_config = ConfigDict(from_attributes=True)

class EventCreateResponse(BaseModel):
    event_id: uuid.UUID
    delivery_id: uuid.UUID

class DeliveryResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    status: str
    next_attempt_at: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class DeliveryAttemptResponse(BaseModel):
    id: uuid.UUID
    delivery_id: uuid.UUID
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    latency_ms: int
    error_message: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
