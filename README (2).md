# NaijaLife AI --- MVP Engineering README & Developer Work Contracts

> **Project:** NaijaLife AI *(working name --- see section 1.3)*\
> **Release:** MVP v1.2 *(supersedes v1.1; see Appendices A and B for the change logs)*\
> **Document type:** Engineering handoff, work allocation and integration contract\
> **Status:** Baseline for implementation --- Contract A (backend foundation) delivered\
> **Architecture:** Modular monolith, API-first\
> **Primary MVP:** Community food purchasing + shared logistics + verified savings + direct farmer-to-supplier sourcing\
> **Channels:** USSD-first, Flutter mobile, web dashboard, SMS and WhatsApp integration, community-agent assisted ordering, farmer USSD/app access\
> **Backend:** Python / FastAPI\
> **Database:** PostgreSQL + PostGIS\
> **Cache/session store:** Redis\
> **Optimisation:** Google OR-Tools

------------------------------------------------------------------------

## 1. Project purpose

NaijaLife AI is a community economic coordination platform designed to
reduce the total cost of essential food purchases by aggregating
household demand, connecting communities with verified suppliers,
comparing total delivered costs and coordinating shared transport.

The MVP supports:

-   Community group purchasing, including recurring standing baskets.
-   Supplier registration, verification, inventory and quotations.
-   Product and price intelligence, including a community price index.
-   Order creation and payment confirmation.
-   Delivery to community collection points or customers' doorsteps.
-   Third-party registered transport operators with consolidated loads.
-   Full USSD access to core workflows for basic-phone users.
-   Community agents who can place orders on behalf of members.
-   Verified Savings Receipts for every completed order.
-   Supplier scorecards that make quality and reliability visible.
-   **Direct farmer-to-supplier sourcing:** verified farmers publish
    harvest availability and suppliers send sourcing requests, so supply
    reaches communities through fewer middlemen, with traceable origin.
-   SMS notifications and human-assisted support.
-   Operational reporting and initial AI-assisted intelligence.

**This is not simply a food delivery marketplace.** The system must
coordinate demand, supply, purchasing and logistics while maintaining
transparent pricing and human accountability.

**Scope boundary:** The platform is limited to **food sourcing,
purchasing and logistics**: farmer-to-supplier supply, community
purchasing, and delivery. It is not a general e-commerce marketplace,
farm-inputs store, lender, insurer or advisory service (see section 3
exclusions).

### 1.1 The problem

-   **Households buy alone.** Individual buyers have no bargaining power
    and pay retail prices plus several layers of middlemen.
-   **Prices are opaque.** Buyers cannot easily tell whether a discount
    is real or whether two offers are the same grade, quantity and
    delivery cost.
-   **Logistics is wasteful.** Small deliveries travel half-empty and
    transport operators have no organised way to share loads.
-   **Basic-phone users are excluded.** Most food technology assumes a
    smartphone and mobile data.
-   **Trust is weak.** Fraud, quality disputes and unverified suppliers
    discourage people from pooling money.
-   **Farmers sell through long, opaque chains.** Smallholders often
    depend on several intermediaries, have little visibility of
    demand, and cannot prove the quality or origin of what they grow.
    Suppliers, in turn, struggle to find reliable, traceable farm
    sources.

### 1.2 How this platform is deliberately different

Group buying for food already exists in Nigeria. Building "another
bulk-buying app" is not the goal. The platform competes on seven
differentiators; each is a binding product requirement, not marketing
language.

| \# | Differentiator | What it means in the system |
|----|----------------|-----------------------------|
| 1 | **Verified savings are the product** | Every completed order can show a Verified Savings Receipt: baseline price, source, timestamp, grade, quantity and delivered cost. No comparable baseline means no savings claim. |
| 2 | **USSD-first, not USSD-added** | The USSD journey is designed first and the app is the richer option. Community agents extend reach to people who will not use any phone interface. |
| 3 | **Trusted communities, not strangers** | Groups form inside existing communities (estates, markets, faith groups, cooperatives, workplaces, unions). Community admins and collection points are the trust layer. |
| 4 | **Transport operators are partners** | Operators receive consolidated routes and a visible cost breakdown; shared-trip savings are attributed and shown to customers. |
| 5 | **Supplier accountability is visible** | Scorecards built from delivery success, grade accuracy, disputes and on-time rate are visible to communities. |
| 6 | **Predictable demand** | Standing baskets (e.g. a monthly rice, oil and beans basket) give suppliers recurring volume and give communities better quotations. |
| 7 | **Direct farm-to-supplier linkage** | Verified farmers publish harvest availability; verified suppliers source from them directly using anonymised demand signals. Origin (provenance) is recorded, and farm-gate, wholesale and delivered prices are shown as separate layers, never mixed. |

### 1.3 Naming

"NaijaLife AI" is generic and implies a chatbot; AI is a supporting
capability, not the product. **Candidate product name: Egbé** (Yoruba
for a group or association). The name is **not approved** until the
Product Owner completes trademark, domain, social-handle, local-language
and USSD/SMS-sender-ID checks (section 15). Until then:

-   Use "NaijaLife AI" in documentation and the repository name.
-   Keep the product name in a single configuration value (`APP_NAME`)
    and in translation files. Never hard-code it in business logic,
    templates or USSD menus.

------------------------------------------------------------------------

## 2. Product principles --- binding engineering requirements

1.  **One source of truth:** Mobile, web, USSD and messaging channels
    must use the same backend business services and transactional
    database.
2.  **Total delivered cost:** Comparisons must account for product
    grade, quantity, product price, delivery, handling and applicable
    fees.
3.  **No unverified payment success:** A payment is successful only
    after server-side verification from the payment provider.
4.  **No invented savings:** Savings are reported only against a
    comparable, timestamped baseline (section 6.6).
5.  **Human oversight:** Supplier verification, dispatch approval,
    disputes and exceptional refunds must have human workflows.
6.  **Digital inclusion:** Basic-phone users must be able to complete
    the core purchasing journey through USSD.
7.  **Security by design:** Minimise personal data, protect financial
    records and enforce role-based access.
8.  **Modular monolith first:** Keep clear module boundaries; do not
    introduce microservices without an agreed architectural decision.
9.  **Proof over promises:** Any savings, quality or reliability figure
    shown to a user must be reproducible from stored data and a
    documented formula.
10. **Consent when acting for someone else:** A community agent may act
    on a member's behalf only with recorded member consent, and every
    such action is auditable (section 6.7).
11. **Agents never touch customer funds:** Payments go from the
    customer to the payment provider. Agents and communities do not hold
    or forward money.
12. **Price layers are never mixed:** Farm-gate, supplier wholesale and
    delivered retail prices are distinct layers. A farm-gate price is
    never used as a baseline for a delivered purchase.
13. **Farmers are paid through approved channels:** The platform
    records sourcing agreements and payment confirmations but never
    holds or advances money for farmers or suppliers.
14. **Protect farmers' data:** Show area, not exact farm coordinates, in
    public views; reveal contact details only after an agreement is
    accepted; share demand data only in aggregated, anonymised form.

## 3. MVP scope and exclusions

### In scope

-   User registration and phone verification.
-   Communities (with a community type), membership and collection
    points.
-   Community agents: registration, assignment and agent-assisted
    ordering with member consent.
-   Product catalogue, grades and units.
-   Supplier onboarding, verification and inventory.
-   Timestamped price observations and a community price index.
-   Purchase groups and household quantity requests.
-   Standing baskets (recurring group purchases) with cycle management.
-   Supplier quotations and comparable cost calculation.
-   Orders, payment initiation, verification and reconciliation.
-   Verified Savings Receipts.
-   Collection-point and doorstep delivery.
-   Transport operator, driver and vehicle registration.
-   Basic vehicle capacity and route optimisation, with a delivery cost
    breakdown that shows shared-trip savings.
-   USSD registration, shopping, group participation, order and delivery
    status, including agent menus.
-   SMS transaction notifications and savings-receipt summaries.
-   Support tickets, complaints and audit logs.
-   Supplier scorecards, price anomaly rules and demand analytics.
-   Agent commission **recording** (accrual only; payout through an
    approved provider process).
-   Farmer and farmer-group registration, verification and farm-cluster
    locations.
-   Harvest listings, supplier sourcing requests, offers and sourcing
    agreements.
-   Supply lots with provenance, and receipt confirmation with
    discrepancy handling.
-   Anonymised demand signals shared with farmers and suppliers.
-   Farm-gate price observations (kept separate from retail prices).
-   Farmer reliability metrics for suppliers.

### Explicitly out of scope for MVP unless approved by the Product Owner

