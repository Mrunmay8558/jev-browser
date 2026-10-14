"""Explicit, bounded contracts. A model never supplies executable browser code."""

from datetime import date
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .navigation import requested_website


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartRun(Contract):
    task: str = Field(min_length=5, max_length=4000)
    start_url: str = Field(default="", max_length=2000)
    mode: Literal["demo", "jev", "live"] = "demo"
    inputs: dict[str, str] = Field(default_factory=dict, max_length=16)
    max_steps: int = Field(default=35, ge=1, le=80)
    threshold: float = Field(default=0.65, ge=0, le=1, allow_inf_nan=False)

    @field_validator("start_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        if value:
            parts = urlsplit(value)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                raise ValueError("Provide an http(s) starting URL without embedded credentials.")
        return value

    @model_validator(mode="after")
    def live_needs_url(self) -> Self:
        if self.mode != "demo":
            self.start_url = requested_website(self.task) or self.start_url
        if self.mode in {"live", "jev"} and not self.start_url:
            raise ValueError("Model-powered tasks need the website's starting URL.")
        if any(not key.strip() or len(key) > 80 or not value.strip() or len(value) > 300 for key, value in self.inputs.items()):
            raise ValueError("Form values need a label (1–80 characters) and value (1–300 characters).")
        return self


class FlightDetails(Contract):
    from_city: str = Field(min_length=1, max_length=100)
    to_city: str = Field(min_length=1, max_length=100)
    departure_date: date
    trip_type: Literal["One way", "Return"]
    return_date: date | None = None

    @field_validator("from_city", "to_city", mode="before")
    @classmethod
    def clean_city(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if '\n' in value or '\r' in value:
                raise ValueError('Enter one city per field.')
        return value

    @model_validator(mode="after")
    def valid_return(self) -> Self:
        if self.trip_type == "Return":
            if not self.return_date:
                raise ValueError('Choose a return date for a return trip.')
            if self.return_date < self.departure_date:
                raise ValueError('The return date must be on or after departure.')
        else:
            self.return_date = None
        return self

    def as_inputs(self) -> dict[str, str]:
        values = {'From': self.from_city, 'To': self.to_city,
                  'Departure date': self.departure_date.isoformat(), 'Trip type': self.trip_type}
        if self.return_date:
            values['Return date'] = self.return_date.isoformat()
        return values


class Control(Contract):
    command: Literal["pause", "resume", "approve", "stop", "message", "focus", "details"]
    message: str = Field(default="", max_length=2000)
    details: FlightDetails | None = None


class Element(Contract):
    ref: str
    tag: str
    role: str
    label: str
    type: str = ""
    value: str = ""
    href: str = ""
    options: list[dict[str, str]] = Field(default_factory=list)
    sensitive: bool = False
    editable: bool = True


class Observation(Contract):
    url: str
    title: str
    text: str
    elements: list[Element]
    revision: str = ""
    document: str
    challenge: str = ""


class Action(Contract):
    id: str = Field(pattern=r"^a[1-9][0-9]?$", max_length=3)
    kind: Literal["click", "fill", "select", "press", "scroll", "back", "wait", "navigate"]
    target: str = Field(default="", max_length=40)
    value: str = Field(default="", max_length=1500)
    reason: str = Field(min_length=1, max_length=500)
    risk: Literal["normal", "confirm", "handoff"] = "normal"


class Plan(Contract):
    status: Literal["act", "complete", "handoff"]
    message: str = Field(max_length=1500)
    actions: list[Action] = Field(default_factory=list, max_length=96)
    evidence: list[str] = Field(default_factory=list, max_length=5)
    flight_details: dict[str, str] | None = Field(default=None, max_length=6)

    @model_validator(mode="after")
    def actions_match_status(self) -> Self:
        if self.status == "act" and not self.actions:
            raise ValueError("An act plan requires candidate actions.")
        if self.status != "act" and self.actions:
            raise ValueError("Only act plans may contain actions.")
        if len({a.id for a in self.actions}) != len(self.actions):
            raise ValueError("Action IDs must be unique.")
        if self.status == "complete" and not self.evidence:
            raise ValueError("Completion requires exact evidence from the page.")
        return self


class Verdict(Contract):
    choice: str
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    goal_met: float = Field(ge=0, le=1, allow_inf_nan=False)
    needs_confirmation: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    payload: dict = Field(default_factory=dict)
    response: dict = Field(default_factory=dict)
    evidence: str = ""


class AgentError(Exception):
    """A user-displayable failure, without keys or raw provider error bodies."""


class StaleObservation(AgentError):
    """The document changed; observe and plan again before taking any action."""
