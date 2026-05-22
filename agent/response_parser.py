"""
agent/response_parser.py — Warstwa 4: Parsowanie odpowiedzi

Model odpowiada JSONem. Ten moduł konwertuje go na typowany obiekt decyzji.
Obsługuje błędy parsowania — LLM czasem zwraca niedoskonały JSON.
"""

import json
import re
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class TradingDecision:
    """Ustrukturyzowana decyzja handlowa z modelu."""
    action: str           # "BUY", "SELL", "HOLD"
    confidence: int       # 0-100
    reasoning: str        # uzasadnienie
    key_signals: list     # lista kluczowych sygnałów
    risk_note: str        # ostrzeżenie o ryzyku
    raw_response: str     # oryginalna odpowiedź (do debugowania)
    parse_error: str = "" # błąd parsowania jeśli wystąpił

    @property
    def is_valid(self) -> bool:
        return self.action in ("BUY", "SELL", "HOLD") and not self.parse_error

    @property
    def is_actionable(self) -> bool:
        """Czy decyzja wymaga działania (nie HOLD)?"""
        return self.is_valid and self.action != "HOLD"

    def __str__(self) -> str:
        signals = ", ".join(self.key_signals[:3]) if self.key_signals else "brak"
        return (
            f"[{self.action}] confidence={self.confidence}% | "
            f"sygnały: {signals} | "
            f"uzasadnienie: {self.reasoning}"
        )


class ResponseParser:
    """
    Parsuje odpowiedź tekstową modelu na obiekt TradingDecision.

    Problem: LLM może zwrócić JSON z drobnymi błędami formatowania,
    np. dodatkowy tekst przed/po JSON, pojedyncze zamiast podwójnych cudzysłowów.
    Dlatego stosujemy kilka strategii ekstrakcji.
    """

    def parse(self, raw_response: str) -> TradingDecision:
        """
        Główna metoda parsowania.
        Próbuje kilku strategii ekstrakcji JSON.
        """
        log.info(raw_response)
        data = self._extract_json(raw_response)

        if data is None:
            log.error(f"Nie udało się sparsować JSON z odpowiedzi: {raw_response[:200]}")
            return TradingDecision(
                action="HOLD",     # przy błędzie zawsze HOLD — bezpieczeństwo!
                confidence=0,
                reasoning="Błąd parsowania odpowiedzi modelu.",
                key_signals=[],
                risk_note="Parse error — decyzja awaryjnie ustawiona na HOLD.",
                raw_response=raw_response,
                parse_error=f"Nie można sparsować: {raw_response[:100]}"
            )

        # Normalizuj i zbuduj obiekt
        action = str(data.get("action", "HOLD")).upper().strip()
        if action not in ("BUY", "SELL", "HOLD"):
            log.warning(f"Nieznana akcja '{action}' — ustawiam HOLD")
            action = "HOLD"

        confidence = int(data.get("confidence", 50))
        confidence = max(0, min(100, confidence))  # ogranicz do 0-100

        # Jeśli confidence poniżej progu, override do HOLD
        if confidence < 55 and action != "HOLD":
            log.info(f"Confidence {confidence}% < próg 55% — override do HOLD")
            action = "HOLD"

        return TradingDecision(
            action=action,
            confidence=confidence,
            reasoning=str(data.get("reasoning", "")),
            key_signals=list(data.get("key_signals", [])),
            risk_note=str(data.get("risk_note", "")),
            raw_response=raw_response,
        )

    def _extract_json(self, text: str) -> dict | None:
        """
        Próbuje wyciągnąć JSON z tekstu różnymi metodami.

        Metoda 1: Cały tekst to JSON
        Metoda 2: JSON w bloku ```json ... ```
        Metoda 3: Pierwsze '{' do ostatniego '}'
        """
        text = text.strip()

        # Metoda 1: bezpośredni parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Metoda 2: wyciągnij z bloku kodu
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass

        # Metoda 3: znajdź nawiasy klamrowe
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except json.JSONDecodeError:
                pass

        return None
