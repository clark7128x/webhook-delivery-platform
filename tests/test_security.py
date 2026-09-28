import pytest
import hmac
import hashlib
from src.security import encrypt_secret, decrypt_secret, generate_signature
import time

def test_encryption():
    secret = "my-super-secret-123"
    encrypted = encrypt_secret(secret)
    assert encrypted != secret
    decrypted = decrypt_secret(encrypted)
    assert decrypted == secret

def test_generate_signature():
    payload = b'{"hello": "world"}'
    secret = "my-secret"
    timestamp = 1600000000
    
    signature = generate_signature(payload, secret, timestamp)
    assert signature.startswith(f"t={timestamp},v1=")
    assert len(signature) > 20

def test_signature_is_verifiable():
    payload = b'{"order": 123}'
    secret = "webhook-secret"
    timestamp = 1700000000
    
    sig = generate_signature(payload, secret, timestamp)
    parts = dict(p.split("=", 1) for p in sig.split(","))
    
    signed_content = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_content, hashlib.sha256).hexdigest()
    assert parts["v1"] == expected
    assert parts["t"] == str(timestamp)
