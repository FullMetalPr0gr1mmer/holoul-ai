"""
Central configuration for the Holoul AI demo.

All settings are read from environment variables (optionally from a local .env
file). Nothing here is Holoul- or provider-specific beyond sensible defaults, so
the same code runs against Anthropic Claude, OpenAI, or a local Ollama install.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "holoul.db"
DOCS_DIR = DATA_DIR / "documents"


def _load_dotenv() -> None:
    """Minimal .env loader so we don't need python-dotenv as a dependency."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # Don't clobber variables already set in the real environment.
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# ── TLS / corporate proxy handling ────────────────────────────────────
# On networks that intercept SSL (e.g. corporate proxies), Python's default
# certificate bundle won't trust the injected root CA. `truststore` makes
# Python validate against the OS trust store instead — keeping verification on.
try:  # best effort; harmless if truststore isn't installed
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

# Last-resort escape hatch for stubborn proxies. Prefer leaving this off.
INSECURE_TLS = os.getenv("INSECURE_TLS", "0").lower() in ("1", "true", "yes")
TLS_VERIFY = not INSECURE_TLS
if INSECURE_TLS:
    try:
        import urllib3

        urllib3.disable_warnings()
    except Exception:
        pass

# ── Provider selection ────────────────────────────────────────────────
# "auto" resolves to the first available of: anthropic -> openai -> ollama.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").lower()
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "auto").lower()

# ── Anthropic (Claude) ────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")

# ── OpenAI ────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# ── Google Gemini ─────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

# ── Ollama (local fallback — free, no API key) ────────────────────────
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")

# ── RAG tuning ────────────────────────────────────────────────────────
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "700"))          # characters
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))    # characters
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
# Weight of dense (semantic) vs sparse (BM25) score in hybrid fusion.
DENSE_WEIGHT = float(os.getenv("DENSE_WEIGHT", "0.5"))
