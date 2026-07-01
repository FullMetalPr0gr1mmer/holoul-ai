"""
Holoul AI Assistant — Streamlit demo.

A chat interface over dummy e-waste recycling data that showcases:
  * Text-to-SQL  — ask about operational data in natural language
  * Hybrid RAG   — ask about services, policies, and compliance
  * Smart routing between the two (plus plain chat)

Run:  streamlit run app.py
"""
from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

import config
from core import router
from core.llm import get_llm
from core.rag import get_rag
from core.text2sql import get_text2sql

st.set_page_config(page_title="Holoul AI Assistant", page_icon="♻️", layout="wide")

EXAMPLE_DB = [
    "What is the total weight of e-waste collected per material category?",
    "Who are the top 5 customers by total invoiced amount?",
    "How many data destruction jobs used degaussing?",
    "What is the total overdue invoice amount by sector?",
    "Which facility processed the most pickups?",
    "How much recovered value came from circuit boards and mobile phones?",
]
EXAMPLE_DOCS = [
    "What data destruction methods does Holoul offer?",
    "Which materials do you not accept?",
    "What certifications does Holoul hold?",
    "How does the e-waste recycling process work?",
]


# ── cached engines ────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Loading Text-to-SQL engine…")
def _sql_engine():
    return get_text2sql()


@st.cache_resource(show_spinner="Building document index…")
def _rag_engine():
    return get_rag()


@st.cache_data(show_spinner=False)
def _db_stats() -> dict:
    if not config.DB_PATH.exists():
        return {}
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    try:
        stats = {}
        for table in ["customers", "pickups", "invoices", "data_destruction_jobs", "shipments"]:
            stats[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return stats
    finally:
        conn.close()


def _summarize_rows(question: str, columns: list[str], rows: list[tuple]) -> str:
    """Turn a small result set into a one/two-sentence natural-language answer."""
    if not rows:
        return "The query ran successfully but returned no rows."
    preview = [dict(zip(columns, r)) for r in rows[:30]]
    prompt = (
        f"Question: {question}\n\nQuery result (JSON rows):\n{preview}\n\n"
        "Answer the question in 1-2 sentences using these numbers. Be precise; "
        "do not invent values. Amounts are in SAR, weights in kg."
    )
    try:
        return get_llm().complete(prompt, max_tokens=220, temperature=0.1)
    except Exception:
        return "Here are the results:"


# ── sidebar ───────────────────────────────────────────────────────────
def render_sidebar() -> str:
    st.sidebar.title("♻️ Holoul AI")
    st.sidebar.caption("RAG + Text-to-SQL demo on dummy recycling data")

    llm = get_llm()
    rag = _rag_engine()
    st.sidebar.subheader("Engine")
    st.sidebar.markdown(
        f"- **LLM:** `{llm.provider}` · `{llm.model}`\n"
        f"- **Retrieval:** {'hybrid (dense + BM25)' if rag.dense_ready else 'BM25 keyword only'}"
    )

    stats = _db_stats()
    if stats:
        st.sidebar.subheader("Database")
        st.sidebar.markdown("\n".join(f"- {k}: **{v}**" for k, v in stats.items()))
    else:
        st.sidebar.error("Database not found. Run `python data/build_db.py` first.")

    mode = st.sidebar.radio(
        "Routing", ["Auto", "Database (SQL)", "Documents (RAG)"], index=0,
        help="Auto lets the router pick; the others force a path.",
    )

    st.sidebar.subheader("Try asking")
    for q in EXAMPLE_DB + EXAMPLE_DOCS:
        if st.sidebar.button(q, key=f"ex_{q}", use_container_width=True):
            st.session_state.pending = q
    return mode


# ── answer handlers ───────────────────────────────────────────────────
def handle_database(question: str) -> dict:
    result = _sql_engine().run(question)
    payload = {"kind": "database", "sql": result.sql, "attempts": result.attempts}
    if not result.ok:
        payload["error"] = result.error
        return payload
    payload["columns"] = result.columns
    payload["rows"] = result.rows
    payload["summary"] = _summarize_rows(question, result.columns, result.rows)
    return payload


def handle_documents(question: str) -> dict:
    ans = _rag_engine().answer(question)
    return {"kind": "documents", "answer": ans.answer, "sources": ans.sources, "mode": ans.mode}


def handle_chat(question: str) -> dict:
    system = (
        "You are the assistant for Holoul, an e-waste recycling company. Be brief "
        "and friendly. If the user asks about data or services, invite them to ask a "
        "specific question."
    )
    return {"kind": "chat", "answer": get_llm().complete(question, system=system, max_tokens=300, temperature=0.4)}


def answer_question(question: str, mode: str) -> dict:
    try:
        if mode == "Database (SQL)":
            intent = router.DATABASE
        elif mode == "Documents (RAG)":
            intent = router.DOCUMENTS
        else:
            intent = router.classify(question)

        if intent == router.DATABASE:
            result = handle_database(question)
        elif intent == router.DOCUMENTS:
            result = handle_documents(question)
        else:
            result = handle_chat(question)
        result["routed"] = intent
        return result
    except Exception as exc:  # keep the demo friendly — no raw tracebacks in the UI
        return {"kind": "error", "message": str(exc)}


# ── rendering ─────────────────────────────────────────────────────────
_ROUTE_LABELS = {
    "database": "🗄️ Database (Text-to-SQL)",
    "documents": "📚 Documents (RAG)",
    "chat": "💬 Chat",
}


def render_payload(payload: dict) -> None:
    kind = payload["kind"]
    routed = payload.get("routed")
    if routed in _ROUTE_LABELS:
        st.caption(f"Routed to: {_ROUTE_LABELS[routed]}")
    if kind == "database":
        if payload.get("error"):
            st.error(f"Couldn't answer from the database: {payload['error']}")
        else:
            st.markdown(payload.get("summary", ""))
            if payload["rows"]:
                df = pd.DataFrame(payload["rows"], columns=payload["columns"])
                st.dataframe(df, use_container_width=True, hide_index=True)
        with st.expander(f"Generated SQL · {payload.get('attempts', 1)} attempt(s)"):
            st.code(payload.get("sql", ""), language="sql")
    elif kind == "documents":
        st.markdown(payload["answer"])
        st.caption(f"Retrieval: {payload.get('mode', 'hybrid')}")
        for s in payload.get("sources", []):
            with st.expander(f"[Source {s['n']}] {s['source']} · score {s['score']}"):
                st.write(s["snippet"])
    elif kind == "error":
        st.warning("The AI service is busy right now — please try again in a moment.")
        with st.expander("Technical details"):
            st.write(payload.get("message", ""))
    else:
        st.markdown(payload["answer"])


# ── main ──────────────────────────────────────────────────────────────
def main() -> None:
    mode = render_sidebar()
    st.title("Holoul AI Assistant")
    st.caption("Ask about operational data (Text-to-SQL) or services & policies (RAG). Demo data is fictional.")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                render_payload(msg["payload"])

    question = st.chat_input("Ask about Holoul's data, services, or policies…")
    if not question and st.session_state.get("pending"):
        question = st.session_state.pop("pending")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                payload = answer_question(question, mode)
            render_payload(payload)
        st.session_state.messages.append({"role": "assistant", "payload": payload})


if __name__ == "__main__":
    main()
