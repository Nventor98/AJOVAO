from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.outbox import OutboxEvent


class EventNames:
    PRODUCT_CREATED = "product.created"
    SUPPLIER_REGISTERED = "supplier.registered"
    SUPPLIER_VERIFIED = "supplier.verified"
    INVENTORY_UPDATED = "inventory.updated"
    PRICE_OBSERVATION_RECORDED = "price_observation.recorded"
    USER_REGISTERED = "user.registered"
    COMMUNITY_MEMBER_JOINED = "community.member_joined"
    AGENT_APPROVED = "agent.approved"
    AGENT_SUSPENDED = "agent.suspended"
    AGENT_ORDER_PLACED = "agent.order_placed"
    PURCHASE_GROUP_OPENED = "purchase_group.opened"
    PURCHASE_GROUP_CLOSED = "purchase_group.closed"
    PURCHASE_REQUEST_SUBMITTED = "purchase_request.submitted"
    PURCHASE_GROUP_DEMAND_PUBLISHED = "purchase_group.demand_published"
    PURCHASE_GROUP_DEMAND_WITHHELD = "purchase_group.demand_withheld"
    PURCHASE_GROUP_CANCELLED = "purchase_group.cancelled"
    BASKET_CYCLE_OPENED = "basket.cycle_opened"
    BASKET_CYCLE_SKIPPED = "basket.cycle_skipped"
    QUOTATION_RECEIVED = "quotation.received"
    QUOTATION_APPROVED = "quotation.approved"
    ORDER_CREATED = "order.created"
    ORDER_PROCESSING = "order.processing"
    ORDER_READY = "order.ready"
    ORDER_IN_TRANSIT = "order.in_transit"
    ORDER_DISPUTED = "order.disputed"
    PAYMENT_INITIATED = "payment.initiated"
    PAYMENT_CONFIRMED = "payment.confirmed"
    PAYMENT_FAILED = "payment.failed"
    DELIVERY_PLANNED = "delivery.planned"
    DELIVERY_ASSIGNED = "delivery.assigned"
    DELIVERY_PICKED_UP = "delivery.picked_up"
    DELIVERY_DELIVERED = "delivery.delivered"
    DELIVERY_FAILED = "delivery.failed"
    SAVINGS_RECEIPT_ISSUED = "savings_receipt.issued"
    SAVINGS_RECEIPT_WITHHELD = "savings_receipt.withheld"
    SUPPLIER_SCORECARD_UPDATED = "supplier.scorecard_updated"
    PRICE_INDEX_PUBLISHED = "price_index.published"
    COMMISSION_ACCRUED = "commission.accrued"
    COMMISSION_REVERSED = "commission.reversed"
    FARMER_REGISTERED = "farmer.registered"
    FARMER_VERIFIED = "farmer.verified"
    HARVEST_LISTING_PUBLISHED = "harvest_listing.published"
    SOURCING_REQUEST_CREATED = "sourcing_request.created"
    SOURCING_OFFER_ACCEPTED = "sourcing_offer.accepted"
    SOURCING_AGREEMENT_DISPATCHED = "sourcing_agreement.dispatched"
    SOURCING_AGREEMENT_RECEIVED = "sourcing_agreement.received"
    SOURCING_AGREEMENT_COMPLETED = "sourcing_agreement.completed"
    SUPPLY_LOT_RECORDED = "supply_lot.recorded"
    FARMER_RELIABILITY_UPDATED = "farmer.reliability_updated"
    SUPPORT_TICKET_OPENED = "support_ticket.opened"


@dataclass(slots=True)
class DomainEvent:
    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_name: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[DomainEvent], Any]]] = {}

    def register(self, event_name: str, handler: Callable[[DomainEvent], Any]) -> None:
        self._handlers.setdefault(event_name, []).append(handler)

    def has_handlers(self, event_name: str) -> bool:
        return bool(self._handlers.get(event_name))

    def dispatch(self, event: DomainEvent) -> list[Any]:
        results: list[Any] = []
        for handler in self._handlers.get(event.event_name, []):
            results.append(handler(event))
        return results


event_bus = EventBus()


def emit(db: Session, event: DomainEvent | str, payload: dict[str, Any] | None = None) -> OutboxEvent:
    if isinstance(event, str):
        event_name = event
        domain_event = DomainEvent(event_name=event_name, payload=payload or {})
    else:
        domain_event = event
        event_name = event.event_name

    record = OutboxEvent(
        event_id=domain_event.event_id,
        event_name=event_name,
        payload=domain_event.payload,
        status="PENDING",
    )
    db.add(record)
    return record


def enqueue(event: str | Callable[..., Any]):
    def decorator(func):
        event_name = event if isinstance(event, str) else event.__name__
        event_bus.register(event_name, func)
        return func

    if callable(event):
        return decorator(event)
    return decorator


def job(func: Callable[[DomainEvent], Any]) -> Callable[[DomainEvent], Any]:
    return enqueue(func)
