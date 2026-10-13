"""Deterministic teaching fixtures. This is not a locally running Jev model."""

from ..payloads import LEVELS
from ..schemas import JevPayload, JevResponse

SCENARIOS = [
    {"id": "install", "label": "Find setup commands", "goal": "Find the installation commands for the Atlas SDK.", "target": "install"},
    {"id": "python", "label": "Find a Python example", "goal": "Find a Python code example for using the Atlas SDK.", "target": "python"},
    {"id": "releases", "label": "Read the latest release", "goal": "Read what changed in the latest Atlas SDK release.", "target": "releases"},
    {"id": "unclear", "label": "Try an unclear goal", "goal": "Open the right thing for me.", "target": None},
]


class DemoProvider:
    async def evaluate(self, payload: JevPayload) -> JevResponse:
        state = payload.state
        target = next((s["target"] for s in SCENARIOS if s["goal"] == state.goal), None)
        complete = bool(target and state.page.id == target)
        route = {"install": "docs", "python": "examples"}.get(target, target)
        direct = next((e for e in state.elements if e.href.endswith(f"page={target}")), None)
        onward = direct or next((e for e in state.elements if e.href.endswith(f"page={route}")), None)
        selected = onward.id if target and not complete and onward else "stop"
        keys = list(payload.questions.next_action.criteria)
        count = len(keys)
        peak = 0.96 if target else max(1 / count, 0.35)
        probabilities = {
            key: 1.0 if count == 1 else peak if key == selected else (1 - peak) / (count - 1)
            for key in keys
        }
        relevance = [0.01, 0.02, 0.97] if complete else [0.03, 0.94, 0.03] if target else [0.34, 0.33, 0.33]
        mode = max(range(3), key=lambda i: relevance[i])
        expected_distance = sum(p * abs(i - mode) for i, p in enumerate(relevance))
        uniform_distance = sum(abs(i - mode) for i in range(3)) / 3
        return JevResponse.model_validate({
            "model": "scripted-demo-not-jev",
            "answers": {
                "next_action": {
                    "type": "choice", "choice": selected, "probabilities": probabilities,
                    "confidence": 1.0 if count == 1 else (max(probabilities.values()) - 1 / count) / (1 - 1 / count),
                },
                "page_relevance": {
                    "type": "score", "score": sum(i * p for i, p in enumerate(relevance)),
                    "probabilities": {str(i): p for i, p in enumerate(relevance)},
                    "legend": {str(i): level for i, level in enumerate(LEVELS)},
                    "confidence": max(0.0, 1 - expected_distance / uniform_distance),
                },
                "goal_met": {"type": "noul", "noul": 0.98 if complete else 0.02 if target else 0.5},
            },
        })
