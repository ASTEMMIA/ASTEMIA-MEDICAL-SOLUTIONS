"""Broker port. The pilot uses a logging broker until the qualified broker is provisioned."""

import json
import logging
from typing import Any, Protocol


class Broker(Protocol):
    def publish(self, topic: str, key: str, envelope: dict[str, Any]) -> None: ...


class LoggingBroker:
    def __init__(self) -> None:
        self.log = logging.getLogger("astemia.broker")
        self.published: list[dict[str, Any]] = []

    def publish(self, topic: str, key: str, envelope: dict[str, Any]) -> None:
        self.published.append(envelope)
        # Envelope metadata only: payloads stay out of logs (CEDA 10.1 telemetry rule).
        meta = {k: envelope[k] for k in ("event_id", "event_type", "tenant_id", "aggregate_id")}
        self.log.info("published %s", json.dumps(meta))
