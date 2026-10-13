import asyncio

import pytest
from pydantic import ValidationError

from examples.browser_decision import sample_state
from jev_lab.errors import EvaluationError
from jev_lab.payloads import build_payload
from jev_lab.policy import decide_policy, validate_answer
from jev_lab.providers.demo import DemoProvider
from jev_lab.schemas import BrowserState, DecideRequest, JevResponse
from jev_lab.service import DecisionService


def demo(state):
    return asyncio.run(DemoProvider().evaluate(build_payload(state)))


def test_installation_route_and_completion():
    for page, expected, status in [
        ("home", "open_docs", "ready"),
        ("docs", "open_install", "ready"),
        ("install", "stop", "complete"),
    ]:
        state = sample_state(page=page)
        response = demo(state)
        validate_answer(response, build_payload(state))
        assert response.answers.next_action.choice == expected
        assert decide_policy(response).status == status


@pytest.mark.parametrize("scenario,page,choice,status", [
    ("python", "home", "open_examples", "ready"),
    ("python", "examples", "open_python", "ready"),
    ("python", "python", "stop", "complete"),
    ("releases", "home", "open_releases", "ready"),
    ("releases", "releases", "stop", "complete"),
    ("unclear", "home", "stop", "review"),
])
def test_other_goals(scenario, page, choice, status):
    response = demo(sample_state(scenario, page))
    assert response.answers.next_action.choice == choice
    assert decide_policy(response).status == status


def test_unknown_goals_and_missing_routes_pause(state):
    state.goal = "Find something outside these presets"
    assert decide_policy(demo(state)).status == "review"
    state = sample_state()
    state.elements = []
    response = demo(state)
    validate_answer(response, build_payload(state))
    assert response.answers.next_action.probabilities == {"stop": 1.0}
    assert decide_policy(response).status == "review"


def test_threshold_changes_and_boundary(state):
    response = demo(state)
    confidence = response.answers.next_action.confidence
    assert decide_policy(response, confidence).status == "ready"
    assert decide_policy(response, confidence + 0.001).status == "review"
    assert decide_policy(response, 0.99).status == "review"


@pytest.mark.parametrize("probability,status", [(0.2, "ready"), (0.201, "review"), (0.899, "review"), (0.9, "complete")])
def test_completion_takes_priority_over_action(state, probability, status):
    response = demo(state)
    response.answers.goal_met.noul = probability
    assert decide_policy(response).status == status


@pytest.mark.parametrize("change", [
    lambda s: s.update(goal=" "),
    lambda s: s["elements"][0].update(id="stop"),
    lambda s: s["elements"][0].update(id="constructor"),
    lambda s: s["elements"][0].update(href="https://example.com"),
    lambda s: s["elements"].append(s["elements"][0]),
    lambda s: s["page"].update(text="x" * 12001),
])
def test_invalid_observations_never_become_model_input(state, change):
    raw = state.model_dump()
    change(raw)
    with pytest.raises(ValidationError):
        BrowserState.model_validate(raw)


@pytest.mark.parametrize("change", [
    lambda a: a["next_action"].update(choice="unknown_link"),
    lambda a: a["next_action"].update(choice="open_home"),
    lambda a: a["next_action"]["probabilities"].update(open_docs=0.1),
    lambda a: a["goal_met"].update(noul=float("nan")),
    lambda a: a["goal_met"].update(noul=True),
    lambda a: a["page_relevance"].update(score=1.9),
    lambda a: a.pop("page_relevance"),
])
def test_malformed_answers_cannot_reach_action_policy(state, change):
    raw = demo(state).model_dump()
    change(raw["answers"])
    with pytest.raises(ValueError):
        validate_answer(JevResponse.model_validate(raw), build_payload(state))


def test_overlapping_requests_are_rejected_and_lock_recovers(state):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        class SlowProvider:
            async def evaluate(self, payload):
                started.set()
                await release.wait()
                return await DemoProvider().evaluate(payload)

        service = DecisionService("test-model", SlowProvider(), SlowProvider())
        request = DecideRequest(state=state)
        pending = asyncio.create_task(service.evaluate(request))
        await started.wait()
        with pytest.raises(EvaluationError) as caught:
            await service.evaluate(request)
        assert caught.value.status_code == 429
        release.set()
        assert (await pending).policy.status == "ready"
        assert (await service.evaluate(request)).policy.status == "ready"

    asyncio.run(run())
