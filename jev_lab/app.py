"""Application factory with explicit lifetime management and test injection."""

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import router
from .config import STATIC_DIR, Settings
from .errors import EvaluationError
from .middleware import LocalOnlyMiddleware
from .providers.demo import DemoProvider
from .providers.jev import JevProvider
from .service import DecisionService
from .agent.api import router as agent_router
from .agent.models import AgentError
from .agent.runner import RunManager

ASSETS = {
    "": ("agent.html", "text/html"),
    "lab": ("index.html", "text/html"),
    "agent.css": ("agent.css", "text/css"),
    "agent.mjs": ("agent.mjs", "text/javascript"),
    "demo/railway.html": ("demo/railway.html", "text/html"),
    "demo/railway.css": ("demo/railway.css", "text/css"),
    "demo/railway.mjs": ("demo/railway.mjs", "text/javascript"),
    "styles.css": ("styles.css", "text/css"),
    "app.mjs": ("app.mjs", "text/javascript"),
    "demo/site.html": ("demo/site.html", "text/html"),
    "demo/site.css": ("demo/site.css", "text/css"),
    "demo/site.mjs": ("demo/site.mjs", "text/javascript"),
}


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
            app.state.service = DecisionService(
                settings.jev_model, DemoProvider(), JevProvider(client, settings.typesafe_api_key)
            )
            app.state.runs = RunManager(settings, client)
            try:
                yield
            finally:
                await app.state.runs.close()

    app = FastAPI(
        title="Jev Browser Agent", version="0.3.0", lifespan=lifespan,
        docs_url=None, redoc_url=None,
    )
    app.state.settings = settings
    app.add_middleware(LocalOnlyMiddleware, port=settings.port)

    @app.exception_handler(AgentError)
    async def agent_error(_request: Request, error: AgentError):
        return JSONResponse({"error": str(error)}, status_code=400)

    @app.exception_handler(EvaluationError)
    async def evaluation_error(_request: Request, error: EvaluationError):
        return JSONResponse({"error": str(error)}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def input_error(_request: Request, error: RequestValidationError):
        # Return field locations, never raw inputs or upstream exception bodies.
        details = [
            {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in error.errors()
        ]
        return JSONResponse({"error": "Invalid request. Check the supplied fields.", "details": details}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, error: StarletteHTTPException):
        return JSONResponse({"error": error.detail}, status_code=error.status_code)

    app.include_router(router)
    app.include_router(agent_router)

    @app.get("/{asset_path:path}", include_in_schema=False)
    async def asset(asset_path: str):
        if asset_path not in ASSETS:
            raise HTTPException(status_code=404, detail="Not found.")
        relative, media_type = ASSETS[asset_path]
        return FileResponse(STATIC_DIR / relative, media_type=media_type)

    return app
