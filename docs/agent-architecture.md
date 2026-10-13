# Multi-step browser agent

The browser agent is the default page at `/`. The original payload learning lab remains at `/lab`.

```text
User task + starting URL
   ↓
Electron opens a native website view; Python attaches through local CDP
   ↓
Observe page text, controls, values, and stable element refs
   ↓
Python generates observed actions (Jev only), OR
Gemini proposes 1–4 alternatives (Gemini + Jev)
   ↓
Jev ranks those candidates and evaluates completion/confirmation
   ↓
Python validates refs, confidence, action boundaries, and page revision
   ↓
Move the visible in-page cursor → dwell → execute one action
   ↓
Observe the changed page and repeat until verified completion or a pause
```

## Modules

- `desktop/main.cjs`: native views, local CDP target, Python startup/shutdown, and restricted navigation IPC.
- `desktop/preload.cjs`: browser controls exposed only to the trusted chat renderer.
- `agent/navigation.py`: explicit user website routing and conservative travel-value extraction.
- `agent/models.py`: observation, action, plan, request, and verdict contracts.
- `agent/browser.py`: Playwright lifecycle, fresh snapshots, guarded execution, screenshots.
- `agent/observe.js`: reads actual DOM controls and assigns current-document refs.
- `agent/overlay.js`: visible pointer, action label, and click ripple.
- `agent/candidates.py`: dynamic action menu from observed DOM and user-supplied values; no model requests.
- `agent/planner.py`: stateless Gemini Interactions requests with structured JSON output.
- `agent/judge.py`: TypeSafe requests over planner candidates, response validation.
- `agent/safety.py`: bounded action vocabulary, credential handover, final-action confirmation, evidence checks.
- `agent/runner.py`: multi-step loop, step budget, stop, suspended handover, explicit approval, final result.
- `agent/api.py`: run status and controls for the dashboard.
- `agent/demo.py`: explicitly scripted planner and evaluator for the railway practice site.

## Modes and chat

`StartRun.mode` is `jev` (Jev only), `live` (Gemini + Jev), or `demo` (scripted practice). Both model modes need a starting URL, supplied explicitly or resolved from a supported website name in the user task. Jev-only validates only the TypeSafe key; it does not construct or call GeminiPlanner. `inputs` holds up to 16 labeled values. Explicit `Label: value` lines in chat can replace values for later candidate generation. Candidate sets are bounded below the API limit and overflow pauses the run.

The Electron app has two sibling WebContentsViews: chat on the left and a real interactive website on the right. A narrow preload bridge exists only in the chat view. Python attaches to the website target ID passed by Electron, so it cannot mistake the chat for its working page. The standalone Python dashboard retains a separate Chrome window with a screenshot mirror. A `message` control queues guidance and invalidates outstanding model proposals, or resumes a pending run without granting approval. State and conversation survive a page refresh but remain in memory on the server.

## What comes from each model

Gemini receives the original task, user updates, the current DOM observation, and recent event history. It proposes actions such as filling a date or clicking an observed button. It also supplies the short user-facing status and final answer. It cannot submit JavaScript, selectors, or executable code. Direct navigation is restricted to URLs explicitly requested by the user or the starting URL; normal page links use observed references.

Jev receives the task, observation, and proposal. `next_action` is a Choice among candidate IDs plus `stop`; `goal_met` is a Noul; `needs_confirmation` asks whether any candidate commits a consequential action. Candidate actions are alternatives, not an unobserved batch. Only one is executed before taking another snapshot.

In Jev-only mode, Python supplies the proposal instead of Gemini. Jev also answers a `completion_evidence` Choice over passages from the page, plus `none`. Completion needs high goal probability, a selected quotation still present on the unchanged page, and no intervening user instruction. The final answer is a template plus the selected quotation; no generative model is called.

The agent's browser state is separate from the original learning lab's deliberately restricted `BrowserState`. It supports arbitrary http(s) page URLs and observed links, inputs, selects, buttons, and common ARIA controls.

## Evidence and uncertainty

Combined-mode completion requires Gemini's completion proposal, Jev completion probability of at least 0.9, exact quoted evidence present on the current page, and an unchanged page revision. A model's interpretation can still be wrong; these checks are safeguards, not proof of semantic correctness.

A low-confidence action, missing details, repeated unchanged action, browser failure, or step limit produces an explicit pause or incomplete outcome. Model transport failures are not retried automatically and never silently switch to demo responses.

A page revision covers URL, text, document identity, and observed controls/values. Before executing, the driver checks that revision again, scrolls to the element, checks its actionability, shows the cursor, and checks once more. Approval is bound to that same observation: a changed page causes replanning instead of acting on stale approval.

## Pause, stop, and takeover

- Pause stops at the next operation boundary. A browser operation already underway may finish.
- Stop cancels the run task, including pending model calls or waits; it does not undo actions already performed.
- During a login/CAPTCHA/payment-details handover, model calls, observation, and screenshots stop until Resume. Secret input values are omitted from snapshots.
- Final purchase/booking/submission actions get a concrete approval prompt. Approve authorizes only the proposed action on the unchanged page; Resume without approval skips it and replans.
- The browser remains open after a completed/stopped run for inspection. In Electron, disconnecting a run leaves both native views alive; closing the Electron window stops its Python child. Standalone mode closes the owned Chrome context when starting another run or shutting down. The dedicated profile preserves sign-in state between launches.

## Scope and limits

The agent supports DOM-based clicking, filling, native dropdown selection, a bounded set of keys, scrolling, back, and waiting. Open shadow DOM is observed; embedded cross-origin iframe controls and canvas/pixel-only interfaces are not implemented. Electron opens website popup links in the existing website pane; standalone mode follows newly opened popup tabs. CAPTCHA and OTP are completed by the user; no bypass is implemented.

The desktop app uses an isolated persistent Electron browser profile; standalone Python mode launches Chrome in a dedicated profile. It does not attach to your already-open personal Chrome tabs or import their cookies. That would require a separate explicit extension/CDP connection workflow.

There is one in-memory run at a time. Restarting the server loses the run history. Screenshots stay in memory; they are not automatically archived. The browser profile is local and ignored by Git. The dashboard is loopback-only; this is not a multi-user hosted service.

## LCG reference

Read-only reference: `/Users/mrunmay/Documents/projects/lcg-poc` (also present at `ai-harness/lcg-prototype`). The implementation uses the same two-view Electron window pattern, with Python retaining the agent loop:

- `src/main/app-window.ts`: two isolated WebContentsViews and renderer-reported browser bounds.
- `src/renderer/app/Shell.tsx` and `Composer.tsx`: conversation on the left, browser on the right, input and approvals beside the page.
- `src/main/browser/overlay/inject.ts`: show intent before the effect.
- `src/main/browser/overlay/overlay.page.ts`: cursor inside the page so it appears on the actual browsing surface.
- `src/main/browser/driver.ts`: check that the observed target remains actionable.
- `src/agent-host/agent/control.ts`: handover is a suspended loop, not a notification followed by more model calls.
- `src/agent-host/agent/prompt.ts`: use fresh refs and verify final claims against page evidence.

The original LCG project was not modified, and no keys were copied from its settings.

## Official API references

- [Playwright persistent browser context](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)
- [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview)
- [TypeSafe API](https://docs.typesafe.ai/api)
