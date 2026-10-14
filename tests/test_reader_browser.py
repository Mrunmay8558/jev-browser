"""Real DOM regressions for the malformed names seen on IRCTC's welcome dialog."""

import asyncio
import os

import pytest
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright

from jev_lab.agent.browser import BrowserDriver, OBSERVER
from jev_lab.agent.candidates import CandidatePlanner
from jev_lab.agent.judge import build_agent_payload
from jev_lab.agent.models import Action, Observation
from jev_lab.config import Settings

pytestmark = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in Chromium checks")


@pytest.mark.parametrize("shared_label", [
    'Confirmation. SafeValue must use [property]=binding: <body><h1>Welcome to IRCTC</h1></body>',
    'Confirmation. Please select your preferred language.',
    'Welcome to IRCTC. ' * 30,
])
def test_language_buttons_remain_distinct_in_the_jev_payload(shared_label):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content('''<button>Covered search</button>
            <div id="welcome" role="dialog" style="position:fixed;inset:0;background:white">
              <h1>Welcome to IRCTC</h1><p>Please select your preferred language.</p>
              <button id="hindi"><span>हिंदी</span></button>
              <button id="english" onclick="document.querySelector('#welcome').remove()"><span>English</span></button>
            </div>''')
        page.locator('#welcome button').evaluate_all('(els,label)=>els.forEach(el=>el.setAttribute("aria-label",label))', shared_label)
        observation = Observation.model_validate(page.evaluate(OBSERVER))
        assert [e.label for e in observation.elements] == ['हिंदी', 'English']
        # A second observation preserves refs, and the selected ref actually
        # opens the underlying page instead of clicking the other language.
        assert page.evaluate(OBSERVER) == observation.model_dump(exclude={'revision'})
        target = observation.elements[1].ref
        page.locator(f'[data-jev-ref="{target}"]').click()
        assert [e['label'] for e in page.evaluate(OBSERVER)['elements']] == ['Covered search']
        browser.close()
    plan = asyncio.run(CandidatePlanner({}).propose('List trains on this website', observation, [], []))
    payload = build_agent_payload('List trains on this website', observation, plan, 'test')
    criteria = payload['questions']['next_action']['criteria']
    assert criteria['a1']['reason'] == 'Click हिंदी'
    assert criteria['a2']['reason'] == 'Click English'
    assert criteria['a2']['target'] == target
    assert [e['label'] for e in payload['state']['page']['elements']] == ['हिंदी', 'English']


def test_reader_preserves_useful_accessible_names_and_shadow_labels():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content('''<button aria-label="Close dialog">×</button>
            <button aria-label="Show train details">Details</button>
            <span id="from" hidden>From station</span><input aria-labelledby="from" placeholder="Search">
            <label>Journey date <input type="text"></label>
            <span id="verb" hidden>Search</span><span id="noun" hidden>trains</span>
            <button aria-labelledby="verb noun">Go</button>
            <div id="shadow"></div>
            <div>October 2026</div><div><table><tr><td><a id="calendar-day" style="cursor:pointer">15</a></td></tr></table></div>
            <a name="section">Inert section anchor</a>''')
        page.locator('#shadow').evaluate("el=>{el.attachShadow({mode:'open'}).innerHTML='<span id=label hidden>Destination station</span><input aria-labelledby=label>'}")
        page.locator('#calendar-day').evaluate("el=>el.addEventListener('click',()=>el.textContent='Selected 15')")
        assert [e['label'] for e in page.evaluate(OBSERVER)['elements']] == [
            'Close dialog', 'Show train details', 'From station', 'Journey date', 'Search trains', '15 October 2026', 'Destination station',
        ]
        day = next(e for e in page.evaluate(OBSERVER)['elements'] if e['label'] == '15 October 2026')
        page.locator(f'[data-jev-ref="{day["ref"]}"]').click()
        assert 'Selected 15' in [e['label'] for e in page.evaluate(OBSERVER)['elements']]
        browser.close()


def test_fill_waits_for_matching_debounced_autocomplete_results():
    async def scenario():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel='chrome', headless=True)
            context = await browser.new_context(viewport={'width':900,'height':633})
            page = await context.new_page()
            await page.route('https://rail.example/**', lambda route: route.fulfill(body='''
                <div style="height:540px"></div>
                <input style="height:40px" aria-label="To station" role="searchbox" aria-controls="stations"
                    oninput="document.querySelector('#stations').innerHTML='';setTimeout(()=>document.querySelector('#stations').innerHTML='<li role=option>HAZRAT NIZAMUDDIN - NZM</li>',900)">
                <ul id="stations"><li role="option">Old unrelated result</li></ul>
                <div style="height:900px"></div>''', content_type='text/html'))
            await page.goto('https://rail.example/search')
            driver = BrowserDriver(Settings(_env_file=None, browser_dwell_ms=0))
            driver.context, driver.page = context, page
            observation = await driver.observe()
            field = next(e for e in observation.elements if e.role == 'searchbox')
            await driver.execute(Action(id='a1', kind='fill', target=field.ref, value='NZM', reason='Enter requested station'), observation)
            options = [e.label for e in (await driver.observe()).elements if e.role == 'option']
            assert options == ['HAZRAT NIZAMUDDIN - NZM']
            box = await page.get_by_role('option').bounding_box()
            assert box['y'] >= 0 and box['y'] + box['height'] <= 633
            await browser.close()
    asyncio.run(scenario())
