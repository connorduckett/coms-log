"""Small HTTP server for the app's page and JSON API (stdlib only).

The desktop window loads http://127.0.0.1:<port>/. With "Share on the network" on, other computers and phones
on the same network can open http://<this-computer>:<port>/ to follow the log read-only. Changes (settings,
typed notes, clear) are only accepted from this computer and need the per-launch token the local page gets.
"""
import json
import logging
import mimetypes
import os
import secrets
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .paths import resource

log = logging.getLogger("comslog.web")
TOKEN = secrets.token_urlsafe(24)


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127.") and not i.startswith("169.254."))


class Server:
    def __init__(self, app):
        self.app = app
        self.httpd = None
        self.port = None

    def start(self):
        s = self.app.settings
        host = "0.0.0.0" if s.get("share_lan") else "127.0.0.1"
        want = int(s.get("port") or 8770)
        app = self.app

        class H(Handler):
            pass
        H.app = app
        for port in [want] + list(range(want + 1, want + 20)) + [0]:
            try:
                self.httpd = ThreadingHTTPServer((host, port), H)
                break
            except OSError:
                continue
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="web").start()
        log.info("serving on %s:%d", host, self.port)

    def restart(self):
        old = self.httpd
        if old:
            old.shutdown()
            old.server_close()
        self.start()

    @property
    def local_url(self):
        return f"http://127.0.0.1:{self.port}/"


class Handler(BaseHTTPRequestHandler):
    app = None
    server_version = "ComsLog"

    def log_message(self, fmt, *args):
        pass

    @property
    def local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if not isinstance(body, (bytes, bytearray)):
            body = (json.dumps(body) if ctype.startswith("application/json") else str(body)).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            self._get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log.exception("GET %s", self.path)
            self._send(500, {"error": str(e)})

    def do_POST(self):
        try:
            if not self.local or self.headers.get("X-ComsLog-Token") != TOKEN:
                return self._send(403, {"error": "Changes can only be made on the computer running Coms Log"})
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            self._post(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log.exception("POST %s", self.path)
            self._send(500, {"error": str(e)})

    def _get(self):
        app = self.app
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        path = u.path
        if path in ("/", "/index.html"):
            with open(resource("static", "index.html"), encoding="utf-8") as f:
                html = f.read()
            import sys
            boot = {"token": TOKEN if self.local else None, "version": __version__, "local": self.local,
                    "platform": sys.platform}
            html = html.replace("/*BOOT*/", "window.BOOT=" + json.dumps(boot) + ";")
            return self._send(200, html, "text/html; charset=utf-8")
        if path.startswith("/static/"):
            name = os.path.normpath(path[len("/static/"):]).replace("\\", "/")
            if name.startswith("..") or name.startswith("/"):
                return self._send(404, {"error": "not found"})
            fp = resource("static", *name.split("/"))
            if not os.path.isfile(fp):
                return self._send(404, {"error": "not found"})
            with open(fp, "rb") as f:
                return self._send(200, f.read(), mimetypes.guess_type(fp)[0] or "application/octet-stream")
        if path == "/api/state":
            return self._send(200, app.state(full=self.local))
        if path == "/api/feed":
            return self._send(200, {"items": app.tr.feed(int(q.get("since") or 0)), "seq": app.tr.seq,
                                    "levels": app.audio.status(), "engine": app.tr.status(), "now": time.time()})
        if path == "/api/devices":
            if not self.local:
                return self._send(403, {"error": "local only"})
            return self._send(200, app.devices())
        if path == "/api/days":
            return self._send(200, {"days": app.tr.days()})
        if path == "/api/day":
            return self._send(200, {"items": app.tr.read_day(q.get("day", ""))})
        if path == "/api/search":
            return self._send(200, {"items": app.tr.search(q.get("q", ""))})
        if path == "/api/export":
            day, fmt = q.get("day", ""), q.get("fmt", "txt")
            fmt = "csv" if fmt == "csv" else "txt"
            body = app.tr.export(day, fmt)
            return self._send(200, body, "text/csv; charset=utf-8" if fmt == "csv" else "text/plain; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="coms-log-{day}.{fmt}"'})
        return self._send(404, {"error": "not found"})

    def _post(self, b):
        app = self.app
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/settings":
            return self._send(200, app.update_settings(b))
        if path == "/api/note":
            item = app.add_note(b.get("ch"), b.get("text", ""))
            return self._send(200, {"ok": bool(item), "item": item})
        if path == "/api/clear":
            app.tr.clear_view()
            return self._send(200, {"ok": True})
        if path == "/api/gate":
            app.set_gate(b.get("ch"), float(b.get("gate_db", -45)))
            return self._send(200, {"ok": True})
        if path == "/api/check-updates":
            app.updates.check_now()
            return self._send(200, {"ok": True})
        if path == "/api/test-alert":
            app.alert("Test alert")
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})