-   Passenger ride-hailing or passenger carpooling.
-   Owning or financing a vehicle fleet.
-   Advanced autonomous dispatch.
-   Computer vision for food grading.
-   Credit scoring or lending.
-   Unregulated escrow or custody of customer funds.
-   Split payments, instalments or rotating-savings style payment
    schedules. These need a licensed payment partner and legal approval;
    if explored, build behind `FEATURE_INSTALMENTS` (default off).
-   National rollout before a controlled pilot.
-   Complex microservice deployment.
-   Any non-food category, a farm-inputs (seed, fertiliser, equipment)
    marketplace, or general e-commerce.
-   Farmer financing, input credit, crop insurance, advance payments to
    farmers, land or contract-farming management.
-   Agronomy advisory services and commodity trading or futures.
-   Platform-held funds for farmer or supplier settlement.
-   Mandatory farm-pickup logistics (optional, behind
    `FEATURE_FARM_PICKUP`, default off).

## 4. System architecture

``` text
Flutter App   Web Dashboard   USSD Gateway   WhatsApp/SMS   Agent / Farmer (USSD/app)
     |               |               |                |                |
     +---------------+---------------+----------------+----------------+
                                     |
                              FastAPI Backend
                                     |
   ------------------------------------------------------------------------
   | Identity | Community | Agents   | Catalogue | Supplier | Pricing       |
   | Purchasing | Baskets | Orders   | Payments  | Logistics | Savings      |
   | Farmers  | Sourcing  | USSD      | Notifications | Support | Analytics   |
   ------------------------------------------------------------------------
                    |                         |
             PostgreSQL + PostGIS           Redis
                    |                         |
              Object Storage           Background Workers
                    |
      External providers: payment, USSD, SMS, maps/routing
```

### Technology baseline

| Area              | Baseline                                           |
|-------------------|----------------------------------------------------|
| Backend           | Python 3.12, FastAPI, Pydantic                     |
| Database          | PostgreSQL with PostGIS                            |
| Migrations        | Alembic                                            |
| ORM               | SQLAlchemy 2.x                                     |
| Cache/session     | Redis                                              |
| Background jobs   | Celery (inline backend for tests/local)            |
| Mobile            | Flutter                                            |
| Web               | React / Next.js                                    |
| Optimisation      | Google OR-Tools                                    |
| API documentation | OpenAPI / Swagger                                  |
| Containers        | Docker                                             |
| Testing           | Pytest, Flutter tests, web test framework          |
| CI                | Automated lint, test, migration and build checks   |

Exact dependency versions are pinned in `backend/requirements.txt`. A
developer must not independently replace a shared technology without an
approved Architecture Decision Record (ADR).

------------------------------------------------------------------------

# 5. Developer work allocation

The work is split into contracts. Each developer owns their module, its
tests and documentation, but must integrate through the shared API and
data contracts.

A person may hold more than one role in a small team. The
responsibilities must still remain explicit.

## Contract A --- Backend foundation and platform architecture

**Owner:** Backend Lead\
**Status:** ✅ **Delivered** (see `backend/README.md` and
`docs/adr/0001-backend-foundation-conventions.md`)\
**Primary responsibility:** Shared backend foundation and cross-module
standards.

### Delivered

-   FastAPI project structure and module folders.
-   Environment configuration; staging/production refuse placeholder
    secrets, example credentials and the inline job backend.
-   SQLAlchemy 2 setup and Alembic migrations (initial migration enables
    PostGIS and creates `users` and `audit_logs`; verified to run from an
    empty database and match the models).
-   PostgreSQL/PostGIS and Redis connections.
-   JWT authentication foundation and role/permission-based access
    control (`app/shared/permissions.py`).
-   Shared success/error envelopes, validation conventions and
    pagination (`?page=&page_size=`, max 100).
-   Structured JSON logging with request IDs and automatic redaction;
    audit helper (`record_audit`) that commits atomically with business
    changes.
-   Shared domain-event bus (idempotent consumers), transactional
    outbox and background-job interface.
-   `/health` and `/ready` endpoints.
-   Docker development environment, pinned dependencies, CI workflow
    (lint, tests, migrations on PostGIS, dependency scan, image build).

### Must expose (available now)

-   `CurrentUser`, `DbSession` dependencies.
-   `require_roles`, `require_permissions`,
    `ensure_owner_or_permission`.
-   `ok()`, `SuccessEnvelope`, standard error classes.
-   `Pagination`, `paginate`, `paginated_ok`.
-   `record_audit`, `@job`/`enqueue`, `DomainEvent`/`event_bus`.

### Follow-up work from v1.1/v1.2 (Backend Lead) --- status

-   ✅ `Role.COMMUNITY_AGENT` and `Role.FARMER`, plus the agent, scorecard,
    price-index, farmer and sourcing permissions, with the permission
    matrix and tests updated.
-   ✅ Redis-based rate limiting as a shared dependency (`RateLimiter`,
    per-IP or custom key such as the MSISDN, standard 429 envelope with
    `Retry-After`). Contract G applies it to the USSD callbacks.
-   ✅ Transactional **outbox** (`emit(db, event)`), with a dispatcher
    that retries with backoff, parks repeated failures as `FAILED`, and
    is safe to run on several workers. Also fixed a defect where a failed
    event handler would never be retried.
-   ✅ All event names from section 6.5 added to `EventNames`.
-   ✅ Trusted-proxy handling for client IPs (`TRUSTED_PROXIES`);
    `X-Forwarded-For` is ignored unless the direct peer is a trusted
    proxy.
-   ✅ Migrations and the full test suite verified on real
    PostgreSQL 16 + PostGIS 3.4 and real Redis, and wired into CI.
-   ⏳ Remaining: confirm the Docker image build and docker-compose stack
    in CI (not testable in the build environment); module owners apply
    `RateLimiter` to their endpoints; alerting on `FAILED` outbox rows
    (Contract K).

### Acceptance criteria

-   A new developer can run the backend using the documented setup.
-   Database migrations run from an empty database.
-   API docs are generated.
-   Protected endpoints reject unauthenticated requests.
-   Role-restricted endpoints reject unauthorised roles.
-   Secrets are not committed to source control.
-   Unit and integration tests run in CI.

### Must not

-   Implement separate business rules inside channel adapters.
-   Commit credentials or production customer data.
-   Change shared API conventions without review.

------------------------------------------------------------------------

## Contract B --- Identity, community and access management

**Owner:** Backend Developer 2 (or Backend Lead)\
**Primary responsibility:** Users, roles, communities, addresses,
collection points and community agents.

### Deliverables

-   User registration and profile management (extend the foundation
    `users` table; do not replace it).
-   Phone-number normalisation and verification workflow.
-   User roles and permissions integration.
-   Community creation and discovery, with a **community type**
    (estate, market, faith group, cooperative, workplace, union, other).
-   Community membership and community-admin assignment.
-   **Community agents:** application, approval, community assignment,
    suspension and agent identity verification.
-   **Member consent records** that authorise an agent to order on a
    member's behalf (scope, expiry, revocation).
-   User addresses and saved delivery locations.
-   Collection-point management, including operating hours and
    responsible person.
-   Consent and preferred-language fields.
-   Support the `farmer` role for phone-verified users (farmer profile
    and farm data live in Contract L); agents may assist farmer
    registration under the same consent rules.

### API ownership

``` text
POST   /api/v1/auth/register
POST   /api/v1/auth/verify-phone
POST   /api/v1/auth/login
GET    /api/v1/users/me
PATCH  /api/v1/users/me

GET    /api/v1/communities
POST   /api/v1/communities
POST   /api/v1/communities/{community_id}/join
GET    /api/v1/communities/{community_id}/collection-points
POST   /api/v1/addresses
GET    /api/v1/addresses
PATCH  /api/v1/addresses/{address_id}

POST   /api/v1/agents/applications
POST   /api/v1/agents/{agent_id}/approve        # authorised staff
POST   /api/v1/communities/{community_id}/agents
POST   /api/v1/members/{user_id}/agent-consents
DELETE /api/v1/members/{user_id}/agent-consents/{consent_id}
```

### Acceptance criteria

-   Phone numbers are stored in normalised international format.
-   A user can join a community only once.
-   Users can only modify their own profile and addresses unless
    authorised.
-   Collection points belong to a valid community.
-   Geographic fields use PostGIS-compatible types.
-   All sensitive changes are auditable.
-   An agent can act only for members of communities they are assigned
    to and only while a valid, unrevoked consent exists.
-   Suspended agents lose agent access immediately.

------------------------------------------------------------------------

## Contract C --- Catalogue, suppliers, inventory and price intelligence

**Owner:** Backend Developer 3\
**Primary responsibility:** Product data, supplier listings, stock,
price observations, the community price index and supplier scorecard
inputs.

### Deliverables

