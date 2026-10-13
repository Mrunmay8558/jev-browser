"""Interchangeable live and explicitly scripted decision providers."""

from typing import Protocol

from ..schemas import JevPayload, JevResponse


class DecisionProvider(Protocol):
    async def evaluate(self, payload: JevPayload) -> JevResponse:
        """Return typed answers without taking a browser action."""
        ...
