"""Start with `python -m jev_lab` from the project directory."""

import argparse

import uvicorn
from pydantic import ValidationError

from .config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Jev Browser Lab locally.")
    parser.add_argument("--reload", action="store_true", help="Restart after Python source changes.")
    args = parser.parse_args()
    try:
        settings = Settings()
    except ValidationError:
        parser.error("Invalid .env configuration. Check PORT (1024–65535) and JEV_MODEL.")
    print(f"Jev Browser Agent · Python\nLocal: http://127.0.0.1:{settings.port}", flush=True)
    print("Jev only: " + ("ready" if settings.live_available else "add TYPESAFE_API_KEY to .env"), flush=True)
    print("Gemini + Jev: " + ("ready" if settings.agent_available else "requires both API keys"), flush=True)
    uvicorn.run(
        "jev_lab.app:create_app", factory=True, host="127.0.0.1", port=settings.port,
        reload=args.reload, proxy_headers=False,
    )


if __name__ == "__main__":
    main()
