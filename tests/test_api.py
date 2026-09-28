import pytest

def test_auth_and_endpoint(client):
    # Create user
    user_data = {"email": "test@example.com", "password": "password123", "role": "owner"}
    resp = client.post("/api/v1/users", json=user_data)
    assert resp.status_code == 201
    
    # Login
    resp = client.post("/api/v1/auth/token", json={"email": "test@example.com", "password": "password123"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Fail to create endpoint without token
    resp_fail = client.post("/api/v1/endpoints", json={"url": "https://example.com/webhook"})
    assert resp_fail.status_code == 401
    
    # Create endpoint
    resp = client.post("/api/v1/endpoints", json={"url": "https://example.com/webhook"}, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    endpoint_id = data["id"]
    
    # Send event
    event_headers = headers.copy()
    event_headers["Idempotency-Key"] = "req_123"
    payload = {"order_id": 12345, "status": "paid"}
    
    resp = client.post(f"/api/v1/endpoints/{endpoint_id}/events", json=payload, headers=event_headers)
    assert resp.status_code == 202
    
    # Test Idempotency with Auth
    resp2 = client.post(f"/api/v1/endpoints/{endpoint_id}/events", json=payload, headers=event_headers)
    assert resp2.status_code == 200
    assert resp2.json()["event_id"] == resp.json()["event_id"]
