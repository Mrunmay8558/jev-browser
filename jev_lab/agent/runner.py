"""One cancellable observe/plan/judge/act loop, with real suspended handovers."""

import asyncio
import json
import time
import uuid
from contextlib import suppress

from playwright.async_api import Error as BrowserError

from ..config import Settings
from .browser import BrowserDriver
from .candidates import CandidatePlanner
from .demo import DemoJudge, RailwayDemoPlanner
from .judge import JevJudge
from .models import AgentError, Control, Plan, StartRun, StaleObservation
from .planner import GeminiPlanner
from .navigation import navigation_urls
from .results import build_result
from .safety import action_boundary, evidence_is_present

TERMINAL = {"completed", "failed", "stopped", "limit_reached"}


class AgentRun:
    def __init__(self, request: StartRun, settings: Settings, client, *, browser=None, planner=None, judge=None):
        self.id = uuid.uuid4().hex
        self.request, self.settings = request, settings
        self.browser = browser or BrowserDriver(settings)
        self.planner = planner or (RailwayDemoPlanner() if request.mode=="demo" else CandidatePlanner(request.inputs) if request.mode=="jev" else GeminiPlanner(client,settings))
        self.judge = judge or (DemoJudge() if request.mode=="demo" else JevJudge(client,settings,select_evidence=request.mode=="jev"))
        self.status, self.message = "starting", "Opening the visible browser…"
        self.step, self.events, self.updates = 0, [], []
        self.observation = None
        self.pending = None
        self.result = None
        self.last_decision = None
        self.image = None
        self.image_revision = 0
        self._resume = asyncio.Event()
        self._pause_requested = False
        self._approved = False
        self._input_revision = 0
        self.task = None
        self.started_at = time.monotonic()
        self.finished_at = None
        self.model_calls = {"gemini": 0, "jev": 0}
        self.event("user", request.task)

    def event(self, kind: str, message: str, **details) -> None:
        self.events.append({"number":len(self.events)+1,"kind":kind,"message":message,"time":time.time(),**details})
        self.message = message

    def snapshot(self) -> dict:
        return {"id":self.id,"task":self.request.task,"startUrl":self.request.start_url,"mode":self.request.mode,"status":self.status,"message":self.message,
            "step":self.step,"maxSteps":self.request.max_steps,"events":self.events,
            "page": {"url":self.observation.url,"title":self.observation.title} if self.observation else None,
            "pending":self.pending,"result":self.result,"lastDecision":self.last_decision,
            "imageRevision":self.image_revision,"modelCalls":dict(self.model_calls),
            "elapsedSeconds":round((self.finished_at or time.monotonic()) - self.started_at, 1)}

    async def capture(self) -> None:
        with suppress(BrowserError):
            self.image = await self.browser.screenshot()
            self.image_revision += 1

    async def park(self, kind: str, message: str, action=None, *, flight_details=None) -> bool:
        self._resume.clear()
        self._approved = False
        self.status = kind
        self.pending = {"kind":kind,"message":message,"action":action.model_dump() if action else None}
        if flight_details is not None:
            self.pending['flightDetails'] = flight_details
        if kind in {"handoff", "paused"}:
            self.image = None
            self.image_revision += 1
        self.event(kind,message)
        with suppress(BrowserError):
            await self.browser.hide_cursor()
        await self._resume.wait()  # No timeout can become consent.
        self.pending = None
        self.status = "running"
        return self._approved

    async def control(self, command: Control) -> None:
        if command.command == "focus":
            await self.browser.focus()
            return
        if command.command == "stop":
            if self.task and not self.task.done():
                self.task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.task
                if self.status not in TERMINAL:
                    self.status = "stopped"
                    self.event("stop", "Stopped before the browser run started.")
                    self.finished_at = time.monotonic()
            return
        if self.status in TERMINAL:
            raise AgentError("This run has finished. Start a new task.")
        if command.command == "details":
            if not self.pending or 'flightDetails' not in self.pending or command.details is None:
                raise AgentError("There is no flight form waiting for details.")
            values = command.details.as_inputs()
            self.updates.append('\n'.join(f'{key}: {value}' for key, value in values.items()))
            self._input_revision += 1
            self.event('user', f"{command.details.from_city} → {command.details.to_city} · {command.details.departure_date} · {command.details.trip_type}" + (f" · Return {command.details.return_date}" if command.details.return_date else ''))
            self._approved = False
            self._pause_requested = False
            self._resume.set()
            return
        if command.command == "message":
            if not command.message.strip():
                raise AgentError("Enter a message to send.")
            self.updates.append(command.message.strip())
            self._input_revision += 1
            self.event("user", command.message.strip())
            if self.pending:
                # Chat guidance changes the plan; it never approves a pending action.
                self._approved = False
                self._pause_requested = False
                self._resume.set()
            else:
                self.event("control", "Instruction received. Updating the plan after the current operation.")
            return
        if command.command == "pause":
            if self.pending:
                return
            self._pause_requested = True
            self.event("control", "Pausing after the current browser operation…")
            return
        if not self.pending:
            raise AgentError("This run is not waiting for input.")
        if command.command == "approve" and self.status != "approval":
            raise AgentError("There is no action awaiting approval.")
        if command.message.strip():
            self.updates.append(command.message.strip())
            self._input_revision += 1
            self.event("user",command.message.strip())
        self._approved = command.command == "approve"
        self._pause_requested = False
        self._resume.set()

    async def run(self) -> None:
        try:
            url = self.request.start_url if self.request.mode!="demo" else f"http://127.0.0.1:{self.settings.port}/demo/railway.html"
            await self.browser.start(url)
            self.status = "running"
            failures = 0
            repeats = {}
            for step in range(1, self.request.max_steps+1):
                self.step = step
                if self._pause_requested:
                    self._pause_requested = False
                    await self.park("paused","You have control of the browser. Resume when ready.")
                observation = await self.browser.observe()
                self.observation = observation
                if observation.challenge:
                    # Stop all further snapshots/model calls while the person types secrets.
                    self.image = None
                    self.image_revision += 1
                    await self.park("handoff",observation.challenge)
                    continue
                await self.capture()
                self.event("observe",f"Read {observation.title}",url=observation.url)
                input_revision = self._input_revision
                if self.request.mode == "live":
                    self.model_calls["gemini"] += 1
                planning_task = self.request.task
                if self.request.inputs and self.request.mode == "live":
                    planning_task += "\nUser-supplied form values: " + str(self.request.inputs)
                plan = await self.planner.propose(planning_task,observation,list(self.events),list(self.updates))
                if input_revision != self._input_revision:
                    continue
                self.event("plan",plan.message,actions=[a.model_dump() for a in plan.actions])
                if self._pause_requested:
                    continue
                if plan.status == "handoff":
                    await self.park("handoff",plan.message,flight_details=plan.flight_details)
                    continue
                # Validate every candidate before sending it to the evaluator.
                allowed_urls = navigation_urls(self.request.task, self.updates, self.request.start_url)
                boundaries = {a.id:action_boundary(a,observation,allowed_urls) for a in plan.actions}
                effective_task = self.request.task
                if self.request.inputs:
                    effective_task += "\nUser-supplied form values: " + str(self.request.inputs)
                if self.updates:
                    effective_task += "\nUser follow-up instructions (latest takes precedence):\n" + "\n".join(self.updates)
                completed_actions = [event['message'] for event in self.events if event['kind'] == 'action'][-6:]
                if completed_actions:
                    effective_task += "\nRecent executed browser actions (historical data; check current page before repeating):\n" + json.dumps(completed_actions)
                if self.request.mode != "demo":
                    self.model_calls["jev"] += 1
                verdict = await self.judge.evaluate(effective_task,observation,plan)
                self.last_decision={"plan":plan.model_dump(),"jevPayload":verdict.payload,"jevResponse":verdict.response}
                self.event("judge",f"{'Scripted judge' if self.request.mode=='demo' else 'Jev'} chose {verdict.choice} · confidence {verdict.confidence:.2f}")
                if self._pause_requested or input_revision != self._input_revision:
                    continue
                # A popup can arrive while the model evaluates the previous
                # page. A stale verdict must not cause a needless user handover.
                if (await self.browser.observe()).revision != observation.revision:
                    self.event("retry", "The page changed while Jev was deciding. Reading it again automatically.")
                    continue
                if self.request.mode == "jev" and verdict.goal_met >= 0.9 and verdict.evidence:
                    plan = Plan(status="complete", message="Jev judged the task complete based on the page evidence below.", evidence=[verdict.evidence])
                if plan.status == "complete":
                    fresh = await self.browser.observe()
                    if fresh.revision!=observation.revision or input_revision != self._input_revision:
                        continue
                    if verdict.goal_met>=0.9 and evidence_is_present(plan,fresh):
                        self.status = "completed"
                        self.result=build_result(plan,fresh,self.request.mode)
                        self.event("complete",self.result["summary"])
                        await self.browser.hide_cursor()
                        await self.capture()
                        return
                    await self.park("review","Completion is not supported by both the page evidence and Jev. Add guidance or take over.")
                    continue
                if verdict.choice=="stop" or verdict.confidence<self.request.threshold:
                    if verdict.choice == "stop" and self.request.mode == "jev" and verdict.evidence and verdict.goal_met < 0.9:
                        message = f"Jev found page evidence, but rated completion at {verdict.goal_met:.0%}; this run requires 90%. Review the page or clarify the goal in chat."
                    elif verdict.choice == "stop":
                        message = "Jev chose to stop without verified completion. Review the page, supply missing form values, or clarify the next step in chat."
                    else:
                        message = f"Jev's action confidence is {verdict.confidence:.0%}, below the {self.request.threshold:.0%} threshold. Add guidance or take over."
                    await self.park("review",message)
                    continue
                action = next((a for a in plan.actions if a.id==verdict.choice),None)
                if not action:
                    raise AgentError("Jev selected an action outside the proposed candidates.")
                boundary = boundaries[action.id]
                if boundary=="handoff":
                    await self.park("handoff","Complete this step in the browser, then resume.",action)
                    continue
                if boundary=="confirm" or verdict.needs_confirmation>0.2:
                    approved = await self.park("approval",f"Approve this action: {action.reason}",action)
                    if not approved:
                        self.event("control","Action not approved; observing the page again.")
                        continue
                fingerprint=(observation.revision,action.kind,action.target,action.value)
                repeats[fingerprint]=repeats.get(fingerprint,0)+1
                if repeats[fingerprint]>2:
                    await self.park("review","The same action is not changing the page. Take over or give a different instruction.")
                    repeats.clear()
                    continue
                try:
                    if self._pause_requested or input_revision != self._input_revision:
                        continue
                    await self.browser.execute(action,observation,self.capture)
                    self.event("action",f"{action.kind}: {action.reason}")
                    failures=0
                except StaleObservation as error:
                    self.event("retry",str(error))
                except (AgentError,BrowserError):
                    failures+=1
                    self.event("retry","The browser action could not finish. Reading the page again; do not repeat an action with uncertain effects blindly.")
                    if failures>=2:
                        await self.park("review","Two browser actions failed. Take over or provide guidance.")
                        failures=0
                await asyncio.sleep(0.1)
            self.status="limit_reached"
            self.event("limit","Step limit reached. The browser remains open; no completion is claimed.")
        except asyncio.CancelledError:
            self.status="stopped"
            self.event("stop","Stopped. No further model calls or browser actions will be started.")
        except AgentError as error:
            self.status="failed"
            self.event("error",str(error))
        except Exception:
            self.status="failed"
            self.event("error","The run failed unexpectedly. The browser may have been closed or changed. Start a new run after checking it.")
        finally:
            self.finished_at = time.monotonic()
            self.pending=None
            with suppress(Exception):
                await self.browser.hide_cursor()


