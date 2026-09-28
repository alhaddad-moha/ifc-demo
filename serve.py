#!/usr/bin/env python
"""Start the web app.

    python serve.py
    python serve.py --port 9000 --host 0.0.0.0

Then open http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser


def main() -> int:
    parser = argparse.ArgumentParser(prog="serve.py")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true",
                        help="auto-restart on code changes (development)")
    parser.add_argument("--no-open", action="store_true",
                        help="do not open a browser window")
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed. Run:  pip install -r requirements.txt")
        return 1

    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    # ASCII only: a Windows console on a legacy code page can't print "→"
    # and would crash the server before it starts.
    print(f"\n  IFC Audit  ->  {url}\n")

    if not args.no_open and not args.reload:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run("webapp.main:app", host=args.host, port=args.port,
                reload=args.reload, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
