#!/usr/bin/env python3
"""Lampejo — servidor local (stdlib). 3 slides no navegador + SSE + pipeline em 2º plano.

    python3 server.py            # http://127.0.0.1:4242
"""
import json
import mimetypes
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lsl import app, config  # noqa: E402

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("video/mp4", ".mp4")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "lsl/0.1"

    def log_message(self, fmt, *a):
        if "/events" not in (a[0] if a else ""):
            t = time.time()
            sys.stderr.write("[%s.%03d] %s\n" % (time.strftime("%H:%M:%S", time.localtime(t)), int(t % 1 * 1000), fmt % a))

    # ---------- helpers ----------
    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 30_000_000:
            raise ValueError("corpo grande demais")
        raw = self.rfile.read(n) if n else b""
        if "json" in (self.headers.get("Content-Type") or ""):
            return json.loads(raw or b"{}")
        return raw

    def _file(self, path: Path, ctype=None):
        if not path.is_file():
            return self._json({"erro": "não encontrado"}, 404)
        size = path.stat().st_size
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = size - int(m.group(2))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def _session(self, sid):
        s = app.SESSIONS.get(sid)
        if not s:
            self._json({"erro": "sessão não existe (o servidor reiniciou?)"}, 404)
        return s

    # ---------- GET ----------
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p in ("/", "/index.html"):
            app.aquecer()                   # home aberta: o Claude do slide 1 já fica esperando o conceito
        if p in ("/", "/index.html") or p.startswith("/s/"):
            return self._file(config.WEB / "index.html", "text/html")
        if p.startswith("/static/"):
            f = (config.WEB / p[len("/static/"):]).resolve()
            if config.WEB.resolve() in f.parents:
                return self._file(f)
            return self._json({"erro": "proibido"}, 403)
        if p.startswith("/runs/"):
            f = (config.RUNS / p[len("/runs/"):]).resolve()
            if config.RUNS.resolve() in f.parents and f.suffix in (".png", ".mp3", ".mp4", ".jpg"):
                return self._file(f)
            return self._json({"erro": "proibido"}, 403)
        if p == "/api/health":
            return self._json({"ok": True, "recursos": config.check(), "sessoes": len(app.SESSIONS),
                               "https_port": config.HTTPS_PORT if config.CERT_FILE.exists() else None})
        m = re.match(r"^/api/s/([0-9a-f]{8})/(state|events)$", p)
        if m:
            s = self._session(m.group(1))
            if not s:
                return
            if m.group(2) == "state":
                return self._json(s.public())
            return self._sse(s, int(parse_qs(u.query).get("since", ["0"])[0]))
        self._json({"erro": "rota desconhecida"}, 404)

    def _sse(self, s, since):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        i = since
        try:
            while True:
                with s.cv:
                    if i >= len(s.events):
                        s.cv.wait(15)
                    batch = s.events[i:]
                if not batch:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                for ev in batch:
                    self.wfile.write(f"id: {ev['i']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                i += len(batch)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    # ---------- POST ----------
    def do_POST(self):
        p = urlparse(self.path).path
        try:
            if p == "/api/sessions":
                b = self._body()
                c = (b.get("concept") or "").strip()
                if not c:
                    return self._json({"erro": "conceito vazio"}, 400)
                s = app.create(c[:120])
                return self._json({"id": s.id, "url": f"/s/{s.id}"})
            if p == "/api/prefetch":
                return self._json(app.prefetch((self._body().get("concept") or "").strip()[:120]))
            m = re.match(r"^/api/s/([0-9a-f]{8})/([a-z_]+)$", p)
            if not m:
                return self._json({"erro": "rota desconhecida"}, 404)
            s = self._session(m.group(1))
            if not s:
                return
            act, b = m.group(2), self._body()
            if act == "exemplos":
                return self._stream(lambda w: app.exemplos_stream(s, w))
            if act == "chat":
                return self._stream(lambda w: app.chat_stream(s, b["q"], w, b.get("modo", "texto")))
            if act == "aquecer":
                return self._json(app.aquecer(s, b.get("alvo")))
            if act == "say":
                return self._raw(app.say(s, b["text"]), "audio/mpeg")
            if act == "stt":
                if not isinstance(b, (bytes, bytearray)) or len(b) < 800:
                    return self._json({"erro": "áudio vazio ou curto demais"}, 400)
                return self._json(app.transcribe(s, bytes(b), self.headers.get("Content-Type", "audio/webm")))
            if act == "exam":
                if b.get("acao") == "start":
                    return self._json(app.exam_start(s))
                if b.get("acao") in ("reaprender", "pular"):
                    return self._json(app.exam_action(s, b["acao"]))
                return self._json(app.exam_answer(s, b["text"]))
            return self._json({"erro": "ação desconhecida"}, 404)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._json({"erro": f"{type(e).__name__}: {str(e)[:300]}"}, 500)

    def _raw(self, data: bytes, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _stream(self, fn):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def write(txt):
            b = txt.encode()
            self.wfile.write(f"{len(b):x}\r\n".encode() + b + b"\r\n")
            self.wfile.flush()
        try:
            fn(write)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    config.RUNS.mkdir(exist_ok=True)
    print(f"sessões restauradas do disco: {app.restore_sessions()}", flush=True)
    print(f"Claude: {config.provider()} {config.auth_status()}", flush=True)
    app.aquecer()
    srv = ThreadingHTTPServer((config.HOST, config.PORT), H)
    srv.daemon_threads = True
    if config.CERT_FILE.exists() and config.KEY_FILE.exists():      # mesmo processo = mesmas sessões nos dois endereços
        import ssl
        tls = ThreadingHTTPServer((config.HOST, config.HTTPS_PORT), H)
        tls.daemon_threads = True
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(config.CERT_FILE), str(config.KEY_FILE))
        tls.socket = ctx.wrap_socket(tls.socket, server_side=True)
        threading.Thread(target=tls.serve_forever, daemon=True).start()
        print(f"Lampejo em https://{config.HOST}:{config.HTTPS_PORT} (microfone pela rede)", flush=True)
    print(f"Lampejo em http://{config.HOST}:{config.PORT}  recursos={config.check()}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
