import asyncio

import pytest
from pydantic import ValidationError

from jev_lab.agent.candidates import CandidatePlanner
from jev_lab.agent.models import Action, AgentError, Control, FlightDetails, Observation, Plan, StartRun, Verdict
from jev_lab.agent.runner import AgentRun, RunManager
from jev_lab.config import Settings


def test_return_date_is_required_and_cannot_precede_departure():
    data=dict(from_city='Mumbai',to_city='Dubai',departure_date='2026-11-01',trip_type='Return')
    with pytest.raises(ValidationError):FlightDetails(**data)
    with pytest.raises(ValidationError):FlightDetails(**data,return_date='2026-10-31')
    assert FlightDetails(**data,return_date='2026-11-04').as_inputs()['Return date']=='2026-11-04'
    assert FlightDetails(**{**data,'trip_type':'One way'},return_date='2026-10-31').return_date is None


class Browser:
    def __init__(self): self.closed=False; self.actions=0
    async def start(self,url): pass
    async def observe(self):
        return Observation(url='https://www.makemytrip.com/flights/',title='Flights',text='Search flights',elements=[],document='test',revision='v1')
    async def screenshot(self):return b''
    async def hide_cursor(self):pass
    async def close(self):self.closed=True
    async def execute(self,*args):self.actions+=1


async def wait_for(predicate):
    for _ in range(300):
        if predicate():return
        await asyncio.sleep(0)
    raise AssertionError('State change did not arrive')


def test_new_task_cancels_a_waiting_run_and_clears_it():
    async def scenario():
        manager=RunManager(Settings(_env_file=None),None)
        browser=Browser()
        manager.current=AgentRun(StartRun(task='Search for Dubai flights',mode='jev',start_url='https://www.makemytrip.com/flights/'),manager.settings,None,browser=browser)
        run=manager.current; run.task=asyncio.create_task(run.run())
        await wait_for(lambda:run.pending)
        assert run.pending['flightDetails']['to_city']=='Dubai'
        await manager.reset()
        assert manager.current is None and run.task.done()
        assert run.status=='stopped' and browser.closed and browser.actions==0
        await manager.reset()  # Double reset remains safe.
    asyncio.run(scenario())


def test_new_task_cancels_an_inflight_model_before_it_can_act():
    async def scenario():
        started=asyncio.Event(); cancelled=asyncio.Event()
        class Planner:
            async def propose(self,*args):
                started.set()
                try:await asyncio.Event().wait()
                finally:cancelled.set()
        browser=Browser();settings=Settings(_env_file=None)
        run=AgentRun(StartRun(task='Read this page',mode='jev',start_url='https://example.org'),settings,None,browser=browser,planner=Planner())
        manager=RunManager(settings,None);manager.current=run
        run.task=asyncio.create_task(run.run());await started.wait()
        await manager.reset()
        assert cancelled.is_set() and browser.closed and browser.actions==0
        assert manager.current is None
    asyncio.run(scenario())


def test_form_submission_resumes_with_values_without_granting_approval():
    async def scenario():
        class Judge:
            async def evaluate(self,*args):
                return Verdict(choice='stop',confidence=1,goal_met=0)
        browser=Browser();settings=Settings(_env_file=None)
        run=AgentRun(StartRun(task='Search for Dubai flights',mode='jev',start_url='https://www.makemytrip.com/flights/'),settings,None,browser=browser,judge=Judge())
        run.task=asyncio.create_task(run.run());await wait_for(lambda:run.pending)
        details=FlightDetails(from_city='Mumbai',to_city='Dubai',departure_date='2026-11-01',trip_type='One way')
        await run.control(Control(command='details',details=details))
        await wait_for(lambda:run.status=='review')
        assert not run._approved
        assert 'From: Mumbai' in run.updates[-1]
        plan=await CandidatePlanner({}).propose(run.request.task,await browser.observe(),[],run.updates)
        assert plan.status=='act' and plan.flight_details is None
        with pytest.raises(AgentError):await run.control(Control(command='details',details=details))
        await run.control(Control(command='stop'))
    asyncio.run(scenario())


def test_reset_api_leaves_no_current_run(client):
    assert client.post('/api/agent/reset',json={}).json()=={'status':'ready'}
    assert client.get('/api/agent/current').json() is None
