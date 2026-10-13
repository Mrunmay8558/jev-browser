"""Opt-in real browser check. Start the local server before enabling this test."""

import os
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright, expect

pytestmark=pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS")!="1",reason="Set RUN_BROWSER_TESTS=1 with the local server running.")


def test_cursor_keeps_its_size_under_the_practice_sites_strict_csp():
    base=os.environ.get("JEV_TEST_URL","http://127.0.0.1:4317")
    overlay=(Path(__file__).parents[1]/'jev_lab/agent/overlay.js').read_text()
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel="chrome",headless=True)
        page=browser.new_page()
        page.goto(base+'/demo/railway.html')
        page.evaluate(overlay)
        page.evaluate("window.__jevCursor.move(100,100,'Click target')")
        assert page.evaluate("window.__jevCursor.bounds()") == {'width':24,'height':30}
        browser.close()


def test_visible_browser_completes_railway_journey_and_reports_evidence():
    base=os.environ.get("JEV_TEST_URL","http://127.0.0.1:4317")
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel="chrome",headless=True)
        page=browser.new_page(viewport={"width":1440,"height":1100})
        errors=[]
        page.on("pageerror",lambda error:errors.append(str(error)))
        page.goto(base)
        page.get_by_text('Loading configuration…',exact=True).wait_for(state='hidden')
        assert not page.locator('#error').is_visible()
        with httpx.Client(base_url=base,trust_env=False) as client:
            # Scripted fixtures are available explicitly through the test API,
            # never as a fallback for the real-site product UI.
            task=client.get('/api/agent/config').json()['demoTask']
            response=client.post('/api/agent/runs',json={'task':task,'mode':'demo'})
            assert response.status_code==202,response.text
            deadline=time.monotonic()+50
            run=None
            while time.monotonic()<deadline:
                run=client.get('/api/agent/current').json()
                if run and run['status'] in {'approval','failed','review','handoff','limit_reached'}: break
                time.sleep(0.25)
            assert run and run['status']=='approval',run
            assert run['step']>=9
            assert run['pending']['action']['reason']=='Confirm demo booking'
            assert run['result'] is None
            page.get_by_role("button",name="Approve this action",exact=True).click()
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                run=client.get('/api/agent/current').json()
                if run['status'] in {'completed','failed','review','limit_reached'}: break
                time.sleep(0.25)
            assert run['status']=='completed',run
            assert 'DEMO-1042' in run['result']['evidence']
            assert sum(event['kind']=='action' for event in run['events'])>=10
            screen=client.get(f"/api/agent/runs/{run['id']}/screen")
            assert screen.status_code==200
            assert screen.headers['content-type']=='image/jpeg'
            page.get_by_text('Demo booking completed:',exact=False).first.wait_for()
            expect(page.locator('.message.result')).to_be_in_viewport()
            page.screenshot(path=str(Path('/private/tmp/jev-multistep-dashboard.png')),full_page=True)
            Path('/private/tmp/jev-multistep-browser.jpg').write_bytes(screen.content)
            assert not errors,errors
            page.get_by_role('button',name='New task',exact=False).click()
            page.get_by_role('button',name='Jev only',exact=True).click()
            assert page.get_by_role('button',name='Jev only',exact=True).get_attribute('aria-pressed')=='true'
            assert 'Requires only a Jev key' in page.locator('#mode-note').inner_text()
            page.get_by_role('button',name='Gemini + Jev',exact=True).click()
            assert 'Requires both keys' in page.locator('#mode-note').inner_text()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        browser.close()


def test_observer_excludes_offscreen_and_covered_controls():
    from jev_lab.agent.browser import OBSERVER

    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':800,'height':600})
        page.set_content('''<button id="covered">Covered</button>
            <button style="position:absolute;top:2000px">Offscreen</button>
            <div style="position:fixed;inset:0;background:white;z-index:5">
                <button id="front">Visible dialog button</button>
                <div id="shadow"></div>
            </div>''')
        page.locator('#shadow').evaluate("el=>{el.attachShadow({mode:'open'}).innerHTML='<button>Shadow button</button>'}")
        labels=[element['label'] for element in page.evaluate(OBSERVER)['elements']]
        assert labels==['Visible dialog button','Shadow button']
        browser.close()
