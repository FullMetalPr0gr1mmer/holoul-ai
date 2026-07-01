"""
Text-to-SQL engine.

Pipeline:  question -> generate SQL (full schema in prompt) -> validate & guard
           -> EXPLAIN (compile check) -> execute read-only -> [self-correct on error]

Safety layers (defence in depth):
  1. Read-only SQLite connection (mode=ro) — the engine physically cannot write.
  2. Keyword guard — reject anything that isn't a single SELECT/WITH statement.
  3. Table allowlist — reject references to unknown tables.
  4. EXPLAIN QUERY PLAN — catch malformed SQL before running it.
  5. Self-correction — on an execution error, feed the error back to the model once.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field

import config
from core.llm import get_llm
from core.schema import ALLOWED_TABLES, SCHEMA_DDL

logger = logging.getLogger(__name__)

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|"
    r"DETACH|PRAGMA|VACUUM|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
MAX_ROWS = 200

_SYSTEM = (
    "You are an expert SQLite analyst. Convert the user's question into ONE "
    "valid SQLite SELECT query.\n\n"
    "RULES:\n"
    "1. Use ONLY the tables and columns in the schema below — never invent names.\n"
    "2. SQLite dialect: use LIMIT (not TOP); date()/strftime() for dates.\n"
    "3. Read-only: output a single SELECT (or WITH ... SELECT). Never write data.\n"
    "4. Join only via the documented relationships.\n"
    "5. For text filters, use the EXACT values from the schema comments "
    "(string comparison is case-sensitive), e.g. status = 'Completed'.\n"
    "6. Return ONLY the SQL — no markdown fences, no commentary, no trailing semicolon.\n\n"
    f"{SCHEMA_DDL}"
)


@dataclass
class SQLResult:
    question: str
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    error: str | None = None
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.sql)


class Text2SQL:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = str(db_path or config.DB_PATH)
        self.llm = get_llm()

    # ── generation ─────────────────────────────────────────────────────
    def _generate(self, question: str, prior_error: str | None = None, prior_sql: str = "") -> str:
        prompt = f"Question: {question}"
        if prior_error:
            prompt = (
                f"Question: {question}\n\n"
                f"Your previous SQL failed:\n{prior_sql}\n\n"
                f"Error: {prior_error}\n\n"
                "Return a corrected single SELECT query."
            )
        raw = self.llm.complete(prompt, system=_SYSTEM, max_tokens=600, temperature=0.0)
        return self._clean(raw)

    @staticmethod
    def _clean(text: str) -> str:
        text = re.sub(r"```sql|```", "", text, flags=re.IGNORECASE).strip()
        # Keep from the first SELECT/WITH onward (drop any preamble).
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.strip().upper().startswith(("SELECT", "WITH")):
                text = "\n".join(lines[i:])
                break
        return text.strip().rstrip(";").strip()

    # ── validation / guard ─────────────────────────────────────────────
    def _guard(self, sql: str) -> str | None:
        """Return an error string if the SQL is unsafe/invalid, else None."""
        if not sql:
            return "No SQL was generated."
        head = sql.lstrip().upper()
        if not (head.startswith("SELECT") or head.startswith("WITH")):
            return "Only SELECT queries are allowed."
        if _FORBIDDEN.search(sql):
            return "Data-modifying or administrative statements are not permitted."
        if ";" in sql.rstrip(";"):
            return "Multiple statements are not allowed."
        if sql.count("(") != sql.count(")"):
            return "Unbalanced parentheses in the generated SQL."
        # Table allowlist: every FROM/JOIN target must be a known table (or CTE).
        cte_names = {m.lower() for m in re.findall(r"\bWITH\s+(\w+)\s+AS", sql, re.IGNORECASE)}
        cte_names |= {m.lower() for m in re.findall(r"\)\s*,\s*(\w+)\s+AS", sql, re.IGNORECASE)}
        referenced = re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", sql, re.IGNORECASE)
        allowed = {t.lower() for t in ALLOWED_TABLES} | cte_names
        unknown = [t for t in referenced if t.lower() not in allowed]
        if unknown:
            return f"Query references unknown table(s): {', '.join(sorted(set(unknown)))}."
        return None

    # ── execution ──────────────────────────────────────────────────────
    def _connect_ro(self) -> sqlite3.Connection:
        # Read-only URI connection — writes are impossible even if guards miss something.
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def _execute(self, sql: str) -> tuple[list[str], list[tuple]]:
        conn = self._connect_ro()
        try:
            cur = conn.cursor()
            cur.execute(f"EXPLAIN QUERY PLAN {sql}")  # compile check, no data touched
            cur.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(MAX_ROWS)
            return columns, rows
        finally:
            conn.close()

    # ── public API ─────────────────────────────────────────────────────
    def run(self, question: str) -> SQLResult:
        result = SQLResult(question=question)
        prior_error, prior_sql = None, ""
        for attempt in range(1, 3):  # one initial try + one self-correction
            result.attempts = attempt
            sql = self._generate(question, prior_error, prior_sql)
            result.sql = sql

            guard_error = self._guard(sql)
            if guard_error:
                result.error = guard_error
                return result  # guard failures are not retried — the query is unsafe

            try:
                result.columns, result.rows = self._execute(sql)
                result.error = None
                return result
            except sqlite3.Error as exc:
                logger.warning("SQL attempt %d failed: %s", attempt, exc)
                result.error = str(exc)
                prior_error, prior_sql = str(exc), sql
        return result


_engine: Text2SQL | None = None


def get_text2sql() -> Text2SQL:
    global _engine
    if _engine is None:
        _engine = Text2SQL()
    return _engine
