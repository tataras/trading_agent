"""
agent/gemini_client.py - Warstwa 3: komunikacja z Gemini API.

Ta klasa zachowuje prosty interfejs klienta LLM:
set_system_prompt() oraz decide(). Reszta agenta nie musi wiedziec,
ktory provider LLM jest uzywany pod spodem.
"""

import logging

from google import genai
from google.genai import types

log = logging.getLogger(__name__)


class GeminiClient:
    """Opakowanie Google Gen AI SDK dla Gemini API."""

    def __init__(self, config):
        self.cfg = config

        if not config.gemini_api_key:
            raise ValueError(
                "Brak GEMINI_API_KEY. Ustaw zmienna srodowiskowa GEMINI_API_KEY "
                "albo dodaj ja do pliku .env."
            )

        self.client = genai.Client(api_key=config.gemini_api_key)
        self._system_prompt: str | None = None

    def set_system_prompt(self, system_prompt: str) -> None:
        """Zapamietaj system prompt. Wywolywane raz przy starcie."""
        self._system_prompt = system_prompt

    def decide(self, user_message: str) -> str:
        """
        Wyslij dane rynkowe do Gemini i odbierz decyzje jako JSON string.
        """
        if not self._system_prompt:
            raise RuntimeError("System prompt nie ustawiony. Wywolaj set_system_prompt() najpierw.")

        log.debug(
            "Wysylam prompt (%s znakow) do %s",
            len(user_message),
            self.cfg.gemini_model,
        )

        response = self.client.models.generate_content(
            model=self.cfg.gemini_model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=self._system_prompt,
                temperature=0.1,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )

        usage = getattr(response, "usage_metadata", None)
        if usage:
            input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
            total_tokens = getattr(usage, "total_token_count", 0) or input_tokens + output_tokens
            log.info(
                "Tokeny Gemini: wejscie=%s, wyjscie=%s, lacznie=%s",
                input_tokens,
                output_tokens,
                total_tokens,
            )

        return response.text or ""
