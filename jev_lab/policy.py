"""Pure Python rules: validate a model answer, then decide whether to offer a click."""

from .schemas import JevPayload, JevResponse, Policy


def validate_answer(response: JevResponse, payload: JevPayload) -> None:
    """Bind a typed response to the actual options in this specific request."""
    action = response.answers.next_action
    relevance = response.answers.page_relevance
    for probabilities, keys in (
        (action.probabilities, set(payload.questions.next_action.criteria)),
        (relevance.probabilities, {"0", "1", "2"}),
    ):
        if set(probabilities) != keys:
            raise ValueError("The response has unexpected probability options.")
        if abs(sum(probabilities.values()) - 1) > 0.01:
            raise ValueError("Probabilities must sum to one.")
    if action.choice not in action.probabilities:
        raise ValueError("The provider selected an unobserved action.")
    if action.probabilities[action.choice] + 0.001 < max(action.probabilities.values()):
        raise ValueError("The selected action is inconsistent with its probabilities.")
    if set(relevance.legend) != {"0", "1", "2"}:
        raise ValueError("The response has unexpected score levels.")
    weighted_score = sum(int(level) * p for level, p in relevance.probabilities.items())
    if abs(relevance.score - weighted_score) > 0.02:
        raise ValueError("The score is inconsistent with its probabilities.")


def decide_policy(response: JevResponse, threshold: float = 0.7) -> Policy:
    """Thresholds are teaching defaults, not guarantees of model correctness."""
    if not 0 <= threshold <= 1:
        raise ValueError("Threshold must be between zero and one.")
    action = response.answers.next_action
    completion = response.answers.goal_met.noul
    if completion >= 0.9:
        return Policy(status="complete", label="Goal reached", reason=(
            "The model judges that the requested information is already on this page."
        ))
    if completion > 0.2:
        return Policy(status="review", label="Review needed", reason=(
            "The model is uncertain whether the goal is already met."
        ))
    if action.choice == "stop":
        return Policy(status="review", label="No click suggested", reason=(
            "No useful next action was selected. Clarify the goal or inspect the page."
        ))
    if action.confidence < threshold:
        return Policy(status="review", label="Below your threshold", reason=(
            "The decision is too uncertain under your current rule."
        ))
    return Policy(status="ready", label="Ready for your click", reason=(
        "The selected action meets your rule. Apply it to the practice browser."
    ))
