import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from jev_lab.agent.demo import DemoJudge, DEMO_TASK
from jev_lab.agent.judge import build_agent_payload, parse_verdict
from jev_lab.agent.models import Action, AgentError, Control, Element, Observation, Plan, StartRun, Verdict
from jev_lab.agent.planner import GeminiPlanner
from jev_lab.agent.runner import AgentRun
from jev_lab.agent.safety import action_boundary, evidence_is_present
from jev_lab.config import Settings


def observation():
    return Observation(url="https://rail.example/search",title="Rail",text="Search trains",document="doc",revision="v1",elements=[Element(ref="e1",tag="button",role="button",label="Search trains")])


@pytest.mark.parametrize("url",["file:///etc/passwd","javascript:alert(1)","https://user:password@example.com"])
def test_start_rejects_unsupported_urls(url):
    with pytest.raises(ValidationError):
        StartRun(task="Find trains",mode="live",start_url=url)


def test_only_observed_refs_and_supported_keys_can_be_used():
    with pytest.raises(AgentError):
        action_boundary(Action(id="a1",kind="click",target="invented",reason="Go"),observation())
    with pytest.raises(AgentError):
        action_boundary(Action(id="a1",kind="press",target="e1",value="Control+L",reason="Go"),observation())


def test_booking_requires_approval_and_secrets_require_handoff():
    page=observation()
    action=Action(id="a1",kind="click",target="e1",reason="Choose")
    assert action_boundary(action,page)=="normal"
    page.elements[0].label="Confirm booking"
    assert action_boundary(action,page)=="confirm"
    page.elements[0].sensitive=True
    assert action_boundary(action,page)=="handoff"


def test_completion_requires_actual_evidence():
    plan=Plan(status="complete",message="Done",evidence=["A booking was made"])
    assert not evidence_is_present(plan,observation())
    plan.evidence=["Search trains"]
    assert evidence_is_present(plan,observation())


def test_jev_payload_contains_candidates_and_rejects_unknown_choice():
    plan=Plan(status="act",message="Search",actions=[Action(id="a1",kind="click",target="e1",reason="Search")])
    payload=build_agent_payload("Find trains",observation(),plan,"test-model")
    assert set(payload["questions"]["next_action"]["criteria"])=={"a1","stop"}
    verdict=asyncio.run(DemoJudge().evaluate("Find trains",observation(),plan))
    assert verdict.choice=="a1"
    raw=verdict.response
    raw["answers"]["next_action"]["choice"]="not-an-option"
    with pytest.raises(AgentError):
        parse_verdict(raw,payload)


def test_gemini_uses_structured_plan_contract_without_browser_tools_or_key_in_body():
    async def run():
        def transport(request):
            assert request.headers["x-goog-api-key"]=="fake-gemini-key"
            body=json.loads(request.content)
            assert body["store"] is False
            assert "fake-gemini-key" not in request.content.decode()
            assert body["response_format"]["schema"]["properties"]["actions"]
            assert "tools" not in body
            return httpx.Response(200,json={"output_text":json.dumps({"status":"handoff","message":"What travel date?","actions":[],"evidence":[]})})
        settings=Settings(_env_file=None,gemini_api_key="fake-gemini-key")
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            plan=await GeminiPlanner(client,settings).propose("Find trains",observation(),[],[])
            assert plan.status=="handoff"
    asyncio.run(run())


class FakeBrowser:
    def __init__(self):
        self.reads=0
        self.actions=0
    async def start(self,url): pass
    async def observe(self):
        self.reads+=1
        return observation()
    async def screenshot(self): return b"fake-jpeg"
    async def hide_cursor(self): pass
    async def execute(self,*args): self.actions+=1


def test_handoff_suspends_observation_and_cancellation_stops_run():
    async def run():
        class Planner:
            async def propose(self,*args):
                return Plan(status="handoff",message="Enter the travel date.")
        browser=FakeBrowser()
        agent=AgentRun(StartRun(task=DEMO_TASK),Settings(_env_file=None),None,browser=browser,planner=Planner(),judge=DemoJudge())
        agent.task=asyncio.create_task(agent.run())
        for _ in range(100):
            if agent.pending: break
            await asyncio.sleep(0)
        assert agent.status=="handoff"
        before=browser.reads
        await asyncio.sleep(0.01)
        assert browser.reads==before
        assert browser.actions==0
        await agent.control(Control(command="stop"))
        assert agent.status=="stopped"
    asyncio.run(run())


