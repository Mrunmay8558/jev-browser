"""Run `python -m examples.browser_decision` to inspect one browser decision."""

import argparse
import asyncio
import json

import httpx
from pydantic import ValidationError

from jev_lab.config import Settings
from jev_lab.errors import EvaluationError
from jev_lab.payloads import build_payload
from jev_lab.providers.demo import DemoProvider, SCENARIOS
from jev_lab.providers.jev import JevProvider
from jev_lab.schemas import BrowserState, DecideRequest, PAGE_IDS
from jev_lab.service import DecisionService


def sample_state(scenario: str = "install", page: str = "home") -> BrowserState:
    """In the UI, real DOM observations replace this small illustrative snapshot."""
    goal = next(item["goal"] for item in SCENARIOS if item["id"] == scenario)
    links = [("home", "Home"), ("docs", "Docs"), ("examples", "Examples"), ("releases", "Releases")]
    if page == "docs":
        links.append(("install", "Installation"))
    if page == "examples":
        links.append(("python", "Python example"))
    page_text = {
        "home": "Atlas SDK. Browse Docs, Examples, and Releases.",
        "docs": "Documentation. Open Installation for setup commands.",
        "install": "Installation commands: pip install atlas-sdk. export ATLAS_API_KEY=your-key.",
        "examples": "Code examples. Open Python example for a complete snippet.",
        "python": "Python code: from atlas import Client; client = Client(); print(client.ping())",
        "releases": "Latest release 2.4: new streaming API and faster connection setup.",
    }
    return BrowserState.model_validate({
        "goal": goal,
        "page": {"id": page, "title": f"Atlas — {page}", "text": page_text[page]},
        "elements": [
            {"id": f"open_{page_id}", "text": label, "href": f"/demo/site.html?page={page_id}"}
            for page_id, label in links
        ],
    })


async def run(args: argparse.Namespace) -> dict:
    settings = Settings()
    state = sample_state(args.scenario, args.page)
    if args.payload_only:
        return build_payload(state, settings.jev_model).model_dump(mode="json")
    async with httpx.AsyncClient(trust_env=False) as client:
        service = DecisionService(
            settings.jev_model, DemoProvider(), JevProvider(client, settings.typesafe_api_key)
        )
        result = await service.evaluate(DecideRequest(
            state=state, mode="live" if args.live else "demo", threshold=args.threshold
        ))
        return result.model_dump(mode="json", by_alias=True, exclude_none=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[s["id"] for s in SCENARIOS], default="install")
    parser.add_argument("--page", choices=PAGE_IDS, default="home")
    parser.add_argument("--threshold", type=float, default=0.7)
    parser.add_argument("--payload-only", action="store_true", help="Print the Jev request without sending it.")
    parser.add_argument("--live", action="store_true", help="Send this example to TypeSafe using your key; may spend credits.")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except (EvaluationError, ValidationError) as error:
        parser.exit(1, f"{str(error) if isinstance(error, EvaluationError) else 'Invalid input or configuration.'}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
