"""
config.py — Centralna konfiguracja agenta
Wszystkie parametry systemu w jednym miejscu. Zmień tutaj, nie w kodzie.
"""

import os
from dataclasses import dataclass


def _load_dotenv(path: str = ".env") -> None:
    """Minimalny loader .env bez dodatkowych zaleznosci."""
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass
class Config:
    # Gemini API
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

    # ─── Instrument ───────────────────────────────────────────────
    # Format dla krypto: "BTCUSDT", dla forex: "EUR/USD"
    symbol: str = "BTCUSDT"
    timeframe: str = "1m"       # interwał świec: 1m, 5m, 15m, 1h, 4h, 1d
    candle_limit: int = 50      # ile ostatnich świec wysyłamy do analizy

    # ─── Pętla agenta ─────────────────────────────────────────────
    # Jak często agent podejmuje decyzję (w sekundach).
    # 300 = co 5 minut. Dla timeframe=1h sensowne jest 3600.
    interval_seconds: int = 60  # krótki interwał na potrzeby testów

    # ─── Zarządzanie ryzykiem ──────────────────────────────────────
    max_position_pct: float = 0.05    # max 5% kapitału na jedną pozycję
    stop_loss_pct: float = 0.02       # stop-loss: zamknij gdy strata > 2%
    max_daily_loss_pct: float = 0.06  # wyłącz agenta gdy dzienna strata > 6%
    max_open_positions: int = 3       # max 3 otwarte pozycje jednocześnie

    # ─── Portfolio startowe ───────────────────────────────────────
    initial_capital_usd: float = 100_000.0

    # ─── Tryb brokera ─────────────────────────────────────────────
    # "mock"             — czysta symulacja w pamięci
    # "alpaca_paper"     — Alpaca Paper Trading (wymaga kluczy Alpaca)
    # "binance_testnet"  — Binance Testnet (wymaga kluczy testowych)
    # "oanda_demo"       — OANDA konto practice (wymaga kluczy)
    broker_mode: str = os.getenv("BROKER_MODE", "alpaca_paper")

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
    alpaca_min_order_notional: float = float(
        os.getenv("ALPACA_MIN_ORDER_NOTIONAL", "10")
    )

    # ─── Logowanie ────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "agent.log"   # "" = tylko konsola
