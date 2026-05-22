"""
risk/manager.py — Warstwa 5: Zarządzanie ryzykiem

To jest najważniejszy moduł bezpieczeństwa.
Działa NIEZALEŻNIE od Claude — nawet jeśli model podejmie złą decyzję,
ten moduł może ją zablokować.

Zasada: wszystkie limity są twarde (hard limits). Brak wyjątków.
"""

import logging
from agent.response_parser import TradingDecision
from data.collector import MarketSnapshot

log = logging.getLogger(__name__)


class RiskCheckResult:
    """Wynik sprawdzenia ryzyka."""
    def __init__(self, approved: bool, reason: str = "", forced_action: str | None = None):
        self.approved = approved
        self.reason = reason
        self.forced_action = forced_action

    def __bool__(self):
        return self.approved

    def __str__(self):
        status = "✓ ZATWIERDZONE" if self.approved else "✗ ZABLOKOWANE"
        if self.forced_action:
            return f"{status}: {self.reason} | wymuszona akcja: {self.forced_action}"
        return f"{status}: {self.reason}"


class RiskManager:
    """
    Niezależna warstwa ryzyka — ostatnia linia obrony przed rynkiem.

    Sprawdza:
    1. Dzienny limit strat
    2. Maksymalną liczbę otwartych pozycji
    3. Maksymalny rozmiar pozycji
    4. Minimalny poziom pewności modelu
    5. Stop-loss dla istniejących pozycji
    """

    # Minimalna pewność modelu aby wykonać BUY lub SELL
    MIN_CONFIDENCE_TO_TRADE = 65

    def __init__(self, config):
        self.cfg = config

    def check(
        self,
        decision: TradingDecision,
        portfolio: dict,
        snapshot: MarketSnapshot,
    ) -> RiskCheckResult:
        """
        Sprawdź czy decyzja jest bezpieczna.

        Args:
            decision: decyzja Claude po parsowaniu
            portfolio: aktualny stan portfela
            snapshot: dane rynkowe

        Returns:
            RiskCheckResult (bool-like: True = zatwierdzone, False = zablokowane)
        """

        # Stop-loss ma pierwszenstwo: musi zamknac pozycje nawet gdy Claude chce HOLD.
        for pos in portfolio.get("open_positions", []):
            if pos.get("symbol") == snapshot.symbol:
                loss_pct = self._calc_loss_pct(pos, snapshot.price)
                if loss_pct < -self.cfg.stop_loss_pct * 100:
                    reason = (
                        f"Stop-loss aktywowany dla {snapshot.symbol}: "
                        f"strata {loss_pct:.2f}% > limit -{self.cfg.stop_loss_pct * 100:.1f}%"
                    )
                    log.warning(f"RISK STOP-LOSS: {reason}")
                    return RiskCheckResult(True, reason, forced_action="SELL")

        # HOLD zawsze przechodzi — nie wymaga działania
        if decision.action == "HOLD":
            return RiskCheckResult(True, "HOLD nie wymaga sprawdzenia")

        # ── Sprawdzenie 1: Dzienny limit strat ────────────────────
        daily_pnl_pct = portfolio.get("daily_pnl_pct", 0.0)
        if daily_pnl_pct <= -self.cfg.max_daily_loss_pct * 100:
            reason = (
                f"Dzienny limit strat osiągnięty: "
                f"{daily_pnl_pct:.2f}% ≤ -{self.cfg.max_daily_loss_pct * 100:.1f}%"
            )
            log.warning(f"RISK BLOCK: {reason}")
            return RiskCheckResult(False, reason)

        # ── Sprawdzenie 2: Limit otwartych pozycji ────────────────
        open_count = len(portfolio.get("open_positions", []))
        if decision.action == "BUY" and open_count >= self.cfg.max_open_positions:
            reason = (
                f"Za dużo otwartych pozycji: "
                f"{open_count} ≥ {self.cfg.max_open_positions}"
            )
            log.warning(f"RISK BLOCK: {reason}")
            return RiskCheckResult(False, reason)

        # ── Sprawdzenie 3: Pewność Claude ─────────────────────────
        if decision.confidence < self.MIN_CONFIDENCE_TO_TRADE:
            reason = (
                f"Za niska pewność modelu: "
                f"{decision.confidence}% < {self.MIN_CONFIDENCE_TO_TRADE}%"
            )
            log.warning(f"RISK BLOCK: {reason}")
            return RiskCheckResult(False, reason)

        # ── Sprawdzenie 4: Rozmiar pozycji ────────────────────────
        max_position_usd = portfolio.get("total_value", 0) * self.cfg.max_position_pct
        if max_position_usd < 10:  # minimalny próg sensowności
            reason = f"Za mały kapitał do handlu: ${max_position_usd:.2f}"
            log.warning(f"RISK BLOCK: {reason}")
            return RiskCheckResult(False, reason)

        log.debug(f"Risk check passed dla {decision.action} z confidence={decision.confidence}%")
        return RiskCheckResult(True, "Wszystkie limity OK")

    def calculate_position_size(self, portfolio: dict) -> float:
        """
        Oblicz rozmiar pozycji w USD zgodnie z regułą max_position_pct.
        Zwraca kwotę w USD do zainwestowania.
        """
        total = portfolio.get("total_value", self.cfg.initial_capital_usd)
        max_usd = total * self.cfg.max_position_pct
        free = portfolio.get("free_capital", 0.0)
        return min(max_usd, free)  # nie wydaj więcej niż masz wolnego

    @staticmethod
    def _calc_loss_pct(position: dict, current_price: float) -> float:
        """Oblicz % P&L dla otwartej pozycji."""
        entry = position.get("entry_price", current_price)
        if entry == 0:
            return 0.0
        return ((current_price - entry) / entry) * 100
