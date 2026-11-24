"""Recent SEC filings that tend to move a stock: 8-K events, offerings, periodic reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import httpx

from perp_monitor.http import DEFAULT_POLICY, RetryPolicy, request_json
from perp_monitor.insights.models import Filing

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
MAX_FILINGS = 6

# 8-K item codes worth showing. 9.01 (exhibits) is boilerplate and left out.
ITEM_LABELS_ZH: Mapping[str, str] = {
    "1.01": "签订重大协议",
    "1.02": "终止重大协议",
    "1.03": "破产/接管",
    "1.05": "网络安全事件",
    "2.01": "完成收购/出售资产",
    "2.02": "业绩公告",
    "2.03": "新增债务",
    "2.04": "债务加速到期",
    "2.05": "重组/裁员",
    "2.06": "资产减值",
    "3.01": "退市或不符合上市标准",
    "3.02": "未注册股权发行",
    "3.03": "股东权利变更",
    "4.01": "更换审计师",
    "4.02": "财报不可依赖（重述）",
    "5.01": "控制权变更",
    "5.02": "董事/高管变动",
    "5.03": "章程或财年变更",
    "5.07": "股东大会投票结果",
    "7.01": "Reg FD 披露",
    "8.01": "其他重大事项",
}

FORM_LABELS_ZH: Mapping[str, str] = {
    "10-Q": "季报",
    "10-K": "年报",
    "20-F": "年报（外国发行人）",
    "6-K": "临时公告（外国发行人）",
    "S-1": "上市/增发注册",
    "S-3": "储架增发注册",
    "SC 13D": "持股超 5%（主动型股东）",
    "SC 13D/A": "主动型股东持股变动",
    "SCHEDULE 13D": "持股超 5%（主动型股东）",
    "SCHEDULE 13D/A": "主动型股东持股变动",
}
OFFERING_PREFIXES = ("424B",)
# Banks file 424B2 structured-note supplements daily; they are not stock catalysts.
SKIPPED_FORMS = frozenset({"424B2"})
EVENT_FORMS = frozenset({"8-K", "8-K/A", "6-K"})
OFFERING_LABEL = "发行说明书（增发或发债）"


def _priority(form: str) -> int:
    """Lower is shown first when there are more filings than slots."""
    if form in EVENT_FORMS:
        return 0
    if form.startswith(OFFERING_PREFIXES) or form in {"S-1", "S-3"}:
        return 2
    return 1


def parse_cik_map(payload: Any) -> dict[str, int]:
    """SEC tickers -> CIK, with share classes in dot form (BRK-B -> BRK.B)."""
    rows = payload.values() if isinstance(payload, Mapping) else ()
    return {str(r["ticker"]).upper().replace("-", "."): int(r["cik_str"]) for r in rows}


def form_labels(form: str, items: Sequence[str]) -> tuple[str, ...]:
    if form == "6-K":
        return ("临时公告（外国发行人）",)
    if form in EVENT_FORMS:
        return tuple(ITEM_LABELS_ZH[i] for i in items if i in ITEM_LABELS_ZH)
    if form.startswith(OFFERING_PREFIXES):
        return (OFFERING_LABEL,)
    label = FORM_LABELS_ZH.get(form)
    return (label,) if label else ()


def _shown(form: str) -> bool:
    if form in SKIPPED_FORMS:
        return False
    return form in EVENT_FORMS or form.startswith(OFFERING_PREFIXES) or form in FORM_LABELS_ZH


def parse_filings(payload: Any, since: date) -> tuple[Filing, ...]:
    recent = payload["filings"]["recent"]
    cik = int(payload["cik"])
    out: list[Filing] = []
    seen: set[tuple[str, date, tuple[str, ...]]] = set()
    for i, form in enumerate(recent["form"]):
        filed = date.fromisoformat(recent["filingDate"][i])
        if filed < since or not _shown(form):
            continue
        items = tuple(x.strip() for x in str(recent["items"][i] or "").split(",") if x.strip())
        labels = form_labels(form, items)
        if form in EVENT_FORMS and not labels:
            continue  # an 8-K with only boilerplate items
        if (form, filed, labels) in seen:
            continue  # e.g. several 424B3 supplements filed the same day
        seen.add((form, filed, labels))
        url = ARCHIVE_URL.format(
            cik=cik,
            accession=str(recent["accessionNumber"][i]).replace("-", ""),
            document=recent["primaryDocument"][i],
        )
        out.append(Filing(form, filed, items, labels, url))
    # Keep the most relevant (8-K first), then show them newest first.
    kept = sorted(out, key=lambda f: (_priority(f.form), -f.filed.toordinal()))[:MAX_FILINGS]
    return tuple(sorted(kept, key=lambda f: f.filed, reverse=True))


def fetch_cik_map(
    client: httpx.Client, user_agent: str, policy: RetryPolicy = DEFAULT_POLICY
) -> dict[str, int]:
    payload = request_json(
        client, "GET", TICKERS_URL, headers={"User-Agent": user_agent}, policy=policy
    )
    return parse_cik_map(payload)


def fetch_filings(
    client: httpx.Client,
    cik: int,
    since: date,
    user_agent: str,
    policy: RetryPolicy = DEFAULT_POLICY,
) -> tuple[Filing, ...]:
    payload = request_json(
        client,
        "GET",
        SUBMISSIONS_URL.format(cik=cik),
        headers={"User-Agent": user_agent},
        policy=policy,
    )
    return parse_filings(payload, since)
