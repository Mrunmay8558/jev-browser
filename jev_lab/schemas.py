"""Typed contracts for browser observations, Jev requests, and Jev answers."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PageId = Literal["home", "docs", "install", "examples", "python", "releases"]
PAGE_IDS = ("home", "docs", "install", "examples", "python", "releases")
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Page(InputModel):
    id: PageId
    title: str = Field(max_length=200)
    text: str = Field(max_length=12000)


class Element(InputModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    role: Literal["link"] = "link"
    text: str = Field(min_length=1, max_length=200)
    href: str

    @field_validator("id")
    @classmethod
    def avoid_reserved_ids(cls, value: str) -> str:
        if value in {"stop", "constructor", "prototype"}:
            raise ValueError("Element ID is reserved.")
        return value

    @field_validator("href")
    @classmethod
    def allow_practice_links_only(cls, value: str) -> str:
        if value not in {f"/demo/site.html?page={page}" for page in PAGE_IDS}:
            raise ValueError("Only links in the local practice site are supported.")
        return value

    @field_validator("text")
    @classmethod
    def require_visible_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Every element needs a visible label.")
        return value


class BrowserState(InputModel):
    goal: str = Field(min_length=1, max_length=1200)
    page: Page
    elements: list[Element] = Field(max_length=20)

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a non-empty goal.")
        return value.strip()

    @model_validator(mode="after")
    def unique_elements(self) -> Self:
        if len({element.id for element in self.elements}) != len(self.elements):
            raise ValueError("Element IDs must be unique.")
        return self


class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: str
    criteria: dict[str, str]


class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    instructions: str
    criteria: list[str]


class NoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    instructions: str
    criteria: dict[Literal["true", "false"], str]


class Questions(BaseModel):
    next_action: ChoiceQuestion
    page_relevance: ScoreQuestion
    goal_met: NoulQuestion


class JevPayload(BaseModel):
    model: str
    state: BrowserState
    questions: Questions


class ProviderModel(BaseModel):
    # Ignore unneeded provider metadata, but validate every field used by policy.
    model_config = ConfigDict(strict=True)


class ChoiceAnswer(ProviderModel):
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, Probability]
    confidence: Probability


class ScoreAnswer(ProviderModel):
    type: Literal["score"]
    score: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)]
    probabilities: dict[str, Probability]
    legend: dict[str, str]
    confidence: Probability


class NoulAnswer(ProviderModel):
    type: Literal["noul"]
    noul: Probability


class Answers(ProviderModel):
    next_action: ChoiceAnswer
    page_relevance: ScoreAnswer
    goal_met: NoulAnswer


class JevResponse(ProviderModel):
    model: str
    answers: Answers
    usage: dict[str, int] | None = None


class Policy(BaseModel):
    status: Literal["ready", "review", "complete"]
    label: str
    reason: str


class PayloadRequest(InputModel):
    state: BrowserState


class DecideRequest(PayloadRequest):
    mode: Literal["demo", "live"] = "demo"
    threshold: Probability = 0.7


class PolicyRequest(PayloadRequest):
    response: JevResponse
    threshold: Probability = 0.7


class DecisionResult(BaseModel):
    mode: Literal["demo", "live"]
    payload: JevPayload
    response: JevResponse
    policy: Policy
    threshold: Probability
    elapsed_ms: int = Field(serialization_alias="elapsedMs")