-   Product categories, products, grades and units.
-   Supplier registration and verification states.
-   Supplier document metadata and private file references.
-   Supplier locations.
-   Inventory and stock updates.
-   Supplier quotations support.
-   Price observations with source and timestamp.
-   Comparable-price query logic.
-   Stale-price and suspicious-price flags.
-   **Community price index:** periodic, reviewable publication of
    comparable prices per product, grade, unit and area.
-   **Supplier scorecard data feed** consumed by Contract J (delivery
    success, grade accuracy, disputes, on-time rate).
-   **Baseline snapshot** storage so a savings receipt always references
    the exact observations used (section 6.6).
-   **Farm-gate price observations** (source type `farm_gate`) stored
    separately from retail/wholesale observations and never mixed in
    comparisons.
-   Optional **supply-lot reference** on supplier inventory so a listing
    can show provenance when a lot record exists (Contract L).

### API ownership

``` text
GET    /api/v1/products
POST   /api/v1/products                 # authorised admin
GET    /api/v1/products/{product_id}
GET    /api/v1/products/{product_id}/prices

POST   /api/v1/suppliers
GET    /api/v1/suppliers
GET    /api/v1/suppliers/{supplier_id}
PATCH  /api/v1/suppliers/{supplier_id}
GET    /api/v1/suppliers/{supplier_id}/scorecard

POST   /api/v1/suppliers/{supplier_id}/inventory
GET    /api/v1/suppliers/{supplier_id}/inventory
POST   /api/v1/price-observations
GET    /api/v1/prices/compare
GET    /api/v1/price-index
POST   /api/v1/price-index/publish      # authorised staff, after review
```

### Acceptance criteria

-   Product grade, unit and quantity basis are explicit.
-   Inventory cannot become negative through normal stock operations.
-   Price records include source, location and observed timestamp.
-   Unverified supplier listings are not presented as verified.
-   Price comparison rejects or clearly separates incompatible grades
    and units.
-   Stale prices are visibly marked.
-   All prices use integer kobo.
-   A published price index entry lists its sample size, date range and
    sources; entries below the minimum sample size are not published.
-   Supplier scorecards are shown only for suppliers who have accepted
    the scorecard-publication policy (section 15).

------------------------------------------------------------------------

## Contract D --- Group purchasing, standing baskets, quotations and order lifecycle

**Owner:** Backend Developer 4\
**Primary responsibility:** Demand aggregation and purchase lifecycle.

### Deliverables

-   Purchase group creation and lifecycle states.
-   Product targets and closing deadlines.
-   Household purchase requests, including requests placed by an agent
    on a member's behalf.
-   Request modification and withdrawal before cutoff.
-   Aggregated demand summaries.
-   **Standing baskets:** a recurring template (products, grades, units,
    cadence) that opens a new purchase-group cycle automatically and
    lets members opt in, skip or leave each cycle.
-   Supplier quotation submission and comparison.
-   Group confirmation rules.
-   Order and order-item creation.
-   Order state transitions.
-   Total delivered cost calculation.
-   Capture of the **baseline snapshot reference** at quotation
    approval so Contract J can issue a savings receipt.
-   Publication of **aggregated, anonymised demand** (product, grade,
    unit, quantity, area, date window) to Contract L when a group
    closes. Never expose member identities.

### API ownership

``` text
POST   /api/v1/purchase-groups
GET    /api/v1/purchase-groups
GET    /api/v1/purchase-groups/{group_id}
POST   /api/v1/purchase-groups/{group_id}/join
POST   /api/v1/purchase-groups/{group_id}/requests
PATCH  /api/v1/purchase-requests/{request_id}
DELETE /api/v1/purchase-requests/{request_id}
GET    /api/v1/purchase-groups/{group_id}/summary
POST   /api/v1/purchase-groups/{group_id}/quotations
GET    /api/v1/purchase-groups/{group_id}/quotations
POST   /api/v1/purchase-groups/{group_id}/confirm

POST   /api/v1/baskets
GET    /api/v1/baskets
GET    /api/v1/baskets/{basket_id}
POST   /api/v1/baskets/{basket_id}/subscribe
POST   /api/v1/baskets/{basket_id}/cycles/{cycle_id}/skip

GET    /api/v1/orders
GET    /api/v1/orders/{order_id}
```

A purchase request submitted by an agent carries `placed_by_agent_id`
and a reference to the member's active consent (section 6.7).

### Required business states

Purchase group:

``` text
DRAFT -> OPEN -> CLOSED -> QUOTING -> AWAITING_APPROVAL
      -> CONFIRMED -> FULFILLING -> COMPLETED
      -> CANCELLED
```

Order:

``` text
PENDING_PAYMENT -> PAID -> PROCESSING -> READY_FOR_PICKUP
                -> IN_TRANSIT -> DELIVERED
                -> DISPUTED / CANCELLED / REFUND_PENDING / REFUNDED
```

The implementation may refine states, but changes must be documented and
agreed with the Backend Lead.

### Acceptance criteria

-   Group demand is aggregated by product, grade and unit.
-   A closed group cannot accept new requests unless an authorised
    reopening occurs.
-   Users cannot alter confirmed orders without an explicit amendment
    workflow.
-   The selected quotation and final customer amount are recorded.
-   Order creation is transaction-safe and idempotent.
-   The customer sees the final price and delivery method before
    payment.
-   A standing-basket cycle never creates duplicate groups or orders if
    the scheduler runs twice.
-   Members can skip or leave a basket cycle before cutoff without
    penalty.
-   Agent-placed requests are rejected without a valid member consent.

------------------------------------------------------------------------

## Contract E --- Payments and financial reconciliation

**Owner:** Backend Developer 5 or designated Payments Engineer\
**Primary responsibility:** Payment-provider integration and financial
integrity.

### Deliverables

-   Payment provider abstraction.
-   Payment-intent creation.
-   Provider checkout or supported payment instructions.
-   Webhook signature verification.
-   Idempotent event processing.
-   Payment status transitions.
-   Payment reconciliation records.
-   Refund request workflow.
-   Customer receipt that links to the Verified Savings Receipt.
-   Administrative transaction view.
-   **Agent commission accrual records** (amount, order, agent, status).
    Records only; payout is performed through an approved provider
    process and never from customer funds held by the platform.
-   Optional, **feature-flagged** instalment/split-payment design
    document (no implementation without legal approval).
-   **Supplier-to-farmer payment handling:** in the MVP, payment
    instructions and confirmation records through the approved provider
    with no platform custody. The settlement model is a product
    decision (section 15).

### API ownership

``` text
POST   /api/v1/orders/{order_id}/payment-intent
GET    /api/v1/payments/{payment_id}
POST   /api/v1/payments/webhooks/{provider}
POST   /api/v1/payments/{payment_id}/refund
GET    /api/v1/orders/{order_id}/receipt
GET    /api/v1/agents/{agent_id}/commissions
```

### Mandatory controls

-   Do not store card details, banking PINs or internet banking
    credentials.
-   Never mark a payment successful based only on a frontend redirect.
-   Verify signed provider callbacks.
-   Use provider transaction references and idempotency.
-   Store money as integer kobo.
-   Maintain a payment event history.
-   Reconcile provider settlement reports.
-   Refunds require an authorised, auditable process.
-   Do not implement an unlicensed escrow or customer-fund custody
    model.
-   Agents must never receive or forward customer payments.
-   Store farmer payout details only as provider tokens/references.
    No advance or credit payments to farmers.

### Acceptance criteria

-   Duplicate webhook delivery does not duplicate a payment.
-   Invalid signatures are rejected.
-   Payment status is updated only after verification.
-   Failed and pending payments are distinguishable.
-   A payment can be reconciled to one valid order and amount.
-   Automated tests cover duplicate, delayed and out-of-order callbacks.
-   A commission accrues only after the related order is delivered and
    not disputed; refunded orders reverse the accrual.

------------------------------------------------------------------------

## Contract F --- Logistics, transport operators and route optimisation

**Owner:** Logistics Engineer / Backend Developer 6\
**Primary responsibility:** Third-party fleet coordination and delivery
execution.

### Deliverables

-   Transport operator registration and verification.
-   Driver and vehicle registration.
-   Vehicle weight and volume capacity.
-   Operator service areas and availability.
-   Delivery mode: collection point or doorstep.
-   Delivery cost estimation.
-   **Delivery cost breakdown** (distance/time, handling, fees) and
    **shared-trip saving** attribution per order.
-   **Consolidated load offers** that let operators see and accept
    guaranteed multi-order loads.
-   Supplier pickup and customer drop-off stops.
-   Optional **farm-pickup stops** for inbound legs from farm clusters
    to supplier hubs (stretch; behind `FEATURE_FARM_PICKUP`).
-   OR-Tools optimisation service.
-   Manual dispatch approval.
-   Driver status updates.
-   Proof of delivery and failed-delivery workflow.

### API ownership

