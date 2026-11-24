"""Chinese one-liners for the insight cards: a headline plus one answer per question.

Pure functions over already-collected data, so every sentence is testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from perp_monitor.insights.models import (
    Catalysts,
    Fundamentals,
    FundingPattern,
    FundingPersistence,
    Profile,
    ShortInterest,
    ShortLevel,
    Side,
    SpotStats,
    VolumeTier,
    VolumeVerdict,
)

EARNINGS_HINT_DAYS = (-3, 7)  # earnings this close make the headline
FILING_HINT_DAYS = 7
BIG_MOVE_1D = 0.05
MAX_WHAT = 240
HINT_TITLE_CHARS = 56
NOTHING_FOUND = "近 7 天没有找到明显的新闻、公告或财报。"
SENTENCE_END = re.compile(r"[.!?]\s+(?=[A-Z])")

VOLUME_LEAD = {
    VolumeTier.MEANINGFUL: ("量有意义", "规模足够，费率能反映真实的多空需求。"),
    VolumeTier.THIN: ("量偏薄", "有一定参考价值，但容易被单个大户左右。"),
    VolumeTier.NOISE: ("量太小", "几笔单就能推动费率，参考意义有限。"),
}
SHORT_LEAD = {
    ShortLevel.HIGH: "热门做空股",
    ShortLevel.ELEVATED: "空头偏多",
    ShortLevel.MODERATE: "空头中等",
    ShortLevel.LOW: "基本没人空",
    ShortLevel.UNKNOWN: "空头持仓",
}


@dataclass(frozen=True, slots=True)
class NarrativeInput:
    ticker: str
    side: Side
    funding_8h: float
    funding_apr: float
    profile: Profile | None
    fundamentals: Fundamentals | None
    spot: SpotStats | None
    catalysts: Catalysts
    short_interest: ShortInterest | None
    short_level: ShortLevel
    persistence: FundingPersistence
    volume: VolumeVerdict
    today: date


# ---------- number formatting ----------


def _zh_amount(x: float) -> str:
    a = abs(x)
    if a < 1e4:
        return f"{a:,.0f}"
    if a < 1e6:
        return f"{a / 1e4:.1f}万"
    if a < 1e8:
        return f"{a / 1e4:,.0f}万"
    if a < 1e12:
        return f"{a / 1e8:,.1f}亿"
    return f"{a / 1e12:.2f}万亿"


def usd_zh(x: float | None) -> str:
    if x is None:
        return "—"
    return ("-" if x < 0 else "") + "$" + _zh_amount(x)


def count_zh(x: float) -> str:
    return ("-" if x < 0 else "") + _zh_amount(x)


def rate_pct(x: float) -> str:
    return f"{x * 100:+.3f}%"


def pct_signed(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:+.1f}%"


def _small_pct(x: float) -> str:
    if x < 0.0001:
        return "<0.01%"
    return f"{x * 100:.2f}%" if x < 0.001 else f"{x * 100:.1f}%"


def _md(d: date) -> str:
    return f"{d.month:02d}/{d.day:02d}"


WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
TIMING_ZH = {"bmo": "盘前", "amc": "盘后"}


def _md_wd(d: date) -> str:
    """Month/day with the weekday in Chinese, e.g. 11/24 (Tuesday)."""
    return f"{_md(d)}（{WEEKDAYS[d.weekday()]}）"


# ---------- headline ----------


def _pattern_phrase(p: FundingPersistence, side: Side) -> str | None:
    neg = side is Side.NEGATIVE
    return {
        FundingPattern.PERSISTENT: "持续偏空" if neg else "持续偏多",
        FundingPattern.SPIKE: "单期急跌" if neg else "单期急升",
        FundingPattern.MIXED: "多空来回",
    }.get(p.pattern)


def _catalyst_hint(n: NarrativeInput) -> str | None:
    cat = n.catalysts
    if cat.earnings is not None and cat.earnings.confirmed:
        days = (cat.earnings.day - n.today).days
        if EARNINGS_HINT_DAYS[0] <= days <= EARNINGS_HINT_DAYS[1]:
            timing = TIMING_ZH.get(cat.earnings.timing or "", "")
            return f"财报 {_md(cat.earnings.day)}{' ' + timing if timing else ''}"
    recent = [f for f in cat.filings if (n.today - f.filed).days <= FILING_HINT_DAYS]
    if recent:
        f = recent[0]
        return f"{_md(f.filed)} {f.form}：{'、'.join(f.labels_zh)}"
    if n.spot is not None and n.spot.ret_1d is not None and abs(n.spot.ret_1d) >= BIG_MOVE_1D:
        return f"现货 1 日 {pct_signed(n.spot.ret_1d)}"
    if cat.news:
        return f"新闻：{_clip(cat.news[0].title, HINT_TITLE_CHARS)}"
    return None


def _clip(text: str, limit: int) -> str:
    """Cut at a word boundary and mark the cut."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return f"{cut}…"


