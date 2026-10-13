"""Resolve user-requested websites; page content cannot authorize navigation."""

import re
from urllib.parse import urlsplit

# Small explicit directory, not an open-ended brand-to-domain guesser.
SITES = {
    'makemytrip': 'https://www.makemytrip.com/flights/',
    'irctc': 'https://www.irctc.co.in/nget/train-search',
    'wikipedia': 'https://en.wikipedia.org/',
    'python documentation': 'https://docs.python.org/3/',
}


def valid_web_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
        raise ValueError('Use an http(s) website address without embedded credentials.')
    return value


def requested_website(text: str) -> str:
    match = re.search(r'https?://[^\s<>"\']+', text, re.I)
    if match:
        return valid_web_url(match[0].rstrip('.,;!?)'))
    for name, url in SITES.items():
        if re.search(r'\b' + re.escape(name) + r'\b', text, re.I):
            return url
    return ''


def navigation_urls(task: str, updates: list[str], start_url: str = '') -> list[str]:
    return list(dict.fromkeys(filter(None, [start_url, requested_website(task), *(requested_website(update) for update in updates)])))


def same_site(first: str, second: str) -> bool:
    return urlsplit(first).hostname == urlsplit(second).hostname


def flight_values(text: str) -> dict[str, str]:
    """Recognize a few explicit trip phrases; never guess dates or a home city."""
    values = {}
    if not re.search(r'\bflights?\b|makemytrip', text, re.I):
        return values
    patterns = {
        'To': r'\b(?:flights?\s+to|to)\s+([A-Za-z]+(?: [A-Za-z]+)?)(?=\s+(?:from|on|for|in|and|one|return)\b|[.,\n]|$)',
        'From': r'\bfrom\s+([A-Za-z]+(?: [A-Za-z]+)?)(?=\s+(?:to|on|for|in|and)\b|[.,\n]|$)',
    }
    for label, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            values[label] = match[1].strip()
    if 'To' not in values:
        match = re.search(r'\b(?:for|find|search)\s+([A-Za-z]+(?: [A-Za-z]+)?)\s+flights?\b', text, re.I)
        if match:
            values['To'] = match[1].strip()
    dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', text)
    if len(dates) == 1:
        values['Departure date'] = dates[0]
    return values
