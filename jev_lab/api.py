"""HTTP routes are deliberately thin; behavior lives in the Python service."""

from fastapi import APIRouter, HTTPException, Request

from .payloads import build_payload
from .policy import decide_policy, validate_answer
from .providers.demo import SCENARIOS
from .schemas import (
    DecideRequest, DecisionResult, JevPayload, PayloadRequest, Policy, PolicyRequest,
)

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "backend": "python"}


@router.get("/config")
async def config(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "liveAvailable": settings.live_available,
        "model": settings.jev_model,
        "scenarios": SCENARIOS,
    }


@router.post("/payload", response_model=JevPayload)
async def preview_payload(body: PayloadRequest, request: Request) -> JevPayload:
    """Preview the exact request without calling Jev or spending credits."""
    return build_payload(body.state, request.app.state.settings.jev_model)


@router.post("/decide", response_model=DecisionResult, response_model_exclude_none=True)
async def decide(body: DecideRequest, request: Request) -> DecisionResult:
    return await request.app.state.service.evaluate(body)


@router.post("/policy", response_model=Policy)
async def policy(body: PolicyRequest, request: Request) -> Policy:
    """Recheck the slider's threshold locally; this never calls a provider."""
    payload = build_payload(body.state, request.app.state.settings.jev_model)
    try:
        validate_answer(body.response, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return decide_policy(body.response, body.threshold)
