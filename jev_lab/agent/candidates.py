"""Generate a bounded menu of real browser actions without a generative model.

Values come from the person. Targets and dropdown options come from the DOM.
Jev selects among these candidates; this module makes no network requests.
"""

import re
from urllib.parse import urlsplit
from pydantic import ValidationError

from .models import Action, AgentError, FlightDetails, Observation, Plan
from .navigation import flight_values, requested_website, same_site

ALIASES = (
    {"from", "origin", "from station", "departure station", "departure city", "from city"},
    {"to", "destination", "to station", "arrival station", "destination city", "to city"},
    {"date", "travel date", "departure date", "journey date"},
    {"class", "travel class", "seat class"},
    {"name", "passenger", "passenger name", "full name"},
    {"trip type", "journey type"},
    {"return date", "return"},
)


def normalize(label: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", label.lower()))


def canonical_label(label: str) -> str:
    key = normalize(label)
    return next((sorted(group)[0] for group in ALIASES if key in group), key)


def matching_values(label: str, inputs: dict[str, str]) -> list[tuple[str, str]]:
    key = normalize(label)
    aliases = next((group for group in ALIASES if key in group), {key})
    matched = [(name, value) for name, value in inputs.items() if normalize(name) in aliases]
    # On unfamiliar forms, Jev can map the supplied labeled values to a field.
    return matched or list(inputs.items())


def explicit_inputs(message: str) -> dict[str, str]:
    """Recognize explicit 'Field label: value' lines, never invent missing data."""
    result = {}
    for line in message.splitlines():
        match = re.fullmatch(r"\s*([\w -]{1,80}):\s+(.{1,300})\s*", line)
        if match and match[1].casefold() not in {"http", "https"}:
            result[match[1].strip()] = match[2].strip()
    return result


class CandidatePlanner:
    def __init__(self, inputs: dict[str, str]):
        self.inputs = dict(inputs)

    async def propose(self, task: str, observation: Observation, history: list, updates: list[str]) -> Plan:
        latest_site = next((requested_website(text) for text in reversed([task, *updates]) if requested_website(text)), '')
        if latest_site and not same_site(latest_site, observation.url):
            return Plan(status="act", message=f"Open the website you requested: {latest_site}", actions=[Action(id="a1",kind="navigate",value=latest_site,reason="Open the user's requested website")])
        values = {canonical_label(key): value for key, value in {**self.inputs, **flight_values(task), **explicit_inputs(task)}.items()}
        for update in updates:
            values.update({canonical_label(key): value for key, value in {**flight_values(update), **explicit_inputs(update)}.items()})
        if values.get(canonical_label('Trip type')) == 'One way':
            values.pop(canonical_label('Return date'), None)
        if 'makemytrip.com' in urlsplit(observation.url).netloc and re.search(r'\bflights?\b', ' '.join([task, *updates]), re.I):
            fields = {key: values.get(canonical_label(label), '') for key, label in {
                'from_city':'From', 'to_city':'To', 'departure_date':'Departure date',
                'trip_type':'Trip type', 'return_date':'Return date'}.items()}
            try:
                FlightDetails.model_validate({**fields, 'return_date': fields['return_date'] or None})
            except ValidationError:
                return Plan(status="handoff", message="Add your trip details in the form below, then choose Save and continue.", flight_details=fields)
        if len(values) > 16:
            raise AgentError("Use at most 16 labeled form values in Jev-only mode.")
        candidates: list[Action] = []
        overflow = False

        def add(kind: str, target: str = "", value: str = "", reason: str = "") -> None:
            nonlocal overflow
            if len(candidates) >= 96:
                overflow = True
                return
            candidates.append(Action(id=f"a{len(candidates)+1}", kind=kind, target=target, value=value, reason=reason[:500]))

        for element in observation.elements:
            if element.sensitive:
                continue
            if element.tag in {"input", "textarea"} or element.role == "textbox":
                if not element.editable:
                    add("click", element.ref, reason=f"Open the picker for {element.label}")
                    continue
                if element.type not in {"", "text", "search", "email", "tel", "url", "number", "date", "textarea"}:
                    continue
                for label, value in matching_values(element.label, values):
                    if value == element.value:
                        continue
                    if element.type == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                        continue
                    if element.type == "number" and not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
                        continue
                    add("fill", element.ref, value, f"Fill {element.label} with the supplied {label}: {value}")
            elif element.tag == "select":
                for option in element.options:
                    if option["value"] and option["value"] != element.value:
                        add("select", element.ref, option["value"], f"Choose {option['label']} in {element.label}")
            elif element.tag in {"a", "button"} or element.role in {"button", "link", "option", "checkbox", "combobox"}:
                if element.href and urlsplit(element.href).scheme not in {"http", "https"}:
                    continue
                if element.href and element.href.rstrip('#') == observation.url.rstrip('#'):
                    continue  # Current-page navigation cannot advance the task.
                add("click", element.ref, reason=f"Click {element.label}")
            if overflow or len(candidates) > 92:
                return Plan(status="handoff", message="This page produces too many possible actions for Jev-only mode. Open a more specific page, provide fewer form values, or start a task in Gemini + Jev mode.")
        add("scroll", value="down", reason="Scroll down to inspect more of the page")
        add("scroll", value="up", reason="Scroll up to inspect earlier content")
        add("wait", reason="Wait briefly for the page to update")
        return Plan(status="act", message=f"Python found {len(candidates)} possible actions. Jev will choose the next step.", actions=candidates)
