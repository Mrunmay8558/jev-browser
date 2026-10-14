import asyncio

import pytest

from jev_lab.agent.candidates import CandidatePlanner
from jev_lab.agent.models import Action, AgentError, Element, Observation, StartRun
from jev_lab.agent.navigation import requested_website, navigation_urls
from jev_lab.agent.safety import action_boundary


def page(url='https://www.makemytrip.com/flights/'):
    return Observation(url=url,title='Flights',text='Search flights',elements=[],document='doc')


def test_named_real_website_overrides_stale_railway_url():
    request=StartRun(task='open a makemytrip app and search for dubai flights',mode='jev',start_url='http://127.0.0.1:4317/demo/railway.html')
    assert request.start_url=='https://www.makemytrip.com/flights/'


def test_named_site_works_without_hidden_settings():
    assert StartRun(task='Open MakeMyTrip',mode='jev').start_url=='https://www.makemytrip.com/flights/'
    assert requested_website('Open https://example.org/search.')=='https://example.org/search'
    assert requested_website('Open an unknown brand')==''


def test_followup_can_propose_navigation_only_to_a_user_requested_site():
    task='Find railway tickets'
    updates=['Open MakeMyTrip and search for Dubai flights']
    observation=page('http://127.0.0.1:4317/demo/railway.html')
    plan=asyncio.run(CandidatePlanner({}).propose(task,observation,[],updates))
    assert plan.actions[0].kind=='navigate'
    allowed=navigation_urls(task,updates,observation.url)
    assert action_boundary(plan.actions[0],observation,allowed)=='normal'
    with pytest.raises(AgentError):
        action_boundary(Action(id='a1',kind='navigate',value='https://not-requested.example',reason='Go elsewhere'),observation,allowed)


def test_jev_only_asks_for_missing_flight_details_instead_of_guessing():
    plan=asyncio.run(CandidatePlanner({}).propose('Open MakeMyTrip and search for Dubai flights',page(),[],[]))
    assert plan.status=='handoff'
    assert plan.flight_details['from_city']==''
    assert plan.flight_details['departure_date']==''
    assert plan.flight_details['to_city']=='Dubai'
    assert 'Save and continue' in plan.message
    assert not plan.actions


def test_supplied_details_allow_dynamic_actions_on_real_site():
    observation=page()
    observation.elements=[Element(ref='e1',tag='button',role='button',label='Search')]
    plan=asyncio.run(CandidatePlanner({}).propose('Open MakeMyTrip and search for Dubai flights',observation,[],['From: Mumbai\nDeparture date: 2026-10-24\nTrip type: One way']))
    assert plan.status=='act'
    assert any(action.target=='e1' for action in plan.actions)


def test_readonly_airport_picker_is_clicked_not_filled():
    observation=page('https://flights.example')
    observation.elements=[Element(ref='e1',tag='input',type='text',role='',label='From',editable=False)]
    plan=asyncio.run(CandidatePlanner({'From':'Mumbai'}).propose('Find flights',observation,[],[]))
    assert plan.actions[0].kind=='click'
    with pytest.raises(AgentError):
        action_boundary(Action(id='a1',kind='fill',target='e1',value='Mumbai',reason='Fill city'),observation)


def test_current_page_links_do_not_create_a_reload_loop():
    observation=page('https://docs.example/tutorial/')
    observation.elements=[
        Element(ref='e1',tag='a',role='',label='Tutorial',href=observation.url),
        Element(ref='e2',tag='a',role='',label='Next chapter',href=observation.url+'chapter.html'),
        Element(ref='e3',tag='a',role='',label='Section',href=observation.url+'#section'),
    ]
    plan=asyncio.run(CandidatePlanner({}).propose('Read the next tutorial chapter',observation,[],[]))
    assert 'e1' not in [action.target for action in plan.actions]
    assert {'e2','e3'} <= {action.target for action in plan.actions}
