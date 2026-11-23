"""Following another Coms Log on the network.

A Coms Log with "Share on the network" on answers a small UDP broadcast ("who's out there?") so other copies
can list it by name; nobody has to type an IP address. A copy set to follow it keeps its own window (float on
top, see-through, tint, text size) and fetches the log from the sharing computer over plain HTTP, read-only.
"""
import json
import logging
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

log = logging.getLogger("comslog.remote")
DISCOVERY_PORT = 8769
ASK = b"COMSLOG_DISCOVER_1"


def host_name():
    n = socket.gethostname() or "Coms Log"
    return re.sub(r"\.local$", "", n)


def normalize_url(s):
    """'192.168.1.20', '192.168.1.20:8770', 'http://host:8770/...' -> 'http://host:port/' (or None)."""
    s = (s or "").strip()
    if not s:
        return None
    if "://" not in s:
        s = "http://" + s
    u = urllib.parse.urlparse(s)
    if u.scheme != "http" or not u.hostname or not re.fullmatch(r"[A-Za-z0-9.\-]+|[0-9a-fA-F:]+", u.hostname):
        return None
    try:
        port = u.port or 8770
    except ValueError:
        return None
    host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
    return f"http://{host}:{port}/"


# ---------------------------------------------------------------- answering (on the sharing computer)
class Responder:
    def __init__(self, app):
        self.app = app
        self.sock = None
        self.stop_flag = threading.Event()

    def start(self, port):
        self.stop()
        self.stop_flag = threading.Event()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", DISCOVERY_PORT))
            s.settimeout(1.0)
        except OSError as e:
            log.warning("discovery responder: %s", e)
            return
        self.sock = s
        threading.Thread(target=self._loop, args=(s, port, self.stop_flag), daemon=True, name="discovery").start()

    def _loop(self, s, port, stop):
        while not stop.is_set():
            try:
                data, addr = s.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            if data.strip() != ASK:
                continue
            reply = {"app": "comslog", "name": host_name(), "port": port, "version": __version__,
                     "channels": len([c for c in self.app.settings.get("channels") if c.get("enabled", True)])}
            try:
                s.sendto(json.dumps(reply).encode(), addr)
            except OSError:
                pass
        try:
            s.close()
        except OSError:
            pass

    def stop(self):
        self.stop_flag.set()
        self.sock = None


# ---------------------------------------------------------------- finding (on the following computer)
def _broadcast_addrs():
    from .server import lan_ips
    out = {"255.255.255.255"}
    for ip in lan_ips():
        p = ip.split(".")
        if len(p) == 4:
            out.add(".".join(p[:3] + ["255"]))       # /24 broadcast: helps when there are several adapters
    return out


def discover(wait=1.6):
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", 0))
        s.settimeout(0.25)
        for a in _broadcast_addrs():
            for _ in range(2):
                try:
                    s.sendto(ASK, (a, DISCOVERY_PORT))
                except OSError:
                    pass
        end = time.time() + wait
        while time.time() < end:
            try:
                data, addr = s.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                d = json.loads(data)
                if d.get("app") != "comslog":
                    continue
                port = int(d.get("port") or 8770)
            except (ValueError, TypeError):
                continue
            url = f"http://{addr[0]}:{port}/"
            found[url] = {"url": url, "name": str(d.get("name") or addr[0])[:60], "ip": addr[0],
                          "version": str(d.get("version") or ""), "channels": int(d.get("channels") or 0)}
    finally:
        s.close()
    from .server import lan_ips
    mine = set(lan_ips()) | {"127.0.0.1"}
    for v in found.values():
        v["self"] = v["ip"] in mine
    return sorted(found.values(), key=lambda v: (v["self"], v["name"].lower()))


# ---------------------------------------------------------------- fetching
def fetch(base, path, timeout=5):
    """GET base+path from the shared Coms Log. Returns (status, body bytes, headers)."""
    req = urllib.request.Request(base.rstrip("/") + path, headers={"User-Agent": f"ComsLog/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def probe(base):
    """Is there a shared Coms Log at this address? Returns {"ok", "name", "error"}."""
    try:
        st, body, _ = fetch(base, "/api/state", timeout=4)
        d = json.loads(body)
        if st != 200 or "channels" not in d:
            return {"ok": False, "error": "That address answered, but it isn't a Coms Log."}
        return {"ok": True, "name": d.get("host") or base, "version": d.get("version")}
    except Exception as e:
        return {"ok": False, "error": f"Couldn't reach it ({_short(e)}). Is “Share on the network” on there?"}


def _short(e):
    r = getattr(e, "reason", None)
    return str(r or e)[:80]