``` text
POST   /api/v1/transport/operators
POST   /api/v1/transport/vehicles
POST   /api/v1/transport/drivers
POST   /api/v1/transport/availability
GET    /api/v1/transport/load-offers
POST   /api/v1/transport/load-offers/{offer_id}/accept

POST   /api/v1/deliveries/quote
POST   /api/v1/deliveries/optimise
POST   /api/v1/deliveries/{delivery_id}/assign
GET    /api/v1/deliveries/{delivery_id}
GET    /api/v1/deliveries/{delivery_id}/cost-breakdown
POST   /api/v1/deliveries/{delivery_id}/events
POST   /api/v1/deliveries/{delivery_id}/proof
```

### Optimisation constraints

-   Vehicle weight capacity.
-   Vehicle volume capacity where available.
-   Supplier pickup precedence.
-   Delivery time windows.
-   Driver and vehicle availability.
-   Collection-point and doorstep destinations.
-   Operator service area.
-   Cost and distance.

### Acceptance criteria

-   No route exceeds the assigned vehicle's configured capacity.
-   Required pickup stops precede associated delivery stops.
-   A route has a calculated cost and estimated duration.
-   The dispatcher can review and approve the route.
-   Every status update records actor and timestamp.
-   Delivery proof is tied to the correct order and recipient.
-   Failed delivery has a reason and escalation path.
-   The cost breakdown's parts sum exactly to the delivery fee in kobo.
-   A shared-trip saving is shown only when a comparable standalone
    delivery cost can be calculated (same rules as section 6.6).

### Important

Use OR-Tools for the optimisation problem. Do not ask an LLM to
calculate vehicle routes or enforce capacity constraints.

------------------------------------------------------------------------

## Contract G --- USSD, SMS and WhatsApp channels

**Owner:** Channel Integration Developer\
**Primary responsibility:** Basic-phone access, agent-assisted access and
messaging integrations. **USSD is the primary channel design; the app is
the richer option.**

### Deliverables

-   USSD provider integration.
-   Provider callback authentication and rate limiting.
-   Redis-backed session state.
-   Menu/state-machine implementation.
-   Registration and community selection.
-   Product and price lookup.
-   Group discovery and joining.
-   Standing-basket subscription, skip and leave.
-   Quantity submission.
-   Quotation and order status.
-   Payment instructions.
-   Collection-point and doorstep selection.
-   Delivery status and support escalation.
-   **Agent menu:** look up a member, confirm consent, place or amend a
    request on the member's behalf, and show the member's order status.
-   **Farmer menu:** register, publish or update a harvest listing,
    view and accept sourcing requests, confirm dispatch, and check
    payment confirmation, in the farmer's preferred language.
-   SMS confirmations and alerts, including a **short savings-receipt
    summary** after delivery (only when a valid receipt exists).
-   WhatsApp integration where provider approval and templates permit.

### API ownership

``` text
POST   /api/v1/channels/ussd/callback
POST   /api/v1/channels/ussd/status
POST   /api/v1/notifications/sms
POST   /api/v1/notifications/whatsapp
```

### USSD requirements

-   Keep menus short and understandable.
-   Support session expiry and recovery.
-   Validate every user input.
-   Do not trust phone number alone for sensitive operations.
-   Do not request banking PINs or card credentials.
-   Send transaction references by SMS where possible.
-   Reuse core purchasing and order services.
-   Support English first and add validated local-language flows
    (Hausa, Igbo, Yoruba, Nigerian Pidgin).
-   Provide an agent escalation option.
-   Agent actions require agent authentication stronger than caller ID
    alone (for example an agent PIN to the platform's own agent service,
    never a banking PIN) and are rate limited.
-   Product name and wording come from translation/config files, not
    code.

### Acceptance criteria

-   A basic-phone user can complete the core purchase journey.
-   An agent can complete a purchase for a consenting member.
-   A farmer can publish a listing and accept a sourcing request using
    USSD only.
-   A session interruption does not create duplicate requests or orders.
-   Expired sessions fail safely.
-   Invalid menu input returns a clear prompt.
-   Session data expires from Redis.
-   Gateway callbacks are authenticated and rate-limited.
-   USSD provider errors are logged without exposing sensitive data.
-   Agent actions without valid consent fail with a clear message and
    are logged.

------------------------------------------------------------------------

## Contract H --- Mobile application

**Owner:** Flutter Developer\
**Primary responsibility:** Customer and, if agreed, driver- and
agent-facing mobile experience.

### Deliverables

-   Authentication and profile.
-   Community selection.
-   Product browsing and price comparison.
-   Group purchasing.
-   Standing baskets (subscribe, skip, leave).
-   Quantity management.
-   Quotation comparison.
-   Order history and receipts.
-   **Verified Savings Receipt screen** showing the baseline, its
    source/date and the delivered cost.
-   **Supplier scorecard** view.
-   Payment-provider flow.
-   Collection-point and doorstep selection.
-   Delivery status and delivery cost breakdown.
-   Complaint and support interface.
-   Agent mode (if agreed): member lookup, consent capture and
    assisted ordering.
-   Push notifications where configured.

### Integration contract

The mobile application must consume documented `/api/v1` endpoints. It
must not connect directly to PostgreSQL or implement independent
pricing, savings, payment or purchasing rules.

### Acceptance criteria

-   Loading, empty, error and success states exist for every major
    screen.
-   Users cannot see another user's private orders.
-   Final payable amount comes from the backend.
-   Savings figures are displayed exactly as returned by the backend; a
    missing receipt shows "savings not available", never an estimate.
-   Payment status is refreshed from the backend.
-   Network failure does not silently duplicate an order.
-   App permissions are requested only when needed.

------------------------------------------------------------------------

## Contract I --- Web dashboards

**Owner:** React / Next.js Developer\
**Primary responsibility:** Supplier, operations, community and
administration interfaces.

### Deliverables

-   Admin overview.
-   Supplier onboarding and verification queue.
-   Product and inventory management.
-   Price observations review and **price-index publication review**.
-   Group purchasing and **standing-basket** management.
-   Quotation comparison.
-   Order and payment monitoring.
-   Transport operator and vehicle management, and **load-offer**
    management.
-   Dispatch and delivery monitoring.
-   **Community agent management** (applications, assignments,
    suspension, commission accruals).
-   **Farmer verification queue**, harvest-listing moderation and
    **sourcing agreement monitoring** (disputes, discrepancies).
-   **Supplier scorecard** moderation and publication controls.
-   Support tickets and dispute management.
-   Community and savings reports.

### Acceptance criteria

-   Dashboard data comes from authorised APIs.
-   Role-based navigation and endpoint permissions are enforced.
-   Sensitive actions require confirmation.
-   Financial values are displayed in naira while stored in kobo.
-   Administrative actions are auditable.
-   Tables support pagination and useful filtering.
-   Publishing a price index or scorecard requires an explicit,
    audited confirmation.

------------------------------------------------------------------------

## Contract J --- AI, analytics, savings and impact measurement

**Owner:** AI / Data Engineer\
**Primary responsibility:** Data quality, analytical models, **Verified
Savings Receipts**, supplier scoring and measured impact.

### Deliverables

-   Data dictionary and analytics definitions.
-   **Verified Savings Receipt service** (formula and baseline policy in
    section 6.6) with receipt API and immutable stored receipts.
-   Demand aggregation and baseline forecasting, including
    standing-basket demand.
-   **Supplier scorecard** calculation and explanation of each component.
-   **Farmer reliability scoring** (fulfilment rate, grade accuracy,
    timeliness) with documented formulas.
-   **Price-chain analytics** showing farm-gate, wholesale and delivered
    price layers separately.
-   Demand-signal forecasting for farmers and suppliers (aggregated
    only).
-   Price anomaly rules.
-   Community and operations dashboards.
-   Model evaluation and monitoring.
-   Controlled AI assistant integration, if included in launch scope.

### API ownership

``` text
GET    /api/v1/orders/{order_id}/savings-receipt
GET    /api/v1/communities/{community_id}/savings-summary
GET    /api/v1/analytics/supplier-scores
```

### Initial model priorities

1.  Deterministic price comparison and verified savings.
2.  Supplier performance scoring.
3.  Statistical price anomaly flags.
4.  Simple demand baseline.
5.  More advanced forecasting only after sufficient quality data.

### Acceptance criteria

-   Every metric has a documented formula.
-   Savings use comparable product, grade, quantity, location and time.
-   Missing or weak baseline data does not produce a savings claim; the
    receipt states why (for example "insufficient comparable prices").
-   A receipt stores the baseline observations it used and is never
    recalculated after issue; corrections create a new, linked receipt.
-   Community savings totals include only orders that have a valid
    receipt and state how many orders were excluded.
