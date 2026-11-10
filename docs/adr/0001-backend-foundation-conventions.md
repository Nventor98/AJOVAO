# ADR 0001: Backend foundation conventions

- Status: Accepted
- Date: 2026-11-09

## Context

NaijaLife AI is a modular monolith backed by a shared API-first backend. The platform must support multi-channel access (mobile, web, USSD, SMS, WhatsApp) without duplicating business rules or data access patterns.

## Decision

We standardise on a Python 3.12 FastAPI backend with SQLAlchemy 2, Alembic migrations, PostgreSQL/PostGIS, Redis and a shared event-driven foundation.

The application exposes consistent envelopes for success and errors, a single auth layer, shared permissions, pagination conventions, audit logging and a transactional outbox for asynchronous work.

## Consequences

- One backend contract for all channels.
- Reusable auth and permission checks across modules.
- Consistent structured logging and auditability.
- Easier integration of business events and background jobs.
- Clear path for module owners to extend the foundation without custom business logic in adapters.