def test_low_action_confidence_reports_the_action_score_not_completion_score():
    async def run():
        class Planner:
            async def propose(self,*args):
                return Plan(status='act',message='Scroll',actions=[Action(id='a1',kind='scroll',value='down',reason='Reveal more controls')])
        class Judge:
            async def evaluate(self,*args):
                return Verdict(choice='a1',confidence=.56,goal_met=.05,evidence='Search trains')
        browser=FakeBrowser()
        agent=AgentRun(StartRun(task='Find train options',mode='jev',start_url='https://rail.example'),Settings(_env_file=None),None,browser=browser,planner=Planner(),judge=Judge())
        agent.task=asyncio.create_task(agent.run())
        for _ in range(100):
            if agent.pending:break
            await asyncio.sleep(0)
        assert agent.status=='review' and browser.actions==0
        assert '56%' in agent.message and '65%' in agent.message
        assert 'completion' not in agent.message
        await agent.control(Control(command='stop'))
    asyncio.run(run())


def test_popup_appearing_during_judgment_replans_without_resume():
    async def run():
        class Browser(FakeBrowser):
            popup = False
            async def observe(self):
                page = observation()
                if self.popup:
                    page.revision = 'language-popup'
                    page.elements[0].label = 'English'
                return page
        class Judge:
            calls = 0
            async def evaluate(self, *args):
                self.calls += 1
                browser.popup = True
                return Verdict(choice='a1', confidence=.28 if self.calls == 1 else .98, goal_met=0)
        browser, judge = Browser(), Judge()
        agent = AgentRun(StartRun(task='Find trains', mode='jev', start_url='https://rail.example', max_steps=2),
                         Settings(_env_file=None), None, browser=browser, judge=judge)
        await asyncio.wait_for(agent.run(), timeout=2)
        assert judge.calls == 2
        assert browser.actions == 1
        assert not any(event['kind'] == 'review' for event in agent.events)
        assert any(event['kind'] == 'retry' for event in agent.events)
    asyncio.run(run())


def test_approval_cannot_become_action_until_explicitly_approved():
    async def run():
        class Planner:
            async def propose(self,*args):
                return Plan(status="act",message="Confirm",actions=[Action(id="a1",kind="click",target="e1",reason="Confirm booking",risk="confirm")])
        browser=FakeBrowser()
        agent=AgentRun(StartRun(task=DEMO_TASK,max_steps=1),Settings(_env_file=None),None,browser=browser,planner=Planner(),judge=DemoJudge())
        agent.task=asyncio.create_task(agent.run())
        for _ in range(100):
            if agent.pending: break
            await asyncio.sleep(0)
        assert agent.status=="approval" and browser.actions==0
        await agent.control(Control(command="approve"))
        await agent.task
        assert browser.actions==1
        assert agent.status=="limit_reached"
        assert agent.result is None
    asyncio.run(run())


def test_fake_completion_pauses_instead_of_claiming_success():
    async def run():
        class Planner:
            async def propose(self,*args):
                return Plan(status="complete",message="Booked!",evidence=["Booked reference XYZ"])
        browser=FakeBrowser()
        agent=AgentRun(StartRun(task=DEMO_TASK),Settings(_env_file=None),None,browser=browser,planner=Planner(),judge=DemoJudge())
        agent.task=asyncio.create_task(agent.run())
        for _ in range(100):
            if agent.pending: break
            await asyncio.sleep(0)
        assert agent.status=="review"
        assert agent.result is None
        await agent.control(Control(command="stop"))
    asyncio.run(run())


def test_live_agent_is_unavailable_without_both_keys(client):
    config=client.get('/api/agent/config').json()
    assert config['liveAvailable'] is False
    assert client.post('/api/agent/runs',json={'task':'Find train tickets','mode':'live','start_url':'https://rail.example'}).status_code==400


def choice_answer(criteria, selected):
    return {'type':'choice','choice':selected,'confidence':1.0,
            'probabilities':{key:float(key==selected) for key in criteria}}


def test_jev_only_generates_dynamic_candidates_from_supplied_values():
    from jev_lab.agent.candidates import CandidatePlanner
    page=observation()
    page.elements.insert(0,Element(ref='e2',tag='input',role='',type='text',label='From station'))
    planner=CandidatePlanner({'From station':'Pune'})
    plan=asyncio.run(planner.propose('Find trains',page,[],['From: Mumbai']))
    fills=[action for action in plan.actions if action.kind=='fill']
    assert [action.value for action in fills]==['Mumbai']
    assert fills[0].target=='e2'
    assert len(plan.actions) == 1  # Fill the grounded form field before submitting.
    page.elements[0].value = 'Mumbai'
    plan=asyncio.run(planner.propose('Find trains',page,[],['From: Mumbai']))
    assert any(action.target=='e1' and action.kind=='click' for action in plan.actions)


