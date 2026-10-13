import json


def test_assets_and_configuration_without_secret_exposure(client):
    assert client.get("/api/health").json() == {"status": "ok", "backend": "python"}
    for path in ["/", "/app.mjs", "/styles.css", "/demo/site.html", "/demo/site.mjs", "/demo/site.css"]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["x-content-type-options"] == "nosniff"
    config = client.get("/api/config").json()
    assert config["liveAvailable"] is False
    assert len(config["scenarios"]) == 4
    assert "typesafe_api_key" not in config
    for path in ["/.env", "/jev_lab/config.py", "/pyproject.toml", "/requirements.lock", "/shared/decision.mjs"]:
        assert client.get(path).status_code == 404
    assert "/api/decide" in client.get("/openapi.json").json()["paths"]


def test_payload_preview_decision_and_threshold_use_same_contract(client, state):
    preview = client.post("/api/payload", json={"state": state.model_dump()})
    assert preview.status_code == 200
    payload = preview.json()
    assert set(payload) == {"model", "state", "questions"}
    assert {q["type"] for q in payload["questions"].values()} == {"choice", "score", "noul"}
    criteria = payload["questions"]["next_action"]["criteria"]
    assert set(criteria) == {e.id for e in state.elements} | {"stop"}
    result = client.post("/api/decide", json={"state": state.model_dump(), "mode": "demo"})
    assert result.status_code == 200
    data = result.json()
    assert data["payload"] == payload
    assert data["response"]["model"] == "scripted-demo-not-jev"
    assert data["policy"]["status"] == "ready"
    assert "elapsedMs" in data
    policy = client.post("/api/policy", json={
        "state": state.model_dump(), "response": data["response"], "threshold": 0.99,
    })
    assert policy.status_code == 200
    assert policy.json()["status"] == "review"


def test_invalid_and_oversized_requests(client, state):
    assert client.post("/api/decide", content="{}").status_code == 415
    assert client.post("/api/decide", content="{broken", headers={"Content-Type": "application/json"}).status_code == 422
    assert client.post("/api/decide", json={"state": state.model_dump(), "threshold": 1.1}).status_code == 422
    assert client.post("/api/decide", json={"state": state.model_dump(), "mode": "wrong"}).status_code == 422
    assert client.post("/api/decide", content=json.dumps({"x": "a" * 65000}), headers={"Content-Type": "application/json"}).status_code == 413


def test_only_local_requests_are_accepted(client):
    assert client.get("/api/config", headers={"Origin": "https://unrelated.example"}).status_code == 403
    assert client.get("/api/config", headers={"Host": "unrelated.example"}).status_code == 403
    assert client.get("/api/config", headers={"Origin": "http://127.0.0.1:4317"}).status_code == 200


def test_missing_key_is_an_explicit_failure(client, state):
    response = client.post("/api/decide", json={"state": state.model_dump(), "mode": "live"})
    assert response.status_code == 503
    assert "TYPESAFE_API_KEY" in response.json()["error"]
    assert "response" not in response.json()
