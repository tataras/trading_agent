"""
agent/prompt_builder.py — Warstwa 2: Budowanie promptu

To jest kluczowy plik z perspektywy jakości decyzji agenta.
Im lepszy prompt, tym lepsze decyzje modelu.

Prompt składa się z dwóch części:
  SYSTEM PROMPT — definiuje rolę i reguły, wysyłany RAZ (lub rzadko)
  USER MESSAGE  — aktualna sytuacja rynkowa, wysyłany przy każdej decyzji
"""

import json
from data.collector import MarketSnapshot


SYSTEM_PROMPT = """Jesteś precyzyjnym asystentem handlowym analizującym rynek kryptowalut.
Twoje zadanie: na podstawie danych rynkowych podjąć jedną z trzech decyzji:
BUY, SELL lub HOLD.

ZASADY DZIAŁANIA:
1. Analizuj TYLKO dostarczone dane — nie spekuluj na podstawie wiedzy spoza promptu.
2. Bądź konserwatywny — w przypadku wątpliwości wybieraj HOLD.
3. RSI > 75 to silny sygnał wykupienia (rozważ SELL lub HOLD).
4. RSI < 25 to silny sygnał wyprzedania (rozważ BUY lub HOLD).
5. Uwzględniaj trend (bullish/bearish/sideways) — nie handluj przeciwko silnemu trendowi.
6. Wysoki volume_ratio (>2) potwierdza sygnał. Niski (<0.5) osłabia.
7. Jeśli masz już otwartą pozycję, nie otwieraj kolejnej w tym samym kierunku.

FORMAT ODPOWIEDZI — zwróć WYŁĄCZNIE poprawny JSON, bez żadnego tekstu przed ani po:
{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 0-100,
  "reasoning": "Zwięzłe uzasadnienie max 3 zdania.",
  "key_signals": ["sygnał 1", "sygnał 2", "sygnał 3"],
  "risk_note": "Co może pójść nie tak z tą decyzją."
}

WAŻNE: confidence oznacza pewność co do decyzji (nie prawdopodobieństwo zysku).
Confidence < 60 powinno skutkować HOLD chyba że sygnały są bardzo jednoznaczne."""


class PromptBuilder:
    """
    Konwertuje dane rynkowe + stan portfela na prompt dla modelu.

    Dobre praktyki inżynierii promptów zastosowane tutaj:
    - Dane strukturalne (liczby) są w sekcjach z wyraźnymi nagłówkami
    - Kontekst portfela pomaga modelowi uwzględnić istniejące pozycje
    - Wymagany format JSON eliminuje potrzebę parsowania tekstu naturalnego
    - System prompt definiuje zasady raz, user message dostarcza danych
    """

    def __init__(self, config):
        self.cfg = config

    def \
            build(self, snapshot: MarketSnapshot, portfolio: dict) -> str:
        """
        Buduje wiadomość użytkownika z aktualnymi danymi rynkowymi.

        Args:
            snapshot: dane rynkowe z MarketDataCollector
            portfolio: stan portfela z MockBroker / brokera

        Returns:
            Tekst promptu gotowy do wysłania do modelu
        """
        open_positions = portfolio.get("open_positions", [])
        current_position = self._find_position(open_positions, snapshot.symbol)

        return f"""## AKTUALNA SYTUACJA RYNKOWA
Instrument: {snapshot.symbol} | Giełda: {snapshot.exchange} | Timeframe: {snapshot.timeframe}

### Cena i zmiana
- Cena aktualna: ${snapshot.price:,.2f}
- Zmiana 24h: {snapshot.change_pct_24h:+.2f}%
- Wolumen 24h: ${snapshot.volume_24h:,.0f}

### Wskaźniki techniczne
- RSI(14): {snapshot.rsi_14} {'⚠️ WYKUPIONY' if snapshot.rsi_14 > 70 else '⚠️ WYPRZEDANY' if snapshot.rsi_14 < 30 else '(neutralny)'}
- SMA(20): ${snapshot.sma_20:,.2f} | SMA(50): ${snapshot.sma_50:,.2f}
- Trend: {snapshot.trend.upper()}
- Volume ratio vs. średnia 20: {snapshot.volume_ratio:.2f}x {'(ponadnorma)' if snapshot.volume_ratio > 1.5 else '(normalny)' if snapshot.volume_ratio > 0.7 else '(niski)'}

### Ostatnie 5 świec ({snapshot.timeframe})
{snapshot.last_candles_summary}

### Stan portfela
- Kapitał wolny: ${portfolio.get('free_capital', 0):,.2f}
- Łączna wartość: ${portfolio.get('total_value', 0):,.2f}
- Dzienna P&L: {portfolio.get('daily_pnl_pct', 0):+.2f}%
- Otwarte pozycje: {len(open_positions)}

### Aktualna pozycja w {snapshot.symbol}
{self._format_position(current_position, snapshot.price)}

---
Przeanalizuj powyższe dane i zwróć decyzję w wymaganym formacie JSON."""

    def _find_position(self, positions: list, symbol: str) -> dict | None:
        """Znajdź otwartą pozycję dla danego symbolu."""
        for pos in positions:
            if pos.get("symbol") == symbol:
                return pos
        return None

    def _format_position(self, position: dict | None, current_price: float) -> str:
        """Opisz aktualną pozycję czytelnie dla modelu."""
        if not position:
            return "Brak otwartej pozycji."

        entry = position["entry_price"]
        size = position["size_usd"]
        pnl = ((current_price - entry) / entry) * 100
        direction = position.get("direction", "LONG")

        return (
            f"Kierunek: {direction} | "
            f"Cena wejścia: ${entry:,.2f} | "
            f"Rozmiar: ${size:,.2f} | "
            f"Niezrealizowany P&L: {pnl:+.2f}%"
        )

    @staticmethod
    def get_system_prompt() -> str:
        """Zwraca system prompt — wywoływany przez klienta LLM."""
        return SYSTEM_PROMPT
