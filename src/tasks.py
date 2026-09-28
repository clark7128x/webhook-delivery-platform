import time
import json
import httpx
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from .celery_app import app
from .database import SessionLocal
from . import models, security

RETRY_INTERVALS = [60, 300, 1800, 7200, 43200]

def send_webhook_request(url, content, headers):
    timeout = httpx.Timeout(15.0, connect=5.0)
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        return client.post(url, content=content, headers=headers)

@app.task(bind=True, max_retries=5)
def deliver_webhook(self, delivery_id: str):
    db: Session = SessionLocal()
    try:
        import uuid
        delivery_uuid = uuid.UUID(delivery_id)
        delivery = db.query(models.Delivery).filter(models.Delivery.id == delivery_uuid).first()
        if not delivery:
            return
            
        event = delivery.event
        endpoint = event.endpoint
        
        secret = security.decrypt_secret(endpoint.secret)
        
        payload_bytes = json.dumps(event.payload).encode('utf-8')
        signature = security.generate_signature(payload_bytes, secret)
        
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "Idempotency-Key": event.idempotency_key
        }
        
        start_time = time.time()
        try:
            response = send_webhook_request(endpoint.url, payload_bytes, headers)
                
            latency_ms = int((time.time() - start_time) * 1000)
            
            attempt = models.DeliveryAttempt(
                delivery_id=delivery.id,
                status_code=response.status_code,
                response_body=response.text[:2048],
                latency_ms=latency_ms
            )
            db.add(attempt)
            
            if 200 <= response.status_code < 300:
                delivery.status = "success"
                db.commit()
            else:
                retries = self.request.retries
                if retries < len(RETRY_INTERVALS):
                    countdown = RETRY_INTERVALS[retries]
                    delivery.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=countdown)
                    db.commit()
                    raise self.retry(countdown=countdown)
                else:
                    delivery.status = "failed"
                    db.commit()
                
        except httpx.RequestError as e:
            latency_ms = int((time.time() - start_time) * 1000)
            attempt = models.DeliveryAttempt(
                delivery_id=delivery.id,
                status_code=None,
                error_message=str(e)[:2048],
                latency_ms=latency_ms
            )
            db.add(attempt)
            
            retries = self.request.retries
            if retries < len(RETRY_INTERVALS):
                countdown = RETRY_INTERVALS[retries]
                delivery.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=countdown)
                db.commit()
                raise self.retry(exc=e, countdown=countdown)
            else:
                delivery.status = "failed"
                db.commit()
                
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
