"""Runtime configuration from environment variables (see .env.example)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

DEX_RE = re.compile(r"^[a-z0-9]{1,16}$")
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Config:
    root: Path
    db_path: Path
    reports_dir: Path
    allowlist_path: Path
    overrides_path: Path
    denylist_path: Path
    hl_dexes: tuple[str, ...]
    expected_window_hours: float
    window_tolerance_hours: float
    top_n: int
    binance_backfill: bool
    binance_base_url: str
    hl_info_url: str
    http_timeout_seconds: float
    sec_user_agent: str
    site_data_dir: Path
    insights_cache_path: Path
    telegram_chat_id: str | None
    telegram_bot_token: str | None = field(default=None, repr=False)

    @property
    def telegram_enabled(self) -> bool:
        return self.telegram_chat_id is not None


def _path(root: Path, env: Mapping[str, str], key: str, default: str) -> Path:
    value = Path(env.get(key) or default)
    return value if value.is_absolute() else root / value


def _number(env: Mapping[str, str], key: str, default: float, *, minimum: float) -> float:
    raw = env.get(key) or str(default)
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}, got {value}")
    return value


def _integer(env: Mapping[str, str], key: str, default: int, *, minimum: int) -> int:
    raw = env.get(key) or str(default)
    if not raw.isdigit():
        raise ConfigError(f"{key} must be a whole number, got {raw!r}")
    value = int(raw)
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}, got {value}")
    return value


def _flag(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = (env.get(key) or ("1" if default else "0")).strip().lower()
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    raise ConfigError(f"{key} must be 1/0, got {raw!r}")


def _dexes(env: Mapping[str, str]) -> tuple[str, ...]:
    raw = env.get("HL_DEXES", "xyz")
    dexes = tuple(d.strip() for d in raw.split(",") if d.strip())
    if not dexes:
        raise ConfigError("HL_DEXES must name at least one HIP-3 dex")
    bad = [d for d in dexes if not DEX_RE.match(d)]
    if bad:
        raise ConfigError(f"HL_DEXES has invalid dex names: {bad}")
    return dexes


def _telegram(env: Mapping[str, str]) -> tuple[str | None, str | None]:
    chat_id = (env.get("TELEGRAM_CHAT_ID") or "").strip() or None
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip() or None
    token_file = (env.get("TELEGRAM_TOKEN_FILE") or "").strip()
    if token is None and token_file:
        path = Path(token_file).expanduser()
        if not path.is_file():
            raise ConfigError(f"TELEGRAM_TOKEN_FILE not found: {path}")
        token = (dotenv_values(path).get("TELEGRAM_BOT_TOKEN") or "").strip() or None
    if chat_id and not token:
        raise ConfigError("TELEGRAM_CHAT_ID is set but no bot token was found")
    return chat_id, token


def load_config(root: Path, env: Mapping[str, str]) -> Config:
    chat_id, token = _telegram(env)
    return Config(
        root=root,
        db_path=_path(root, env, "PERP_MONITOR_DB", "data/monitor.db"),
        reports_dir=_path(root, env, "PERP_MONITOR_REPORTS_DIR", "reports"),
        allowlist_path=_path(root, env, "PERP_MONITOR_ALLOWLIST", "assets/stocks_allowlist.txt"),
        overrides_path=_path(root, env, "PERP_MONITOR_OVERRIDES", "assets/symbol_overrides.toml"),
        denylist_path=_path(root, env, "PERP_MONITOR_DENYLIST", "assets/crypto_denylist.txt"),
        hl_dexes=_dexes(env),
        expected_window_hours=_number(env, "EXPECTED_WINDOW_HOURS", 8, minimum=0.1),
        window_tolerance_hours=_number(env, "WINDOW_TOLERANCE_HOURS", 1, minimum=0),
        top_n=_integer(env, "TOP_N", 10, minimum=1),
        binance_backfill=_flag(env, "BINANCE_BACKFILL", True),
        binance_base_url=env.get("BINANCE_BASE_URL") or "https://fapi.binance.com",
        hl_info_url=env.get("HL_INFO_URL") or "https://api.hyperliquid.xyz/info",
        http_timeout_seconds=_number(env, "HTTP_TIMEOUT_SECONDS", 15, minimum=1),
        sec_user_agent=env.get("SEC_USER_AGENT") or "perp-oi-funding-monitor admin@example.com",
        site_data_dir=_path(root, env, "SITE_DATA_DIR", "web/data"),
        insights_cache_path=_path(root, env, "INSIGHTS_CACHE", "data/cache/insights.json"),
        telegram_chat_id=chat_id,
        telegram_bot_token=token,
    )
