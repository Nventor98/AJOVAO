from __future__ import annotations

import logging
import time

from app.db.session import SessionLocal
from app.shared.events import event_bus
from app.shared.outbox_dispatcher import OutboxDispatcher

logger = logging.getLogger(__name__)


def main() -> None:
    from app.main import app  # noqa: F401

    dispatcher = OutboxDispatcher(SessionLocal, event_bus)
    logger.info("Starting transactional outbox worker")
    while True:
        counts = dispatcher.dispatch_pending()
        if not any(counts.values()):
            time.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
