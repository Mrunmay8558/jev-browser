# Architecture

```text
Practice website DOM
  ↓ goal, page text, observed links
Browser interface (static/app.mjs)
  ↓ POST /api/decide
FastAPI route (api.py)
  ↓ Pydantic validates the request
DecisionService (service.py)
  ↓ build_payload(state) → model + state + questions
  ├─ DemoProvider → explicitly scripted teaching response
  └─ JevProvider → TypeSafe API with a server-side key
  ↓ validate typed answers and consistency with observed options
  ↓ decide_policy(response, threshold)
Browser interface displays answer + policy
  ↓ user chooses Apply
  ↓ verify the current DOM snapshot still matches
Click the observed local link → read a fresh snapshot
```

## Responsibilities

`schemas.py` describes the data. `payloads.py` describes the questions. Providers supply answers. `policy.py` decides how the app reacts. `service.py` connects these steps without depending on a browser or HTTP route. The web UI, Python example, and tests use the same behavior.

`create_app()` owns the HTTP client's lifetime. Tests inject an HTTPX mock transport; real calls use the fixed HTTPS TypeSafe endpoint. One service-level lock prevents overlapping evaluations. Live errors are reported without substituting demo answers. Paid requests are not retried automatically.

## Payload

The top level has `model`, `state`, and `questions`. Our state contains the goal, page id/title/text, and observed link ids/labels/destinations. These nested field names are application-defined.

- `next_action`: Choice over current element ids plus `stop`.
- `page_relevance`: Score over three ordered descriptions, levels zero through two.
- `goal_met`: Noul asking whether the information is already visible.

Question names label answers for code. The full meaning belongs in `instructions`, because names are not sent to the underlying model. Questions are independent; our Python policy combines their answers.

`POST /api/payload` previews the exact request without inference. `POST /api/policy` recalculates only application rules when the slider changes; it never calls TypeSafe.

## Python action policy

1. Completion probability at least 0.90: report goal reached.
2. Completion probability greater than 0.20 but below 0.90: pause.
3. Choice `stop`: pause.
4. Confidence below the selected threshold: pause.
5. Otherwise: offer Apply.

Relevance is displayed to explain Score, not used as an action gate. Confidence is a distribution statistic, not a probability of correctness. Demo numbers are fixtures, never measured performance.

## Browser responsibility

JavaScript reads the iframe DOM and performs the selected link click. Payload construction, inference, answer validation, and policy evaluation are in Python. A changed page, goal, or mode invalidates the old result. Apply is disabled while a new threshold is checked. Before clicking, the interface verifies the snapshot and the element's current destination.

This is confined to the authored practice site. External automation would need a new browser adapter, navigation synchronization, and decisions about allowed actions. The model returns an element id, never executable code.

## Boundaries

The server binds to loopback, checks local Host/Origin, bounds request bodies, and serves an explicit asset list. The key is a masked `SecretStr`, used only by the HTTP client. Environment files are never served. Error responses exclude provider response bodies and network exception details.

This project implements the application around Jev, not Jev's private neural-network or training implementation.
