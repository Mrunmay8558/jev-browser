"""Present verified page results without asking a model to invent an answer."""

import re
from urllib.parse import urlsplit

from .models import Observation, Plan


TRAIN_HEADING = re.compile(r"^([^\n|]{2,120}?)\s*\((\d{5})\)\s*$", re.M)
STOP = re.compile(
    r"^(?P<time>(?:[01]\d|2[0-3]):[0-5]\d)\s*\|\s*"
    r"(?P<station>[^|\n]+?)\s*\|\s*"
    r"(?P<date>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s*\d{1,2}\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\s+\d{4})?)\s*$",
    re.M,
)


def irctc_train_results(observation: Observation) -> dict | None:
    """Read each schedule within its own card; never borrow a missing time.

    This adapter accepts only IRCTC's train-list page and its observed text.
    Unreadable/truncated cards are reported as partial results, not filled in.
    """
    url = urlsplit(observation.url)
    if url.hostname not in {"irctc.co.in", "www.irctc.co.in"} or url.path.rstrip("/") != "/nget/booking/train-list":
        return None
    text = observation.text
    heading = re.search(r"^(\d+) Results? for ([^\n]+)$", text, re.M)
    if not heading:
        return None
    reported_count = int(heading[1])
    headings = list(TRAIN_HEADING.finditer(text, heading.end()))
    trains = []
    seen = set()
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        stops = list(STOP.finditer(text, match.end(), end))
        if len(stops) != 2:
            continue
        departure, arrival = ({key: value.strip() for key, value in stop.groupdict().items()} for stop in stops)
        identity = (match[2], *departure.values(), *arrival.values())
        if identity in seen:
            continue
        seen.add(identity)
        trains.append({"number": match[2], "name": match[1].strip(),
                       "departure": departure, "arrival": arrival})
    count = len(trains)
    if count == reported_count:
        summary = ("Here is the train option shown by IRCTC." if count == 1 else
                   f"Here are the {count} train options shown by IRCTC." if count else
                   "IRCTC shows no trains for this search.")
        note = "Times, dates, and stations are copied from IRCTC."
    else:
        schedules = "schedule" if count == 1 else "schedules"
        summary = f"IRCTC reports {reported_count} results. I could read {count} train {schedules} from the page."
        note = "Some schedules could not be read completely. Check the results page for the remaining details."
    return {"summary": summary, "trains": trains, "reportedCount": reported_count,
            "sourceHeading": heading[0].strip(), "note": note}


def build_result(plan: Plan, observation: Observation, mode: str) -> dict:
    result = {"summary": plan.message, "evidence": plan.evidence, "url": observation.url, "mode": mode}
    trains = irctc_train_results(observation)
    if trains is not None:
        result.update(trains)
    return result