-   Models are evaluated against a baseline.
-   Predictions include model/version and generation timestamp.
-   AI assistant cannot directly mutate orders or payments without
    authorised backend workflows.

------------------------------------------------------------------------

## Contract K --- QA, DevOps and security

**Owner:** QA / DevOps Lead\
**Primary responsibility:** Release quality, deployment, test automation
and operational readiness.

### Deliverables

-   CI/CD pipelines.
-   Development, staging and production environments.
-   Docker build and deployment configuration.
-   Automated unit, integration and end-to-end tests.
-   Database migration checks (on PostGIS).
-   API contract tests.
-   Load and resilience tests.
-   Backup and restore test.
-   Security review and dependency scanning.
-   Monitoring and alerting.
-   Release checklist and rollback plan.
-   Test packs for savings receipts, agent consent, standing-basket
    scheduling, sourcing reservations (no overselling) and demand-signal
    anonymisation.

### Acceptance criteria

-   Pull requests cannot merge when required checks fail.
-   Staging deployment is reproducible.
-   Production secrets are managed outside source control.
-   Database backups are configured and restore-tested.
-   Critical errors trigger alerts.
-   Payment and USSD integrations have failure-path tests.
-   Release has a documented rollback procedure.
-   Tests prove that a savings receipt is not issued without a valid
    baseline, and that agent actions fail without valid consent.

------------------------------------------------------------------------

## Contract L --- Farmer sourcing and direct supplier linkage

**Owner:** Backend Developer 7 (or Backend Developer 3 and 4 jointly in a
small team)\
**Primary responsibility:** Connect verified farmers and farmer groups
directly with verified suppliers (aggregators and wholesalers), so that
supply reaches communities through fewer intermediaries, with traceable
origin and transparent farm-gate pricing.

**Scope boundary:** Food only. This contract covers sourcing between
farmers and suppliers. It does not cover farm inputs, financing,
insurance, advisory services or holding funds.

### Deliverables

-   Farmer and farmer-group (cooperative) registration and profile.
-   Farm or farm-cluster location using PostGIS types; public views show
    area only.
-   Farmer verification states (`PENDING`, `VERIFIED`, `SUSPENDED`) with
    a human review workflow.
-   **Harvest listings:** product, grade, unit, quantity available,
    availability window, indicative farm-gate price (kobo) and expiry.
-   **Supplier discovery** of listings by product, grade, area,
    availability and farmer reliability.
-   **Sourcing requests** from verified suppliers (product, grade,
    quantity, delivery window), optionally linked to a demand signal.
-   **Offers and sourcing agreements** (quantity, grade specification,
    farm-gate price, handover point, date) with an auditable state
    machine and an amendment workflow.
-   **Supply lots and provenance:** on receipt the supplier records a lot
    linked to the farmer(s); provenance is shown to customers only when
    a lot record exists and the farmer has consented.
-   **Receipt confirmation** with quantity and grade check, and a
    discrepancy path into the support/dispute workflow.
-   **Demand signals** built from aggregated, anonymised group demand
    (Contract D) for farmers and suppliers.
-   Posting of **farm-gate price observations** to Contract C.
-   Reliability data feed for Contract J.

### API ownership

``` text
POST   /api/v1/farmers
GET    /api/v1/farmers/{farmer_id}
PATCH  /api/v1/farmers/{farmer_id}
POST   /api/v1/farmers/{farmer_id}/verify          # authorised staff
POST   /api/v1/farms

POST   /api/v1/harvest-listings
GET    /api/v1/harvest-listings
PATCH  /api/v1/harvest-listings/{listing_id}

POST   /api/v1/sourcing-requests
GET    /api/v1/sourcing-requests
POST   /api/v1/sourcing-requests/{request_id}/offers
POST   /api/v1/sourcing-offers/{offer_id}/accept
GET    /api/v1/sourcing-agreements/{agreement_id}
POST   /api/v1/sourcing-agreements/{agreement_id}/events
POST   /api/v1/sourcing-agreements/{agreement_id}/receipt-confirmation

GET    /api/v1/demand-signals
```

### Required business states

Harvest listing:

``` text
DRAFT -> PUBLISHED -> RESERVED -> FULFILLED
                   -> EXPIRED / WITHDRAWN
```

Sourcing agreement:

``` text
PROPOSED -> ACCEPTED -> DISPATCHED -> RECEIVED -> PAID -> COMPLETED
         -> DISPUTED / CANCELLED
```

`PAID` is set only from a payment confirmation event owned by Contract E.
The sourcing module never marks payment itself.

### Acceptance criteria

-   Only verified farmers can publish listings visible to suppliers;
    only verified suppliers can create sourcing requests.
-   Quantities carry units, prices are integer kobo and grades are
    explicit.
-   An offer or reservation cannot exceed the available quantity;
    reservations are transaction-safe and idempotent (no overselling).
-   An accepted agreement changes only through an explicit amendment
    workflow.
-   Demand signals contain no personal data and are published only when
    at least `DEMAND_SIGNAL_MIN_HOUSEHOLDS` households contributed.
-   A farmer's contact details are hidden from suppliers until an
    agreement is accepted.
-   Public views never show exact farm coordinates.
-   Farm-gate prices never appear in delivered-price baselines.
-   Provenance appears to customers only with a lot record and farmer
    consent.
-   A farmer can complete listing and acceptance through USSD alone.
-   Every state change records actor and timestamp and is auditable.

### Must not

-   Hold, advance or move funds for farmers or suppliers.
-   Force exclusivity between a farmer and a supplier.
-   Expose member identities in demand signals.
-   Implement pricing or savings rules outside the shared contracts.

------------------------------------------------------------------------

# 6. Shared API and data contracts

These rules apply to every developer.

## 6.1 API conventions

-   Base path: `/api/v1`.
-   JSON request and response bodies.
-   ISO 8601 timestamps (UTC).
-   UUID identifiers.
-   Money represented as integer kobo.
-   Explicit units for all quantities.
-   Pagination for collection endpoints (`page`, `page_size`; max 100;
    metadata in `meta.pagination`).
-   Consistent error envelope.
-   Authentication through bearer JWT access tokens.
-   OpenAPI specification is the shared source of API documentation.

### Standard success response

``` json
{
  "success": true,
  "data": {
    "id": "uuid",
    "status": "active"
  },
  "meta": {}
}
```

### Standard error response

``` json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The supplied quantity is invalid.",
    "details": []
  }
}
```

Do not expose stack traces, secrets, provider credentials or sensitive
personal data in API errors. Submitted input values are never echoed in
validation errors.

## 6.2 Money contract

-   Database: integer kobo.
-   API: integer kobo for authoritative monetary fields.
-   UI: format as naira.
-   Never use binary floating-point for financial calculations.
-   Round only according to documented business rules.

Example:

``` json
{
  "subtotal_kobo": 2500000,
  "delivery_fee_kobo": 150000,
  "total_kobo": 2650000,
  "currency": "NGN"
}
```

## 6.3 Quantity contract

Every quantity must include a unit.

Examples:

``` json
{
  "quantity": "2.5",
  "unit": "kg"
}
```

For internal calculations, use a defined decimal representation and
unit-conversion rules. Do not assume a bag, basket or measure has a
universal weight.

## 6.4 Order and payment ownership

-   Purchasing module owns purchase-group, basket and order business
    states.
-   Payments module owns payment states, commission accruals and
    provider event records.
-   Logistics module owns delivery states and load offers.
-   Savings module (Contract J) owns savings receipts; other modules
    only reference them.
-   Sourcing module (Contract L) owns harvest listings, sourcing
    requests, offers, agreements and supply lots.
-   A module must not directly overwrite another module's state.
-   Cross-module changes must use agreed service methods or domain
    events.

## 6.5 Domain events

Use internal events/background jobs for work that should not block an
API request.

Suggested event names:

``` text
user.registered
community.member_joined
agent.approved
agent.suspended
agent.order_placed
purchase_group.opened
purchase_group.closed
purchase_request.submitted
basket.cycle_opened
basket.cycle_skipped
quotation.received
quotation.approved
order.created
payment.initiated
payment.confirmed
payment.failed
delivery.planned
delivery.assigned
delivery.picked_up
delivery.delivered
delivery.failed
savings_receipt.issued
savings_receipt.withheld
supplier.scorecard_updated
price_index.published
commission.accrued
commission.reversed
farmer.registered
farmer.verified
harvest_listing.published
sourcing_request.created
sourcing_offer.accepted
sourcing_agreement.dispatched
sourcing_agreement.received
sourcing_agreement.completed
supply_lot.recorded
farmer.reliability_updated
support_ticket.opened
```

Events must have unique IDs, timestamps and versioned payloads.
Consumers must be idempotent. Publish after the business transaction
commits; use the outbox once available (Contract A follow-up).

## 6.6 Verified savings contract

