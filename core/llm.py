"""
Unified LLM client — a thin abstraction over Anthropic Claude, OpenAI, and
local Ollama so the rest of the app never hard-codes a provider.

Design notes
------------
* Provider is resolved once (auto -> anthropic -> openai -> ollama).
* `complete()` is the single entry point: system prompt + user prompt -> text.
* Anthropic calls go through the official `anthropic` SDK. Note that Claude
  Opus/Sonnet 4.7+ reject `temperature`, so we deliberately omit it there.
* Cloud SDKs are imported lazily, so a pure-Ollama demo needs no extra installs.
"""
from __future__ import annotations

import logging

import config

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when no configured LLM provider can serve a request."""


class LLMClient:
    def __init__(self) -> None:
        self.provider = self._resolve_provider()
        self.model = self._model_for(self.provider)
        logger.info("LLMClient ready | provider=%s | model=%s", self.provider, self.model)

    # ── provider resolution ───────────────────────────────────────────
    @staticmethod
    def _resolve_provider() -> str:
        choice = config.LLM_PROVIDER
        if choice != "auto":
            return choice
        if config.ANTHROPIC_API_KEY:
            return "anthropic"
        if config.GEMINI_API_KEY:
            return "gemini"
        if config.OPENAI_API_KEY:
            return "openai"
        return "ollama"

    @staticmethod
    def _model_for(provider: str) -> str:
        return {
            "anthropic": config.ANTHROPIC_MODEL,
            "gemini": config.GEMINI_MODEL,
            "openai": config.OPENAI_MODEL,
            "ollama": config.OLLAMA_MODEL,
        }.get(provider, config.OLLAMA_MODEL)

    # ── public API ────────────────────────────────────────────────────
    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """Return a single completion for `prompt` (optionally with a system prompt)."""
        if self.provider == "anthropic":
            return self._anthropic(prompt, system, max_tokens)
        if self.provider == "gemini":
            return self._gemini(prompt, system, max_tokens, temperature)
        if self.provider == "openai":
            return self._openai(prompt, system, max_tokens, temperature)
        return self._ollama(prompt, system, max_tokens, temperature)

    # ── Anthropic ─────────────────────────────────────────────────────
    def _anthropic(self, prompt: str, system: str | None, max_tokens: int) -> str:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - env dependent
            raise LLMError("anthropic package not installed. Run: pip install anthropic") from exc

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        # No `temperature`: current Claude models reject it.
        resp = client.messages.create(**kwargs)
        return "".join(block.text for block in resp.content if block.type == "text").strip()

    # ── Google Gemini (REST) ──────────────────────────────────────────
    _TRANSIENT = {429, 500, 502, 503, 529}

    def _gemini(self, prompt: str, system: str | None, max_tokens: int, temperature: float) -> str:
        import time

        import requests

        url = f"{config.GEMINI_BASE_URL}/models/{self.model}:generateContent"
        gen_cfg: dict = {"temperature": temperature, "maxOutputTokens": max_tokens}
        # Gemini 2.5 "flash" spends output tokens on hidden reasoning; disable it
        # so short factual answers (SQL, classification) come back directly.
        if "flash" in self.model:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen_cfg,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        resp = None
        for attempt in range(4):  # retry transient overloads (free tier 429/503 etc.)
            try:
                resp = requests.post(
                    url, params={"key": config.GEMINI_API_KEY}, json=body,
                    timeout=120, verify=config.TLS_VERIFY,
                )
                if resp.status_code in self._TRANSIENT:
                    raise requests.HTTPError(f"{resp.status_code} {resp.reason}", response=resp)
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                transient = status in self._TRANSIENT or isinstance(
                    exc, (requests.ConnectionError, requests.Timeout)
                )
                if attempt < 3 and transient:
                    time.sleep(2 * (attempt + 1))
                    continue
                detail = getattr(getattr(exc, "response", None), "text", "") or ""
                raise LLMError(f"Gemini request failed: {exc} {detail[:300]}") from exc

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            reason = data.get("promptFeedback", {}).get("blockReason", "unknown")
            raise LLMError(f"Gemini returned no candidates (blockReason={reason}).")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip()

    # ── OpenAI ────────────────────────────────────────────────────────
    def _openai(self, prompt: str, system: str | None, max_tokens: int, temperature: float) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - env dependent
            raise LLMError("openai package not installed. Run: pip install openai") from exc

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()

    # ── Ollama (local) ────────────────────────────────────────────────
    def _ollama(self, prompt: str, system: str | None, max_tokens: int, temperature: float) -> str:
        import requests

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=180,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(
                f"Could not reach Ollama at {config.OLLAMA_HOST}. Is it running "
                f"(`ollama serve`) and is the model '{self.model}' pulled? ({exc})"
            ) from exc
        return resp.json().get("message", {}).get("content", "").strip()


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    """Return a process-wide LLMClient singleton."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
