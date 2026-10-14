from pathlib import Path

from jev_lab.agent.models import Observation, Plan
from jev_lab.agent.results import build_result, irctc_train_results


def train_page(text=None):
    return Observation(
        url="https://www.irctc.co.in/nget/booking/train-list", title="IRCTC",
        text=text if text is not None else (Path(__file__).parent / "fixtures/irctc-train-list.txt").read_text(),
        elements=[], document="test", revision="results",
    )


def test_real_irctc_snapshot_preserves_all_names_times_dates_and_stations():
    result = irctc_train_results(train_page())
    assert result["reportedCount"] == len(result["trains"]) == 17
    first = result["trains"][0]
    assert first == {"name": "TVC NZM SF EXP", "number": "12643",
                     "departure": {"time": "00:25", "station": "NAGPUR", "date": "Thu, 15 Oct"},
                     "arrival": {"time": "18:45", "station": "HAZRAT NIZAMUDDIN JN", "date": "Thu, 15 Oct"}}
    # IRCTC includes nearby destinations; don't relabel these as NZM.
    overnight = result["trains"][4]
    assert overnight["name"] == "PDY NDLS SF EXP"
    assert overnight["departure"]["time"] == "06:50"
    assert overnight["arrival"] == {"time": "00:20", "station": "NEW DELHI", "date": "Fri, 16 Oct"}
    assert result["trains"][-1]["number"] == "18237"
    assert result["trains"][-1]["arrival"]["time"] == "19:50"


def test_incomplete_card_does_not_borrow_next_trains_arrival():
    page = train_page()
    page.text = page.text.replace("18:45 | HAZRAT NIZAMUDDIN JN | Thu, 15 Oct", "Arrival unavailable", 1)
    result = irctc_train_results(page)
    assert len(result["trains"]) == 16
    assert all(train["number"] != "12643" for train in result["trains"])
    assert result["trains"][0]["name"] == "SAMTA EXPRESS"
    assert "17 results" in result["summary"] and "16 train schedules" in result["summary"]
    assert "could not be read" in result["note"]


def test_truncated_and_duplicate_cards_are_not_invented_or_counted_twice():
    page = train_page()
    card = page.text[page.text.index("TVC NZM SF EXP"):page.text.index("SAMTA EXPRESS")]
    page.text = "17 Results for NAGPUR HAZRAT NIZAMUDDIN\n" + card + card + "SAMTA EXPRESS (12807)\n00:40 | NAGPUR | Thu, 15 Oct"
    result = irctc_train_results(page)
    assert len(result["trains"]) == 1
    assert "1 train schedule from the page" in result["summary"]


def test_only_extracts_irctc_search_results_and_preserves_other_final_answers():
    plan = Plan(status="complete", message="Done", evidence=["Visible result"])
    page = train_page()
    page.url = "https://irctc.co.in.example.org/nget/booking/train-list"
    assert irctc_train_results(page) is None
    result = build_result(plan, page, "jev")
    assert result == {"summary": "Done", "evidence": ["Visible result"], "url": page.url, "mode": "jev"}
    page.url = "https://www.irctc.co.in/nget/train-search"
    assert irctc_train_results(page) is None


def test_empty_results_and_unreadable_schedules_are_explicit():
    result = irctc_train_results(train_page("0 Results for NAGPUR HAZRAT NIZAMUDDIN"))
    assert result["trains"] == [] and "no trains" in result["summary"]
    result = irctc_train_results(train_page("17 Results for NAGPUR HAZRAT NIZAMUDDIN"))
    assert result["trains"] == [] and "read 0" in result["summary"]


def test_completed_answer_includes_structured_results_and_original_evidence():
    plan = Plan(status="complete", message="Task complete", evidence=["17 Results for NAGPUR"])
    result = build_result(plan, train_page(), "jev")
    assert len(result["trains"]) == 17
    assert result["evidence"] == plan.evidence
    assert result["mode"] == "jev"
