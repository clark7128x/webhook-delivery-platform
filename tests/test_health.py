import pytest

def test_health_check_success(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["postgres"] == "ok"
    assert data["redis"] == "ok"

def test_health_check_redis_fail(client, mock_redis_client):
    mock_redis_client.ping.side_effect = Exception("Connection Error")
    resp = client.get("/health")
    assert resp.status_code == 503
    data = resp.json()["detail"]
    assert data["status"] == "failed"
    assert data["redis"] == "failed"
    assert data["postgres"] == "ok"

def test_health_check_db_fail(client, db_session):
    from unittest.mock import patch
    with patch.object(db_session, "execute", side_effect=Exception("DB Down")):
        resp = client.get("/health")
        assert resp.status_code == 503
        data = resp.json()["detail"]
        assert data["postgres"] == "failed"
        assert data["redis"] == "ok"
