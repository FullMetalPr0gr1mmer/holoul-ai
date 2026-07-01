"""
Intent router — decides whether a question should be answered from the database
(Text-to-SQL), the document knowledge base (RAG), or as a plain chat reply.

Design: deterministic first, LLM only for genuine ambiguity.

  1. Greeting / trivial      -> chat
  2. Aggregation + a data entity (total/how many/top/average ... of pickups,
     invoices, weight, materials ...) -> database   [high precision]
  3. Policy/service topic with no aggregation        -> documents
  4. Otherwise: a few-shot LLM classification, then a keyword heuristic fallback.

Relying on a single small-model classification proved fragile (e.g. "total
weight per material category" was misrouted to documents), so quantitative
questions are now settled deterministically before the LLM is ever consulted.
"""
from __future__ import annotations

import json
import logging
import re

from core.llm import get_llm

logger = logging.getLogger(__name__)

DATABASE = "database"
DOCUMENTS = "documents"
CHAT = "chat"

# ── deterministic signals ─────────────────────────────────────────────
_GREETING = re.compile(
    r"^\s*(hi|hello|hey|yo|thanks|thank you|good (morning|afternoon|evening)|"
    r"salam|salaam|assalam)\b",
    re.IGNORECASE,
)

# Quantitative intent — the signature of a database query.
_AGG = re.compile(
    r"\b(how many|how much|count|number of|total|sum|average|avg|mean|median|"
    r"highest|lowest|most|least|maximum|minimum|breakdown|compare|"
    r"top\s+\d+|for each|grouped? by|"
    r"per\s+(material|customer|sector|city|facilit|categor|partner|method|status|container))\b",
    re.IGNORECASE,
)

# Nouns that actually exist in the operational database.
_ENTITY = re.compile(
    r"\b(customer|invoice|pickup|weight|kg|kilogram|tonne|material|facilit|"
    r"sector|cit(y|ies)|shipment|device|revenue|value|amount|partner|container|"
    r"collected|recovered|degauss|shred|destruction job|jobs?)\b",
    re.IGNORECASE,
)

# Policy / service / company-info topics that live in the documents.
_POLICY = re.compile(
    r"\b(certif|iso|r2|basel|complian|policy|policies|process|processed|service|"
    r"do you (take|accept|offer|provide|handle)|accept|refuse|step by step|"
    r"how does|how do you|what is holoul|about holoul|region|serve|located|"
    r"address|warranty|chain of custody|cctv|verification|container types?|"
    r"hazardous|not accept)\b",
    re.IGNORECASE,
)

_LLM_SYSTEM = (
    "Classify a question about Holoul, an e-waste recycling company, as exactly "
    "one of: database, documents, chat.\n"
    "- database: needs specific numbers/records (counts, totals, weights, "
    "revenue, invoices, pickups, customers, top-N).\n"
    "- documents: about services, processes, policies, certifications, accepted "
    "materials, company info.\n"
    "- chat: greetings/small talk.\n"
    "Reply with ONLY JSON: {\"intent\": \"database|documents|chat\"}.\n\n"
    "Examples:\n"
    "Q: total weight collected per material category -> {\"intent\": \"database\"}\n"
    "Q: which materials do you not accept -> {\"intent\": \"documents\"}\n"
    "Q: how many pickups are completed -> {\"intent\": \"database\"}\n"
    "Q: what certifications does Holoul hold -> {\"intent\": \"documents\"}\n"
    "Q: top 5 customers by revenue -> {\"intent\": \"database\"}\n"
    "Q: how does data destruction work -> {\"intent\": \"documents\"}"
)


def _llm_classify(question: str) -> str | None:
    try:
        raw = get_llm().complete(
            f"Q: {question}", system=_LLM_SYSTEM, max_tokens=40, temperature=0.0
        )
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            intent = json.loads(match.group(0)).get("intent", "").lower()
            if intent in (DATABASE, DOCUMENTS, CHAT):
                return intent
    except Exception as exc:  # pragma: no cover - env dependent
        logger.warning("LLM classification failed (%s) — using heuristic.", exc)
    return None


def _heuristic(q: str) -> str:
    if _AGG.search(q):
        return DATABASE
    if _POLICY.search(q):
        return DOCUMENTS
    return DOCUMENTS


def classify(question: str) -> str:
    q = question.strip()
    if _GREETING.match(q):
        return CHAT

    has_agg = bool(_AGG.search(q))
    # 1. Quantitative question about real data -> database (settled here).
    if has_agg and _ENTITY.search(q):
        return DATABASE
    # 2. Policy/service topic with no aggregation -> documents.
    if _POLICY.search(q) and not has_agg:
        return DOCUMENTS
    # 3. Ambiguous -> ask the model, then fall back to keywords.
    return _llm_classify(question) or _heuristic(q)
