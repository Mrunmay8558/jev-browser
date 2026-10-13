import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from jev_lab.app import create_app
from jev_lab.config import Settings
from jev_lab.payloads import build_payload
from jev_lab.providers.demo import DemoProvider

TEST_KEY = "fake-test-key-never-a-real-secret"


def settings():
    return Settings(_env_file=None, typesafe_api_key=TEST_KEY, port=4317, jev_model="jev-1.13.0")


def test_live_wire_contract_without_network_or_credits(state):
    provider_body = asyncio.run(DemoProvider().evaluate(build_payload(state))).model_dump(exclude_none=True)
    provider_body["model"] = "stubbed-provider"
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.method == "POST"
        assert request.headers["authorization"] == f"Bearer {TEST_KEY}"
        assert json.loads(request.content) == build_payload(state).model_dump(mode="json")
        return httpx.Response(200, json=provider_body)

    app = create_app(settings(), transport=httpx.MockTransport(handler))
    with TestClient(app, base_url="http://127.0.0.1:4317") as client:
        config = client.get("/api/config")
        assert config.json()["liveAvailable"] is True
        assert TEST_KEY not in config.text
        result = client.post("/api/decide", json={"mode": "live", "state": state.model_dump()})
        assert result.status_code == 200
        assert result.json()["response"]["model"] == "stubbed-provider"
        assert TEST_KEY not in result.text
        assert len(calls) == 1
        client.post("/api/policy", json={"state": state.model_dump(), "response": provider_body, "threshold": 0.99})
        assert len(calls) == 1  # Adjusting a threshold must not spend API credits.


@pytest.mark.parametrize("failure,status", [("redirect", 502), ("unauthorized", 502), ("rate_limit", 502), ("invalid_json", 502), ("timeout", 504), ("network", 502)])
def test_live_errors_are_sanitized_do_not_retry_or_fall_back(state, failure, status):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(TEST_KEY)
        if failure == "network":
            raise httpx.ConnectError(TEST_KEY)
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://unrelated.example"})
        if failure == "invalid_json":
            return httpx.Response(200, text=TEST_KEY)
        return httpx.Response(401 if failure == "unauthorized" else 429, text=TEST_KEY)

    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler)), base_url="http://127.0.0.1:4317") as client:
        for _ in range(2):  # A failure must release the service's in-flight lock.
            response = client.post("/api/decide", json={"mode": "live", "state": state.model_dump()})
            assert response.status_code == status
            assert TEST_KEY not in response.text
            assert "response" not in response.json()
    assert len(calls) == 2
