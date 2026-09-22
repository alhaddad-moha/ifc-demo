"""Test the text-to-SQL plumbing without a real API key.

Stands up a minimal OpenAI-compatible server, points the app at it, and
checks the whole chain: schema assembly -> HTTP call -> markdown-fence
stripping -> safety guard -> execution against the real SQLite database.

The stub deliberately replies inside a ```sql fence, because real models do.

    python tests/test_nlq_stub.py path/to/model.db

With no argument it uses the most recent job database under data/.
"""

from __future__ import annotations

import glob
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8899
ANSWER_SQL = (
    "SELECT COUNT(*) AS n FROM IfcDoor d WHERE NOT EXISTS "
    "(SELECT 1 FROM psets p WHERE p.ifc_id = d.ifc_id AND p.name = 'FireRating')"
)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = body["messages"][-1]["content"]
        # The model must be handed the real schema, or it would be guessing.
        assert "CREATE TABLE" in user, "schema was not passed to the model"
        assert "psets" in user, "schema notes were not passed to the model"
        payload = json.dumps({
            "choices": [{"message": {"content": f"```sql\n{ANSWER_SQL}\n```"}}]
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def latest_db() -> str | None:
    candidates = sorted(glob.glob(os.path.join("data", "*", "model.db")),
                        key=os.path.getmtime, reverse=True)
    return candidates[0] if candidates else None


def main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    db = sys.argv[1] if len(sys.argv) > 1 else latest_db()
    if not db or not os.path.isfile(db):
        print("No model database found. Upload a model through the web app "
              "first, or pass a path to a .db file.")
        return 1

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    os.environ["OPENAI_API_KEY"] = "stub-key"
    os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{PORT}/v1"

    from webapp import nlq

    failures = []

    def check(label, condition, detail=""):
        print(("  PASS  " if condition else "  FAIL  ") + label +
              ("" if condition else f"  {detail}"))
        if not condition:
            failures.append(label)

    print(f"\nUsing {db}\n")
    check("provider is detected", nlq.available())

    result = nlq.ask(db, "how many doors have no fire rating?")
    check("no error returned", not result.get("error"), result.get("error", ""))
    check("markdown fence stripped", result.get("sql", "").startswith("SELECT"),
          repr(result.get("sql", ""))[:60])
    check("query executed", result.get("columns") == ["n"],
          str(result.get("columns")))
    check("returned a real number from SQLite",
          bool(result.get("rows")) and isinstance(result["rows"][0][0], int),
          str(result.get("rows")))

    if result.get("rows"):
        print(f"\n  Answer: {result['rows'][0][0]} doors without a fire rating")

    server.shutdown()

    print()
    if failures:
        print(f" {len(failures)} check(s) FAILED")
        return 1
    print(" All checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
