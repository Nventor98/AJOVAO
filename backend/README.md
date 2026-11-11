# NaijaLife AI Backend Foundation

This project provides the shared backend foundation and identity/community module described in the MVP engineering handoff for NaijaLife AI.

It includes a FastAPI application skeleton, SQLAlchemy models, a shared auth/permission layer, responses, pagination helpers, audit logging, a transactional outbox/event bus, health endpoints and a migration scaffold.

Contract B currently includes phone-based registration and verification, bearer-token login, profiles, communities and memberships, addresses, collection points, agent approval and assignment, and scoped member consent with revocation. A phone-verified user can enable the `farmer` role at `POST /api/v1/farmers/role`; an approved agent can enable it for a member at `POST /api/v1/members/{user_id}/farmer-role` only when the member has an active, unrevoked, unexpired `farmer:register` consent for that agent. Both actions are auditable. This only enables the identity role; farmer profiles, farm data, and verification belong to Contract L. Address and collection-point locations use PostGIS `POINT` columns in PostgreSQL and a text-backed SQLite equivalent for local tests.

Contract C includes product categories, explicit grade/unit catalogue data, supplier verification and private document references, inventory movements, price observations and comparisons, immutable baseline snapshots, reviewed price-index publication, and consent-gated supplier scorecards.

Contract D includes community-scoped purchase groups and target lines, household requests and agent consent checks, anonymous demand summaries, verified-supplier quotations, confirmed customer orders with immutable baseline references, and recurring basket templates/cycles. A group creator or community administrator supplies any household/quantity minimum and the group's cutoff; no unapproved platform minimum is assumed. A group can be cancelled only before confirmation. The selected quotation is approved and orders are created in one transaction at `POST /api/v1/purchase-groups/{group_id}/confirm`; repeating that request with the same quotation returns the existing orders. Quotation confirmation proceeds directly from `QUOTING` to `CONFIRMED`, with approval and order creation atomic.

Standing basket cadence, start date, and cutoff duration are specified when the basket is created. A scheduled worker must call `open_due_basket_cycles` or the staff-only `POST /api/v1/baskets/process-due-cycles`; `GET /api/v1/baskets/{basket_id}/cycles` lists cycle IDs, and the unique basket/start constraint makes sequential retries idempotent. A worker must also call `close_due_purchase_groups` or the staff-only `POST /api/v1/purchase-groups/process-due` so expired groups close; the first supplier quote moves a closed group to `QUOTING`. Members subscribe to a basket and explicitly join, skip, or leave each open cycle. Weekly/monthly schedules are supported; monthly cycles retain the original day-of-month anchor. Per-member delivery and handling fees are allocated proportionally to item subtotal, rounded to kobo with any remainder assigned by largest fractional remainder (member ID breaks ties).

Orders are created as `PENDING_PAYMENT`; this module never marks payment successful. Payment-provider handling must make the verified `PAID` transition in Contract E. A supplier may move a paid order to `PROCESSING`; staff may advance the delivery-method-appropriate state to `READY_FOR_PICKUP` or `IN_TRANSIT` and then `DELIVERED`. The customer or staff may mark a delivered order `DISPUTED`. Group states progress through `OPEN`, `CLOSED`, `QUOTING`, `CONFIRMED`, `FULFILLING` and `COMPLETED`; cancellation is available only before confirmation.

Group closing writes anonymised demand to the transactional outbox only when `NAIJALIFE_DEMAND_SIGNAL_MIN_HOUSEHOLDS` is configured above zero and the group reaches that threshold. Its default of `0` disables publication until the Product Owner approves a minimum. Until household records exist, the threshold counts distinct requesting member accounts as a household proxy; confirm that policy before launch. An agent request is recorded with its consent and emits a transactional `purchase_request.submitted` outbox event for downstream member notification; SMS notification delivery is not yet wired to that event.

## Quick start

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

Add categories, units, and products (including grades) using staff/admin endpoints before opening supplier inventory or price records. Price-index sample/source requirements, baseline rules, anomaly ratio, and observation freshness settings have development defaults and must be confirmed by the Product Owner before launch; see `.env.example`.

## Local Docker services

From `backend`, run `docker compose up --build` to start the API, PostGIS, and Redis. The API container runs database migrations before starting and binds only to localhost. Compose credentials are for local development only; replace them before any shared or deployed use. The outbox worker is intentionally not started by default because event handlers must be registered before processing pending events.

## Background jobs

The background-job interface is available through `app.shared.jobs`:

- `@job` registers a function as a background job.
- `enqueue(task, *args, **kwargs)` executes the job inline or submits it to Celery, depending on `NAIJALIFE_JOB_BACKEND`.

The default backend is `inline`, which is suitable for local development and tests. Staging and production require `NAIJALIFE_JOB_BACKEND=celery`.

### Running the Celery worker

The Celery worker is optional and is not started by the normal Docker Compose command.

To use Celery locally, set the backend environment variable in PowerShell:

```powershell
$env:NAIJALIFE_JOB_BACKEND = "celery"
docker compose --profile celery up --build
```

This starts the API and the optional Celery worker. Both use the configured Redis service as their broker.

To return to inline execution in the current PowerShell session:

```powershell
Remove-Item Env:NAIJALIFE_JOB_BACKEND
```
The Celery worker loads the `app.tasks` package on startup. Each application job module must be imported by `app/tasks/__init__.py` so its tasks are registered before they are executed. The current foundation provides the job interface and worker configuration; application-specific job declarations will be added when those jobs are introduced.

### Celery and the transactional outbox

Celery job execution and transactional outbox processing are separate mechanisms. The Celery worker does not replace the outbox dispatcher or its retry and failed-event handling. The outbox worker remains intentionally separate and is not started automatically by Docker Compose because event handlers must be registered before pending events are processed.

## Core conventions

- JSON response envelope: `success`, `data`, `meta`
- Standard `?page=&page_size=` pagination
- JWT-based authentication foundation
- Role and permission enforcement
- Structured audit records
- Domain event bus with outbox support
- Health and readiness checks; readiness returns `503` unless both the database and Redis respond

## Notes

The repository README is the product specification for the wider platform. This backend foundation is intentionally modular and extendable so subsequent contracts can build on top of the shared services.

Phone verification delivery is provided through the configured Twilio adapter below. It returns a service-unavailable error rather than claiming delivery when credentials are missing or Twilio cannot accept the message.

## Twilio SMS

The Twilio Programmable Messaging adapter sends the locally generated, short-lived verification code. Configure all three settings in your untracked `.env` file (see `.env.example`):

- `NAIJALIFE_TWILIO_ACCOUNT_SID`
- `NAIJALIFE_TWILIO_AUTH_TOKEN`
- `NAIJALIFE_TWILIO_FROM_NUMBER` (a Twilio number enabled for SMS)

Never commit real credentials. With these values unset, registration responds with `503 Service Unavailable`; it does not claim that a message was sent. The adapter uses HTTPS, has a fixed 10-second request timeout, and does not include credentials or provider response bodies in errors.

## PostgreSQL and PostGIS

Set `NAIJALIFE_DATABASE_URL` to a PostgreSQL connection URL, install PostGIS for that PostgreSQL server version, and run `python -m alembic upgrade head`. The identity migration enables the PostGIS extension and stores address/collection-point coordinates as SRID 4326 points. SQLite is used only for local tests and its migration does not verify PostGIS installation or spatial queries.

The GitHub Actions workflow runs the test suite and migrations against PostgreSQL/PostGIS and Redis, scans dependencies, and builds the container. Those hosted integration checks have not been run from this local environment.
