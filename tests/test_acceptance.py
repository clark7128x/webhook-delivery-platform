"""
Acceptance criteria tests from TECH_SPEC §10 and integration tests from §9.
"""
import pytest
import uuid
import json
import hmac
import hashlib
from unittest.mock import patch, MagicMock
from src import models


class MockResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


# --- AC1: Correct payload delivery with valid HMAC signature ---

@patch("src.tasks.send_webhook_request")
def test_event_delivered_with_correct_payload_and_signature(mock_send, client, db_session):
    mock_send.return_value = MockResponse(200, "OK")

    client.post("/api/v1/users", json={"email": "ac1@test.com", "password": "pw", "role": "owner"})
    token = client.post("/api/v1/auth/token", json={"email": "ac1@test.com", "password": "pw"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ep = client.post("/api/v1/endpoints", json={"url": "https://target.example.com/hook"}, headers=headers).json()
    secret = ep["secret"]

    payload = {"order_id": 42, "status": "paid", "amount": 99.95}
    resp = client.post(
        f"/api/v1/endpoints/{ep['id']}/events",
        json=payload,
        headers={**headers, "Idempotency-Key": "ac1-key"}
    )
    assert resp.status_code == 202

    mock_send.assert_called_once()
    url, content, sent_headers = mock_send.call_args[0]

    # Payload must be identical
    assert json.loads(content) == payload

    # Signature must be verifiable with the endpoint's secret
    sig = sent_headers["X-Webhook-Signature"]
    parts = dict(p.split("=", 1) for p in sig.split(","))
    signed_content = f"{parts['t']}.".encode() + content
    expected = hmac.new(secret.encode(), signed_content, hashlib.sha256).hexdigest()
    assert parts["v1"] == expected


# --- AC2: 503 creates delivery_attempt and schedules backoff ---

@patch("src.tasks.send_webhook_request")
def test_503_creates_attempt_and_schedules_backoff(mock_send, client, db_session):
    mock_send.return_value = MockResponse(503, "Service Unavailable")

    client.post("/api/v1/users", json={"email": "ac2@test.com", "password": "pw", "role": "owner"})
    token = client.post("/api/v1/auth/token", json={"email": "ac2@test.com", "password": "pw"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ep = client.post("/api/v1/endpoints", json={"url": "https://target.example.com"}, headers=headers).json()

    resp = client.post(
        f"/api/v1/endpoints/{ep['id']}/events",
        json={"test": True},
        headers={**headers, "Idempotency-Key": "ac2-key"}
    )
    delivery_id = resp.json()["delivery_id"]

    db_session.expire_all()
    attempts = db_session.query(models.DeliveryAttempt).join(models.Delivery).filter(
        models.Delivery.id == uuid.UUID(delivery_id)
    ).all()
    assert len(attempts) >= 1
    assert all(a.status_code == 503 for a in attempts)

    delivery = db_session.query(models.Delivery).filter_by(id=uuid.UUID(delivery_id)).first()
    # After exhausting retries, status should be failed
    assert delivery.status == "failed"


# --- AC3: Fifth consecutive failure marks delivery as failed ---

@patch("src.tasks.send_webhook_request")
def test_exhausted_retries_marks_delivery_failed(mock_send, client, db_session):
    mock_send.return_value = MockResponse(500, "Internal Server Error")

    client.post("/api/v1/users", json={"email": "ac3@test.com", "password": "pw", "role": "owner"})
    token = client.post("/api/v1/auth/token", json={"email": "ac3@test.com", "password": "pw"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ep = client.post("/api/v1/endpoints", json={"url": "https://target.example.com"}, headers=headers).json()

    resp = client.post(
        f"/api/v1/endpoints/{ep['id']}/events",
        json={"data": "test"},
        headers={**headers, "Idempotency-Key": "ac3-key"}
    )
    delivery_id = resp.json()["delivery_id"]

    db_session.expire_all()
    delivery = db_session.query(models.Delivery).filter_by(id=uuid.UUID(delivery_id)).first()
    assert delivery.status == "failed"

    # 1 initial attempt + 5 retries = 6 delivery_attempts
    attempts = db_session.query(models.DeliveryAttempt).filter_by(delivery_id=delivery.id).all()
    assert len(attempts) == 6
    assert all(a.status_code == 500 for a in attempts)


# --- AC4: Operator cannot create endpoint (403) ---

def test_operator_cannot_create_endpoint(client, db_session):
    client.post("/api/v1/users", json={"email": "ac4_op@test.com", "password": "pw", "role": "operator"})
    token = client.post("/api/v1/auth/token", json={"email": "ac4_op@test.com", "password": "pw"}).json()["access_token"]

    resp = client.post(
        "/api/v1/endpoints",
        json={"url": "https://example.com/hook"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403

    # DB state unchanged — no endpoints created
    count = db_session.query(models.Endpoint).count()
    assert count == 0


# --- Integration: Delivery lifecycle with retries (§9) ---
# Mock server returns 500 twice, then 200. Verify 3 attempts and final success.

@patch("src.tasks.send_webhook_request")
def test_delivery_lifecycle_retries_then_succeeds(mock_send, client, db_session):
    mock_send.side_effect = [MockResponse(500, "Error"), MockResponse(500, "Error"), MockResponse(200, "OK")]

    client.post("/api/v1/users", json={"email": "lc@test.com", "password": "pw", "role": "owner"})
    token = client.post("/api/v1/auth/token", json={"email": "lc@test.com", "password": "pw"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ep = client.post("/api/v1/endpoints", json={"url": "https://target.example.com"}, headers=headers).json()

    resp = client.post(
        f"/api/v1/endpoints/{ep['id']}/events",
        json={"data": "lifecycle"},
        headers={**headers, "Idempotency-Key": "lc-key"}
    )
    delivery_id = resp.json()["delivery_id"]

    db_session.expire_all()
    delivery = db_session.query(models.Delivery).filter_by(id=uuid.UUID(delivery_id)).first()
    assert delivery.status == "success"

    attempts = db_session.query(models.DeliveryAttempt).filter_by(delivery_id=delivery.id).all()
    assert len(attempts) == 3
    status_codes = sorted([a.status_code for a in attempts])
    assert status_codes == [200, 500, 500]
