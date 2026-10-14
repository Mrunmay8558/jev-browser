# Jev Browser — Python + Electron

Chat on the left, an interactive Chromium browser on the right. The Python agent reads the real page, chooses one action, moves a visible cursor, acts, then reads the changed page before choosing again. You can click, scroll, and type directly in the same browser pane.

## Start the desktop app

```bash
cd /Users/mrunmay/Documents/projects/dev
npm start
```

Electron starts the local Python backend automatically on an available loopback port. Closing the desktop window stops that backend. Your existing `.env` supplies the keys; the Electron renderer does not receive them.

For a fresh installation (Python 3.11+ and Node.js required):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
npm ci
npm start
```

Add `TYPESAFE_API_KEY` to `.env` before running Jev tasks. Add `GEMINI_API_KEY` only for the combined mode. Restart after changing keys.

## Try the real MakeMyTrip example

Choose **Jev only**, click **Search flights on MakeMyTrip**, and send. The app opens `https://www.makemytrip.com/flights/`. If details are missing, a **Your flight details** form appears in the conversation. Fill in **Flying from**, **Flying to**, **Departure date**, and **Trip type**. A return trip also asks for a return date. Then click **Save and continue**. No `Label: value` syntax is needed.

**New task** is available during running, paused, waiting, and finished tasks. It cancels the current run, clears its form values and conversation, and lets you choose either model mode for your next task. It does not undo website actions already performed. The real browser stays open for inspection.

If the website shows a login popup or a control the agent cannot use, choose **Pause / take over**, interact directly in the right pane, and **Continue after my changes**. You can also type guidance in chat to resume. Login, verification, and payment details require manual handover. This prototype does not bypass CAPTCHA or promise successful booking on every travel site.

The named website in your message overrides an older starting URL. **New task** clears the previous starting URL and form values. Named sites currently supported are MakeMyTrip, IRCTC, Wikipedia, and Python documentation; supply a full `https://` URL for other websites.

## Compare the two modes

| Mode | Creates action choices | Selects the next action | Keys |
| --- | --- | --- | --- |
| Jev only | Python, using observed controls and your supplied values | Jev | TypeSafe |
| Gemini + Jev | Gemini proposes alternatives from the observation | Jev | Gemini and TypeSafe |

There is no simulated fallback in either model mode. The footer shows actual request counts, and **How this decision was made** exposes the candidate list, Jev payload, and response. Change modes between runs to compare the same task and inputs.

In Jev-only mode, Python recognizes a few explicit travel phrases and the structured flight form. For another website, Task settings has optional Field on website / Text to enter rows. Existing `Label: value` chat input also remains supported. It does not provide general language planning or generate missing input text. Jev selects actions and completion evidence. On unfamiliar pages, custom widgets, or too many choices, the run can pause for help. Gemini can propose more flexible steps but still uses the same bounded browser actions and validation.

## How one step works

1. Playwright attaches to Electron's designated website view. The chat view is a separate browser target.
2. `observe.js` reads real DOM text and visible, reachable controls, assigning references such as `e12`. Offscreen and covered controls are excluded from action choices.
3. Python or Gemini proposes actions against those references.
4. Jev receives the goal, page observation, and questions about which action to take, whether the goal is met, and whether confirmation is needed.
5. Python checks confidence, the selected target, action boundaries, and whether the page has changed.
6. The visible cursor moves to the target, then Playwright executes one action. The loop starts again with a fresh observation.

Completion requires supporting text still present on the page. A stop decision alone is not reported as success. Final purchase or booking actions require explicit approval of that concrete action.

## Project structure

```text
dev/
├── desktop/
│   ├── main.cjs             # Electron window, two native views, Python lifecycle
│   └── preload.cjs          # Narrow bridge available only to the chat UI
├── jev_lab/
│   ├── agent/
│   │   ├── browser.py       # Playwright attachment and guarded execution
│   │   ├── observe.js       # Live DOM observation
│   │   ├── overlay.js       # Visible cursor and action label
│   │   ├── navigation.py    # User-requested URLs and explicit travel values
│   │   ├── candidates.py    # Python proposals for Jev-only mode
│   │   ├── planner.py       # Gemini proposals for combined mode
│   │   ├── judge.py         # Jev request and response handling
│   │   ├── runner.py        # Multi-step loop and pause/resume/stop
│   │   ├── safety.py        # Target, approval, and completion checks
│   │   └── api.py           # Run status and control routes
│   ├── static/agent.*      # Chat UI and desktop browser slot
│   └── providers/jev.py    # TypeSafe HTTP client
├── tests/
├── examples/browser_decision.py
├── docs/agent-architecture.md
├── package.json
├── requirements.lock
└── .env                    # Local keys, ignored
```

## Tests

```bash
.venv/bin/python -m pytest
# With npm start running in a development session:
npm run test:desktop
# Optional standalone browser regressions, with a separate test server running:
RUN_BROWSER_TESTS=1 JEV_TEST_URL=http://127.0.0.1:4318 .venv/bin/python -m pytest tests/test_agent_browser.py
```

Desktop checks temporarily use a local test fixture, verify Python and direct interaction affect the same native page, verify chat/website isolation, then restore the previous URL. Unit tests use mocked provider responses and do not spend API credits. Local railway fixtures remain for explicit regression tests and the original teaching lab; they are not offered as a product task or substituted for a real website.

## Standalone Python mode and learning lab

`source .venv/bin/activate && python -m jev_lab` still serves the dashboard at `http://127.0.0.1:4317/`. In this mode it launches a separate Chrome window and the dashboard shows screenshots. Use **npm start** for the interactive embedded browser requested here. Standalone mode requires Chrome (`BROWSER_CHANNEL=chrome`) or installed Playwright Chromium.

The original one-step payload lab remains at `/lab`, with explicitly labeled local teaching examples. `python -m examples.browser_decision --payload-only` prints an illustrative request without calling a model. See `docs/architecture.md` and `docs/session-guide.md` for that separate learning exercise.

## Current limits

This is a local, single-run MVP. It uses a dedicated persistent browser profile under `.runtime/electron-profile`, not your personal browser cookies. Run history is in Python memory and is lost on restart. Open shadow DOM is supported; cross-origin iframe controls and canvas-only interfaces are not. Complex custom widgets may need manual help. Website changes, access restrictions, and model mistakes can prevent completion; the app reports pauses and failures rather than inventing results.

The desktop shell follows the sibling `WebContentsView` pattern in the user's LCG prototype. LCG source and settings were not modified or copied. Official references: [Electron WebContentsView](https://www.electronjs.org/docs/latest/api/web-contents-view), [Playwright CDP](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp), [TypeSafe API](https://docs.typesafe.ai/api).