class RunManager:
    def __init__(self, settings: Settings, client):
        self.settings,self.client=settings,client
        self.current=None
        self._lock=asyncio.Lock()

    async def start(self, request: StartRun) -> AgentRun:
        async with self._lock:
            if self.current and self.current.status not in TERMINAL:
                raise AgentError("A browser run is already active. Stop it before starting another.")
            if request.mode=="live" and not self.settings.agent_available:
                raise AgentError("Live mode needs GEMINI_API_KEY and TYPESAFE_API_KEY in .env. Add both and restart.")
            if request.mode=="jev" and not self.settings.live_available:
                raise AgentError("Jev-only mode needs TYPESAFE_API_KEY in .env. Gemini is not required.")
            if self.current:
                await self.current.browser.close()
            self.current=AgentRun(request,self.settings,self.client)
            self.current.task=asyncio.create_task(self.current.run())
            return self.current

    def get(self, run_id: str) -> AgentRun:
        if not self.current or self.current.id!=run_id:
            raise AgentError("Run not found. Runs are kept in memory for this server session.")
        return self.current

    async def reset(self) -> None:
        """Cancel first, then disconnect and clear the task under the start lock."""
        async with self._lock:
            if self.current:
                await self.current.control(Control(command="stop"))
                await self.current.browser.close()
                self.current = None

    async def close(self) -> None:
        if self.current:
            await self.current.control(Control(command="stop"))
            await self.current.browser.close()
