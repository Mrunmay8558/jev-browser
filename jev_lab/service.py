"""Coordinate payload construction, inference, validation, and policy."""

import asyncio
from time import perf_counter

from .errors import EvaluationError
from .payloads import build_payload
from .policy import decide_policy, validate_answer
from .providers import DecisionProvider
from .schemas import DecideRequest, DecisionResult


class DecisionService:
    def __init__(self, model: str, demo: DecisionProvider, live: DecisionProvider) -> None:
        self.model = model
        self._providers = {"demo": demo, "live": live}
        self._lock = asyncio.Lock()

    async def evaluate(self, request: DecideRequest) -> DecisionResult:
        if self._lock.locked():
            raise EvaluationError("A decision is in progress. Wait for it to finish.", 429)
        async with self._lock:
            started = perf_counter()
            payload = build_payload(request.state, self.model)
            response = await self._providers[request.mode].evaluate(payload)
            try:
                validate_answer(response, payload)
            except ValueError:
                raise EvaluationError("Jev returned an inconsistent answer. No click was performed.") from None
            return DecisionResult(
                mode=request.mode,
                payload=payload,
                response=response,
                policy=decide_policy(response, request.threshold),
                threshold=request.threshold,
                elapsed_ms=round((perf_counter() - started) * 1000),
            )
