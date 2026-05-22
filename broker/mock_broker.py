"""
broker/mock_broker.py — Warstwa 6: Wirtualna giełda (Paper Trading)

Symuluje wykonanie zleceń w pamięci — żadnych prawdziwych pieniędzy.
Idealne do testowania strategii bez ryzyka.

Jak podmienić na prawdziwego brokera:
  1. Stwórz plik broker/binance_testnet.py z tą samą nazwą metod
  2. W main.py zmień: broker = MockBroker(cfg) → broker = BinanceTestnet(cfg)
  3. Reszta systemu działa bez zmian (interfejs identyczny)
"""

import logging
from datetime import datetime, date
from dataclasses import dataclass, field
from agent.response_parser import TradingDecision
from data.collector import MarketSnapshot

log = logging.getLogger(__name__)


@dataclass
class Trade:
    """Zapis pojedynczej transakcji."""
    id: int
    symbol: str
    action: str           # "BUY" or "SELL"
    price: float
    size_usd: float
    timestamp: datetime = field(default_factory=datetime.now)
    pnl: float = 0.0      # P&L dla transakcji zamykającej
    note: str = ""


class MockBroker:
    """
    Symulacja brokera w pamięci.

    Śledzi:
    - Wolny kapitał (nieużyty w pozycjach)
    - Otwarte pozycje (kupione, ale nie sprzedane)
    - Historię transakcji
    - Dzienną P&L
    """

    def __init__(self, config):
        self.cfg = config
        self._free_capital = config.initial_capital_usd
        self._open_positions: list[dict] = []
        self._trade_history: list[Trade] = []
        self._daily_start_value = config.initial_capital_usd
        self._last_reset_date = date.today()
        self._trade_counter = 0
        self._last_prices: dict[str, float] = {}

        log.info(
            f"MockBroker uruchomiony | "
            f"kapitał startowy: ${config.initial_capital_usd:,.2f}"
        )

    # ─── Publiczne API ────────────────────────────────────────────

    def get_portfolio(self, market_prices: dict[str, float] | None = None) -> dict:
        """
        Zwróć aktualny stan portfela.
        Format musi być zgodny z tym czego oczekuje PromptBuilder i RiskManager.
        """
        if market_prices:
            self._last_prices.update(market_prices)

        self._maybe_reset_daily(self._last_prices)
        total = self._calc_total_value(self._last_prices)
        positions_value = self._calc_positions_value(self._last_prices)

        daily_pnl_usd = total - self._daily_start_value
        daily_pnl_pct = (daily_pnl_usd / self._daily_start_value) * 100

        return {
            "free_capital": round(self._free_capital, 2),
            "total_value": round(total, 2),
            "invested_value": round(positions_value, 2),
            "daily_pnl_usd": round(daily_pnl_usd, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 4),
            "open_positions": self._with_unrealized_pnl(self._last_prices),
            "total_trades": len(self._trade_history),
        }

    def execute(self, decision: TradingDecision, snapshot: MarketSnapshot) -> str:
        """
        Wykonaj decyzję handlową.

        Args:
            decision: sparsowana decyzja Claude (zatwierdzona przez RiskManager)
            snapshot: aktualne dane rynkowe (potrzebujemy ceny)

        Returns:
            Opis wykonanej operacji
        """
        self._last_prices[snapshot.symbol] = snapshot.price

        if decision.action == "BUY":
            return self._open_position(snapshot)
        elif decision.action == "SELL":
            return self._close_position(snapshot)
        else:
            return "HOLD — brak działania"

    def get_trade_history(self) -> list[Trade]:
        """Zwróć historię wszystkich transakcji."""
        return list(self._trade_history)

    def print_summary(self) -> None:
        """Wydrukuj podsumowanie do konsoli (użyj przy zamykaniu)."""
        portfolio = self.get_portfolio()
        initial = self.cfg.initial_capital_usd
        total = portfolio["total_value"]
        total_pnl = total - initial
        total_pnl_pct = (total_pnl / initial) * 100

        print("\n" + "=" * 50)
        print("📊 PODSUMOWANIE SESJI")
        print("=" * 50)
        print(f"Kapitał startowy:  ${initial:>10,.2f}")
        print(f"Wartość końcowa:   ${total:>10,.2f}")
        print(f"Łączna P&L:        ${total_pnl:>+10,.2f} ({total_pnl_pct:+.2f}%)")
        print(f"Liczba transakcji: {len(self._trade_history)}")
        print(f"Otwarte pozycje:   {len(self._open_positions)}")
        print("=" * 50)

        if self._trade_history:
            print("\n📋 HISTORIA TRANSAKCJI:")
            for t in self._trade_history[-10:]:  # ostatnie 10
                print(
                    f"  [{t.timestamp.strftime('%H:%M:%S')}] "
                    f"{t.action:4s} {t.symbol} "
                    f"@ ${t.price:>10,.2f} | "
                    f"${t.size_usd:>8,.2f}"
                    + (f" | P&L: ${t.pnl:>+8,.2f}" if t.pnl != 0 else "")
                )

    # ─── Prywatne metody ──────────────────────────────────────────

    def _open_position(self, snapshot: MarketSnapshot) -> str:
        """Otwórz długą pozycję (BUY)."""
        # Oblicz rozmiar pozycji
        size_usd = self._free_capital * self.cfg.max_position_pct
        size_usd = min(size_usd, self._free_capital)  # nie więcej niż mamy

        if size_usd < 1.0:
            return f"SKIP BUY — za mało wolnego kapitału: ${self._free_capital:.2f}"

        # Sprawdź czy już mamy pozycję
        existing = next(
            (p for p in self._open_positions if p["symbol"] == snapshot.symbol), None
        )
        if existing:
            return f"SKIP BUY — już mamy pozycję w {snapshot.symbol}"

        # Wykonaj
        self._free_capital -= size_usd
        self._trade_counter += 1

        position = {
            "id": self._trade_counter,
            "symbol": snapshot.symbol,
            "direction": "LONG",
            "entry_price": snapshot.price,
            "size_usd": size_usd,
            "opened_at": datetime.now().isoformat(),
        }
        self._open_positions.append(position)

        trade = Trade(
            id=self._trade_counter,
            symbol=snapshot.symbol,
            action="BUY",
            price=snapshot.price,
            size_usd=size_usd,
        )
        self._trade_history.append(trade)

        result = (
            f"✓ BUY {snapshot.symbol} | "
            f"cena: ${snapshot.price:,.2f} | "
            f"rozmiar: ${size_usd:,.2f}"
        )
        log.info(result)
        return result

    def _close_position(self, snapshot: MarketSnapshot) -> str:
        """Zamknij pozycję (SELL)."""
        position = next(
            (p for p in self._open_positions if p["symbol"] == snapshot.symbol), None
        )
        if not position:
            return f"SKIP SELL — brak otwartej pozycji w {snapshot.symbol}"

        # Oblicz P&L
        entry = position["entry_price"]
        size = position["size_usd"]
        pnl_pct = (snapshot.price - entry) / entry
        pnl_usd = size * pnl_pct
        proceeds = size + pnl_usd

        # Zaktualizuj stan
        self._free_capital += proceeds
        self._open_positions.remove(position)

        self._trade_counter += 1
        trade = Trade(
            id=self._trade_counter,
            symbol=snapshot.symbol,
            action="SELL",
            price=snapshot.price,
            size_usd=size,
            pnl=pnl_usd,
        )
        self._trade_history.append(trade)

        result = (
            f"{'✓' if pnl_usd >= 0 else '✗'} SELL {snapshot.symbol} | "
            f"wejście: ${entry:,.2f} → wyjście: ${snapshot.price:,.2f} | "
            f"P&L: ${pnl_usd:>+,.2f} ({pnl_pct * 100:+.2f}%)"
        )
        log.info(result)
        return result

    def _calc_total_value(self, market_prices: dict[str, float] | None = None) -> float:
        """
        Całkowita wartość portfela = wolny kapitał + wartość rynkowa pozycji.
        (Dla mock brokera: pozycje wyceniamy po cenie wejścia bo nie mamy live feed tu)
        """
        return self._free_capital + self._calc_positions_value(market_prices)

    def _calc_positions_value(self, market_prices: dict[str, float] | None = None) -> float:
        """Wycena otwartych pozycji po aktualnej cenie, jesli jest dostepna."""
        return sum(
            self._position_market_value(position, market_prices)
            for position in self._open_positions
        )

    @staticmethod
    def _position_market_value(
        position: dict,
        market_prices: dict[str, float] | None = None,
    ) -> float:
        entry = position.get("entry_price", 0)
        size = position.get("size_usd", 0)
        if not entry:
            return size

        price = (market_prices or {}).get(position.get("symbol"), entry)
        return size * (price / entry)

    def _with_unrealized_pnl(self, market_prices: dict[str, float] | None = None) -> list[dict]:
        """Dodaj do pozycji wycene rynkowa i niezrealizowany P&L dla promptu."""
        enriched = []
        for position in self._open_positions:
            current_value = self._position_market_value(position, market_prices)
            copy = dict(position)
            copy["market_value_usd"] = round(current_value, 2)
            copy["unrealized_pnl_usd"] = round(current_value - position["size_usd"], 2)
            enriched.append(copy)
        return enriched

    def _maybe_reset_daily(self, market_prices: dict[str, float] | None = None) -> None:
        """Resetuj statystyki dzienne o północy."""
        today = date.today()
        if today > self._last_reset_date:
            self._daily_start_value = self._calc_total_value(market_prices)
            self._last_reset_date = today
            log.info("Reset statystyk dziennych")
