import pytest
from src import models
from unittest.mock import patch

class MockResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

def test_stage4_endpoints(client, db_session, mock_redis_client):
    # Setup roles
    client.post("/api/v1/users", json={"email": "owner@a.com", "password": "pw", "role": "owner"})
    client.post("/api/v1/users", json={"email": "operator@a.com", "password": "pw", "role": "operator"})
    
    t_owner = client.post("/api/v1/auth/token", json={"email": "owner@a.com", "password": "pw"}).json()["access_token"]
    t_operator = client.post("/api/v1/auth/token", json={"email": "operator@a.com", "password": "pw"}).json()["access_token"]
    
    h_owner = {"Authorization": f"Bearer {t_owner}"}
    h_operator = {"Authorization": f"Bearer {t_operator}"}
    
    # Create endpoint
    ep_id = client.post("/api/v1/endpoints", json={"url": "http://test"}, headers=h_owner).json()["id"]
    
    # Try sending event (test rate limit mock)
    # mock returns 1, so it shouldn't 429
    with patch("src.tasks.send_webhook_request") as mock_send:
        mock_send.return_value = MockResponse(500, "Error")
        
        resp = client.post(f"/api/v1/endpoints/{ep_id}/events", json={}, headers={**h_owner, "Idempotency-Key": "k1"})
        assert resp.status_code == 202
        delivery_id = resp.json()["delivery_id"]
        
    # Get deliveries
    resp = client.get(f"/api/v1/endpoints/{ep_id}/deliveries", headers=h_owner)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    
    # Get attempts
    resp = client.get(f"/api/v1/deliveries/{delivery_id}/attempts", headers=h_owner)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
    assert resp.json()[0]["status_code"] == 500
    
    # Force delivery to failed state manually for test
    import uuid
    delivery = db_session.query(models.Delivery).filter_by(id=uuid.UUID(delivery_id)).first()
    delivery.status = "failed"
    db_session.commit()
    
    # Owner tries to retry -> Forbidden? Actually, route is RequireRole(["operator"]) so it should be 403
    resp = client.post(f"/api/v1/deliveries/{delivery_id}/retry", headers=h_owner)
    assert resp.status_code == 403
    
    # Operator retries
    with patch("src.tasks.send_webhook_request") as mock_send:
        mock_send.return_value = MockResponse(200, "OK")
        resp = client.post(f"/api/v1/deliveries/{delivery_id}/retry", headers=h_operator)
        assert resp.status_code == 202
        
    db_session.refresh(delivery)
    assert delivery.status == "success"

def test_rate_limiter(client, mock_redis_client):
    client.post("/api/v1/users", json={"email": "rate@a.com", "password": "pw", "role": "owner"})
    token = client.post("/api/v1/auth/token", json={"email": "rate@a.com", "password": "pw"}).json()["access_token"]
    h_owner = {"Authorization": f"Bearer {token}"}
    
    ep_id = client.post("/api/v1/endpoints", json={"url": "http://test"}, headers=h_owner).json()["id"]
    
    # simulate > 100 requests
    mock_redis_client.incr.return_value = 101
    
    resp = client.post(f"/api/v1/endpoints/{ep_id}/events", json={}, headers={**h_owner, "Idempotency-Key": "k2"})
    assert resp.status_code == 429
