from sqlalchemy import Column, String, Integer, Text, ForeignKey, DateTime, JSON, UniqueConstraint
from sqlalchemy.types import Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
from .database import Base

def _utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="owner")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    
    endpoints = relationship("Endpoint", back_populates="user")

class Endpoint(Base):
    __tablename__ = "endpoints"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    url = Column(Text, nullable=False)
    secret = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    
    user = relationship("User", back_populates="endpoints")
    events = relationship("Event", back_populates="endpoint")

class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint('endpoint_id', 'idempotency_key', name='uq_endpoint_idempotency'),)
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint_id = Column(Uuid, ForeignKey("endpoints.id"), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    payload = Column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    
    endpoint = relationship("Endpoint", back_populates="events")
    deliveries = relationship("Delivery", back_populates="event")

class Delivery(Base):
    __tablename__ = "deliveries"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id = Column(Uuid, ForeignKey("events.id"), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    next_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    
    event = relationship("Event", back_populates="deliveries")
    attempts = relationship("DeliveryAttempt", back_populates="delivery")

class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    delivery_id = Column(Uuid, ForeignKey("deliveries.id"), nullable=False)
    status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    
    delivery = relationship("Delivery", back_populates="attempts")
