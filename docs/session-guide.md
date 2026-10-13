# A short teaching walkthrough

## Start with the goal

“We want the browser to find installation instructions. The browser can read a page and click a link. Something still has to judge which link helps.”

## Show the request

Open Request payload. Point to:

- **State:** the goal and the page information supplied to Jev.
- **Instructions:** the focused question being asked.
- **Criteria:** each allowed answer and its meaning.
- **Type:** Choice, Score, or Noul.

Question names are labels used by code. The complete question belongs in the instructions.

For a code-first explanation, run `python -m examples.browser_decision --payload-only`. Open `jev_lab/payloads.py` to show how Python creates the three questions. Open `jev_lab/providers/jev.py` to show the HTTPS POST and server-side key.

## Show one decision

Choose Find setup commands and evaluate. Explain that demo mode uses invented, scripted answers. With your key configured, the Live option makes a real API request.

The selected link is a Choice. Page relevance is a Score on levels zero through two. Goal met is a Noul: the probability of yes.

## Separate judgment from action

“Jev supplies the judgment. Our application checks the result and lets us apply the click.”

Show `jev_lab/policy.py`. Its ordinary Python conditions decide whether the UI offers a click, pauses, or reports completion. Jev does not operate the browser itself.

Apply the Docs click, inspect the new state, and repeat for Installation. Evaluate once more to see completion.

## Explain uncertainty

Reset. Raise the confidence threshold to 0.99 and evaluate: the application pauses. Then try the unclear goal. Probabilities describe the model's assessment; confidence is derived from them, and neither makes a decision infallible.

## Explain training briefly

RLCD means Reinforcement Learning for Calibrated Decisions. It describes the training approach, not something passed in a request. Public documentation does not disclose a complete reproducible network and training architecture.

## Questions for a later practice interview

1. What belongs in state?
2. How do instructions differ from criteria?
3. Why include a stop option?
4. Does detecting the right action authorize performing it?
5. Is confidence the same as probability of correctness?
6. Why do we observe the page again after a click?
7. Which part would change to control an external website?
