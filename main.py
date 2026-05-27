"""
main.py — Serce agenta: główna pętla decyzyjna

Łączy wszystkie warstwy w jeden spójny przepływ:
  1. Pobierz dane  →  2. Zbuduj prompt  →  3. Zapytaj Gemini
  →  4. Parsuj decyzję  →  5. Sprawdź ryzyko  →  6. Wykonaj

Każdy krok jest niezależny i wymienialny.
"""

import time
import logging
import signal
import sys
from datetime import datetime

from config import Config
from data.collector import MarketDataCollector
from agent.prompt_builder import PromptBuilder
from agent.gemini_client import GeminiClient
from agent.response_parser import ResponseParser
from risk.manager import RiskManager
from broker.alpaca_broker import AlpacaPaperBroker
from broker.exante_broker import ExanteDemoBroker
from broker.mock_broker import MockBroker
from broker.oanda_broker import OandaPracticeBroker


def create_broker(cfg: Config):
    """Utworz brokera zgodnie z konfiguracja."""
    if cfg.broker_mode == "alpaca_paper":
        return AlpacaPaperBroker(cfg)
    if cfg.broker_mode == "oanda_demo":
        return OandaPracticeBroker(cfg)
    if cfg.broker_mode == "exante_demo":
        return ExanteDemoBroker(cfg)
    if cfg.broker_mode == "mock":
        return MockBroker(cfg)
    raise ValueError(f"Nieznany broker_mode: {cfg.broker_mode}")


def setup_logging(cfg: Config) -> logging.Logger:
    """Konfiguruj logowanie do konsoli i opcjonalnie do pliku."""
    handlers = [logging.StreamHandler(sys.stdout)]
    if cfg.log_file:
        handlers.append(logging.FileHandler(cfg.log_file, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, cfg.log_level),
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    return logging.getLogger("main")


def run_cycle(
    collector: MarketDataCollector,
    prompt_builder: PromptBuilder,
    llm: GeminiClient,
    parser: ResponseParser,
    risk: RiskManager,
    broker,
    log: logging.Logger,
    cycle_number: int,
) -> None:
    """
    Jeden pełny cykl decyzyjny agenta.
    Wydzielony żeby czytelnie obsłużyć błędy i logować każdy etap.
    """
    log.info(f"─── Cykl #{cycle_number} ───────────────────────────────")

    # ── Krok 1: Pobierz dane rynkowe ──────────────────────────────
    log.info("Krok 1/6: Pobieranie danych rynkowych...")
    snapshot = collector.fetch()
    log.info(
        f"  Cena: ${snapshot.price:,.2f} | "
        f"RSI: {snapshot.rsi_14} | "
        f"Trend: {snapshot.trend} | "
        f"Vol ratio: {snapshot.volume_ratio}x"
    )

    # ── Krok 2: Pobierz stan portfela ─────────────────────────────
    log.info("Krok 2/6: Odczyt stanu portfela...")
    portfolio = broker.get_portfolio({snapshot.symbol: snapshot.price})
    log.info(
        f"  Wolny kapitał: ${portfolio['free_capital']:,.2f} | "
        f"Łącznie: ${portfolio['total_value']:,.2f} | "
        f"Dzienna P&L: {portfolio['daily_pnl_pct']:+.2f}%"
    )

    # ── Krok 3: Zbuduj prompt i zapytaj Gemini ────────────────────
    log.info("Krok 3/6: Budowanie promptu i wywołanie Gemini...")
    user_message = prompt_builder.build(snapshot, portfolio)
    raw_response = llm.decide(user_message)
    log.debug(f"  Surowa odpowiedź Gemini:\n{raw_response}")

    # ── Krok 4: Parsuj odpowiedź ──────────────────────────────────
    log.info("Krok 4/6: Parsowanie decyzji...")
    decision = parser.parse(raw_response)
    log.info(f"  {decision}")


    if not decision.is_valid:
        log.error(f"  Błąd parsowania: {decision.parse_error}")
        return

    # ── Krok 5: Sprawdzenie ryzyka ────────────────────────────────
    log.info("Krok 5/6: Sprawdzenie limitów ryzyka...")
    risk_result = risk.check(decision, portfolio, snapshot)
    log.info(f"  {risk_result}")

    if not risk_result:
        return  # Decyzja zablokowana — nie wykonuj

    if risk_result.forced_action:
        log.warning(
            f"Risk manager wymusza {risk_result.forced_action}: {risk_result.reason}"
        )
        decision.action = risk_result.forced_action

    # ── Krok 6: Wykonaj zlecenie ──────────────────────────────────
    if decision.is_actionable:
        log.info("Krok 6/6: Wykonywanie zlecenia...")
        result = broker.execute(decision, snapshot)
        log.info(f"  {result}")
    else:
        log.info("Krok 6/6: HOLD — brak zlecenia do wykonania")


def main():
    cfg = Config()
    log = setup_logging(cfg)

    log.info("=" * 60)
    log.info("🤖 AGENT HANDLOWY AI — START")
    log.info(f"   Symbol:   {cfg.symbol}")
    log.info(f"   Dane:     {cfg.market_data_source}")
    log.info(f"   Broker:   {cfg.broker_mode}")
    log.info(f"   Model:    {cfg.gemini_model}")
    log.info(f"   Interwał: {cfg.interval_seconds}s")
    log.info(f"   Kapitał:  ${cfg.initial_capital_usd:,.2f}")
    log.info("=" * 60)

    # Inicjalizacja wszystkich komponentów
    collector = MarketDataCollector(cfg)
    prompt_builder = PromptBuilder(cfg)
    llm = GeminiClient(cfg)
    parser = ResponseParser()
    risk = RiskManager(cfg)
    broker = create_broker(cfg)

    # Załaduj system prompt do Gemini (raz)
    llm.set_system_prompt(PromptBuilder.get_system_prompt())

    # Graceful shutdown — Ctrl+C wydrukuje podsumowanie
    def handle_shutdown(sig, frame):
        log.info("\nAgent zatrzymany przez użytkownika.")
        broker.print_summary()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # ── Główna pętla ──────────────────────────────────────────────
    cycle = 0
    while True:
        cycle += 1
        try:
            run_cycle(
                collector, prompt_builder, llm, parser, risk, broker, log, cycle
            )
        except Exception as e:
            log.error(f"Błąd w cyklu #{cycle}: {e}", exc_info=True)
            log.info("Agent kontynuuje po błędzie...")

        log.info(f"Czekam {cfg.interval_seconds}s do kolejnego cyklu...\n")
        time.sleep(cfg.interval_seconds)


if __name__ == "__main__":
    main()
