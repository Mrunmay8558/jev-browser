"""Start, inspect, pause, approve, resume, and stop a browser run."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .demo import DEMO_TASK
from .models import Control, StartRun

router=APIRouter(prefix="/api/agent")


@router.get("/config")
async def config(request: Request):
    settings=request.app.state.settings
    return {"liveAvailable":settings.agent_available,"jevOnlyAvailable":settings.live_available,"geminiConfigured":bool(settings.gemini_api_key.get_secret_value()),
        "jevConfigured":settings.live_available,"plannerModel":settings.gemini_model,"jevModel":settings.jev_model,
        "browser":settings.browser_channel or "chromium","demoTask":DEMO_TASK}


@router.get("/current")
async def current(request: Request):
    run=request.app.state.runs.current
    return run.snapshot() if run else None


@router.post("/reset")
async def reset(request: Request):
    await request.app.state.runs.reset()
    return {"status": "ready"}


@router.post("/runs",status_code=202)
async def start(body: StartRun, request: Request):
    run=await request.app.state.runs.start(body)
    return run.snapshot()


@router.get("/runs/{run_id}")
async def status(run_id: str, request: Request):
    return request.app.state.runs.get(run_id).snapshot()


@router.post("/runs/{run_id}/control")
async def control(run_id: str, body: Control, request: Request):
    run=request.app.state.runs.get(run_id)
    await run.control(body)
    return run.snapshot()


@router.get("/runs/{run_id}/screen")
async def screen(run_id: str, request: Request):
    run=request.app.state.runs.get(run_id)
    if not run.image:
        raise HTTPException(status_code=404,detail="No browser image is available during takeover.")
    return Response(run.image,media_type="image/jpeg")
