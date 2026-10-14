"""UI regressions with controlled API responses: no models or external websites."""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect

pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Start the local test server and set RUN_BROWSER_TESTS=1.')


def test_flight_form_preserves_typing_submits_details_and_new_task_works_while_waiting():
    base=os.environ.get('JEV_TEST_URL','http://127.0.0.1:4318')
    run={'id':'test-trip','task':'Search Dubai flights','mode':'jev','status':'handoff','step':1,'maxSteps':35,
         'events':[{'kind':'user','message':'Search Dubai flights'},{'kind':'handoff','message':'Add your trip details in the form below, then choose Save and continue.'}],
         'pending':{'message':'Add your trip details in the form below, then choose Save and continue.',
                    'flightDetails':{'from_city':'','to_city':'Dubai','departure_date':'','trip_type':'','return_date':''}},
         'page':None,'result':None,'lastDecision':None,'imageRevision':0,'modelCalls':{'jev':0,'gemini':0},'message':'Waiting for trip details'}
    state={'run':run,'details':None,'resets':0,'reads':0}
    def api(route):
        path=route.request.url.split('/api/agent/')[1]
        if path=='config':data={'jevOnlyAvailable':True,'liveAvailable':True,'jevConfigured':True,'geminiConfigured':True}
        elif path=='reset':state['run']=None;state['resets']+=1;data={'status':'ready'}
        elif path.endswith('/control'):
            state['details']=route.request.post_data_json
            state['run']={**run,'pending':{'message':'Use the browser, then continue.'},'status':'paused','events':[*run['events'],{'kind':'user','message':'Trip details saved.'}]}
            data=state['run']
        else:state['reads']+=1;data=state['run']
        route.fulfill(content_type='application/json',body=json.dumps(data))
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':960})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/api/agent/**',api)
        page.goto(base)
        expect(page.locator('#trip-form')).to_be_visible()
        expect(page.get_by_role('button',name='New task',exact=False)).to_be_enabled()
        expect(page.get_by_label('Flying to',exact=True)).to_have_value('Dubai')
        page.get_by_label('Flying from',exact=True).fill('Mumbai')
        # A background status poll must not erase unfinished typing.
        with page.expect_response(lambda r:'/api/agent/runs/test-trip' in r.url):pass
        expect(page.get_by_label('Flying from',exact=True)).to_have_value('Mumbai')
        page.get_by_label('Departure date',exact=True).fill('2026-11-01')
        page.get_by_label('Trip type',exact=True).select_option('Return')
        expect(page.get_by_label('Return date',exact=True)).to_be_visible()
        page.get_by_label('Return date',exact=True).fill('2026-11-05')
        page.get_by_role('button',name='Save and continue',exact=True).click()
        expect(page.locator('#trip-form')).to_be_hidden()
        assert state['details']=={'command':'details','details':{'from_city':'Mumbai','to_city':'Dubai','departure_date':'2026-11-01','trip_type':'Return','return_date':'2026-11-05'}}
        # Still paused: a fresh task must work without completing the old one.
        page.get_by_role('button',name='New task',exact=False).click()
        expect(page.locator('#welcome')).to_be_visible()
        expect(page.locator('#handoff')).to_be_hidden()
        expect(page.get_by_role('button',name='Gemini + Jev',exact=True)).to_be_enabled()
        assert state['resets']==1
        page.get_by_role('button',name='Gemini + Jev',exact=True).click()
        expect(page.get_by_role('button',name='Gemini + Jev',exact=True)).to_have_attribute('aria-pressed','true')
        page.reload()
        expect(page.locator('#welcome')).to_be_visible()
        expect(page.locator('#handoff')).to_be_hidden()
        assert not errors,errors
        # Compact screen still fits, including the full trip form in chat.
        state['run']=run;page.reload();page.set_viewport_size({'width':390,'height':844})
        expect(page.locator('#trip-form')).to_be_visible()
        page.get_by_role('button',name='Save and continue',exact=True).scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/private/tmp/jev-trip-form-mobile.png',full_page=True)
        page.set_viewport_size({'width':1440,'height':960})
        page.screenshot(path='/private/tmp/jev-trip-form.png',full_page=True)
        browser.close()


def test_completed_train_schedules_are_readable_in_chat_and_on_mobile():
    from jev_lab.agent.models import Observation, Plan
    from jev_lab.agent.results import build_result
    page_text = (Path(__file__).parent / 'fixtures/irctc-train-list.txt').read_text()
    result = build_result(Plan(status='complete', message='Done', evidence=['17 Results for NAGPUR']),
                          Observation(url='https://www.irctc.co.in/nget/booking/train-list', title='IRCTC',
                                      text=page_text, elements=[], document='test'), 'jev')
    run = {'id':'train-results', 'task':'List trains', 'mode':'jev', 'status':'completed', 'step':11,
           'maxSteps':35, 'events':[{'kind':'user','message':'List trains'}, {'kind':'complete','message':result['summary']}],
           'pending':None, 'page':{'url':result['url']}, 'result':result, 'lastDecision':None,
           'imageRevision':0, 'modelCalls':{'jev':11,'gemini':0}, 'message':result['summary']}
    def api(route):
        data = {'jevOnlyAvailable':True,'liveAvailable':False,'jevConfigured':True,'geminiConfigured':False} if route.request.url.endswith('/config') else run
        route.fulfill(content_type='application/json', body=json.dumps(data))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width':1440,'height':960})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/api/agent/**', api)
        page.goto(os.environ.get('JEV_TEST_URL','http://127.0.0.1:4318'))
        expect(page.locator('.train-card')).to_have_count(17)
        expect(page.locator('.train-card').first).to_be_in_viewport()
        expect(page.locator('.train-card').first).to_contain_text('TVC NZM SF EXP · 12643')
        expect(page.locator('.train-card').first).to_contain_text('00:25')
        expect(page.locator('.train-card').first).to_contain_text('18:45')
        expect(page.locator('.train-card').nth(4)).to_contain_text('Fri, 16 Oct')
        expect(page.locator('.train-card').nth(4)).to_contain_text('NEW DELHI')
        expect(page.locator('.result a')).to_have_attribute('href', result['url'])
        page.screenshot(path='/private/tmp/jev-train-results-desktop.png',full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.reload()
        expect(page.locator('.train-card').first).to_be_in_viewport()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#thread').evaluate('el => el.scrollWidth <= el.clientWidth')
        page.locator('.train-card').last.scroll_into_view_if_needed()
        expect(page.locator('.train-card').last).to_contain_text('CHATTISGARH EXP · 18237')
        page.screenshot(path='/private/tmp/jev-train-results-mobile.png',full_page=True)
        # Website-provided train names must never turn into HTML in the chat.
        result['trains'][0]['name'] = '<img src=x onerror="window.untrustedRan=true">'
        page.reload()
        expect(page.locator('.train-card').first).to_contain_text('<img src=x')
        assert page.locator('.train-card img').count() == 0
        assert page.evaluate('window.untrustedRan === undefined')
        assert not errors, errors
        browser.close()
