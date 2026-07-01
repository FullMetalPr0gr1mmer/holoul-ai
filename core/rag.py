"""
Hybrid RAG engine.

Retrieval combines two signals and fuses them:
  * dense   — semantic similarity via embeddings (cosine)
  * sparse  — BM25 keyword relevance

Scores are min-max normalised per query and blended by DENSE_WEIGHT. If no
embedding provider is reachable, retrieval falls back to BM25-only so the demo
still runs with zero setup. Answers are grounded strictly in retrieved chunks
and cite their sources as [Source N].
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

import config
from core.embeddings import get_embedder
from core.llm import get_llm

logger = logging.getLogger(__name__)

_ANSWER_SYSTEM = (
    "You are Holoul's knowledge assistant. Answer the question using ONLY the "
    "context passages provided. Be specific and concise. Cite every claim with "
    "[Source N] using the passage numbers. If the answer is not in the context, "
    "say: 'I could not find that in the Holoul documents.' Do not invent facts."
)


@dataclass
class Chunk:
    text: str
    source: str
    index: int


@dataclass
class RAGAnswer:
    question: str
    answer: str
    sources: list[dict] = field(default_factory=list)
    mode: str = "hybrid"  # 'hybrid' or 'bm25-only'


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class RAGEngine:
    def __init__(self, docs_dir: Path | None = None) -> None:
        self.docs_dir = Path(docs_dir or config.DOCS_DIR)
        self.llm = get_llm()
        self.embedder = get_embedder()
        self.chunks: list[Chunk] = []
        self.bm25: BM25Okapi | None = None
        self.matrix: np.ndarray | None = None  # dense embeddings (n_chunks, dim)
        self.dense_ready = False
        self._build_index()

    # ── indexing ───────────────────────────────────────────────────────
    def _chunk_text(self, text: str, source: str) -> list[Chunk]:
        size, overlap = config.CHUNK_SIZE, config.CHUNK_OVERLAP
        chunks, start, idx = [], 0, 0
        text = text.strip()
        while start < len(text):
            end = start + size
            # Prefer to break on a paragraph or sentence boundary.
            if end < len(text):
                window = text[start:end]
                brk = max(window.rfind("\n\n"), window.rfind(". "))
                if brk > size * 0.5:
                    end = start + brk + 1
            piece = text[start:end].strip()
            if piece:
                chunks.append(Chunk(text=piece, source=source, index=idx))
                idx += 1
            start = end - overlap if end - overlap > start else end
        return chunks

    def _build_index(self) -> None:
        if not self.docs_dir.exists():
            logger.warning("Docs dir %s missing — RAG has no documents.", self.docs_dir)
            return
        for path in sorted(self.docs_dir.glob("*.md")) + sorted(self.docs_dir.glob("*.txt")):
            self.chunks.extend(self._chunk_text(path.read_text(encoding="utf-8"), path.name))

        if not self.chunks:
            return

        # Sparse index (always available).
        self.bm25 = BM25Okapi([_tokenize(c.text) for c in self.chunks])

        # Dense index (best-effort, cached to disk).
        if self.embedder.available:
            try:
                mat = self._load_or_embed()
                norms = np.linalg.norm(mat, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self.matrix = mat / norms
                self.dense_ready = True
                logger.info("RAG index: %d chunks, dense=%s", len(self.chunks), self.matrix.shape)
            except Exception as exc:  # pragma: no cover - env dependent
                logger.warning("Dense index unavailable (%s) — BM25-only.", exc)
        else:
            logger.info("No embedding provider — RAG runs BM25-only.")

    def _cache_key(self) -> str:
        """Fingerprint of the corpus + embedding config; changes invalidate cache."""
        meta = f"{self.embedder.provider}:{self.embedder.model}:{config.CHUNK_SIZE}:{config.CHUNK_OVERLAP}"
        blob = meta + "||" + "||".join(c.text for c in self.chunks)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _load_or_embed(self) -> np.ndarray:
        """Return the chunk embedding matrix, using a disk cache when valid."""
        cache_path = config.DATA_DIR / ".rag_cache.npz"
        key = self._cache_key()
        if cache_path.exists():
            try:
                data = np.load(cache_path, allow_pickle=False)
                if str(data["key"]) == key:
                    logger.info("RAG dense index loaded from cache (%d chunks).", len(self.chunks))
                    return data["matrix"].astype(np.float32)
            except Exception:
                pass  # stale/corrupt cache — re-embed below
        mat = np.asarray(self.embedder.embed([c.text for c in self.chunks]), dtype=np.float32)
        try:
            np.savez(cache_path, key=np.array(key), matrix=mat)
        except Exception as exc:  # pragma: no cover - fs dependent
            logger.warning("Could not write RAG cache: %s", exc)
        return mat

    # ── retrieval ──────────────────────────────────────────────────────
    @staticmethod
    def _normalize(scores: np.ndarray) -> np.ndarray:
        lo, hi = float(scores.min()), float(scores.max())
        if hi - lo < 1e-9:
            return np.zeros_like(scores)
        return (scores - lo) / (hi - lo)

    def retrieve(self, query: str, k: int | None = None) -> tuple[list[tuple[Chunk, float]], str]:
        k = k or config.RAG_TOP_K
        if not self.chunks or self.bm25 is None:
            return [], "empty"

        sparse = np.asarray(self.bm25.get_scores(_tokenize(query)), dtype=np.float32)

        if self.dense_ready and self.matrix is not None:
            qvec = np.asarray(self.embedder.embed([query])[0], dtype=np.float32)
            qnorm = np.linalg.norm(qvec) or 1.0
            dense = self.matrix @ (qvec / qnorm)
            fused = config.DENSE_WEIGHT * self._normalize(dense) + (1 - config.DENSE_WEIGHT) * self._normalize(sparse)
            mode = "hybrid"
        else:
            fused = self._normalize(sparse)
            mode = "bm25-only"

        top = np.argsort(fused)[::-1][:k]
        return [(self.chunks[i], float(fused[i])) for i in top], mode

    # ── answer generation ──────────────────────────────────────────────
    def answer(self, question: str) -> RAGAnswer:
        hits, mode = self.retrieve(question)
        if not hits:
            return RAGAnswer(question, "No documents are indexed yet.", [], mode)

        context = "\n\n".join(f"[Source {i}] ({c.source})\n{c.text}" for i, (c, _) in enumerate(hits, 1))
        prompt = f"Context passages:\n{context}\n\nQuestion: {question}\n\nAnswer with citations:"
        answer = self.llm.complete(prompt, system=_ANSWER_SYSTEM, max_tokens=700, temperature=0.1)

        sources = [
            {"n": i, "source": c.source, "score": round(score, 3), "snippet": c.text[:220].strip() + "…"}
            for i, (c, score) in enumerate(hits, 1)
        ]
        return RAGAnswer(question=question, answer=answer, sources=sources, mode=mode)


_engine: RAGEngine | None = None


def get_rag() -> RAGEngine:
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine
