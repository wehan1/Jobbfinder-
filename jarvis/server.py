"""HTTP API + the Jarvis web app. Standard library only.

Both front doors (this web app and the Obsidian plugin) call the same API, and
the API only reads/writes the vault folder on disk — that is what keeps them on
one memory.
"""
from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import Config
from .core import Jarvis
from .vault import VaultError, render_frontmatter
from .voice import VoiceUnavailable

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 25 * 1024 * 1024
AUDIO_SUFFIX = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/x-wav": ".wav",
                "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/aac": ".aac"}


def make_handler(jarvis: Jarvis, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Jarvis/0.1"

        def log_message(self, fmt, *args):  # quieter logs
            sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

        # ---- helpers ----
        def _send(self, status: int, body: bytes, ctype: str = "application/json"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200):
            self._send(status, json.dumps(obj, ensure_ascii=False).encode())

        def _err(self, status: int, msg: str):
            self._json({"error": msg}, status)

        def _authed(self) -> bool:
            if not token:
                # No token => loopback only. Reject foreign Host headers (DNS rebinding).
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
                return host in {"localhost", "127.0.0.1", "::1"}
            got = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            return hmac.compare_digest(got, token)

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("request too large")
            return self.rfile.read(n) if n else b""

        def _json_body(self) -> dict:
            # Requiring application/json forces a CORS preflight, which we never grant, so a
            # random web page can't fire a "simple" cross-site POST at the local API.
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                raise ValueError("Content-Type must be application/json")
            raw = self._body()
            return json.loads(raw or b"{}")

        # ---- routes ----
        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if not url.path.startswith("/api/"):
                return self._static(url.path)
            if url.path == "/api/health":
                return self._json({"ok": True, "vault": str(jarvis.vault.root), "auth": bool(token)})
            if not self._authed():
                return self._err(401, "unauthorized")
            try:
                if url.path == "/api/skills":
                    return self._json([{"name": s.name, "description": s.description, "triggers": s.triggers,
                                        "save_to": s.save_to, "path": s.path} for s in jarvis.skills.load()])
                if url.path == "/api/search":
                    hits = jarvis.retriever.search(q.get("q", ""), k=int(q.get("k", 8)))
                    return self._json([h.as_dict() for h in hits])
                if url.path == "/api/note":
                    rel = jarvis.vault.find_note(q.get("path", "")) or q.get("path", "")
                    return self._json({"path": rel, "content": jarvis.vault.read(rel)})
                if url.path == "/api/notes":
                    return self._json(jarvis.vault.recent_notes(int(q.get("n", 30))))
                if url.path == "/api/conversation":
                    rel = f"Jarvis/Conversations/{jarvis.vault.now():%Y-%m-%d}.md"
                    content = jarvis.vault.read(rel) if jarvis.vault.exists(rel) else ""
                    return self._json({"path": rel, "content": content})
            except VaultError as e:
                return self._err(404, str(e))
            return self._err(404, "not found")

        def do_POST(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if not self._authed():
                return self._err(401, "unauthorized")
            try:
                if url.path == "/api/chat":
                    b = self._json_body()
                    r = jarvis.handle(b.get("text", ""), source=str(b.get("source", "web"))[:32],
                                      history=b.get("history"), mode=b.get("mode"),
                                      context_path=b.get("context_path"))
                    out = r.as_dict()
                    if b.get("speak"):
                        out["audio_b64"] = self._tts_b64(r.reply)
                    return self._json(out)
                if url.path in ("/api/voice", "/api/stt") and not (self.headers.get("Content-Type") or "").startswith("audio/"):
                    return self._err(400, "Content-Type must be audio/*")
                if url.path == "/api/voice":
                    ctype = (self.headers.get("Content-Type") or "audio/webm").split(";")[0].strip()
                    audio = self._body()
                    r = jarvis.handle_voice(audio, suffix=AUDIO_SUFFIX.get(ctype, ".webm"),
                                            source=q.get("source", "web")[:32], mode=q.get("mode") or None)
                    out = r.as_dict()
                    if q.get("speak") in ("1", "true"):
                        out["audio_b64"] = self._tts_b64(r.reply)
                    return self._json(out)
                if url.path == "/api/stt":
                    ctype = (self.headers.get("Content-Type") or "audio/webm").split(";")[0].strip()
                    return self._json({"text": jarvis.stt.transcribe(self._body(), AUDIO_SUFFIX.get(ctype, ".webm"))})
                if url.path == "/api/tts":
                    wav = jarvis.tts.synthesize(self._json_body().get("text", ""))
                    return self._send(200, wav, "audio/wav")
                if url.path == "/api/note":
                    b = self._json_body()
                    title = (b.get("title") or "").strip()
                    path = (b.get("path") or (f"Jarvis/Inbox/{title}.md" if title else "")).strip()
                    if not path:
                        return self._err(400, "path or title required")
                    content = b.get("content", "")
                    if not content.startswith("---"):
                        content = render_frontmatter({"type": "note", "date": f"{jarvis.vault.now():%Y-%m-%d}",
                                                      "source": str(b.get("source", "web"))[:32]}) + \
                                  (f"# {title}\n\n" if title else "") + content
                    rel = jarvis.vault.write(path, content, overwrite=bool(b.get("overwrite")))
                    return self._json({"saved": rel})
            except VoiceUnavailable as e:
                return self._err(501, str(e))
            except VaultError as e:
                return self._err(400, str(e))
            except (ValueError, json.JSONDecodeError) as e:
                return self._err(400, str(e))
            return self._err(404, "not found")

        def _tts_b64(self, text: str) -> str | None:
            try:
                return base64.b64encode(jarvis.tts.synthesize(text)).decode()
            except VoiceUnavailable:
                return None

        def _static(self, path: str):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            p = (WEB_DIR / rel).resolve()
            if WEB_DIR.resolve() not in p.parents or not p.is_file():
                return self._err(404, "not found")
            self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")

    return Handler


def _is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return host == "localhost"
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def make_server(jarvis: Jarvis, host: str, port: int, token: str) -> ThreadingHTTPServer:
    if not _is_loopback(host) and not token:
        raise SystemExit(f"Refusing to bind {host} without JARVIS_TOKEN set. Your vault would be open to the network.")
    return ThreadingHTTPServer((host, port), make_handler(jarvis, token))


def serve(config: Config) -> None:
    jarvis = Jarvis(config)
    srv = make_server(jarvis, config.host, config.port, config.token)
    print(f"Jarvis on http://{config.host}:{srv.server_address[1]}  vault={jarvis.vault.root}"
          f"  fast={config.fast_model}  frontier={config.frontier_model}"
          f"  auth={'on' if config.token else 'off (loopback only)'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
