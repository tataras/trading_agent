"""
data/collector.py — Warstwa 1: Pobieranie danych rynkowych

Pobiera dane OHLCV (Open/High/Low/Close/Volume) z Binance public API
i oblicza wskaźniki techniczne. Nie wymaga żadnego klucza API.

OHLCV = Open, High, Low, Close, Volume
     Open  — cena otwarcia świecy
     High  — najwyższa cena w interwale
     Low   — najniższa cena w interwale
     Close — cena zamknięcia (najważniejsza)
     Volume— wolumen obrotu
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests


@dataclass
class MarketSnapshot:
    """Kompletny snapshot rynku w danej chwili — to co trafi do promptu."""
    symbol: str
    price: float           # aktualna cena
    change_pct_1h: float   # zmiana % w ostatniej godzinie
    change_pct_24h: float  # zmiana % w ostatnich 24h
    volume_24h: float      # wolumen 24h w USD
    volume_ratio: float    # wolumen ostatniej świecy / średnia 20 świec (>1 = ponadnorma)

    # Wskaźniki techniczne
    rsi_14: float          # RSI(14): <30=wyprzedany, >70=wykupiony
    sma_20: float          # Średnia ruchoma 20 świec
    sma_50: float          # Średnia ruchoma 50 świec
    trend: str             # "bullish" / "bearish" / "sideways"

    # Ostatnie 5 świec jako kontekst
    last_candles_summary: str

    # Metadane
    exchange: str = "Binance"
    timeframe: str = "1h"


class MarketDataCollector:
    """
    Pobiera dane z Binance public REST API albo z wybranego demo brokera.
    Endpoint Binance /api/v3/klines nie wymaga uwierzytelnienia.

    Tryb demo: ustaw demo_mode=True w config lub gdy API niedostępne.
    """

    BASE_URL = "https://api.binance.com"

    def __init__(self, config):
        self.cfg = config
        self.base_url = config.binance_base_url.rstrip("/")
        self.oanda_base_url = config.oanda_base_url.rstrip("/")
        self.exante_md_base_url = config.exante_md_base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def fetch(self) -> MarketSnapshot:
        """Pobierz dane — z API lub z generatora demo."""
        source = self.cfg.market_data_source

        if source == "demo":
            return self._generate_demo_snapshot()

        if source == "oanda":
            return self._fetch_oanda()

        if source == "exante":
            return self._fetch_exante()

        if source != "binance":
            raise ValueError(
                f"Nieznane MARKET_DATA_SOURCE='{source}'. Dozwolone: binance, oanda, exante, demo."
            )

        try:
            return self._fetch_live()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"API niedostępne ({e}). Używam trybu demo."
            )
            return self._generate_demo_snapshot()

    def _fetch_oanda(self) -> MarketSnapshot:
        """Pobierz swiece forex z OANDA practice REST API."""
        if not self.cfg.oanda_access_token:
            raise ValueError("Brak OANDA_ACCESS_TOKEN w konfiguracji.")

        instrument = self._to_oanda_instrument(
            self.cfg.oanda_instrument or self.cfg.symbol
        )
        url = f"{self.oanda_base_url}/v3/instruments/{instrument}/candles"
        params = {
            "granularity": self._to_oanda_granularity(self.cfg.timeframe),
            "count": max(self.cfg.candle_limit, 60),
            "price": "M",
        }
        headers = {"Authorization": f"Bearer {self.cfg.oanda_access_token}"}
        resp = self.session.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        raw = resp.json()

        rows = []
        for candle in raw.get("candles", []):
            if not candle.get("complete", True):
                continue
            mid = candle.get("mid", {})
            rows.append(
                {
                    "open_time": pd.to_datetime(candle["time"]),
                    "open": float(mid["o"]),
                    "high": float(mid["h"]),
                    "low": float(mid["l"]),
                    "close": float(mid["c"]),
                    "volume": float(candle.get("volume", 0)),
                }
            )

        if len(rows) < 20:
            raise RuntimeError(f"OANDA zwrocila za malo swiec: {len(rows)}")

        df = pd.DataFrame(rows)
        ticker = {
            "priceChangePercent": self._compute_period_change_pct(
                df["close"], self.cfg.timeframe, 24 * 60
            ),
            "quoteVolume": float(df["volume"].tail(min(len(df), 24)).sum()),
        }
        snapshot = self._build_snapshot(df, ticker)
        snapshot.symbol = self._from_oanda_instrument(instrument)
        snapshot.exchange = "OANDA Practice"
        snapshot.timeframe = self.cfg.timeframe
        return snapshot

    def _fetch_exante(self) -> MarketSnapshot:
        """Pobierz swiece OHLC z EXANTE HTTP API demo."""
        if not self.cfg.exante_application_id or not self.cfg.exante_access_key:
            raise ValueError(
                "Brak EXANTE_APPLICATION_ID lub EXANTE_ACCESS_KEY w konfiguracji."
            )

        symbol = self.cfg.exante_symbol or self.cfg.symbol
        duration = self._timeframe_to_seconds(self.cfg.timeframe)
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=duration * max(self.cfg.candle_limit, 60))
        url = f"{self.exante_md_base_url}/3.0/ohlc/{symbol}/{duration}"
        params = {
            "from": int(start.timestamp() * 1000),
            "to": int(end.timestamp() * 1000),
            "size": max(self.cfg.candle_limit, 60),
        }
        resp = self.session.get(
            url,
            params=params,
            auth=(self.cfg.exante_application_id, self.cfg.exante_access_key),
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
        candles = raw.get("candles", raw) if isinstance(raw, dict) else raw

        rows = []
        for candle in candles:
            rows.append(
                {
                    "open_time": pd.to_datetime(candle["timestamp"], unit="ms"),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": 1.0,
                }
            )

        if len(rows) < 20:
            raise RuntimeError(f"EXANTE zwrocilo za malo swiec: {len(rows)}")

        df = pd.DataFrame(rows).sort_values("open_time")
        ticker = {
            "priceChangePercent": self._compute_period_change_pct(
                df["close"], self.cfg.timeframe, 24 * 60
            ),
            "quoteVolume": 0.0,
        }
        snapshot = self._build_snapshot(df, ticker)
        snapshot.symbol = symbol
        snapshot.exchange = "EXANTE Demo"
        snapshot.timeframe = self.cfg.timeframe
        return snapshot

    def _fetch_live(self) -> MarketSnapshot:
        """Pobierz dane na żywo z Binance."""
        df = self._fetch_klines()
        ticker = self._fetch_ticker()
        return self._build_snapshot(df, ticker)

    def _generate_demo_snapshot(self) -> MarketSnapshot:
        """
        Generator realistycznych danych demo.
        Używany gdy Binance API jest niedostępne.
        """
        import random
        from datetime import datetime, timedelta

        rng = random.Random()
        base_price = 65_000.0
        prices = [base_price]
        for _ in range(49):
            change = rng.gauss(0, 0.005)
            prices.append(prices[-1] * (1 + change))

        closes = pd.Series(prices)
        current_price = closes.iloc[-1]

        candles_lines = []
        now = datetime.now()
        for i in range(-4, 1):
            t = now + timedelta(hours=i)
            o = closes.iloc[45 + i]
            c = closes.iloc[46 + i]
            v = rng.uniform(800, 2000)
            direction = "▲" if c > o else "▼"
            candles_lines.append(
                f"  {t.strftime('%H:%M')} {direction} O:{o:.1f} C:{c:.1f} Vol:{v:.0f}"
            )

        sma_20 = closes.rolling(20).mean().iloc[-1]
        sma_50 = closes.rolling(min(50, len(closes))).mean().iloc[-1]
        rsi = self._compute_rsi(closes).iloc[-1]
        vol_ratio = round(rng.uniform(0.6, 2.5), 2)

        if current_price > sma_20 > sma_50:
            trend = "bullish"
        elif current_price < sma_20 < sma_50:
            trend = "bearish"
        else:
            trend = "sideways"

        return MarketSnapshot(
            symbol=self.cfg.symbol,
            price=round(current_price, 2),
            change_pct_1h=round(rng.uniform(-1.5, 1.5), 2),
            change_pct_24h=round(rng.uniform(-4.0, 4.0), 2),
            volume_24h=round(rng.uniform(1_500_000_000, 3_000_000_000), 0),
            volume_ratio=vol_ratio,
            rsi_14=round(rsi, 1),
            sma_20=round(sma_20, 2),
            sma_50=round(sma_50, 2),
            trend=trend,
            last_candles_summary="\n".join(candles_lines),
            exchange="Binance (DEMO)",
            timeframe=self.cfg.timeframe,
        )

    def _fetch_klines(self) -> pd.DataFrame:
        """
        Pobiera świece OHLCV.
        Każda świeca = jeden interwał czasowy (np. 1h).
        """
        url = f"{self.base_url}/api/v3/klines"
        params = {
            "symbol": self.cfg.symbol,
            "interval": self.cfg.timeframe,
            "limit": self.cfg.candle_limit,
        }
        resp = self.session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        raw = resp.json()

        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore"
        ])

        # Konwersja typów — API zwraca stringi
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = df[col].astype(float)

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        return df

    def _fetch_ticker(self) -> dict:
        """Pobiera statystyki 24h (zmiana ceny, wolumen)."""
        url = f"{self.base_url}/api/v3/ticker/24hr"
        resp = self.session.get(url, params={"symbol": self.cfg.symbol}, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _build_snapshot(self, df: pd.DataFrame, ticker: dict) -> MarketSnapshot:
        """Oblicza wskaźniki i buduje obiekt MarketSnapshot."""
        closes = df["close"]
        volumes = df["volume"]

        # ── Wskaźniki techniczne ──────────────────────────────────

        rsi = self._compute_rsi(closes, period=14).iloc[-1]
        sma_20 = closes.rolling(20).mean().iloc[-1]
        sma_50 = closes.rolling(min(50, len(closes))).mean().iloc[-1]

        # Trend: cena względem średnich
        current_price = closes.iloc[-1]
        if current_price > sma_20 > sma_50:
            trend = "bullish"
        elif current_price < sma_20 < sma_50:
            trend = "bearish"
        else:
            trend = "sideways"

        # Wolumen ostatniej świecy vs. średnia 20 świec
        vol_ratio = volumes.iloc[-1] / volumes.rolling(20).mean().iloc[-1]

        # ── Podsumowanie ostatnich 5 świec ────────────────────────
        last5 = df.tail(5)[["open_time", "open", "close", "volume"]].copy()
        candles_lines = []
        for _, row in last5.iterrows():
            direction = "▲" if row["close"] > row["open"] else "▼"
            candles_lines.append(
                f"  {row['open_time'].strftime('%H:%M')} {direction} "
                f"O:{row['open']:.1f} C:{row['close']:.1f} "
                f"Vol:{row['volume']:.0f}"
            )
        candles_summary = "\n".join(candles_lines)

        return MarketSnapshot(
            symbol=self.cfg.symbol,
            price=current_price,
            change_pct_1h=self._compute_period_change_pct(closes, self.cfg.timeframe, 60),
            change_pct_24h=float(ticker["priceChangePercent"]),
            volume_24h=float(ticker["quoteVolume"]),
            volume_ratio=round(vol_ratio, 2),
            rsi_14=round(rsi, 1),
            sma_20=round(sma_20, 2),
            sma_50=round(sma_50, 2),
            trend=trend,
            last_candles_summary=candles_summary,
            timeframe=self.cfg.timeframe,
        )

    @staticmethod
    def _compute_period_change_pct(
        closes: pd.Series,
        timeframe: str,
        period_minutes: int,
    ) -> float:
        """Policz zmiane procentowa dla zadanego okresu na podstawie swiec."""
        interval_minutes = MarketDataCollector._timeframe_to_minutes(timeframe)
        candles_back = max(1, round(period_minutes / interval_minutes))

        if len(closes) <= candles_back:
            candles_back = len(closes) - 1
        if candles_back <= 0:
            return 0.0

        previous = closes.iloc[-1 - candles_back]
        current = closes.iloc[-1]
        if previous == 0:
            return 0.0
        return round(((current - previous) / previous) * 100, 2)

    @staticmethod
    def _timeframe_to_minutes(timeframe: str) -> int:
        """Konwertuj interwal Binance (np. 5m, 1h, 1d) na minuty."""
        if not timeframe:
            return 60

        unit = timeframe[-1]
        try:
            value = int(timeframe[:-1])
        except ValueError:
            return 60

        multipliers = {
            "m": 1,
            "h": 60,
            "d": 1440,
            "w": 10080,
            "M": 43200,
        }
        return max(1, value * multipliers.get(unit, 60))

    @staticmethod
    def _timeframe_to_seconds(timeframe: str) -> int:
        return MarketDataCollector._timeframe_to_minutes(timeframe) * 60

    @staticmethod
    def _to_oanda_instrument(symbol: str) -> str:
        """Konwertuj EUR/USD, EURUSD albo EUR_USD do formatu OANDA."""
        normalized = symbol.strip().upper().replace("-", "_").replace("/", "_")
        if "_" in normalized:
            return normalized
        if len(normalized) == 6:
            return f"{normalized[:3]}_{normalized[3:]}"
        return normalized

    @staticmethod
    def _from_oanda_instrument(instrument: str) -> str:
        parts = instrument.upper().split("_", 1)
        if len(parts) == 2:
            return f"{parts[0]}/{parts[1]}"
        return instrument.upper()

    @staticmethod
    def _to_oanda_granularity(timeframe: str) -> str:
        mapping = {
            "1m": "M1",
            "5m": "M5",
            "10m": "M10",
            "15m": "M15",
            "30m": "M30",
            "1h": "H1",
            "2h": "H2",
            "3h": "H3",
            "4h": "H4",
            "6h": "H6",
            "8h": "H8",
            "12h": "H12",
            "1d": "D",
            "1w": "W",
        }
        return mapping.get(timeframe, "H1")

    @staticmethod
    def _compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
        """
        Oblicza RSI (Relative Strength Index).

        RSI mierzy siłę trendu:
         < 30 → rynek wyprzedany (potencjalny sygnał kupna)
         > 70 → rynek wykupiony (potencjalny sygnał sprzedaży)
         30-70 → strefa neutralna

        Algorytm: średnia zysków / średnia strat z ostatnich N świec.
        """
        delta = closes.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
        rs = gain / (loss + 1e-10)  # +epsilon żeby uniknąć dzielenia przez 0
        return 100 - (100 / (1 + rs))
