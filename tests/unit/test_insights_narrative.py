from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from perp_monitor.insights.models import (
    Catalysts,
    EarningsDate,
    Filing,
    Fundamentals,
    FundingPattern,
    FundingPersistence,
    FundingPoint,
    LastEarnings,
    NewsItem,
    Profile,
    ShortInterest,
    ShortLevel,
    Side,
    SpotStats,
    VolumeTier,
    VolumeVerdict,
)
from perp_monitor.insights.narrative import (
    NarrativeInput,
    answers,
    headline,
    pct_signed,
    rate_pct,
    usd_zh,
)

NOW = datetime(2026, 11, 24, 4, 0, tzinfo=UTC)


def persistence(pattern: FundingPattern, share: float | None = 0.0) -> FundingPersistence:
    pts = tuple(FundingPoint(NOW - timedelta(hours=8 * i), 0.0) for i in range(3))
    return FundingPersistence(pattern, pts, share, 0.0, None)


def base(**overrides: object) -> NarrativeInput:
    values: dict[str, object] = {
        "ticker": "FWDI",
        "side": Side.NEGATIVE,
        "funding_8h": -0.00341942,
        "funding_apr": -3.744,
        "profile": Profile(
            "Forward Industries, Inc.",
            "Finance",
            "Finance: Consumer Services",
            "Forward Industries is a Solana treasury company. It buys SOL.",
        ),
        "fundamentals": None,
        "spot": SpotStats(date(2026, 11, 23), 3.7, -0.061, 0.12, None, 1.2e7, 8e7),
        "catalysts": Catalysts(),
        "short_interest": None,
        "short_level": ShortLevel.UNKNOWN,
        "persistence": persistence(FundingPattern.SPIKE),
        "volume": VolumeVerdict(VolumeTier.THIN, 362_000, 2_746_000, 0.03),
        "today": NOW.date(),
    }
    values.update(overrides)
    return NarrativeInput(**values)  # type: ignore[arg-type]


class TestFormatting:
    def test_usd_zh(self) -> None:
        assert usd_zh(950) == "$950"
        assert usd_zh(362_000) == "$36.2万"
        assert usd_zh(1_551_445) == "$155万"
        assert usd_zh(41_119_000) == "$4,112万"
        assert usd_zh(1.62e9) == "$16.2亿"
        assert usd_zh(None) == "—"

    def test_tiny_spot_ratio(self) -> None:
        v = VolumeVerdict(VolumeTier.NOISE, 28_000, 15_000, 0.00002)
        assert "<0.01%" in dict(answers(base(volume=v)))["volume"]

    def test_rate_and_pct(self) -> None:
        assert rate_pct(-0.00341942) == "-0.342%"
        assert pct_signed(0.1234) == "+12.3%"
        assert pct_signed(-0.061) == "-6.1%"
        assert pct_signed(None) == "—"


class TestHeadline:
    def test_spike_thin_with_filing(self) -> None:
        filing = Filing(
            "8-K", date(2026, 11, 19), ("1.01",), ("签订重大协议",), "https://sec.gov/x"
        )
        text = headline(base(catalysts=Catalysts(filings=(filing,))))
        assert text.startswith("FWDI 资金费率 -0.342%/8h（年化 -374%）")
        assert "单期急跌" in text
        assert "量偏薄" in text
        assert "11/19 8-K：签订重大协议" in text

    def test_persistent_positive_meaningful(self) -> None:
        text = headline(
            base(
                ticker="NBIS",
                side=Side.POSITIVE,
                funding_8h=0.0008,
                funding_apr=0.876,
                persistence=persistence(FundingPattern.PERSISTENT, 0.9),
                volume=VolumeVerdict(VolumeTier.MEANINGFUL, 4.1e7, 7.2e7, 0.02),
            )
        )
        assert "持续偏多" in text and "量有意义" in text

    def test_earnings_beats_big_move(self) -> None:
        cat = Catalysts(earnings=EarningsDate(date(2026, 11, 25), "amc"))
        assert "财报 11/25" in headline(base(catalysts=cat))

    def test_news_hint_is_clipped_at_a_word(self) -> None:
        title = "Natural Gas Rises for a Third Straight Week as Winter Nears and Storage Falls"
        news = NewsItem(title, "https://a.com/x", NOW, "a.com", "")
        text = headline(base(spot=None, catalysts=Catalysts(news=(news,))))
        assert text.endswith("新闻：Natural Gas Rises for a Third Straight Week as Winter…")

    def test_big_spot_move_when_no_event(self) -> None:
        assert "现货 1 日 -6.1%" in headline(base())