A savings figure may be shown or sent to a user **only** through a
Verified Savings Receipt issued by Contract J.

**Baseline eligibility** (all values configurable, see section 13, and
confirmed by the Product Owner before launch):

-   Same product, **same grade** and a convertible **unit**.
-   Observed within `SAVINGS_BASELINE_MAX_AGE_DAYS` of the order.
-   Within `SAVINGS_BASELINE_RADIUS_KM` of the delivery area.
-   At least `SAVINGS_BASELINE_MIN_SAMPLES` independent observations from
    at least two distinct sources.
-   Outlier observations excluded by the documented anomaly rule.
-   Observations with source type `farm_gate` are never used as a
    baseline for a delivered retail purchase.

**Formula (integer kobo):**

``` text
baseline_total_kobo = sum over items( baseline_unit_price_kobo x quantity )
                      + baseline_delivery_kobo   # only if comparable
paid_total_kobo     = order total including delivery, handling and fees
savings_kobo        = baseline_total_kobo - paid_total_kobo   # may be <= 0
```

If savings is zero or negative, the receipt says so. It is never
hidden or rounded up.

**Receipt fields:**

``` json
{
  "receipt_id": "uuid",
  "order_id": "uuid",
  "status": "ISSUED",
  "baseline": {
    "method": "median_of_comparable_observations",
    "observation_ids": ["uuid"],
    "sample_size": 7,
    "oldest_observed_at": "2026-11-01T09:00:00Z",
    "newest_observed_at": "2026-11-05T14:30:00Z",
    "area": "text"
  },
  "baseline_total_kobo": 2900000,
  "paid_total_kobo": 2650000,
  "savings_kobo": 250000,
  "currency": "NGN",
  "formula_version": "1",
  "issued_at": "2026-11-06T10:00:00Z"
}
```

If no valid baseline exists, `status` is `WITHHELD`, `savings_kobo` is
`null`, and a `reason` is provided. Receipts are immutable; corrections
create a new receipt linked to the old one.

## 6.7 Agent-on-behalf-of contract

-   An agent may act only for a member who has granted an active,
    unrevoked, unexpired consent that covers the action.
-   Every agent-initiated request records `placed_by_agent_id`,
    `consent_id`, channel and timestamp, and writes an audit entry.
-   The member is notified (SMS where possible) of every agent-placed
    request and may cancel it before cutoff.
-   Agents never collect, hold or forward customer money.
-   Commission is accrued as a record only (Contract E) and reversed on
    refund or dispute.

## 6.8 Sourcing, price-layer and provenance contract

-   **Price layers:** `farm_gate`, `supplier_wholesale` and
    `delivered_retail`. Each observation and display states its layer.
    Layers are shown side by side in price-chain views and are never
    averaged or compared as if equivalent.
-   **Demand signals:** aggregated by product, grade, unit, area and
    date window; contain no personal data; withheld below
    `DEMAND_SIGNAL_MIN_HOUSEHOLDS`; time-limited and versioned.
-   **Provenance:** recorded at supply-lot level, linked to farmer and
    agreement, shown to customers only with farmer consent, and never
    including exact farm coordinates.
-   **Payments:** supplier-to-farmer settlement uses the approved
    provider process. The platform stores references and confirmations
    only and never holds or advances funds.
-   **Agreements:** immutable once accepted; changes create an amendment
    record with both parties' acceptance.

------------------------------------------------------------------------

# 7. Database ownership and migration rules

1.  The Backend Lead owns the base migration framework.
2.  Each module developer owns migrations for their module's tables.
3.  Table names and column changes must be communicated before merging.
4.  Do not edit a migration already applied to shared staging or
    production.
5.  Use a new migration for schema changes.
6.  Use foreign keys and database constraints where appropriate.
7.  Add indexes for common filters and joins.
8.  Use PostGIS types consistently for geographic fields.
9.  Keep financial event records auditable.
10. Do not use production personal data in local development.
11. Register every module's models in `app/models_registry.py` and run
    `alembic check` before opening a pull request.
12. The foundation `users` and `audit_logs` tables are owned as follows:
    `audit_logs` by the Backend Lead, `users` by Contract B (extend, do
    not recreate).

### Naming conventions

-   Tables: `snake_case`, plural nouns.
-   Columns: `snake_case`.
-   Primary key: `id`.
-   Foreign key: `<referenced_table_singular>_id`.
-   Timestamps: `created_at`, `updated_at`.
-   Status values: controlled enums or documented state strings.
-   API paths: plural resource names.

### Tables introduced by v1.1 and v1.2 (owners in brackets)

``` text
agents, agent_assignments, agent_consents        [B]
price_index_entries, baseline_snapshots          [C]
baskets, basket_subscriptions, basket_cycles     [D]
agent_commissions                                [E]
load_offers, delivery_cost_components            [F]
savings_receipts, supplier_scorecards            [J]
farmers, farms, farmer_groups                    [L]
harvest_listings, sourcing_requests              [L]
sourcing_offers, sourcing_agreements             [L]
supply_lots, demand_signals                      [L]
farmer_scorecards                                [J]
```

------------------------------------------------------------------------

# 8. Repository structure

Recommended monorepo:

``` text
naijalife-ai/
├── README.md
├── CONTRIBUTING.md
├── .env.example
├── docker-compose.yml
├── .github/workflows/ci.yml
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── database/
│   ├── ussd/
│   ├── security/
│   ├── adr/
│   └── operations/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── models_registry.py
│   │   ├── core/
│   │   ├── shared/
│   │   ├── modules/
│   │   │   ├── identity/
│   │   │   ├── communities/
│   │   │   ├── agents/
│   │   │   ├── catalogue/
│   │   │   ├── suppliers/
│   │   │   ├── pricing/
│   │   │   ├── purchasing/
│   │   │   ├── baskets/
│   │   │   ├── orders/
│   │   │   ├── payments/
│   │   │   ├── logistics/
│   │   │   ├── savings/
│   │   │   ├── farmers/
│   │   │   ├── sourcing/
│   │   │   ├── ussd/
│   │   │   ├── notifications/
│   │   │   ├── support/
│   │   │   └── analytics/
│   │   └── workers/
│   ├── migrations/
│   ├── tests/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── pyproject.toml
├── mobile/
│   └── flutter_app/
├── web/
│   └── dashboard/
├── ai/
│   ├── demand_forecasting/
│   ├── supplier_scoring/
│   ├── price_anomaly/
│   ├── savings/
│   └── evaluation/
├── infrastructure/
│   ├── docker/
│   ├── deployment/
│   └── monitoring/
└── scripts/
```

The Backend Lead may adjust the exact folder layout, but module
boundaries and ownership must remain clear. Placeholders already exist for `communities`, `catalogue`, `suppliers`,
`pricing`, `purchasing`, `orders`, `payments`, `logistics`, `ussd`,
`notifications`, `support` and `analytics`. The `agents`, `baskets`,
`savings`, `farmers` and `sourcing` folders are new and are created by
their contract owners.

------------------------------------------------------------------------

# 9. Git workflow and pull-request contract

## Branch naming

``` text
main
develop
feature/<module>-<short-description>
bugfix/<module>-<short-description>
hotfix/<short-description>
```

Examples:

``` text
feature/ussd-group-joining
feature/logistics-route-optimisation
feature/payments-webhook-verification
feature/savings-receipt-issuance
feature/agents-consent-capture
bugfix/catalogue-unit-conversion
```

## Pull-request requirements

Every pull request must include:

-   What changed and why.
-   Contract/module owner.
-   Related issue or task ID.
-   API or database changes.
-   Tests added or updated.
-   Screenshots for UI changes where useful.
-   Security and privacy implications.
-   Migration notes.
-   Known limitations.

### Merge rules

-   No direct pushes to `main`.
-   At least one reviewer for normal changes.
-   Backend Lead reviews shared API, schema and architecture changes.
-   Payments changes require Payments Engineer review.
-   Savings-formula and baseline-policy changes require AI/Data
    Engineer **and** Product Owner review.
-   Security-sensitive changes (including agent consent and agent
    authentication) require security/technical lead review.
-   CI checks must pass.
-   Conflicting migrations must be resolved before merge.

------------------------------------------------------------------------

# 10. Sprint plan and workstream dependencies

The target implementation plan is 12 two-week sprints. Work can proceed
in parallel after shared contracts are agreed. **Sprint 2 (backend
foundation) is complete** at the baseline level described in Contract A;
its follow-up items are scheduled below.