def headline(n: NarrativeInput) -> str:
    lead = f"{n.ticker} 资金费率 {rate_pct(n.funding_8h)}/8h（年化 {n.funding_apr * 100:+.0f}%）"
    parts = [
        _pattern_phrase(n.persistence, n.side),
        VOLUME_LEAD[n.volume.tier][0],
        _catalyst_hint(n),
    ]
    return " · ".join([lead, *(p for p in parts if p)])


# ---------- answers ----------


def _first_sentence(text: str) -> str:
    for match in SENTENCE_END.finditer(text):
        if match.start() >= 40:
            text = text[: match.start() + 1]
            break
    return text if len(text) <= MAX_WHAT else text[: MAX_WHAT - 1] + "…"


def english_summary(p: Profile | None) -> str | None:
    """First sentence of the English description, shown under the Chinese one."""
    return _first_sentence(p.description) if p is not None and p.description else None


def _fundamentals_line(f: Fundamentals | None) -> str | None:
    if f is None:
        return None
    parts = []
    if f.market_cap_usd:
        parts.append(f"市值 {usd_zh(f.market_cap_usd)}")
    if f.revenue_ttm_usd:
        label = "近四季营收" if f.quarters >= 4 else f"近 {f.quarters} 季营收"
        parts.append(f"{label} {usd_zh(f.revenue_ttm_usd)}")
    if f.gross_margin is not None:
        parts.append(f"毛利率 {f.gross_margin:.1%}")
    if not parts:
        return None
    period = f"（财报截至 {f.period_end.year}/{f.period_end.month:02d}）" if f.period_end else ""
    return "，".join(parts) + period + "。"


def _what(p: Profile | None, f: Fundamentals | None) -> str:
    if p is None:
        return "暂无公司资料。"
    kind = p.industry or p.sector
    if p.name_zh and p.description_zh:
        lead = f"{p.name_zh}（{p.name}）：{p.description_zh.rstrip('。')}。"
    else:
        lead = (f"{p.name} · {kind}。" if kind else f"{p.name}。") + (
            _first_sentence(p.description) if p.description else ""
        )
    money = _fundamentals_line(f)
    if money is None:
        money = "暂无财务数据（外国发行人、基金或新上市公司常见）。"
    return f"{lead}{money}"


def _funding(n: NarrativeInput) -> str:
    neg = n.side is Side.NEGATIVE
    payer = "空头每 8 小时付给多头" if neg else "多头每 8 小时付给空头"
    sign_word = "负" if neg else "正"
    crowd = "空头" if neg else "多头"
    head = f"{payer} {abs(n.funding_8h) * 100:.3f}%（年化 {abs(n.funding_apr) * 100:.0f}%）。"
    p = n.persistence
    share = f"{(p.same_sign_share or 0):.0%}"
    if p.pattern is FundingPattern.PERSISTENT:
        mean = rate_pct(p.mean_8h or 0)
        tail = (
            f"过去 7 天 {len(p.buckets)} 个 8h 时段里 {share} 同为{sign_word}，"
            f"均值 {mean}，是持续的{crowd}拥挤。"
        )
    elif p.pattern is FundingPattern.SPIKE:
        times = f"，当前值是平均水平的 {p.multiple_of_mean:.0f} 倍" if p.multiple_of_mean else ""
        tail = f"过去 7 天只有 {share} 的时段为{sign_word}{times}，属于单期异动。"
    elif p.pattern is FundingPattern.MIXED:
        tail = f"过去 7 天正负交替（同向时段占 {share}），方向不稳定。"
    else:
        tail = "历史数据不足，暂无法判断是否持续。"
    return head + tail


