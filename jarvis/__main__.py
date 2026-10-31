"""CLI:  python -m jarvis serve | chat | ask "..." | route "..." | reindex"""
from __future__ import annotations

import argparse
import json
import sys

from .config import Config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="jarvis")
    ap.add_argument("--vault", help="override JARVIS_VAULT")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the web app + API")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    a = sub.add_parser("ask", help="send one request through the full pipeline")
    a.add_argument("text", nargs="+")
    a.add_argument("--json", action="store_true")
    r = sub.add_parser("route", help="show how a request would be routed (no model call)")
    r.add_argument("text", nargs="+")
    sub.add_parser("chat", help="interactive terminal chat")
    sub.add_parser("search", help="search the vault").add_argument("text", nargs="+")
    args = ap.parse_args(argv)

    cfg = Config.from_env()
    if args.vault:
        from pathlib import Path
        cfg.vault_path = Path(args.vault).expanduser().resolve()

    if args.cmd == "serve":
        from .server import serve
        cfg.host = args.host or cfg.host
        cfg.port = args.port or cfg.port
        serve(cfg)
        return 0

    from .core import Jarvis
    j = Jarvis(cfg)
    if args.cmd == "route":
        rt = j.router.route(" ".join(args.text))
        print(json.dumps({k: v for k, v in rt.__dict__.items()}, indent=2))
    elif args.cmd == "search":
        for h in j.retriever.search(" ".join(args.text), k=8):
            print(f"{h.score:6.2f}  {h.path} › {h.heading}  ({h.date})")
    elif args.cmd == "ask":
        res = j.handle(" ".join(args.text), source="cli")
        print(json.dumps(res.as_dict(), indent=2, ensure_ascii=False) if args.json
              else f"[tier {res.tier} · {res.model} · {res.route['reason']}]\n{res.reply}")
    elif args.cmd == "chat":
        history: list[dict] = []
        while True:
            try:
                text = input("you › ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            res = j.handle(text, source="cli", history=history)
            print(f"jarvis [tier {res.tier}{' ↑' if res.escalated else ''} · {res.model}] › {res.reply}\n")
            history += [{"role": "user", "content": text}, {"role": "assistant", "content": res.reply}]
    return 0


if __name__ == "__main__":
    sys.exit(main())
