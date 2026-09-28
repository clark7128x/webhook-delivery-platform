import os
import base64
import hmac
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import time

# [ASSUMPTION] Use a fixed key for development if not provided, in production this must be set!
ENCRYPTION_KEY_B64 = os.getenv("ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode('utf-8'))
_aesgcm = None

def get_aesgcm():
    global _aesgcm
    if _aesgcm is None:
        key = base64.b64decode(ENCRYPTION_KEY_B64)
        if len(key) not in (16, 24, 32):
            key = key.ljust(32, b'\0')[:32]
        _aesgcm = AESGCM(key)
    return _aesgcm

def encrypt_secret(secret: str) -> str:
    aesgcm = get_aesgcm()
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, secret.encode('utf-8'), None)
    return base64.b64encode(nonce + ciphertext).decode('utf-8')

def decrypt_secret(encrypted_secret: str) -> str:
    aesgcm = get_aesgcm()
    data = base64.b64decode(encrypted_secret)
    nonce, ciphertext = data[:12], data[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode('utf-8')

def generate_signature(payload: bytes, secret: str, timestamp: int = None) -> str:
    if timestamp is None:
        timestamp = int(time.time())
    
    # Sign "timestamp.payload" so the timestamp is cryptographically bound
    signed_content = f"{timestamp}.".encode('utf-8') + payload
    mac = hmac.new(secret.encode('utf-8'), msg=signed_content, digestmod=hashlib.sha256)
    
    return f"t={timestamp},v1={mac.hexdigest()}"
