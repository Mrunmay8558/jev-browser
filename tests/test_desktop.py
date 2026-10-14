"""Opt-in integration check against a running desktop app. No model calls.

Run this only in a development session: it opens the local browser test fixture
in the native pane, then restores the previously open URL.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

from jev_lab.agent.browser import BrowserDriver
from jev_lab.agent.models import Action
from jev_lab.config import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get('RUN_DESKTOP_TESTS') != '1',
    reason='Start npm start, then run npm run test:desktop.',
)


def test_python_controls_only_the_native_website_and_disconnect_preserves_it():
    async def scenario():
        info = json.loads((Path(__file__).parents[1] / '.runtime/desktop.json').read_text())
        settings = Settings(_env_file=None, jev_cdp_endpoint=info['cdpEndpoint'],
                            jev_browser_target_id=info['browserTargetId'], browser_dwell_ms=50)
        async with async_playwright() as playwright:
            connection = await playwright.chromium.connect_over_cdp(info['cdpEndpoint'], no_defaults=True)
            ui = next(page for context in connection.contexts for page in context.pages
                      if page.url == info['origin'] + '/')
            assert await ui.evaluate('typeof window.jevDesktop.navigate') == 'function'
            driver = BrowserDriver(settings)
            previous_url = (await ui.evaluate('window.jevDesktop.state()'))['url']
            try:
                await driver.start(info['origin'] + '/demo/railway.html')
                page = driver.page
                assert page != ui
                assert await page.evaluate('typeof window.jevDesktop') == 'undefined'
                observation = await driver.observe()
                field = next(element for element in observation.elements if element.label == 'From station')
                await driver.execute(Action(id='a1', kind='fill', target=field.ref,
                                            value='Pune', reason='Integration test input'), observation)
                assert await page.locator(f'[data-jev-ref="{field.ref}"]').input_value() == 'Pune'
                assert await page.evaluate('window.__jevCursor.bounds()') == {'width':24, 'height':30}
                await expect(ui.locator('#browser-address')).to_have_value(page.url)
                # The user can type directly in this same live website pane.
                await page.get_by_label('From station', exact=True).fill('Mumbai')
                assert next(e for e in (await driver.observe()).elements if e.ref == field.ref).value == 'Mumbai'
                await ui.get_by_role('button', name='Task settings', exact=True).click()
                await expect(ui.locator('#settings')).to_be_visible()
                await ui.locator('#start-url').fill('https://old.example/')
                await ui.locator('#extra-settings summary').click()
                await ui.locator('[data-name]').fill('From')
                await ui.locator('[data-value]').fill('Old city')
                await ui.locator('#save-settings').click()
                await ui.locator('#new-chat').click()
                await expect(ui.locator('#start-url')).to_have_value('')
                await expect(ui.locator('[data-value]')).to_have_value('')
                website_url = page.url
                await driver.close()
                # Disconnecting Python must leave Electron and both views alive.
                remaining = next(candidate for context in connection.contexts for candidate in context.pages
                                 if candidate.url == website_url)
                assert not remaining.is_closed()
                assert await remaining.title()
                assert ui.url == info['origin'] + '/'
                with pytest.raises(Exception, match='http|address'):
                    await ui.evaluate("window.jevDesktop.navigate('file:///etc/hosts')")
            finally:
                await driver.close()
                if previous_url.startswith(('https://', 'http://')):
                    await ui.evaluate('(url)=>window.jevDesktop.navigate(url)', previous_url)

    asyncio.run(scenario())
