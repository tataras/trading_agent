"""
Build prompts for the trading decision model.

The prompt is intentionally broker-agnostic, so the same agent can analyze
crypto data from Binance or forex data from OANDA.
"""

from data.collector import MarketSnapshot


SYSTEM_PROMPT = """Jestes precyzyjnym asystentem handlowym analizujacym instrument finansowy.
Twoje zadanie: na podstawie dostarczonych danych rynkowych podjac jedna z trzech decyzji:
BUY, SELL lub HOLD.

ZASADY DZIALANIA:
1. Analizuj TYLKO dostarczone dane - nie spekuluj na podstawie wiedzy spoza promptu.
2. Badz konserwatywny - w przypadku watpliwosci wybieraj HOLD.
3. RSI > 75 to silny sygnal wykupienia (rozwaz SELL lub HOLD).
4. RSI < 25 to silny sygnal wyprzedania (rozwaz BUY lub HOLD).
5. Uwzgledniaj trend (bullish/bearish/sideways) - nie handluj przeciwko silnemu trendowi.
6. Wysoki volume_ratio (>2) potwierdza sygnal. Niski (<0.5) oslabia.
7. Jesli masz juz otwarta pozycje, nie otwieraj kolejnej w tym samym kierunku.
8. SELL oznacza zamkniecie istniejacej pozycji long, a nie otwieranie shorta.

FORMAT ODPOWIEDZI - zwroc WYLACZNIE poprawny JSON, bez tekstu przed ani po:
{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 0-100,
  "reasoning": "Zwiezle uzasadnienie max 3 zdania.",
  "key_signals": ["sygnal 1", "sygnal 2", "sygnal 3"],
  "risk_note": "Co moze pojsc nie tak z ta decyzja."
}

WAZNE: confidence oznacza pewnosc co do decyzji, nie prawdopodobienstwo zysku.
Confidence < 60 powinno skutkowac HOLD, chyba ze sygnaly sa bardzo jednoznaczne."""


class PromptBuilder:
    """Convert market data and portfolio state into a model prompt."""

    def __init__(self, config):
        self.cfg = config

    def build(self, snapshot: MarketSnapshot, portfolio: dict) -> str:
        open_positions = portfolio.get("open_positions", [])
        current_position = self._find_position(open_positions, snapshot.symbol)

        return f"""## AKTUALNA SYTUACJA RYNKOWA
Instrument: {snapshot.symbol} | Zrodlo: {snapshot.exchange} | Timeframe: {snapshot.timeframe}

### Cena i zmiana
- Cena aktualna: {snapshot.price:,.5f}
- Zmiana 1h: {snapshot.change_pct_1h:+.2f}%
- Zmiana 24h: {snapshot.change_pct_24h:+.2f}%
- Wolumen / tick volume 24h: {snapshot.volume_24h:,.0f}

### Wskazniki techniczne
- RSI(14): {snapshot.rsi_14} {self._rsi_label(snapshot.rsi_14)}
- SMA(20): {snapshot.sma_20:,.5f} | SMA(50): {snapshot.sma_50:,.5f}
- Trend: {snapshot.trend.upper()}
- Volume ratio vs. srednia 20: {snapshot.volume_ratio:.2f}x {self._volume_label(snapshot.volume_ratio)}

### Ostatnie 5 swiec ({snapshot.timeframe})
{snapshot.last_candles_summary}

### Stan portfela
- Kapital wolny / margin available: {portfolio.get('free_capital', 0):,.2f}
- Laczna wartosc / NAV: {portfolio.get('total_value', 0):,.2f}
- P&L: {portfolio.get('daily_pnl_pct', 0):+.2f}%
- Otwarte pozycje: {len(open_positions)}

### Aktualna pozycja w {snapshot.symbol}
{self._format_position(current_position, snapshot.price)}

---
Przeanalizuj powyzsze dane i zwroc decyzje w wymaganym formacie JSON."""

    def _find_position(self, positions: list, symbol: str) -> dict | None:
        for pos in positions:
            if pos.get("symbol") == symbol:
                return pos
        return None

    def _format_position(self, position: dict | None, current_price: float) -> str:
        if not position:
            return "Brak otwartej pozycji."

        entry = position["entry_price"]
        size = position["size_usd"]
        pnl = ((current_price - entry) / entry) * 100 if entry else 0.0
        direction = position.get("direction", "LONG")

        return (
            f"Kierunek: {direction} | "
            f"Cena wejscia: {entry:,.5f} | "
            f"Rozmiar: {size:,.2f} | "
            f"Niezrealizowany P&L: {pnl:+.2f}%"
        )

    @staticmethod
    def _rsi_label(rsi: float) -> str:
        if rsi > 70:
            return "(wykupiony)"
        if rsi < 30:
            return "(wyprzedany)"
        return "(neutralny)"

    @staticmethod
    def _volume_label(volume_ratio: float) -> str:
        if volume_ratio > 1.5:
            return "(ponadnorma)"
        if volume_ratio > 0.7:
            return "(normalny)"
        return "(niski)"

    @staticmethod
    def get_system_prompt() -> str:
        return SYSTEM_PROMPT
