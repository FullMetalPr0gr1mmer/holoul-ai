# Holoul AI Assistant — RAG + Text-to-SQL demo

A small, self-contained demo built for **Holoul Electronic Recycling**. It lets
anyone ask questions in plain English and get answers from two sources:

- **Operational data** → converted to SQL, run against a database, and explained
  (*"What is the total overdue invoice amount by sector?"*).
- **Company knowledge** → answered from Holoul's service, policy, and compliance
  documents with citations (*"What data destruction methods do you offer?"*).

All data here is **fictional** and generated locally — it is only for
demonstrating the capability, not real Holoul records.

---

## What's inside

| Capability | How it works |
|---|---|
| **Text-to-SQL** | Full schema is given to the model, which writes a query. The query is guarded (read-only, allow-listed tables), validated with `EXPLAIN`, executed against SQLite, and **self-corrects once** if it errors. |
| **Hybrid RAG** | Documents are chunked and indexed with **both** semantic embeddings (dense) and **BM25** keyword search (sparse); scores are fused so both meaning and exact terms are matched. Answers cite their sources. |
| **Smart routing** | A lightweight classifier decides whether a question needs the database, the documents, or a plain reply. |
| **Provider-agnostic** | Runs on **Anthropic Claude**, **OpenAI**, or a **local Ollama** install — auto-detected. No cloud account needed for the local path. |

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Build the demo database (one time)

```bash
python data/build_db.py
```

This creates `data/holoul.db` with fictional customers, pickups, materials,
invoices, data-destruction jobs, and shipments.

### 3. Choose a model provider

**Option A — Local & free (Ollama), recommended for a live demo**

```bash
# once: install Ollama from https://ollama.com then pull the models
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

Nothing else to configure — `LLM_PROVIDER` defaults to `auto` and falls back to
Ollama.

**Option B — Anthropic Claude (best quality)**

```bash
pip install anthropic
cp .env.example .env      # then set ANTHROPIC_API_KEY in .env
```

**Option C — OpenAI**

```bash
pip install openai
cp .env.example .env      # then set OPENAI_API_KEY in .env
```

**Option D — Google Gemini (free tier)**

No SDK needed — Gemini is called over REST. In `.env`:

```
LLM_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_EMBEDDING_MODEL=text-embedding-004
```

> **Behind a corporate SSL proxy?** `truststore` (in requirements) makes Python
> trust the OS certificate store, so cloud calls work without disabling
> verification. If a proxy still blocks it, set `INSECURE_TLS=1` in `.env` as a
> last resort.

> Embeddings power the *dense* half of retrieval. They come from OpenAI (if a key
> is set) or Ollama (`nomic-embed-text`). If neither is reachable, RAG
> automatically falls back to **BM25-only** keyword search and still works.

### 4. Run

```bash
streamlit run app.py
```

Then open the browser tab Streamlit prints (usually http://localhost:8501).

---

## Example questions

**Data (Text-to-SQL)**
- Total weight of e-waste collected per material category?
- Top 5 customers by total invoiced amount?
- How many data destruction jobs used degaussing?
- Total overdue invoice amount by sector?
- Which facility processed the most pickups?

**Knowledge (RAG)**
- What data destruction methods does Holoul offer?
- Which materials do you not accept?
- What certifications does Holoul hold?

---

## Project layout

```
holoul-ai-demo/
├── app.py                  # Streamlit chat UI
├── config.py               # env-driven settings + provider defaults
├── core/
│   ├── llm.py              # LLM abstraction (Claude / OpenAI / Ollama)
│   ├── embeddings.py       # embedding abstraction (OpenAI / Ollama)
│   ├── schema.py           # DDL description + table allowlist
│   ├── text2sql.py         # generate → guard → EXPLAIN → run → self-correct
│   ├── rag.py              # hybrid retrieval (dense + BM25) + grounded answers
│   └── router.py           # database / documents / chat classifier
└── data/
    ├── build_db.py         # creates + seeds the fictional SQLite database
    └── documents/          # knowledge base (services, policies, compliance…)
```

---

## Safety notes

- The Text-to-SQL engine connects to SQLite in **read-only** mode and rejects any
  statement that isn't a single `SELECT`/`WITH`, so generated queries can never
  modify data.
- Generated SQL and retrieval sources are always shown in the UI for
  transparency.
