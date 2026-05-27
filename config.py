"""
Central configuration for the trading agent.

Values are loaded from environment variables and, if present, from a local
.env file. Real credentials should stay in .env and never be committed.
"""

import os
from dataclasses import dataclass


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader without extra dependencies."""
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


_load_dotenv()


@dataclass
class Config:
    # Gemini API
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # Instrument
    symbol: str = os.getenv("SYMBOL", "BTCUSDT")
    timeframe: str = os.getenv("TIMEFRAME", "1m")
    candle_limit: int = _get_int("CANDLE_LIMIT", 50)

    # Market data source: binance, oanda, exante, demo
    market_data_source: str = os.getenv("MARKET_DATA_SOURCE", "exante").lower()
    binance_base_url: str = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")

    # Agent loop
    interval_seconds: int = _get_int("INTERVAL_SECONDS", 60)

    # Risk management
    max_position_pct: float = _get_float("MAX_POSITION_PCT", 0.05)
    stop_loss_pct: float = _get_float("STOP_LOSS_PCT", 0.02)
    max_daily_loss_pct: float = _get_float("MAX_DAILY_LOSS_PCT", 0.06)
    max_open_positions: int = _get_int("MAX_OPEN_POSITIONS", 3)

    # Starting portfolio for mock mode and fallbacks
    initial_capital_usd: float = _get_float("INITIAL_CAPITAL_USD", 100_000.0)

    # Broker mode: mock, alpaca_paper, oanda_demo, exante_demo
    broker_mode: str = os.getenv("BROKER_MODE", "exante_demo")

    # Alpaca Paper Trading
    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", os.getenv("APCA_API_KEY_ID", ""))
    alpaca_secret_key: str = os.getenv(
        "ALPACA_SECRET_KEY",
        os.getenv("APCA_API_SECRET_KEY", ""),
    )
    alpaca_base_url: str = os.getenv(
        "ALPACA_BASE_URL",
        "https://paper-api.alpaca.markets",
    )
    alpaca_symbol: str = os.getenv("ALPACA_SYMBOL", "")
    alpaca_time_in_force: str = os.getenv("ALPACA_TIME_IN_FORCE", "gtc")
    alpaca_min_order_notional: float = _get_float("ALPACA_MIN_ORDER_NOTIONAL", 10.0)

    # OANDA Practice / Demo
    oanda_account_id: str = os.getenv("OANDA_ACCOUNT_ID", "")
    oanda_access_token: str = os.getenv("OANDA_ACCESS_TOKEN", "")
    oanda_base_url: str = os.getenv(
        "OANDA_BASE_URL",
        "https://api-fxpractice.oanda.com",
    )
    oanda_instrument: str = os.getenv("OANDA_INSTRUMENT", "")
    oanda_min_order_units: int = _get_int("OANDA_MIN_ORDER_UNITS", 1)

    # EXANTE HTTP API Demo
    exante_application_id: str = os.getenv("EXANTE_APPLICATION_ID", "")
    exante_access_key: str = os.getenv("EXANTE_ACCESS_KEY", "")
    exante_account_id: str = os.getenv("EXANTE_ACCOUNT_ID", "")
    exante_trade_base_url: str = os.getenv(
        "EXANTE_TRADE_BASE_URL",
        "https://api-demo.exante.eu/trade",
    )
    exante_md_base_url: str = os.getenv(
        "EXANTE_MD_BASE_URL",
        "https://api-demo.exante.eu/md",
    )
    exante_symbol: str = os.getenv("EXANTE_SYMBOL", "AAPL.NASDAQ")
    exante_summary_currency: str = os.getenv("EXANTE_SUMMARY_CURRENCY", "EUR")
    exante_order_duration: str = os.getenv("EXANTE_ORDER_DURATION", "day")
    exante_min_order_quantity: float = _get_float("EXANTE_MIN_ORDER_QUANTITY", 1.0)

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: str = os.getenv("LOG_FILE", "agent.log")