def test_candidate_overflow_hands_over_instead_of_emitting_invalid_ids():
    from jev_lab.agent.candidates import CandidatePlanner
    page=observation()
    page.elements=[Element(ref='e1',tag='select',role='',label='Station',options=[{'label':str(i),'value':str(i)} for i in range(100)])]
    plan=asyncio.run(CandidatePlanner({}).propose('Choose a station',page,[],[]))
    assert plan.status=='handoff'


def test_form_prompt_names_match_only_the_corresponding_supplied_value():
    from jev_lab.agent.candidates import matching_values
    values = {'From': 'NGP', 'To': 'Delhi', 'Journey date': '15/10/2026'}
    assert matching_values('Enter From station. Input is Mandatory.', values) == [('From', 'NGP')]
    assert matching_values('Enter To station. Input is Mandatory.', values) == [('To', 'Delhi')]
    assert matching_values('Select the departure date', values) == [('Journey date', '15/10/2026')]
    assert matching_values('DD/MM/YYYY *', values) == [('Journey date', '15/10/2026')]
    # Unknown field names still go to Jev for interpretation.
    assert matching_values('Unfamiliar control', values) == list(values.items())


def test_autocomplete_commits_only_matching_supplied_suggestions():
    from jev_lab.agent.candidates import CandidatePlanner
    page = observation()
    page.elements += [Element(ref='from', tag='input', role='searchbox', label='From', value='NGP'),
                      Element(ref='ngp', tag='li', role='option', label='NAGPUR - NGP (NAGPUR)'),
                      Element(ref='vngp', tag='li', role='option', label='VANGAICHUNGPAO - VNGP')]
    planner = CandidatePlanner({'From': 'NGP'})
    plan = asyncio.run(planner.propose('List trains', page, [], []))
    assert [(a.kind, a.target) for a in plan.actions] == [('click', 'ngp')]
    assert 'confirm From: NGP' in plan.actions[0].reason
    history = [{'kind': 'action', 'message': 'click: ' + plan.actions[0].reason}]
    page.elements[1].value = 'NAGPUR - NGP (NAGPUR)'
    page.elements = page.elements[:2]
    plan = asyncio.run(planner.propose('List trains', page, history, []))
    assert not any(a.kind == 'fill' for a in plan.actions)
    # A later user edit to a different station must not be treated as confirmed.
    page.elements[1].value = 'VANGAICHUNGPAO - VNGP'
    plan = asyncio.run(planner.propose('List trains', page, history, []))
    assert any(a.kind == 'fill' for a in plan.actions)
    page.elements[1].value = ''
    plan = asyncio.run(planner.propose('List trains', page, [], []))
    assert any(a.kind == 'fill' for a in plan.actions)
    assert len(plan.actions) == 1


def test_autocomplete_prefers_station_over_saved_multi_field_journey():
    from jev_lab.agent.candidates import CandidatePlanner
    page = observation()
    page.elements = [Element(ref='from', tag='input', role='searchbox', label='From', value='NGP'),
                     Element(ref='journey', tag='li', role='option', label='NAGPUR - NGP → HAZRAT NIZAMUDDIN - NZM'),
                     Element(ref='station', tag='li', role='option', label='NAGPUR - NGP (NAGPUR) MAHARASHTRA')]
    planner = CandidatePlanner({'From': 'NGP', 'To': 'NZM'})
    plan = asyncio.run(planner.propose('Find trains', page, [], []))
    assert [action.target for action in plan.actions] == ['station']
    # Do not discard the only available match on a site offering saved journeys.
    page.elements.pop()
    plan = asyncio.run(planner.propose('Find trains', page, [], []))
    assert [action.target for action in plan.actions] == ['journey']


@pytest.mark.parametrize('value', ['2026-10-15', '15/10/2026'])
def test_calendar_uses_the_full_requested_date(value):
    from jev_lab.agent.candidates import CandidatePlanner
    page = observation()
    page.elements += [Element(ref='oct',tag='a',role='',label='15 October 2026'),
                      Element(ref='nov',tag='a',role='',label='15 November 2026')]
    plan = asyncio.run(CandidatePlanner({'Journey date':value}).propose('Find trains',page,[],[]))
    assert [a.target for a in plan.actions] == ['oct']
    # An ambiguous date must not silently assume a locale.
    plan = asyncio.run(CandidatePlanner({'Journey date':'01/02/2026'}).propose('Find trains',page,[],[]))
    assert len(plan.actions) > 1


