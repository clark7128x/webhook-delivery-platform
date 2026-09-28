import pytest
from src import models
import uuid
from unittest.mock import patch, MagicMock

@patch("src.tasks.send_webhook_request")
def test_deliver_webhook_success(mock_send, client, db_session):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "OK"
    mock_send.return_value = mock_response

    # Setup data
    user_data = {"email": "task@example.com", "password": "pw", "role": "owner"}
    client.post("/api/v1/users", json=user_data)
    resp = client.post("/api/v1/auth/token", json={"email": "task@example.com", "password": "pw"})
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = client.post("/api/v1/endpoints", json={"url": "https://example.com/webhook"}, headers=headers)
    endpoint_id = resp.json()["id"]
    
    resp = client.post(f"/api/v1/endpoints/{endpoint_id}/events", json={"test": "data"}, headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "test_task_1"})
    delivery_id = resp.json()["delivery_id"]
    
    # Task was executed eagerly
    # Check if delivery status is success
    db_delivery = db_session.query(models.Delivery).filter(models.Delivery.id == uuid.UUID(delivery_id)).first()
    assert db_delivery.status == "success"
    
    # Check if attempt was logged
    attempt = db_session.query(models.DeliveryAttempt).filter(models.DeliveryAttempt.delivery_id == db_delivery.id).first()
    assert attempt is not None
    assert attempt.status_code == 200
    
    # Check if correct headers were sent
    mock_send.assert_called_once()
    args, kwargs = mock_send.call_args
    assert len(args) == 3
    assert "X-Webhook-Signature" in args[2]

def test_backoff_intervals():
    from src.tasks import RETRY_INTERVALS
    assert RETRY_INTERVALS == [60, 300, 1800, 7200, 43200]
    assert len(RETRY_INTERVALS) == 5
