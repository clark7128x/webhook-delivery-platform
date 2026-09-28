import pytest
from pydantic import ValidationError
from src.schemas import EndpointCreate, UserCreate


def test_endpoint_create_requires_valid_url():
    ep = EndpointCreate(url="https://example.com/webhook")
    assert "example.com" in str(ep.url)

    with pytest.raises(ValidationError):
        EndpointCreate(url="not-a-valid-url")


def test_user_create_validates_email():
    user = UserCreate(email="test@example.com", password="pw")
    assert user.email == "test@example.com"

    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="pw")


def test_user_create_defaults_to_owner():
    user = UserCreate(email="a@b.com", password="pw")
    assert user.role == "owner"
