from fastapi import FastAPI, Depends, HTTPException, Header, status, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import secrets
import uuid
import sqlalchemy

from . import models, schemas, auth, security
from .database import get_db
from .rate_limit import check_rate_limit
from .logger import setup_logging

setup_logging()

app = FastAPI(title="Webhook Delivery Platform")

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    from .redis_client import redis_client
    
    status_dict = {"status": "ok", "postgres": "ok", "redis": "ok"}
    try:
        db.execute(sqlalchemy.text("SELECT 1"))
    except Exception:
        status_dict["postgres"] = "failed"
        status_dict["status"] = "failed"
        
    try:
        redis_client.ping()
    except Exception:
        status_dict["redis"] = "failed"
        status_dict["status"] = "failed"
        
    if status_dict["status"] != "ok":
        raise HTTPException(status_code=503, detail=status_dict)
    return status_dict

@app.post("/api/v1/users", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = auth.get_password_hash(user.password)
    db_user = models.User(email=user.email, password_hash=hashed_password, role=user.role)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/api/v1/auth/token", response_model=schemas.Token)
def login_for_access_token(user_cred: schemas.UserCreate, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == user_cred.email).first()
    if not user or not auth.verify_password(user_cred.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = auth.create_access_token(
        data={"user_id": str(user.id), "role": user.role}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/api/v1/endpoints", response_model=schemas.EndpointResponse, status_code=status.HTTP_201_CREATED)
def create_endpoint(
    endpoint: schemas.EndpointCreate, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.RequireRole(["owner"]))
):
    secret = secrets.token_urlsafe(32)
    encrypted_secret = security.encrypt_secret(secret)
    
    db_endpoint = models.Endpoint(
        url=str(endpoint.url),
        secret=encrypted_secret,
        status="active",
        user_id=current_user.id
    )
    db.add(db_endpoint)
    db.commit()
    db.refresh(db_endpoint)
    
    return schemas.EndpointResponse(
        id=db_endpoint.id,
        url=db_endpoint.url,
        secret=secret
    )

@app.post("/api/v1/endpoints/{id}/events", response_model=schemas.EventCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def receive_event(
    id: uuid.UUID, 
    payload: dict,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.RequireRole(["owner"]))
):
    check_rate_limit(str(id))
    
    endpoint = db.query(models.Endpoint).filter(models.Endpoint.id == id, models.Endpoint.user_id == current_user.id).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
        
    if endpoint.status != "active":
        raise HTTPException(status_code=400, detail="Endpoint is not active")

    try:
        db_event = models.Event(
            endpoint_id=id,
            idempotency_key=idempotency_key,
            payload=payload
        )
        db.add(db_event)
        
        db_delivery = models.Delivery(
            event=db_event,
            status="pending"
        )
        db.add(db_delivery)
        
        db.commit()
        db.refresh(db_event)
        db.refresh(db_delivery)
        
        from .tasks import deliver_webhook
        deliver_webhook.delay(str(db_delivery.id))
        
        return schemas.EventCreateResponse(
            event_id=db_event.id,
            delivery_id=db_delivery.id
        )
    except IntegrityError:
        db.rollback()
        existing_event = db.query(models.Event).filter(
            models.Event.endpoint_id == id,
            models.Event.idempotency_key == idempotency_key
        ).first()
        
        if existing_event:
            existing_delivery = db.query(models.Delivery).filter(
                models.Delivery.event_id == existing_event.id
            ).first()
            
            response.status_code = status.HTTP_200_OK
            return schemas.EventCreateResponse(
                event_id=existing_event.id,
                delivery_id=existing_delivery.id if existing_delivery else uuid.uuid4()
            )
            
        raise HTTPException(status_code=500, detail="Database error")

@app.get("/api/v1/endpoints/{id}/deliveries", response_model=list[schemas.DeliveryResponse])
def get_deliveries(
    id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.RequireRole(["owner", "operator"]))
):
    endpoint = db.query(models.Endpoint).filter(models.Endpoint.id == id).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
        
    if current_user.role == "owner" and endpoint.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
        
    deliveries = db.query(models.Delivery).join(models.Event).filter(models.Event.endpoint_id == id).offset(skip).limit(limit).all()
    return deliveries

@app.get("/api/v1/deliveries/{id}/attempts", response_model=list[schemas.DeliveryAttemptResponse])
def get_delivery_attempts(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.RequireRole(["owner", "operator"]))
):
    delivery = db.query(models.Delivery).filter(models.Delivery.id == id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
        
    endpoint = delivery.event.endpoint
    if current_user.role == "owner" and endpoint.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
        
    attempts = db.query(models.DeliveryAttempt).filter(models.DeliveryAttempt.delivery_id == id).all()
    return attempts

@app.post("/api/v1/deliveries/{id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_delivery(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.RequireRole(["operator"]))
):
    delivery = db.query(models.Delivery).filter(models.Delivery.id == id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
        
    if delivery.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed deliveries can be retried")
        
    delivery.status = "pending"
    db.commit()
    
    from .tasks import deliver_webhook
    deliver_webhook.delay(str(delivery.id))
    
    return {"message": "Retry scheduled"}
