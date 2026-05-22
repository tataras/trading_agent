"""
broker/alpaca_broker.py - Alpaca Paper Trading broker.

Uses Alpaca Trading API directly through requests, so the project does not
need the alpaca-py SDK. This broker keeps the same public interface as
MockBroker: get_portfolio(), execute(), get_trade_history(), print_summary().
"""

import logging
from datetime import datetime
from dataclasses import dataclass, field
from urllib.parse import quote

import requests

from agent.response_parser import TradingDecision
from data.collector import MarketSnapshot

log = logging.getLogger(__name__)


@dataclass
class AlpacaTrade:
    """Local record of submitted Alpaca actions."""
    id: str
    symbol: str
    action: str
    status: str
    timestamp: datetime = field(default_factory=datetime.now)
    raw: dict = field(default_factory=dict)


class AlpacaPaperBroker:
    """Broker implementation for Alpaca Paper Trading."""

    def __init__(self, config):
        self.cfg = config
        self.base_url = config.alpaca_base_url.rstrip("/")
        self.symbol = config.alpaca_symbol or self._to_alpaca_symbol(config.symbol)
        self._trade_history: list[AlpacaTrade] = []

        if not config.alpaca_api_key or not config.alpaca_secret_key:
            raise ValueError(
                "Brak kluczy Alpaca Paper Trading. Ustaw ALPACA_API_KEY "
                "i ALPACA_SECRET_KEY w zmiennych srodowiskowych."
            )

        self.session = requests.Session()
        self.session.headers.update(
            {
                "APCA-API-KEY-ID": config.alpaca_api_key,
                "APCA-API-SECRET-KEY": config.alpaca_secret_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        account = self._request("GET", "/v2/account")
        log.info(
            "AlpacaPaperBroker uruchomiony | equity=$%s | buying_power=$%s | symbol=%s",
            account.get("equity"),
            account.get("buying_power"),
            self.symbol,
        )

    def get_portfolio(self, market_prices: dict[str, float] | None = None) -> dict:
        """Return account/positions in the format expected by PromptBuilder/RiskManager."""
        account = self._request("GET", "/v2/account")
        positions = self._request("GET", "/v2/positions")

        equity = self._to_float(account.get("equity"))
        cash = self._to_float(account.get("cash"))
        last_equity = self._to_float(account.get("last_equity"), equity)
        daily_pnl_usd = equity - last_equity
        daily_pnl_pct = (daily_pnl_usd / last_equity) * 100 if last_equity else 0.0

        normalized_positions = [
            self._normalize_position(position)
            for position in positions
            if self._same_symbol(position.get("symbol"))
        ]

        invested_value = sum(
            abs(self._to_float(position.get("market_value")))
            for position in positions
            if self._same_symbol(position.get("symbol"))
        )

        return {
            "free_capital": round(cash, 2),
            "total_value": round(equity, 2),
            "invested_value": round(invested_value, 2),
            "daily_pnl_usd": round(daily_pnl_usd, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 4),
            "open_positions": normalized_positions,
            "total_trades": len(self._trade_history),
            "broker": "alpaca_paper",
        }

    def execute(self, decision: TradingDecision, snapshot: MarketSnapshot) -> str:
        """Submit the approved BUY/SELL action to Alpaca Paper Trading."""
        if decision.action == "BUY":
            return self._open_position(snapshot)
        if decision.action == "SELL":
            return self._close_position(snapshot)
        return "HOLD - brak dzialania"

    def get_trade_history(self) -> list[AlpacaTrade]:
        return list(self._trade_history)

    def print_summary(self) -> None:
        portfolio = self.get_portfolio()
        print("\n" + "=" * 50)
        print("PODSUMOWANIE SESJI - ALPACA PAPER")
        print("=" * 50)
        print(f"Equity:           ${portfolio['total_value']:>10,.2f}")
        print(f"Cash:             ${portfolio['free_capital']:>10,.2f}")
        print(f"Dzienna P&L:      ${portfolio['daily_pnl_usd']:>+10,.2f} ({portfolio['daily_pnl_pct']:+.2f}%)")
        print(f"Otwarte pozycje:  {len(portfolio['open_positions'])}")
        print(f"Akcje w sesji:    {len(self._trade_history)}")
        print("=" * 50)

    def _open_position(self, snapshot: MarketSnapshot) -> str:
        portfolio = self.get_portfolio()
        size_usd = min(
            portfolio["total_value"] * self.cfg.max_position_pct,
            portfolio["free_capital"],
        )

        if size_usd < self.cfg.alpaca_min_order_notional:
            return (
                "SKIP BUY - za mala kwota zlecenia: "
                f"${size_usd:.2f} < ${self.cfg.alpaca_min_order_notional:.2f}"
            )

        if portfolio["open_positions"]:
            return f"SKIP BUY - pozycja w {self.symbol} jest juz otwarta"

        order = self._request(
            "POST",
            "/v2/orders",
            json={
                "symbol": self.symbol,
                "side": "buy",
                "type": "market",
                "time_in_force": self.cfg.alpaca_time_in_force,
                "notional": str(round(size_usd, 2)),
            },
        )
        self._record_trade("BUY", order)
        return (
            f"ALPACA BUY {self.symbol} | notional=${size_usd:,.2f} | "
            f"status={order.get('status', 'unknown')} | id={order.get('id')}"
        )

    def _close_position(self, snapshot: MarketSnapshot) -> str:
        portfolio = self.get_portfolio()
        if not portfolio["open_positions"]:
            return f"SKIP SELL - brak otwartej pozycji w {self.symbol}"

        response = self._request("DELETE", f"/v2/positions/{quote(self.symbol, safe='')}")
        raw = response[0] if isinstance(response, list) and response else response
        self._record_trade("SELL", raw if isinstance(raw, dict) else {"status": "submitted"})
        return (
            f"ALPACA SELL/CLOSE {self.symbol} | "
            f"status={raw.get('status', 'submitted') if isinstance(raw, dict) else 'submitted'}"
        )

    def _normalize_position(self, position: dict) -> dict:
        qty = self._to_float(position.get("qty"))
        entry = self._to_float(position.get("avg_entry_price"))
        market_value = abs(self._to_float(position.get("market_value")))
        cost_basis = abs(self._to_float(position.get("cost_basis"), market_value))
        unrealized_pnl = self._to_float(position.get("unrealized_pl"))

        return {
            "id": position.get("asset_id", ""),
            "symbol": self.cfg.symbol,
            "broker_symbol": position.get("symbol", self.symbol),
            "direction": position.get("side", "long").upper(),
            "entry_price": entry,
            "qty": qty,
            "size_usd": cost_basis,
            "market_value_usd": round(market_value, 2),
            "unrealized_pnl_usd": round(unrealized_pnl, 2),
            "opened_at": "",
        }

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(method, url, timeout=15, **kwargs)
            response.raise_for_status()
            if response.text:
                return response.json()
            return {}
        except requests.HTTPError as exc:
            body = exc.response.text if exc.response is not None else ""
            raise RuntimeError(f"Alpaca API error {method} {path}: {body}") from exc

    def _record_trade(self, action: str, raw: dict) -> None:
        self._trade_history.append(
            AlpacaTrade(
                id=str(raw.get("id", "")),
                symbol=self.symbol,
                action=action,
                status=str(raw.get("status", "submitted")),
                raw=raw,
            )
        )

    def _same_symbol(self, symbol: str | None) -> bool:
        if not symbol:
            return False
        return symbol.replace("/", "").upper() == self.symbol.replace("/", "").upper()

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_alpaca_symbol(symbol: str) -> str:
        normalized = symbol.upper().replace("-", "").replace("/", "")
        if normalized.endswith("USDT"):
            return f"{normalized[:-4]}/USD"
        if normalized.endswith("USD") and len(normalized) > 3:
            return f"{normalized[:-3]}/USD"
        return symbol.upper()
