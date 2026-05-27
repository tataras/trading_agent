"""
broker/oanda_broker.py - OANDA Practice broker for forex trading.

Uses OANDA v3 REST API directly through requests and exposes the same public
interface as MockBroker and AlpacaPaperBroker.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import requests

from agent.response_parser import TradingDecision
from data.collector import MarketSnapshot

log = logging.getLogger(__name__)


@dataclass
class OandaTrade:
    """Local record of submitted OANDA actions."""

    id: str
    instrument: str
    action: str
    status: str
    timestamp: datetime = field(default_factory=datetime.now)
    raw: dict = field(default_factory=dict)


class OandaPracticeBroker:
    """Broker implementation for OANDA practice accounts."""

    def __init__(self, config):
        self.cfg = config
        self.base_url = config.oanda_base_url.rstrip("/")
        self.account_id = config.oanda_account_id
        self.instrument = self._to_oanda_instrument(
            config.oanda_instrument or config.symbol
        )
        self.symbol = self._from_oanda_instrument(self.instrument)
        self._trade_history: list[OandaTrade] = []

        if not self.account_id or not config.oanda_access_token:
            raise ValueError(
                "Brak danych OANDA Practice. Ustaw OANDA_ACCOUNT_ID i "
                "OANDA_ACCESS_TOKEN w zmiennych srodowiskowych."
            )

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.oanda_access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        summary = self._request("GET", f"/v3/accounts/{self.account_id}/summary")
        account = summary.get("account", {})
        log.info(
            "OandaPracticeBroker uruchomiony | NAV=%s | marginAvailable=%s | instrument=%s",
            account.get("NAV"),
            account.get("marginAvailable"),
            self.instrument,
        )

    def get_portfolio(self, market_prices: dict[str, float] | None = None) -> dict:
        """Return account/positions in the format expected by the agent."""
        summary = self._request("GET", f"/v3/accounts/{self.account_id}/summary")
        positions_response = self._request(
            "GET", f"/v3/accounts/{self.account_id}/openPositions"
        )

        account = summary.get("account", {})
        nav = self._to_float(account.get("NAV"), self.cfg.initial_capital_usd)
        balance = self._to_float(account.get("balance"), nav)
        margin_available = self._to_float(account.get("marginAvailable"), balance)
        pl = self._to_float(account.get("pl"))
        unrealized_pl = self._to_float(account.get("unrealizedPL"))
        daily_pnl_usd = pl + unrealized_pl
        daily_pnl_pct = (daily_pnl_usd / balance) * 100 if balance else 0.0

        normalized_positions = [
            self._normalize_position(position)
            for position in positions_response.get("positions", [])
            if position.get("instrument") == self.instrument
        ]
        invested_value = sum(
            abs(position.get("size_usd", 0.0)) for position in normalized_positions
        )

        return {
            "free_capital": round(margin_available, 2),
            "total_value": round(nav, 2),
            "invested_value": round(invested_value, 2),
            "daily_pnl_usd": round(daily_pnl_usd, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 4),
            "open_positions": normalized_positions,
            "total_trades": len(self._trade_history),
            "broker": "oanda_demo",
        }

    def execute(self, decision: TradingDecision, snapshot: MarketSnapshot) -> str:
        """Submit the approved BUY/SELL action to OANDA Practice."""
        if decision.action == "BUY":
            return self._open_long(snapshot)
        if decision.action == "SELL":
            return self._close_long()
        return "HOLD - brak dzialania"

    def get_trade_history(self) -> list[OandaTrade]:
        return list(self._trade_history)

    def print_summary(self) -> None:
        portfolio = self.get_portfolio()
        print("\n" + "=" * 50)
        print("PODSUMOWANIE SESJI - OANDA PRACTICE")
        print("=" * 50)
        print(f"NAV:              ${portfolio['total_value']:>10,.2f}")
        print(f"Margin available: ${portfolio['free_capital']:>10,.2f}")
        print(f"P&L:              ${portfolio['daily_pnl_usd']:>+10,.2f} ({portfolio['daily_pnl_pct']:+.2f}%)")
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
        units = int(notional / snapshot.price) if snapshot.price else 0
        if units < self.cfg.oanda_min_order_units:
            return (
                "SKIP BUY - za mala liczba jednostek: "
                f"{units} < {self.cfg.oanda_min_order_units}"
            )

        order = self._request(
            "POST",
            f"/v3/accounts/{self.account_id}/orders",
            json={
                "order": {
                    "type": "MARKET",
                    "instrument": self.instrument,
                    "units": str(units),
                    "timeInForce": "FOK",
                    "positionFill": "DEFAULT",
                }
            },
        )
        transaction = order.get("orderFillTransaction") or order.get("orderCreateTransaction", {})
        self._record_trade("BUY", transaction)
        return (
            f"OANDA BUY {self.symbol} | units={units} | "
            f"price={transaction.get('price', 'market')} | id={transaction.get('id')}"
        )

    def _close_long(self) -> str:
        portfolio = self.get_portfolio()
        if not portfolio["open_positions"]:
            return f"SKIP SELL - brak otwartej pozycji w {self.symbol}"

        response = self._request(
            "PUT",
            f"/v3/accounts/{self.account_id}/positions/{self.instrument}/close",
            json={"longUnits": "ALL"},
        )
        transaction = response.get("longOrderFillTransaction") or response
        self._record_trade("SELL", transaction)
        return (
            f"OANDA SELL/CLOSE {self.symbol} | "
            f"price={transaction.get('price', 'market')} | id={transaction.get('id')}"
        )

    def _normalize_position(self, position: dict) -> dict:
        long = position.get("long", {})
        short = position.get("short", {})
        long_units = self._to_float(long.get("units"))
        short_units = self._to_float(short.get("units"))

        if long_units > 0:
            side = long
            direction = "LONG"
            units = long_units
        elif short_units < 0:
            side = short
            direction = "SHORT"
            units = abs(short_units)
        else:
            side = long
            direction = "FLAT"
            units = 0.0

        entry = self._to_float(side.get("averagePrice"))
        unrealized_pnl = self._to_float(position.get("unrealizedPL"))
        size_usd = units * entry if entry else 0.0

        return {
            "id": position.get("instrument", self.instrument),
            "symbol": self.symbol,
            "broker_symbol": position.get("instrument", self.instrument),
            "direction": direction,
            "entry_price": entry,
            "qty": units,
            "size_usd": round(size_usd, 2),
            "market_value_usd": round(size_usd + unrealized_pnl, 2),
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
            raise RuntimeError(f"OANDA API error {method} {path}: {body}") from exc

    def _record_trade(self, action: str, raw: dict) -> None:
        self._trade_history.append(
            OandaTrade(
                id=str(raw.get("id", "")),
                instrument=self.instrument,
                action=action,
                status=str(raw.get("reason", raw.get("type", "submitted"))),
                raw=raw,
            )
        )

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_oanda_instrument(symbol: str) -> str:
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
