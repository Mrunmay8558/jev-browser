"""LCG-style action boundaries and grounded completion checks."""

import re
from urllib.parse import urlsplit

from .models import Action, AgentError, Observation, Plan
from .navigation import valid_web_url

COMMIT = re.compile(r"\b(pay|payment|purchase|buy now|place order|confirm(?:\s+\w+){0,3}\s+booking|book now|reserve now|complete booking|delete|remove account|send message|submit application)\b", re.I)
SECRET = re.compile(r"\b(password|passcode|otp|verification code|card number|cvv|cvc|security code)\b", re.I)


def action_boundary(action: Action, observation: Observation, allowed_urls: list[str] | None = None) -> str:
    if action.kind == "navigate":
        try:
            valid_web_url(action.value)
        except ValueError:
            raise AgentError("The requested navigation URL is not supported.") from None
        if action.value not in (allowed_urls or []):
            raise AgentError("Navigation must use a website requested by the user.")
        return "normal"
    target = next((e for e in observation.elements if e.ref == action.target), None)
    if action.kind in {"click", "fill", "select", "press"} and target is None:
        raise AgentError("The planner referenced a control that was not observed.")
    if target and (target.sensitive or SECRET.search(target.label)):
        return "handoff"
    if action.risk == "handoff":
        return "handoff"
    if target and target.href and urlsplit(target.href).scheme not in {"http", "https"}:
        raise AgentError("This action uses an unsupported URL scheme.")
    if action.kind == "fill" and target and target.tag not in {"input", "textarea"} and target.role != "textbox":
        raise AgentError("The selected element is not an editable field.")
    if action.kind == "fill" and target and not target.editable:
        raise AgentError("This field is read-only. Open its picker with a click.")
    if action.kind == "select" and target and target.tag != "select":
        raise AgentError("Select requires a native dropdown; custom dropdowns need clicks.")
    if action.kind == "press" and action.value not in {"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "Space"}:
        raise AgentError("The requested key is not supported.")
    if action.risk == "confirm" or (target and COMMIT.search(target.label)):
        return "confirm"
    return "normal"


def evidence_is_present(plan: Plan, observation: Observation) -> bool:
    text = " ".join(observation.text.split()).casefold()
    return bool(plan.evidence) and all(
        len(quote.strip()) >= 4 and " ".join(quote.split()).casefold() in text
        for quote in plan.evidence
    )