class TestAnswers:
    def test_keys_in_display_order(self) -> None:
        keys = [k for k, _ in answers(base())]
        assert keys == ["what", "funding", "catalyst", "volume", "short"]

    def test_what_uses_first_sentence(self) -> None:
        what = dict(answers(base()))["what"]
        assert what.startswith("Forward Industries, Inc.")
        assert "Solana treasury company." in what
        assert "It buys SOL" not in what

    def test_what_without_profile(self) -> None:
        assert dict(answers(base(profile=None)))["what"] == "暂无公司资料。"

    def test_funding_spike_text(self) -> None:
        text = dict(answers(base()))["funding"]
        assert text.startswith("空头每 8 小时付给多头 0.342%")
        assert "单期异动" in text

    def test_funding_insufficient(self) -> None:
        p = FundingPersistence(FundingPattern.INSUFFICIENT, (), None, None, None)
        assert "历史数据不足" in dict(answers(base(persistence=p)))["funding"]

    def test_volume_noise(self) -> None:
        v = VolumeVerdict(VolumeTier.NOISE, 67_000, 358_000, 0.0001)
        text = dict(answers(base(volume=v)))["volume"]
        assert text.startswith("量太小")
        assert "$6.7万" in text and "0.01%" in text

    def test_catalyst_lists_events(self) -> None:
        news = NewsItem("Forward adds SOL", "https://a.com/x", NOW - timedelta(days=1), "a.com", "")
        filing = Filing(
            "424B5", date(2026, 11, 9), (), ("发行说明书（增发或发债）",), "https://sec.gov/y"
        )
        cat = Catalysts(
            news=(news,), filings=(filing,), earnings=EarningsDate(date(2026, 12, 8), None)
        )
        text = dict(answers(base(catalysts=cat)))["catalyst"]
        assert "现货 1 日 -6.1%" in text
        assert "12/08（周二）发财报（14 天后，盘前盘后未定）" in text
        assert "11/09 424B5 发行说明书（增发或发债）" in text
        assert "1 条新闻" in text

    def test_catalyst_nothing_found(self) -> None:
        text = dict(answers(base(spot=None)))["catalyst"]
        assert text == "近 7 天没有找到明显的新闻、公告或财报。"

    def test_short_high(self) -> None:
        si = ShortInterest(date(2026, 10, 30), 24_163_022, 25_538_849, 5.37, 0.189)
        text = dict(answers(base(short_interest=si, short_level=ShortLevel.HIGH)))["short"]
        assert text.startswith("热门做空股")
        assert "18.9%" in text and "5.4 天" in text and "-5.4%" in text and "10/30" in text

    def test_short_multi_class_caveat(self) -> None:
        si = ShortInterest(date(2026, 10, 30), 65_093_337, 66_937_592, 6.2, 0.063)
        spot = SpotStats(date(2026, 11, 23), 68.0, 0.0, 0.0, 0.0, 1e9, 1.036e9, multi_class=True)
        text = dict(answers(base(short_interest=si, short_level=ShortLevel.MODERATE, spot=spot)))[
            "short"
        ]
        assert "占全部类别总股本 6.3%（多类股，该类占比会更高）" in text

    def test_short_unknown(self) -> None:
        assert dict(answers(base()))["short"] == "暂无空头持仓数据。"


class TestCompanyAndEarnings:
    def test_usd_zh_trillions(self) -> None:
        assert usd_zh(4.3e12) == "$4.30万亿"
        assert usd_zh(3.03e11) == "$3,030亿"
        assert usd_zh(2.9e10) == "$290.0亿"

    def test_what_in_chinese_with_fundamentals(self) -> None:
        profile = Profile(
            "NVIDIA Corporation",
            "Technology",
            "Semiconductors",
            "NVIDIA designs GPUs.",
            "英伟达",
            "全球最大的 AI 芯片设计公司。",
        )
        f = Fundamentals(4.3e12, 2.0e11, 1.5e11, date(2026, 7, 26), 4)
        what = dict(answers(base(profile=profile, fundamentals=f)))["what"]
        assert what.startswith("英伟达（NVIDIA Corporation）：全球最大的 AI 芯片设计公司。")
        assert "市值 $4.30万亿" in what and "近四季营收 $2,000亿" in what
        assert "毛利率 75.0%" in what and "财报截至 2026/07" in what

    def test_what_without_financials_says_so(self) -> None:
        assert "暂无财务数据" in dict(answers(base()))["what"]

    def test_confirmed_earnings_with_weekday_and_timing(self) -> None:
        cat = Catalysts(earnings=EarningsDate(date(2026, 11, 24), "bmo"))
        text = dict(answers(base(catalysts=cat)))["catalyst"]
        assert "11/24（周二）盘前发财报（今天）" in text
        assert "财报 11/24 盘前" in headline(base(catalysts=cat))

    def test_estimated_earnings_is_marked(self) -> None:
        cat = Catalysts(earnings=EarningsDate(date(2027, 2, 23), None, confirmed=False))
        text = dict(answers(base(catalysts=cat)))["catalyst"]
        assert "下次财报预计 02/23（周二）前后（按上次财报日推算，未确认）" in text
        assert "财报" not in headline(base(catalysts=cat))  # estimates never make the headline

    def test_last_earnings_surprise(self) -> None:
        last = LastEarnings(date(2026, 9, 1), "Jul 2026", 1.45, 1.39, 4.32)
        text = dict(answers(base(catalysts=Catalysts(last_earnings=last))))["catalyst"]
        assert "上次财报 09/01（周二）（Jul 2026 季度） EPS 1.45 vs 预期 1.39，超预期 4.3%" in text


def test_spike_multiple_only_when_meaningful() -> None:
    pts = tuple(FundingPoint(NOW - timedelta(hours=8 * i), 0.0) for i in range(3))
    low = FundingPersistence(FundingPattern.SPIKE, pts, 0.1, 0.0, 1.2)
    high = FundingPersistence(FundingPattern.SPIKE, pts, 0.1, 0.0, 6.0)
    assert "倍" not in dict(answers(base(persistence=low)))["funding"]
    assert "平均水平的 6 倍" in dict(answers(base(persistence=high)))["funding"]
