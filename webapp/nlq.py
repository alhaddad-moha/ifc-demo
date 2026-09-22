"""Natural-language querying: question -> SQL -> answer.

The model is given the real schema and asked for one SELECT. It never sees
the IFC file and never produces a number itself — the number comes from
SQLite executing the SQL it wrote, and the SQL is shown to the user so the
answer can be checked.

The model may also write the *wording* of the answer, as a template with
{column} placeholders ("There are {n} walls"). The server fills the
placeholders from the result rows. A template containing any digit of its own
is thrown away, so every number the user reads still comes from SQLite.

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
You answer questions about a building model (IFC file) and its audit by
writing one SQLite SELECT statement against the schema you are given.

Reply with a JSON object and nothing else:
{"sql": "<one SELECT or WITH statement>",
 "answer": "<one short sentence for the user>"}

Rules for "sql":
- Exactly one statement, starting with SELECT or WITH.
- Use only tables and columns that appear in the schema.
- Give result columns short readable aliases (e.g. AS walls, AS issues).
- For "what are the biggest/most serious issues", order by severity_rank
  then by count, and limit to the top 10.

Rules for "answer":
- It is a TEMPLATE. Refer to values from the FIRST result row as {alias},
  and to the number of rows as {row_count}. Example:
  "The model contains {walls} walls on {storeys} storeys."
- NEVER write a number or any digit yourself. Every number must come from a
  placeholder. For lists, write an intro such as "The most serious issues:".

If the question cannot be answered from this schema, reply with exactly:
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


def _parse(raw: str) -> tuple[str, Optional[str]]:
    """Model reply -> (sql, answer template). Accepts the JSON object the
    prompt asks for, and falls back to treating the reply as bare SQL."""
    text = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)```$", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    if '"sql"' in text and "{" in text:
        try:
            obj = json.loads(text[text.index("{"):text.rindex("}") + 1])
            return _strip_fences(str(obj.get("sql", ""))), obj.get("answer")
        except (ValueError, AttributeError):
            pass
    return _strip_fences(raw), None


def _fmt(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, float):
        return f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def fill_answer(template: Any, result: dict[str, Any]) -> Optional[str]:
    """Fill {column} / {row_count} from the result. Returns None when the
    template is unusable: not a string, contains a digit of its own, or names
    a column the query did not return."""
    if not isinstance(template, str) or not template.strip() or "error" in result:
        return None
    if re.search(r"\d", re.sub(r"\{[^{}]*\}", "", template)):
        return None
    first = dict(zip(result["columns"], result["rows"][0])) if result["rows"] else {}
    values = {k.lower(): v for k, v in first.items()}
    values["row_count"] = result["row_count"]

    missing: list[str] = []

    def sub(m: "re.Match[str]") -> str:
        key = m.group(1).strip().lower()
        if key not in values:
            missing.append(key)
            return m.group(0)
        return _fmt(values[key])

    text = re.sub(r"\{([^{}]+)\}", sub, template.strip())
    return None if missing else text


def _call_model(prompt: str, question: str) -> str:
    cfg = provider()
    assert cfg is not None
    body = json.dumps({
        "model": cfg["model"],
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{prompt}\n\nQuestion: {question}"},
        ],
    }).encode()

    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {cfg['key']}"}
    # Anthropic keys that are not scoped to a workspace must name one.
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace:
        headers["anthropic-workspace-id"] = workspace
    request = urllib.request.Request(cfg["url"], data=body, headers=headers)
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
        + "\n".join(f"-- {q['label']}\n{q['sql']}"
                    for q in sql_export.EXAMPLE_QUERIES + sql_export.AUDIT_EXAMPLES)
    )

    try:
        raw = _call_model(prompt, question)
    except urllib.error.HTTPError as exc:
        return {"available": True, "error": f"Model API error {exc.code}: "
                                            f"{exc.read()[:200].decode('utf-8', 'replace')}"}
    except Exception as exc:
        return {"available": True, "error": f"Could not reach the model: {exc}"}

    sql, template = _parse(raw)
    if sql.upper().startswith("CANNOT_ANSWER"):
        return {"available": True, "question": question,
                "error": "That question cannot be answered from this model's data."}

    result = sql_export.query(db_path, sql)
    result["answer"] = fill_answer(template, result)
    result["available"] = True
    result["question"] = question
    result["model"] = cfg["model"]
    return result
