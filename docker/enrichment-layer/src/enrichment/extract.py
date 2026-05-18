from __future__ import annotations

import re

import trafilatura
from bs4 import BeautifulSoup

from enrichment.fetch import FetchResult
from enrichment.models import ExtractedPage

IMPERATIVE_VERBS = {
    "click", "select", "drag", "choose", "open", "press", "type",
    "navigate", "tap", "drop", "drag", "enter", "create", "save",
    "delete", "remove", "add", "go", "scroll", "hover", "right-click",
}
WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")


def extract(fetch: FetchResult, application: str, goal: str) -> ExtractedPage:
    html_text = fetch.html.decode("utf-8", errors="replace")
    main_text = trafilatura.extract(html_text) or ""

    soup = BeautifulSoup(html_text, "lxml")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    ordered_items = sum(len(ol.find_all("li", recursive=False)) for ol in soup.find_all("ol"))
    image_count = len(soup.find_all("img"))

    words = WORD_RE.findall(main_text.lower())
    verb_hits = sum(1 for w in words if w in IMPERATIVE_VERBS)
    verb_density = verb_hits / len(words) if words else 0.0

    text_lower = main_text.lower()
    return ExtractedPage(
        url=fetch.final_url,
        content_hash=fetch.content_hash,
        http_status=fetch.http_status,
        title=title,
        text=main_text,
        text_length=len(main_text),
        ordered_list_items=ordered_items,
        imperative_verb_density=verb_density,
        image_count=image_count,
        application_term_present=application.lower() in text_lower if application else False,
        goal_term_present=any(tok in text_lower for tok in goal.lower().split() if len(tok) > 3),
    )
