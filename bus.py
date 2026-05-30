import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable) -> None:
        self._handlers[event].append(handler)

    async def publish(self, event: str, payload: Any) -> None:
        for h in self._handlers[event]:
            try:
                await h(payload)
            except Exception as e:
                logger.error("Bus handler error [%s]: %s", event, e)


bus = EventBus()
