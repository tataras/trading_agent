"""
broker/exante_broker.py - EXANTE HTTP API demo broker.

Uses EXANTE demo REST endpoints directly through requests and exposes the same
public interface as the other brokers in this project.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import requests

from agent.response_parser import TradingDecision
from data.collector import MarketSnapshot

log = logging.getLogger(__name__)


@dataclass
class ExanteTrade:
    """Local record of submitted EXANTE actions."""

    id: str
    symbol: str
    action: str
    status: str
    timestamp: datetime = field(default_factory=datetime.now)
    raw: dict = field(default_factory=dict)


class ExanteDemoBroker:
    """Broker implementation for EXANTE HTTP API demo accounts."""

    def __init__(self, config):
        self.cfg = config
        self.trade_base_url = config.exante_trade_base_url.rstrip("/")
        self.md_base_url = config.exante_md_base_url.rstrip("/")
        self.account_id = config.exante_account_id
        self.symbol = config.exante_symbol or config.symbol
        self._trade_history: list[ExanteTrade] = []

        if (
            not config.exante_application_id
            or not config.exante_access_key
            or not self.account_id
        ):
            raise ValueError(
                "Brak danych EXANTE demo. Ustaw EXANTE_APPLICATION_ID, "
                "EXANTE_ACCESS_KEY i EXANTE_ACCOUNT_ID w zmiennych srodowiskowych."
            )

        self.session = requests.Session()
        self.session.auth = (config.exante_application_id, config.exante_access_key)
        self.session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )

        summary = self._get_summary()
        log.info(
            "ExanteDemoBroker uruchomiony | NAV=%s %s | freeMoney=%s | symbol=%s",
            summary.get("netAssetValue"),
            summary.get("currency", self.cfg.exante_summary_currency),
            summary.get("freeMoney"),
            self.symbol,
        )

    def get_portfolio(self, market_prices: dict[str, float] | None = None) -> dict:
        """Return account/positions in the format expected by the agent."""
        summary = self._get_summary()

        nav = self._to_float(summary.get("netAssetValue"), self.cfg.initial_capital_usd)
        free_money = self._to_float(summary.get("freeMoney"), nav)
        positions = summary.get("positions", [])

        normalized_positions = [
            self._normalize_position(position)
            for position in positions
            if position.get("symbolId") == self.symbol
            and abs(self._to_float(position.get("quantity"))) > 0
        ]
        invested_value = sum(
            abs(position.get("market_value_usd", 0.0))
            for position in normalized_positions
        )
        daily_pnl_usd = sum(
            position.get("unrealized_pnl_usd", 0.0)
            for position in normalized_positions
        )
        daily_pnl_pct = (daily_pnl_usd / nav) * 100 if nav else 0.0

        return {
            "free_capital": round(free_money, 2),
            "total_value": round(nav, 2),
            "invested_value": round(invested_value, 2),
            "daily_pnl_usd": round(daily_pnl_usd, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 4),
            "open_positions": normalized_positions,
            "total_trades": len(self._trade_history),
            "broker": "exante_demo",
        }

    def execute(self, decision: TradingDecision, snapshot: MarketSnapshot) -> str:
        """Submit the approved BUY/SELL action to EXANTE demo."""
        if decision.action == "BUY":
            return self._open_long(snapshot)
        if decision.action == "SELL":
            return self._close_long()
        return "HOLD - brak dzialania"

    def get_trade_history(self) -> list[ExanteTrade]:
        return list(self._trade_history)

    def print_summary(self) -> None:
        portfolio = self.get_portfolio()
        currency = self.cfg.exante_summary_currency
        print("\n" + "=" * 50)
        print("PODSUMOWANIE SESJI - EXANTE DEMO")
        print("=" * 50)
        print(f"NAV:              {portfolio['total_value']:>10,.2f} {currency}")
        print(f"Free money:       {portfolio['free_capital']:>10,.2f} {currency}")
        print(f"P&L pozycji:      {portfolio['daily_pnl_usd']:>+10,.2f} ({portfolio['daily_pnl_pct']:+.2f}%)")
        print(f"Otwarte pozycje:  {len(portfolio['open_positions'])}")
        print(f"Akcje w sesji:    {len(self._trade_history)}")
        print("=" * 50)

    def _open_long(self, snapshot: MarketSnapshot) -> str:
        portfolio = self.get_portfolio()
        if portfolio["open_positions"]:
            return f"SKIP BUY - pozycja w {self.symbol} jest juz otwarta"

        notional = min(
            portfolio["total_value"] * self.cfg.max_position_pct,
            portfolio["free_capital"],
        )
        quantity = int(notional / snapshot.price) if snapshot.price else 0
        min_quantity = self.cfg.exante_min_order_quantity
        if quantity < min_quantity:
            return (
                "SKIP BUY - za mala liczba jednostek: "
                f"{quantity} < {min_quantity:g}"
            )

        order = self._place_market_order("buy", quantity)
        self._record_trade("BUY", order)
        return (
            f"EXANTE BUY {self.symbol} | qty={quantity} | "
            f"status={self._order_status(order)} | id={self._order_id(order)}"
        )

    def _close_long(self) -> str:
        portfolio = self.get_portfolio()
        positions = portfolio["open_positions"]
        if not positions:
            return f"SKIP SELL - brak otwartej pozycji w {self.symbol}"

        quantity = sum(position["qty"] for position in positions)
        order = self._place_market_order("sell", quantity)
        self._record_trade("SELL", order)
        return (
            f"EXANTE SELL/CLOSE {self.symbol} | qty={quantity:g} | "
            f"status={self._order_status(order)} | id={self._order_id(order)}"
        )

    def _place_market_order(self, side: str, quantity: float):
        return self._request(
            "POST",
            self.trade_base_url,
            "/3.0/orders",
            json={
                "symbolId": self.symbol,
                "orderType": "market",
                "side": side,
                "quantity": str(quantity),
                "duration": self.cfg.exante_order_duration,
                "accountId": self.account_id,
            },
        )

    def _get_summary(self) -> dict:
        session_date = date.today().isoformat()
        return self._request(
            "GET",
            self.md_base_url,
            f"/3.0/summary/{self.account_id}/{session_date}/{self.cfg.exante_summary_currency}",
        )

    def _normalize_position(self, position: dict) -> dict:
        qty = self._to_float(position.get("quantity"))
        entry = self._to_float(position.get("averagePrice"))
        price = self._to_float(position.get("price"), entry)
        market_value = abs(self._to_float(position.get("convertedValue")))
        if not market_value:
            market_value = abs(qty * price)
        unrealized_pnl = self._to_float(position.get("convertedPnl"))

        return {
            "id": position.get("symbolId", self.symbol),
            "symbol": self.cfg.symbol,
            "broker_symbol": position.get("symbolId", self.symbol),
            "direction": "LONG" if qty > 0 else "SHORT",
            "entry_price": entry,
            "qty": abs(qty),
            "size_usd": round(abs(qty * entry), 2) if entry else round(market_value, 2),
            "market_value_usd": round(market_value, 2),
            "unrealized_pnl_usd": round(unrealized_pnl, 2),
            "opened_at": "",
        }

    def _request(self, method: str, base_url: str, path: str, **kwargs):
        url = f"{base_url}{path}"
        try:
            response = self.session.request(method, url, timeout=15, **kwargs)
            response.raise_for_status()
            if response.text:
                return response.json()
            return {}
        except requests.HTTPError as exc:
            body = exc.response.text if exc.response is not None else ""
            raise RuntimeError(f"EXANTE API error {method} {path}: {body}") from exc

    def _record_trade(self, action: str, raw) -> None:
        order = raw[0] if isinstance(raw, list) and raw else raw
        if not isinstance(order, dict):
            order = {"status": "submitted"}

        self._trade_history.append(
            ExanteTrade(
                id=self._order_id(order),
                symbol=self.symbol,
                action=action,
                status=self._order_status(order),
                raw=order,
            )
        )

    @staticmethod
    def _order_id(raw) -> str:
        order = raw[0] if isinstance(raw, list) and raw else raw
        if isinstance(order, dict):
            return str(order.get("orderId", order.get("id", "")))
        return ""

    @staticmethod
    def _order_status(raw) -> str:
        order = raw[0] if isinstance(raw, list) and raw else raw
        if isinstance(order, dict):
            state = order.get("orderState", {})
            return str(state.get("status", order.get("status", "submitted")))
        return "submitted"

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
