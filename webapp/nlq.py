"""Natural-language querying: question -> SQL -> answer.

The model is given the real schema and asked for one SELECT. It never sees
the IFC file and never produces a number itself — the number comes from
SQLite executing the SQL it wrote, and the SQL is shown to the user so the
answer can be checked.

This is deliberately the opposite of what IFCflow's `server-python-executor.ts`
does. That file regex-matches Python source and reimplements it in TypeScript,
so a question it does not recognise gets a plausible wrong answer. Here, when
no model is configured, the endpoint says so and offers the example queries.
Nothing is ever faked.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from . import sql_export

DEFAULT_MODEL = "gpt-4o-mini"
TIMEOUT_S = 60

SYSTEM_PROMPT = """\
You translate questions about a building model into SQLite SELECT statements.

Rules:
- Reply with the SQL only. No prose, no explanation, no markdown fences.
- Exactly one statement. It must start with SELECT or WITH.
- Use only tables and columns that appear in the schema given to you.
- If the question cannot be answered from this schema, reply with exactly:
  CANNOT_ANSWER
"""


def provider() -> Optional[dict[str, str]]:
    """Resolve an OpenAI-compatible endpoint from the environment."""
    if os.environ.get("OPENAI_API_KEY"):
        return {
            "key": os.environ["OPENAI_API_KEY"],
            "url": os.environ.get("OPENAI_BASE_URL",
                                  "https://api.openai.com/v1") + "/chat/completions",
            "model": os.environ.get("IFC_NLQ_MODEL", DEFAULT_MODEL),
            "name": "openai",
        }
    if os.environ.get("OPENROUTER_API_KEY"):
        return {
            "key": os.environ["OPENROUTER_API_KEY"],
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "model": os.environ.get("IFC_NLQ_MODEL", "openai/gpt-4o-mini"),
            "name": "openrouter",
        }
    return None


def available() -> bool:
    return provider() is not None


def _strip_fences(text: str) -> str:
    text = text.strip()
    fenced = re.match(r"^```(?:sql)?\s*(.*?)```$", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    return text.strip().rstrip(";").strip()


def _call_model(prompt: str, question: str) -> str:
    cfg = provider()
    assert cfg is not None
    body = json.dumps({
        "model": cfg["model"],
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{prompt}\n\nQuestion: {question}\n\nSQL:"},
        ],
    }).encode()

    request = urllib.request.Request(
        cfg["url"], data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg['key']}"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        payload = json.loads(response.read())
    return payload["choices"][0]["message"]["content"]


def ask(db_path: str, question: str) -> dict[str, Any]:
    cfg = provider()
    if cfg is None:
        return {
            "available": False,
            "error": "No language model is configured.",
            "hint": ("Set OPENAI_API_KEY or OPENROUTER_API_KEY before starting "
                     "the server to enable natural-language questions. The SQL "
                     "console and the example queries work without it."),
            "examples": sql_export.EXAMPLE_QUERIES,
        }

    prompt = (
        "Schema:\n" + sql_export.schema_text(db_path) + "\n\n"
        + sql_export.SCHEMA_NOTES + "\n"
        + "Worked examples:\n"
        + "\n".join(f"-- {q['label']}\n{q['sql']}" for q in sql_export.EXAMPLE_QUERIES)
    )

    try:
        raw = _call_model(prompt, question)
    except urllib.error.HTTPError as exc:
        return {"available": True, "error": f"Model API error {exc.code}: "
                                            f"{exc.read()[:200].decode('utf-8', 'replace')}"}
    except Exception as exc:
        return {"available": True, "error": f"Could not reach the model: {exc}"}

    sql = _strip_fences(raw)
    if sql.upper().startswith("CANNOT_ANSWER"):
        return {"available": True, "question": question,
                "error": "That question cannot be answered from this model's data."}

    result = sql_export.query(db_path, sql)
    result["available"] = True
    result["question"] = question
    result["model"] = cfg["model"]
    return result
