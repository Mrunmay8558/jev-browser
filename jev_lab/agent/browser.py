"""A visible Playwright browser with live DOM refs and an intent cursor."""

import asyncio
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from ..config import Settings
from .models import Action, AgentError, Observation, StaleObservation

SOURCE_DIR = Path(__file__).parent
OBSERVER = (SOURCE_DIR / "observe.js").read_text()
OVERLAY = (SOURCE_DIR / "overlay.js").read_text()


class BrowserDriver:
    def __init__(self, settings: Settings, *, headless: bool = False) -> None:
        self.settings = settings
        self.headless = headless
        self.playwright = None
        self.context = None
        self.page = None
        self.connection = None

    async def start(self, url: str) -> None:
        if urlsplit(url).scheme not in {"http", "https"}:
            raise AgentError("Only http(s) websites can be opened.")
        self.playwright = await async_playwright().start()
        try:
            if self.settings.jev_cdp_endpoint:
                await self._attach_desktop()
            else:
                self.context = await self.playwright.chromium.launch_persistent_context(
                    str(self.settings.browser_profile_dir.resolve()),
                    channel=self.settings.browser_channel or None,
                    headless=self.headless,
                    viewport={"width": 1280, "height": 820},
                    accept_downloads=False,
                )
                self.page = await self.context.new_page()
            self.context.set_default_timeout(8000)
            await self.page.add_init_script(OVERLAY)
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.page.bring_to_front()
        except Exception:
            await self.close()
            raise AgentError("Could not open the browser. Check BROWSER_CHANNEL and browser installation; close other agent processes using this profile.") from None

    async def _attach_desktop(self) -> None:
        """Attach only to Electron's designated website view, never the chat UI."""
        endpoint = urlsplit(self.settings.jev_cdp_endpoint)
        if endpoint.hostname not in {"127.0.0.1", "localhost"} or not self.settings.jev_browser_target_id:
            raise AgentError("The desktop browser connection must be local and identify its target.")
        self.connection = await self.playwright.chromium.connect_over_cdp(self.settings.jev_cdp_endpoint, no_defaults=True, timeout=10000)
        for context in self.connection.contexts:
            for page in context.pages:
                session = await context.new_cdp_session(page)
                try:
                    target = await session.send("Target.getTargetInfo")
                finally:
                    await session.detach()
                if target["targetInfo"]["targetId"] == self.settings.jev_browser_target_id:
                    self.context, self.page = context, page
                    return
        raise AgentError("The desktop website view is unavailable. Restart the desktop app.")

    async def observe(self) -> Observation:
        if not self.page or self.page.is_closed():
            raise AgentError("The controlled browser tab was closed.")
        if urlsplit(self.page.url).scheme not in {"http", "https"}:
            raise AgentError("The browser reached an unsupported page. Open an http(s) page and start again.")
        raw = await self.page.evaluate(OBSERVER)
        result = Observation.model_validate(raw)
        result.revision = hashlib.sha256(result.model_dump_json().encode()).hexdigest()[:24]
        return result

    async def screenshot(self) -> bytes:
        return await self.page.screenshot(type="jpeg", quality=70, timeout=5000)

    async def focus(self) -> None:
        if not self.page or self.page.is_closed():
            raise AgentError("The browser is not open yet.")
        await self.page.bring_to_front()

    async def hide_cursor(self) -> None:
        if self.page and not self.page.is_closed():
            await self.page.evaluate("window.__jevCursor?.hide()")

    async def execute(self, action: Action, observation: Observation, on_intent=None) -> None:
        # Re-observe before every action, including one delayed by approval.
        fresh = await self.observe()
        if fresh.revision != observation.revision:
            raise StaleObservation("The page changed. Reading it again before acting.")
        locator = None
        if action.target:
            target = next((e for e in observation.elements if e.ref == action.target), None)
            if not target:
                raise AgentError("The selected control is not in the current observation.")
            locator = self.page.locator(f'[data-jev-ref="{target.ref}"]')
            if await locator.count() != 1:
                raise StaleObservation("The selected control changed.")
            await locator.scroll_into_view_if_needed()
            await locator.click(trial=True)
            box = await locator.bounding_box()
            if not box:
                raise StaleObservation("The selected control is no longer visible.")
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            await self.page.evaluate(OVERLAY)
            await self.page.evaluate("([x,y,label])=>window.__jevCursor.move(x,y,label)", [x, y, f"{action.kind}: {target.label}"])
            await self.page.mouse.move(x, y, steps=12)
            if on_intent:
                await on_intent()
            await asyncio.sleep(self.settings.browser_dwell_ms / 1000)
            # Re-check after the visible dwell, so user edits invalidate the action.
            if (await self.observe()).revision != observation.revision:
                raise StaleObservation("The page changed while the cursor moved.")
            await self.page.evaluate("([x,y])=>window.__jevCursor.ring(x,y)", [x,y])

        before = set(self.context.pages)
        if action.kind == "navigate":
            await self.page.goto(action.value, wait_until="domcontentloaded", timeout=30000)
        elif action.kind == "click":
            await locator.click()
        elif action.kind == "fill":
            if await locator.get_attribute("contenteditable") == "true":
                await locator.fill(action.value)
            else:
                await locator.fill(action.value)
                if await locator.input_value() != action.value:
                    raise AgentError("The field did not retain the requested value.")
        elif action.kind == "select":
            try:
                await locator.select_option(value=action.value, timeout=2000)
            except Exception:
                await locator.select_option(label=action.value, timeout=3000)
        elif action.kind == "press":
            await locator.press(action.value)
        elif action.kind == "scroll":
            await self.page.mouse.wheel(0, -600 if action.value == "up" else 600)
        elif action.kind == "back":
            await self.page.go_back(wait_until="domcontentloaded")
        elif action.kind == "wait":
            await asyncio.sleep(1)
        await asyncio.sleep(0.35)
        new_pages = [p for p in self.context.pages if p not in before]
        if new_pages and not self.settings.jev_cdp_endpoint:
            self.page = new_pages[-1]
            await self.page.bring_to_front()
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass  # The next observation reports the current state or a concrete error.

    async def close(self) -> None:
        try:
            if self.context and not self.settings.jev_cdp_endpoint:
                await self.context.close()
        finally:
            if self.playwright:
                await self.playwright.stop()
            self.context = self.playwright = self.page = None
            self.connection = None