def _volume(v: VolumeVerdict) -> str:
    lead, conclusion = VOLUME_LEAD[v.tier]
    body = f"OI {usd_zh(v.oi_usd)}，24h 成交 {usd_zh(v.volume_24h_usd)}"
    if v.oi_to_spot_adv is not None:
        body += f"，OI 相当于现货日均成交额的 {_small_pct(v.oi_to_spot_adv)}"
    return f"{lead}：{body}。{conclusion}"


def _spot_moves(s: SpotStats | None) -> str | None:
    if s is None:
        return None
    moves = [
        f"{label} {pct_signed(value)}"
        for label, value in (("1 日", s.ret_1d), ("5 日", s.ret_5d), ("20 日", s.ret_20d))
        if value is not None
    ]
    return "现货 " + "，".join(moves) if moves else None


def _when(days: int) -> str:
    return "今天" if days == 0 else (f"{days} 天后" if days > 0 else f"{-days} 天前")


def _earnings(cat: Catalysts, today: date) -> str | None:
    e = cat.earnings
    if e is None:
        return None
    days = (e.day - today).days
    if not e.confirmed:
        if days < 0:
            return "下次财报按惯例应在近期，日期还没公布"
        return f"下次财报预计 {_md_wd(e.day)}前后（按上次财报日推算，未确认）"
    timing = TIMING_ZH.get(e.timing or "")
    verb = "发财报" if days >= 0 else "已发财报"
    note = "" if timing else "，盘前盘后未定"
    return f"{_md_wd(e.day)}{timing or ''}{verb}（{_when(days)}{note}）"


def _last_earnings(cat: Catalysts) -> str | None:
    e = cat.last_earnings
    if e is None:
        return None
    text = f"上次财报 {_md_wd(e.reported)}"
    if e.fiscal_quarter:
        text += f"（{e.fiscal_quarter} 季度）"
    if e.eps is not None and e.consensus is not None:
        text += f" EPS {e.eps:g} vs 预期 {e.consensus:g}"
        if e.surprise_pct is not None:
            beat = "超预期" if e.surprise_pct >= 0 else "低于预期"
            text += f"，{beat} {abs(e.surprise_pct):.1f}%"
    return text


def _catalyst(n: NarrativeInput) -> str:
    cat = n.catalysts
    events = [
        _earnings(cat, n.today),
        _last_earnings(cat),
        *(f"{_md(f.filed)} {f.form} {'、'.join(f.labels_zh)}" for f in cat.filings[:3]),
    ]
    if cat.news:
        events.append(f"近 7 天 {len(cat.news)} 条新闻，最新：{cat.news[0].title}")
    found = [e for e in events if e]
    moves = _spot_moves(n.spot)
    if not found:
        return f"{moves}。{NOTHING_FOUND}" if moves else NOTHING_FOUND
    return "；".join([m for m in (moves,) if m] + found) + "。"


def _short(si: ShortInterest | None, level: ShortLevel, spot: SpotStats | None) -> str:
    if si is None:
        return "暂无空头持仓数据。"
    parts = [f"空头 {count_zh(si.shares)} 股"]
    if si.pct_of_shares is not None:
        multi = spot is not None and spot.multi_class
        basis = "占全部类别总股本" if multi else "占总股本"
        caveat = "（多类股，该类占比会更高）" if multi else ""
        parts.append(f"{basis} {si.pct_of_shares:.1%}{caveat}")
    if si.days_to_cover is not None:
        parts.append(f"回补 {si.days_to_cover:.1f} 天")
    if si.change_pct is not None:
        parts.append(f"环比 {pct_signed(si.change_pct)}")
    return f"{SHORT_LEAD[level]}：{'，'.join(parts)}（{_md(si.settlement_date)} 结算）。"


def answers(n: NarrativeInput) -> tuple[tuple[str, str], ...]:
    return (
        ("what", _what(n.profile, n.fundamentals)),
        ("funding", _funding(n)),
        ("catalyst", _catalyst(n)),
        ("volume", _volume(n.volume)),
        ("short", _short(n.short_interest, n.short_level, n.spot)),
    )
