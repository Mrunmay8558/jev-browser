"""Small HTTP adapter for TypeSafe's documented systemone endpoint."""

import asyncio

import httpx
from pydantic import SecretStr, ValidationError

from ..errors import EvaluationError
from ..schemas import JevPayload, JevResponse

JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class JevProvider:
    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr) -> None:
        self._client = client
        self._api_key = api_key

    async def evaluate(self, payload: JevPayload) -> JevResponse:
        key = self._api_key.get_secret_value().strip()
        if not key:
            raise EvaluationError("Add TYPESAFE_API_KEY to .env and restart before using live mode.", 503)
        try:
            # Both a total deadline and per-operation limits; never replay a paid request.
            async with asyncio.timeout(25):
                response = await self._client.post(
                    JEV_ENDPOINT,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload.model_dump(mode="json"),
                    timeout=20,
                    follow_redirects=False,
                )
        except (TimeoutError, httpx.TimeoutException):
            raise EvaluationError("Jev timed out. No click was performed.", 504) from None
        except httpx.HTTPError:
            raise EvaluationError("Jev could not be reached. No click was performed.") from None
        if response.status_code == 401:
            raise EvaluationError("Jev rejected the API key. Check .env and restart.")
        if not response.is_success:
            raise EvaluationError(f"Jev returned HTTP {response.status_code}. No click was performed.")
        try:
            return JevResponse.model_validate(response.json())
        except (ValueError, ValidationError):
            raise EvaluationError("Jev returned an invalid response. No click was performed.") from None
