"""An explicitly scripted railway journey for testing real browser execution."""

from .judge import build_agent_payload, parse_verdict
from .models import Action, AgentError, Observation, Plan

DEMO_TASK = "Book a demo train from Pune to Mumbai on 2026-10-24 for Asha. Choose the first train."


class RailwayDemoPlanner:
    async def propose(self, task: str, observation: Observation, history: list, updates: list[str]) -> Plan:
        if task != DEMO_TASK:
            return Plan(status="handoff", message="Demo mode supports the railway preset only. Choose that preset or use live mode for your own task.")
        if updates:
            return Plan(status="handoff", message="The local demo follows a fixed trip and cannot interpret chat changes. Stop this run and start Jev only or Gemini + Jev to use your instructions.")
        if "Demo booking confirmed" in observation.text:
            return Plan(status="complete", message="Demo booking completed: Pune → Mumbai, 24 October 2026, Asha, first train. Reference DEMO-1042. This is a local simulation; no real ticket was booked.", evidence=["Demo booking confirmed", "DEMO-1042"])
        desired = {"From station": "Pune", "To station": "Mumbai", "Travel date": "2026-10-24", "Travel class": "chair", "Passenger name": "Asha"}
        for element in observation.elements:
            if element.label in desired and element.value != desired[element.label]:
                return Plan(status="act", message=f"Set {element.label}.", actions=[Action(id="a1", kind="select" if element.tag == "select" else "fill", target=element.ref, value=desired[element.label], reason=f"Complete {element.label} from the user's request.")])
        for label in ["Search trains", "View morning train", "Choose this train", "Review journey", "Confirm demo booking"]:
            element = next((e for e in observation.elements if e.label == label), None)
            if element:
                return Plan(status="act", message=label, actions=[Action(id="a1",kind="click",target=element.ref,reason=label,risk="confirm" if label=="Confirm demo booking" else "normal")])
        raise AgentError("The railway demo page changed unexpectedly.")


class DemoJudge:
    async def evaluate(self, task: str, observation: Observation, plan: Plan):
        payload = build_agent_payload(task, observation, plan, "scripted-demo-not-jev")
        keys = list(payload["questions"]["next_action"]["criteria"])
        selected = plan.actions[0].id if plan.actions else "stop"
        probabilities = {key: 1.0 if len(keys)==1 else 0.98 if key==selected else 0.02/(len(keys)-1) for key in keys}
        response = {"model":"scripted-demo-not-jev", "answers": {
            "next_action":{"type":"choice","choice":selected,"probabilities":probabilities,"confidence":1.0 if len(keys)==1 else (0.98-1/len(keys))/(1-1/len(keys))},
            "goal_met":{"type":"noul","noul":0.99 if plan.status=="complete" else 0.01},
            "needs_confirmation":{"type":"noul","noul":0.99 if any(a.risk=="confirm" for a in plan.actions) else 0.01},
        }}
        return parse_verdict(response,payload)
