"""Recent headlines per ticker from Yahoo Finance's public RSS feed."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from perp_monitor.http import DEFAULT_POLICY, RetryPolicy, request_text
from perp_monitor.insights.models import NewsItem

log = logging.getLogger(__name__)

RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
MAX_SUMMARY = 280
MAX_TITLE = 200
NAME_NOISE = re.compile(r"[^A-Za-z0-9&]")
NAME_SUFFIXES = frozenset(
    [
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "companies",
        "holdings",
        "holding",
        "group",
        "plc",
        "ltd",
        "limited",
        "sa",
        "spa",
        "nv",
        "ag",
        "se",
        "llc",
        "lp",
        "the",
        "class",
        "common",
        "stock",
        "ordinary",
        "shares",
        "adr",
    ]
)
# First words too common to identify a company on their own ("General Motors").
GENERIC_WORDS = frozenset(
    [
        "general",
        "american",
        "first",
        "united",
        "national",
        "international",
        "global",
        "digital",
        "advanced",
        "applied",
        "new",
        "bank",
        "energy",
        "health",
        "capital",
        "financial",
        "data",
        "power",
        "solar",
        "royal",
        "western",
        "eastern",
        "southern",
        "northern",
        "pacific",
        "atlantic",
        "central",
        "standard",
        "universal",
        "allied",
        "consolidated",
        "great",
        "big",
        "smart",
        "super",
        "planet",
        "life",
        "home",
        "core",
        "rocket",
        "live",
        "open",
        "on",
        "one",
        "now",
        "all",
        "best",
        "target",
        "block",
    ]
)


@dataclass(frozen=True, slots=True)
class Relevance:
    """Patterns deciding whether a headline is about this company.

    Yahoo's per-symbol feed mixes in market-wide stories. A strong ticker form ($MDT,
    (MDT), NYSE: MDT) counts anywhere; a bare ticker or the company name counts only in
    the title, so list articles that mention the company in passing are dropped.
    """

    anywhere: tuple[re.Pattern[str], ...]
    title_only: tuple[re.Pattern[str], ...]

    def matches(self, title: str, summary: str) -> bool:
        text = f"{title} {summary}"
        return any(p.search(text) for p in self.anywhere) or any(
            p.search(title) for p in self.title_only
        )


def _core_words(company: str) -> list[str]:
    words = [NAME_NOISE.sub("", w) for w in company.split()]
    return [w for w in words if w and w.lower() not in NAME_SUFFIXES]


def relevance_for(ticker: str, company: str | None) -> Relevance:
    t = re.escape(ticker)
    anywhere = [
        re.compile(rf"\$\s?{t}(?![A-Za-z])"),
        re.compile(rf"\(\s?{t}\s?\)"),
        re.compile(rf"(?:NASDAQ|NYSE|NYSEAMERICAN|AMEX)\s?(?:CM|GS|GM)?\s?:\s?\$?{t}(?![A-Za-z])"),
    ]
    title_only: list[re.Pattern[str]] = []
    if len(ticker) >= 3:
        title_only.append(re.compile(rf"(?<![A-Za-z]){t}(?![A-Za-z])"))
    words = _core_words(company or "")
    if words:
        first = words[0]
        if first.lower() in GENERIC_WORDS or len(first) < 4:
            if len(words) >= 2:
                phrase = rf"{re.escape(first)}\W+{re.escape(words[1])}"
                title_only.append(re.compile(rf"\b{phrase}", re.IGNORECASE))
        else:
            title_only.append(re.compile(rf"\b{re.escape(first)}", re.IGNORECASE))
            if len(first) >= 8:  # ExxonMobil -> also "Exxon"
                title_only.append(re.compile(rf"\b{re.escape(first[:5])}", re.IGNORECASE))
    return Relevance(tuple(anywhere), tuple(title_only))


def _text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return " ".join((node.text or "").split()) if node is not None else ""


def _published(raw: str) -> datetime | None:
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)


def _safe_url(raw: str) -> str | None:
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return raw


def _source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def parse_rss(
    xml: str, since: datetime, limit: int, relevance: Relevance | None = None
) -> tuple[NewsItem, ...]:
    if "<!DOCTYPE" in xml[:2000].upper():
        log.warning("news feed has a DOCTYPE; refusing to parse it")
        return ()
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        log.warning("news feed is not valid XML: %s", exc)
        return ()
    items: list[NewsItem] = []
    seen_titles: set[str] = set()
    for node in root.iter("item"):
        title = _text(node, "title")[:MAX_TITLE]
        url = _safe_url(_text(node, "link"))
        published = _published(_text(node, "pubDate"))
        if not title or url is None or published is None or published < since:
            continue
        if title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())
        summary = _text(node, "description")[:MAX_SUMMARY]
        if relevance is not None and not relevance.matches(title, summary):
            continue
        items.append(NewsItem(title, url, published, _source(url), summary))
    items.sort(key=lambda i: i.published_at, reverse=True)
    return tuple(items[:limit])


def fetch_news(
    client: httpx.Client,
    ticker: str,
    since: datetime,
    limit: int = 5,
    company: str | None = None,
    policy: RetryPolicy = DEFAULT_POLICY,
) -> tuple[NewsItem, ...]:
    xml = request_text(
        client,
        "GET",
        RSS_URL,
        params={"s": ticker.replace(".", "-"), "region": "US", "lang": "en-US"},
        headers=HEADERS,
        policy=policy,
    )
    return parse_rss(xml, since, limit, relevance_for(ticker, company))
