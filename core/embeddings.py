"""
Unified embedding client — OpenAI or local Ollama.

Embeddings power the *dense* half of hybrid RAG. If no embedding provider is
reachable, `available` is False and the RAG engine gracefully degrades to
BM25-only keyword search (so the demo still works with zero setup).
"""
from __future__ import annotations

import logging

import config

logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self) -> None:
        self.provider = self._resolve_provider()
        self.model = {
            "openai": config.OPENAI_EMBEDDING_MODEL,
            "gemini": config.GEMINI_EMBEDDING_MODEL,
            "ollama": config.OLLAMA_EMBEDDING_MODEL,
        }.get(self.provider)
        logger.info("EmbeddingClient | provider=%s | model=%s", self.provider, self.model)

    @staticmethod
    def _resolve_provider() -> str | None:
        choice = config.EMBEDDING_PROVIDER
        if choice in ("openai", "gemini", "ollama"):
            return choice
        # auto: OpenAI/Gemini need a key; Ollama is assumed local. Anthropic has
        # no first-party embeddings endpoint, so we never pick it here.
        if config.OPENAI_API_KEY:
            return "openai"
        if config.GEMINI_API_KEY:
            return "gemini"
        return "ollama"

    @property
    def available(self) -> bool:
        """Best-effort check that the chosen embedding backend can be used."""
        if self.provider == "openai":
            return bool(config.OPENAI_API_KEY)
        if self.provider == "gemini":
            return bool(config.GEMINI_API_KEY)
        if self.provider == "ollama":
            try:
                import requests

                requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=3).raise_for_status()
                return True
            except Exception:
                return False
        return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return an embedding vector for each input string."""
        if not texts:
            return []
        if self.provider == "openai":
            return self._openai(texts)
        if self.provider == "gemini":
            return self._gemini(texts)
        return self._ollama(texts)

    def _openai(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        resp = client.embeddings.create(model=self.model, input=texts)
        ordered = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in ordered]

    def _gemini(self, texts: list[str]) -> list[list[float]]:
        import requests

        url = f"{config.GEMINI_BASE_URL}/models/{self.model}:embedContent"
        model_path = f"models/{self.model}"
        vectors: list[list[float]] = []
        for text in texts:
            body = {"model": model_path, "content": {"parts": [{"text": text}]}}
            resp = requests.post(
                url, params={"key": config.GEMINI_API_KEY}, json=body,
                timeout=120, verify=config.TLS_VERIFY,
            )
            resp.raise_for_status()
            vectors.append(resp.json()["embedding"]["values"])
        return vectors

    def _ollama(self, texts: list[str]) -> list[list[float]]:
        import requests

        vectors: list[list[float]] = []
        for text in texts:
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=120,
            )
            resp.raise_for_status()
            vectors.append(resp.json()["embedding"])
        return vectors


_client: EmbeddingClient | None = None


def get_embedder() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
