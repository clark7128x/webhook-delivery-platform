import time
from fastapi import HTTPException
from .redis_client import redis_client
import redis

RATE_LIMIT = 100

def check_rate_limit(endpoint_id: str):
    current_second = int(time.time())
    key = f"rate_limit:{endpoint_id}:{current_second}"
    
    try:
        current_count = redis_client.incr(key)
        if current_count == 1:
            redis_client.expire(key, 5)
            
        if current_count > RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Too Many Requests")
    except redis.exceptions.ConnectionError:
        pass
