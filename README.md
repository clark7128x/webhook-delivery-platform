# Webhook Delivery Platform

A backend service that receives events from an application and delivers them to customer-defined HTTP endpoints, with signed payloads, automatic retries, and a full delivery history.

Sending a webhook directly from your main request path ties your response time to a server you don't control. If that server is slow or down, you either block the caller or drop the event. This service takes the event off your hands immediately, stores it, and handles delivery — including retries and backoff — asynchronously. It's the same problem Stripe, Svix, and Hookdeck solve for their own webhook traffic.

## What it does

- **Endpoint registration.** Clients register a URL and receive a secret used to sign every payload sent to them.
- **Signed delivery.** Every outbound request carries an `X-Webhook-Signature` header: HMAC-SHA256 over `timestamp.payload`, so receivers can verify authenticity and reject old, replayed requests.
- **Idempotent event intake.** Events are submitted with an `Idempotency-Key` header. A duplicate key for the same endpoint returns the existing event instead of creating a new one — enforced at the database level with a unique constraint, not a check-then-insert race.
- **Retries with backoff.** Failed deliveries (4xx except 429, 5xx, timeouts) are retried up to 5 times, with intervals of 1 minute, 5 minutes, 30 minutes, 2 hours, and 12 hours. After the fifth failure, the delivery is marked `failed` and no further attempts are scheduled.
- **Full delivery history.** Every attempt — status code, latency, error message — is recorded and queryable through the API, with pagination.
- **Manual retry.** A failed delivery can be requeued on demand instead of waiting for the schedule.
- **Rate limiting.** Each endpoint is capped at 100 requests per second; excess requests get a `429` immediately, before touching the database.
- **Role-based access.** `owner` manages their own endpoints and secrets. `operator` has read access to delivery history and can trigger manual retries, but can't create or modify endpoints.

## Tech stack

Python 3.13, FastAPI, PostgreSQL, SQLAlchemy 2.x, Redis, Celery, Pydantic v2, Alembic, pytest, Docker Compose.

## How delivery works

1. `POST /api/v1/endpoints/{id}/events` writes the event to PostgreSQL and pushes a delivery task onto Redis. This returns in under 50ms — it doesn't wait for the outbound request.
2. A Celery worker picks up the task, signs the payload, and sends it to the endpoint's URL with a 5-second connect timeout and 15-second read timeout. Redirects are not followed, to avoid SSRF via a compromised or misconfigured endpoint.
3. A non-2xx response or a timeout creates a `delivery_attempt` record and reschedules the delivery according to the backoff schedule above.
4. Once an attempt succeeds, or once retries are exhausted, the delivery's status is updated and no further work is scheduled for it.

## API reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/auth/token` | Get a JWT for an existing user |
| `POST` | `/api/v1/endpoints` | Register a new endpoint (owner only) |
| `POST` | `/api/v1/endpoints/{id}/events` | Submit an event for delivery (requires `Idempotency-Key`) |
| `GET` | `/api/v1/endpoints/{id}/deliveries` | List deliveries for an endpoint, paginated |
| `GET` | `/api/v1/deliveries/{id}/attempts` | List attempts for a specific delivery |
| `POST` | `/api/v1/deliveries/{id}/retry` | Manually requeue a failed delivery |

## Running it locally

Requires Docker and Docker Compose.

```bash
git clone https://github.com/<your-username>/webhook-delivery-platform.git
cd webhook-delivery-platform
cp .env.example .env   # set JWT_SECRET_KEY and ENCRYPTION_KEY to real values
docker compose up --build
```

This starts the API, a Celery worker, PostgreSQL, and Redis. The API is available at `http://localhost:8000`; interactive docs at `http://localhost:8000/docs`.

Example flow, once running:

```bash
# Register an endpoint
curl -X POST http://localhost:8000/api/v1/endpoints \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"url": "https://example.com/webhook"}'

# Send an event
curl -X POST http://localhost:8000/api/v1/endpoints/<endpoint_id>/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: order-42-created" \
  -d '{"order_id": 42, "status": "created"}'
```

## Running the tests

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pytest
```

Tests run against SQLite instead of a live PostgreSQL instance, so no Docker setup is needed just to run the suite.

## Project structure

```
src/
  main.py          # API routes
  models.py        # SQLAlchemy models
  schemas.py       # Pydantic request/response schemas
  tasks.py         # Celery delivery worker, retry logic
  security.py      # HMAC signing, secret encryption
  auth.py          # JWT issuance and role-based access control
  rate_limit.py     # Redis-backed rate limiter
tests/
  test_acceptance.py  # End-to-end scenarios matching the acceptance criteria
  test_tasks.py        # Delivery worker and retry behavior
  ...
```

## Notes on a few design decisions

- **Idempotency is a database constraint, not application logic.** A unique index on `(endpoint_id, idempotency_key)` means a race between two identical requests can't create two events, regardless of timing.
- **The HMAC signature includes a timestamp**, not just the payload, so a receiver can reject a signed request that's simply too old — without this, a captured request could be replayed indefinitely with a valid signature.
- **Rate limiting fails open.** If Redis is unreachable, requests are allowed through rather than rejected — availability of event intake was judged more important than strict enforcement of a soft limit.

## Out of scope

This service handles receipt, queuing, and delivery of webhook events. It does not include:

- A user interface — it's an API only.
- Multi-tenant billing or usage-based pricing.
- Payload transformation or filtering — events are delivered exactly as received.
- Fan-out to multiple endpoints — one event is delivered to exactly one endpoint.

## License

MIT