def test_jev_only_runs_to_completion_without_a_gemini_key_or_request():
    from jev_lab.agent.judge import JevJudge
    async def run():
        class Browser(FakeBrowser):
            async def observe(self):
                page=observation()
                if self.actions:
                    page.text='Demo booking confirmed\nDEMO-1042'
                    page.elements=[]
                    page.revision='v2'
                return page
        calls=[]
        def transport(request):
            calls.append(str(request.url))
            assert str(request.url)=='https://api.typesafe.ai/v1/systemone'
            payload=json.loads(request.content)
            done='DEMO-1042' in payload['state']['page']['text']
            criteria=payload['questions']['next_action']['criteria']
            selected='stop' if done else next(key for key, action in criteria.items() if isinstance(action,dict) and action['kind']=='click')
            quotes=payload['questions']['completion_evidence']['criteria']
            quote=next((key for key,value in quotes.items() if 'DEMO-1042' in value),'none')
            return httpx.Response(200,json={'answers':{
                'next_action':choice_answer(criteria,selected),
                'goal_met':{'type':'noul','noul':float(done)},
                'needs_confirmation':{'type':'noul','noul':0.0},
                'completion_evidence':choice_answer(quotes,quote)}})
        settings=Settings(_env_file=None,typesafe_api_key='fake-jev',gemini_api_key='')
        browser=Browser()
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            agent=AgentRun(StartRun(task='Complete the demo booking',mode='jev',start_url='https://rail.example',max_steps=3),settings,client,browser=browser)
            assert isinstance(agent.judge,JevJudge)
            await agent.run()
        assert agent.status=='completed',agent.snapshot()
        assert browser.actions==1
        assert agent.model_calls=={'gemini':0,'jev':2}
        assert len(calls)==2
        assert 'DEMO-1042' in agent.result['evidence'][0]
    asyncio.run(run())


def test_jev_only_is_available_with_just_the_typesafe_key():
    from fastapi.testclient import TestClient
    from jev_lab.app import create_app
    settings=Settings(_env_file=None,typesafe_api_key='fake-jev',gemini_api_key='')
    with TestClient(create_app(settings),base_url='http://127.0.0.1:4317') as client:
        config=client.get('/api/agent/config').json()
        assert config['jevOnlyAvailable'] is True
        assert config['liveAvailable'] is False
        response=client.post('/api/agent/runs',json={'task':'Find trains','mode':'live','start_url':'https://rail.example'})
        assert response.status_code==400


def test_chat_message_at_approval_never_approves_the_action():
    async def run():
        class Planner:
            async def propose(self,*args):
                return Plan(status='act',message='Confirm',actions=[Action(id='a1',kind='click',target='e1',reason='Confirm booking',risk='confirm')])
        browser=FakeBrowser()
        agent=AgentRun(StartRun(task=DEMO_TASK,max_steps=1),Settings(_env_file=None),None,browser=browser,planner=Planner(),judge=DemoJudge())
        agent.task=asyncio.create_task(agent.run())
        for _ in range(100):
            if agent.pending: break
            await asyncio.sleep(0)
        assert agent.status=='approval'
        await agent.control(Control(command='message',message='Show me another train first'))
        await agent.task
        assert browser.actions==0
        assert agent.updates==['Show me another train first']
    asyncio.run(run())


def test_chat_guidance_invalidates_an_in_flight_model_proposal():
    async def run():
        waiting=asyncio.Event()
        release=asyncio.Event()
        class Planner:
            async def propose(self,*args):
                waiting.set()
                await release.wait()
                return Plan(status='act',message='Search',actions=[Action(id='a1',kind='click',target='e1',reason='Search')])
        browser=FakeBrowser()
        agent=AgentRun(StartRun(task=DEMO_TASK,max_steps=1),Settings(_env_file=None),None,browser=browser,planner=Planner(),judge=DemoJudge())
        agent.task=asyncio.create_task(agent.run())
        await waiting.wait()
        await agent.control(Control(command='message',message='Change the destination'))
        release.set()
        await agent.task
        assert browser.actions==0
        assert agent.last_decision is None
    asyncio.run(run())