| Sprint | Main outcome | Primary owners | Dependencies |
|--------|--------------|----------------|--------------|
| 1 | PRD, pilot research, architecture, API and data contracts; **naming checks, baseline policy, agent model and commission policy decisions** | Product, Operations, all leads | None |
| 2 | Backend foundation, CI, database, auth ✅ *delivered*; follow-ups: agent role, rate limiting, outbox, live-PostGIS CI | Backend Lead, DevOps | Sprint 1 |
| 3 | Communities (with types), agents and consent, **farmer accounts and verification**, catalogue, suppliers, inventory | Identity, Catalogue, Web | Sprint 2 |
| 4 | Group purchasing, quotations, **standing baskets** and **harvest listings** | Purchasing, Catalogue, Sourcing | Sprints 2--3 |
| 5 | Orders, payments, reconciliation and **commission accrual** | Purchasing, Payments, QA | Sprint 4 |
| 6 | Operators, vehicles, delivery workflows, **load offers**, and **sourcing requests, offers and agreements** | Logistics, Sourcing, Web, Mobile | Sprints 2--5 |
| 7 | OR-Tools route optimisation and **delivery cost breakdown** | Logistics, Data, Operations | Sprint 6 |
| 8 | USSD registration, browsing, group joining and **agent menu** | USSD, Backend, QA | Sprints 3--4 |
| 9 | USSD order, payment instructions, tracking and **savings SMS** and **farmer menu** | USSD, Payments, Logistics, Sourcing | Sprints 5--8 |
| 10 | **Savings receipts, price index, supplier and farmer scorecards, price-chain analytics**, demand signals and initial AI | AI/Data, Backend, Web | Reliable operational data |
| 11 | End-to-end testing, security, field validation, agent and consent testing | QA, DevOps, Operations | All core modules |
| 12 | Controlled pilot and measurement against the pilot success metrics | Product, Operations, all developers | Release candidate |

### Pilot success metrics (measured in Sprint 12)

Define targets with the Product Owner before the pilot; record actuals
from stored data only:

-   Verified savings per household (receipts only; withheld receipts
    reported separately).
-   Share of orders that received a valid receipt.
-   Group fill rate and standing-basket retention.
-   Delivery cost per order and shared-trip saving.
-   Share of orders placed via USSD and via agents.
-   On-time delivery rate and dispute rate.
-   Supplier scorecard coverage.
-   Share of supplier volume sourced directly from verified farmers,
    farm-gate price paid, and farmer fulfilment rate.

### Parallel work

These tasks should begin early, not at the end:

-   USSD provider procurement and shortcode application.
-   Payment provider onboarding and sandbox access.
-   Supplier and transporter recruitment.
-   Farmer cluster or cooperative and direct-supplier recruitment, and
    the farmer verification procedure.
-   Community-agent recruitment, training material and commission
    policy.
-   Pilot-community research and community-type selection.
-   Product grade and unit definition.
-   Baseline-price data collection (needed before savings receipts can
    be issued).
-   Collection-point assessment.
-   Name, trademark, domain and sender-ID checks.
-   Data-protection and legal review (including agent consent and any
    instalment-payment idea).

External provider approval timelines may extend the schedule.

------------------------------------------------------------------------

# 11. Definition of done

A task is not complete merely because the code runs on the developer's
machine.

A task is done when:

-   Requirements and acceptance criteria are satisfied.
-   Code follows agreed project conventions.
-   Unit tests are included.
-   Integration tests cover external or cross-module behaviour.
-   API documentation is updated.
-   Database migration is included where necessary.
-   Permissions and validation are enforced.
-   Error and failure paths are handled.
-   Logs do not expose secrets or sensitive data.
-   Any user-visible savings, quality or reliability figure traces to a
    documented formula and stored data.
-   Pull request is reviewed and merged.
-   Staging deployment is successful.
-   Relevant developer documentation is updated.

------------------------------------------------------------------------

# 12. Required end-to-end acceptance scenarios

Before pilot approval, QA must demonstrate these journeys.

### Scenario 1 --- Smartphone customer purchase

1.  Customer registers and joins a community.
2.  Customer browses available products.
3.  Customer joins a group and submits quantities.
4.  Supplier submits quotation.
5.  Customer sees final delivered cost.
6.  Customer confirms and pays.
7.  Payment provider confirms payment.
8.  Order is assigned to a delivery.
9.  Customer receives goods at collection point or doorstep.
10. Customer confirms receipt.
11. Customer views the Verified Savings Receipt (or a clear
    "savings not available" reason).

### Scenario 2 --- Basic-phone USSD customer purchase

1.  Customer dials the provisioned shortcode.
2.  Customer registers or retrieves their account.
3.  Customer selects a community.
4.  Customer browses an open group.
5.  Customer submits quantity.
6.  Customer selects collection point or saved doorstep address.
7.  Customer receives group and order updates.
8.  Customer confirms final amount.
9.  Customer completes the supported payment flow.
10. Customer checks delivery status and confirms receipt.
11. Customer receives an SMS savings-receipt summary when a valid
    receipt exists.

### Scenario 3 --- Shared logistics

1.  Multiple paid orders are ready.
2.  Orders are grouped by compatible pickup and delivery needs.
3.  Supplier pickup points are loaded.
4.  Vehicle capacities are checked.
5.  OR-Tools proposes routes.
6.  Dispatcher reviews and approves.
7.  Driver receives route instructions.
8.  Pickup and delivery events are recorded.
9.  Proof of delivery is captured.
10. Exceptions are escalated.
11. The cost breakdown and shared-trip saving are available to the
    customer.

### Scenario 4 --- Payment failure

1.  Customer initiates payment.
2.  Provider reports failure, timeout or pending status.
3.  Order is not marked paid.
4.  Customer can safely retry or use another supported method.
5.  A delayed duplicate webhook is processed idempotently.
6.  Reconciliation identifies the final provider status.

### Scenario 5 --- Dispute

1.  Customer reports missing or damaged goods.
2.  Support ticket is created and linked to the order.
3.  Relevant supplier, driver and delivery evidence is accessible to
    authorised staff.
4.  Human review records the decision.
5.  Refund or replacement is initiated through the approved process.
6.  Customer receives an update.
7.  The resolution is retained in the audit history.
8.  Supplier scorecard and any agent commission are updated or
    reversed accordingly.

### Scenario 6 --- Agent-assisted purchase

1.  An approved agent assigned to the community authenticates.
2.  Agent looks up a member who has an active consent.
3.  Agent places a quantity request on the member's behalf.
4.  Member receives an SMS and can cancel before cutoff.
5.  Member pays directly through the payment provider (never via the
    agent).
6.  Delivery completes; the commission accrues as a record only.
7.  A request attempted without valid consent is rejected and logged.

### Scenario 7 --- Standing basket cycle

1.  A community admin creates a monthly basket.
2.  Members subscribe; one member skips a cycle.
3.  The scheduler opens the next cycle (and, if run twice, creates no
    duplicate).
4.  The cycle follows the normal quotation, payment and delivery flow.
5.  Savings receipts are issued per order.

### Scenario 8 --- Savings withheld

1.  An order contains a product with too few comparable price
    observations.
2.  The order completes normally.
3.  The receipt status is `WITHHELD` with a stated reason.
4.  No savings figure appears in the app, dashboard or SMS, and the
    order is excluded (and counted as excluded) from community savings
    totals.

### Scenario 9 --- Farmer-to-supplier sourcing

1.  A farmer registers (via USSD, app or an assisted agent) and is
    verified by staff.
2.  The farmer publishes a harvest listing with grade, unit, quantity
    and window.
3.  A verified supplier sees an anonymised demand signal and creates a
    sourcing request.
4.  The farmer submits an offer; the supplier accepts and an agreement
    is recorded; the reservation reduces available quantity.
5.  The farmer's goods are handed over and the supplier confirms
    quantity and grade at receipt.
6.  Payment is made through the approved provider and the confirmation
    moves the agreement to `PAID`, then `COMPLETED`.
7.  A supply lot with provenance is created; a customer later sees the
    origin only because the farmer consented.
8.  A quantity discrepancy opens a dispute and updates the farmer
    reliability score.
9.  An attempt to oversell a listing is rejected, and the farm-gate
    price never appears in any delivered-price savings baseline.

------------------------------------------------------------------------

# 13. Environment variables

Commit `.env.example`, never a real `.env`.

Example:

``` dotenv
APP_ENV=local
APP_NAME=NaijaLifeAI
API_V1_PREFIX=/api/v1
LOG_LEVEL=INFO

DATABASE_URL=postgresql+psycopg://naijalife:naijalife@localhost:5432/naijalife
REDIS_URL=redis://localhost:6379/0

JWT_SECRET=replace_in_secret_manager
ACCESS_TOKEN_EXPIRE_MINUTES=30

JOB_BACKEND=inline          # "celery" is required in staging/production

PAYMENT_PROVIDER=sandbox
PAYMENT_SECRET_KEY=replace_me
PAYMENT_WEBHOOK_SECRET=replace_me

USSD_PROVIDER=replace_me
USSD_CALLBACK_SECRET=replace_me

SMS_PROVIDER=replace_me
SMS_API_KEY=replace_me

MAPS_PROVIDER=replace_me
OBJECT_STORAGE_BUCKET=replace_me
OBJECT_STORAGE_ACCESS_KEY=replace_me
OBJECT_STORAGE_SECRET_KEY=replace_me

# --- v1.1/v1.2 product-policy settings (values are Product Owner decisions) ---
SAVINGS_BASELINE_MAX_AGE_DAYS=replace_me
SAVINGS_BASELINE_RADIUS_KM=replace_me
SAVINGS_BASELINE_MIN_SAMPLES=replace_me
PRICE_INDEX_MIN_SAMPLES=replace_me
AGENT_COMMISSION_BPS=replace_me      # basis points of order value; accrual only
FEATURE_INSTALMENTS=false            # off until a licensed partner and legal approval exist
FEATURE_FARM_PICKUP=false            # optional farm-pickup logistics stops
HARVEST_LISTING_EXPIRY_DAYS=replace_me
FARM_GATE_PRICE_MAX_AGE_DAYS=replace_me
DEMAND_SIGNAL_MIN_HOUSEHOLDS=replace_me
```

The `PAYMENT_PROVIDER` value must match the selected provider's adapter
name before implementation. All provider credentials belong in a secret
manager or protected deployment environment. In staging and production
the application refuses to start with the placeholder JWT secret, the
example database credentials, or `JOB_BACKEND=inline`.

------------------------------------------------------------------------

# 14. Engineering communication and ownership rules

-   Each developer reports progress against their contract.
-   Each contract owner identifies blockers early.
-   API and schema changes are announced before implementation.
-   Cross-module integration is tested continuously, not postponed until
    the final sprint.
-   Product decisions are owned by the Product Owner.
-   Architecture decisions are recorded by the Backend/Technical Lead.
-   Financial and security decisions require designated review.
-   Operational assumptions must be validated with real suppliers,
    customers, agents and transporters.
-   No developer may silently change a business rule that affects
    another module.

### Weekly engineering review

Each workstream owner reports:

1.  Completed deliverables.
2.  Work in progress.
3.  Blockers and dependencies.
4.  API/schema changes proposed.
5.  Tests and quality status.
6.  Risks to the sprint commitment.

------------------------------------------------------------------------

# 15. Initial task handoff checklist

Before developers start coding, the Product Owner and Technical Lead
must confirm:

-   [ ] Pilot community and geographic boundary.
-   [ ] Eligible community types for the pilot.
-   [ ] Initial food products, grades and units.
-   [ ] Group minimum quantities and closing rules.
-   [ ] Standing-basket rules (cadence, cutoffs, skipping, leaving).
-   [ ] Supplier verification policy.
-   [ ] Supplier scorecard publication policy and supplier consent.
-   [ ] Savings baseline policy (maximum age, radius, minimum samples,
        outlier rule) and formula version 1.
-   [ ] Price-index publication rules and reviewer role.
-   [ ] Collection-point operating procedure.
-   [ ] Doorstep delivery pricing policy.
-   [ ] Transport operator and driver verification requirements.
-   [ ] Load-offer rules for operators.
-   [ ] Agent recruitment, verification, training and suspension policy.
-   [ ] Agent commission rate and accrual/reversal rules.
-   [ ] Member consent wording, duration and revocation rules.
-   [ ] Farmer and farmer-group verification policy.
-   [ ] Pilot farmer cluster or cooperative and the direct suppliers
        who will source from them.
-   [ ] Harvest-listing rules (expiry, grade definitions, quantity
        tolerance) and receipt-quality inspection procedure.
-   [ ] Supplier-to-farmer settlement model (provider process; no
        platform custody) and legal review.
-   [ ] Provenance display policy and farmer consent wording.
-   [ ] Demand-signal rules (minimum households, delay, area
        granularity).
-   [ ] Payment provider and settlement model.
-   [ ] Legal position on instalment or split payments (default: out of
        scope).
-   [ ] USSD provider, shortcode and commercial terms.
-   [ ] SMS and WhatsApp provider.
-   [ ] Refund, cancellation and dispute policy.
-   [ ] Data-protection notices and consent.
-   [ ] Product name decision (trademark, domain, social handles,
        local-language review, USSD/SMS sender ID).
-   [ ] Pilot success-metric targets.
-   [ ] API contracts and database ownership.
-   [ ] Developer names assigned to each contract.
-   [ ] Sprint board and acceptance criteria created.

Do not invent these decisions in code. Where a decision is not yet
confirmed, implement behind configuration or record it as a product
decision requiring approval.

------------------------------------------------------------------------

# 16. Final instruction to all developers

Build your assigned module as an independently testable component of one
integrated platform.

Do not build isolated applications that happen to share the NaijaLife
name. The purchasing engine, payment lifecycle, delivery system, savings
receipts and USSD channel must work together through documented
contracts.

**The objective is a reliable community economic system that helps
people buy essential food at a lower verified total cost, creates work
for farmers, local suppliers, transport operators and community agents,
and includes people who do not own smartphones.**

What sets this platform apart is proof and inclusion: savings that can
be verified, communities that already trust each other, and a phone
journey that works without a smartphone, and a shorter, traceable path
from farm to household. Every technical decision should
support that outcome.

------------------------------------------------------------------------

# Appendix A --- Change log (v1.0 → v1.1)

| Area | Change |
|------|--------|
| Header and section 1 | Added problem statement, six differentiators (1.2) and naming note (1.3); status updated for delivered foundation. |
| Section 2 | Added principles 9--11 (proof over promises, consent for agents, agents never touch funds). |
| Section 3 | Added agents, standing baskets, price index, savings receipts, scorecards and commission recording to scope; instalments/split payments explicitly out of scope behind a feature flag. |
| Section 4 | Architecture adds Agents, Baskets and Savings modules and the agent channel; Python pinned to 3.12; dependencies pinned in `requirements.txt`. |
| Contract A | Marked delivered with the list of what exists; added required follow-ups (agent role, rate limiting, outbox, live-PostGIS CI, proxy headers). |
| Contracts B--K | Added agent management and consent (B), price index and scorecard data (C), standing baskets and agent-placed requests (D), commission accrual (E), load offers and cost breakdown (F), agent menu and savings SMS (G), receipt and scorecard screens (H, I), receipt service and scoring (J), new test packs (K). |
| Section 6 | Pagination and bearer-token conventions made explicit; added 6.6 verified savings contract and 6.7 agent-on-behalf-of contract; expanded event list. |
| Sections 7--8 | New tables and module folders; models-registry rule. |
| Section 10 | Sprint plan re-scoped for new features; pilot success metrics added; new parallel tasks. |
| Section 12 | Scenarios 1--5 extended; added scenarios 6--8 (agent purchase, standing basket, savings withheld). |
| Section 13 | `.env.example` aligned with the foundation; added savings, commission and feature-flag settings; fixed the `PAYMENT_PROVIDER` example. |
| Section 15 | Added decisions for baselines, agents, commissions, consent, scorecards, price index, baskets, naming and pilot metrics. |

------------------------------------------------------------------------

# Appendix B --- Change log (v1.1 → v1.2)

| Area | Change |
|------|--------|
| Header, sections 1 and 3 | Added direct farmer-to-supplier sourcing to purpose, problem and differentiators (now seven); added an explicit scope boundary (food only) and new exclusions (inputs marketplace, financing, insurance, advisory, platform-held funds, mandatory farm pickup). |
| Section 2 | Added principles 12--14 (price layers never mixed, farmers paid through approved channels, farmer data protection). |
| Section 4 | Architecture adds Farmers and Sourcing modules and the farmer channel. |
| Contract A | Follow-ups extended with `Role.FARMER` and sourcing permissions. |
| Contracts B, C, D, E, F, G, I, J, K | Farmer role support (B); farm-gate observations and supply-lot reference (C); anonymised demand publication (D); supplier-to-farmer payment handling without custody (E); optional farm-pickup stops (F); farmer USSD menu (G); farmer verification and sourcing monitoring (I); farmer reliability, price-chain analytics and demand-signal forecasting (J); sourcing and anonymisation tests (K). |
| **New Contract L** | Farmer sourcing and direct supplier linkage: farmers, farms, harvest listings, sourcing requests/offers/agreements, supply lots with provenance, receipt confirmation, demand signals. |
| Section 6 | New events; farm-gate exclusion in the savings baseline (6.6); new 6.8 sourcing, price-layer and provenance contract. |
| Sections 7, 8 | New tables and module folders; corrected the note on which module folders already exist. |
| Sections 10, 12, 13, 15 | Sprint plan, pilot metrics and parallel work extended; new Scenario 9; new settings and feature flag; new product decisions on farmer verification, settlement, provenance and demand signals. |
