"""Ties settings, audio, transcription and the web server together."""
import logging
import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
import json
import re
import secrets
import time

from . import __version__
from .audio import AudioMonitor, list_devices
from .paths import data_dir, sub
from . import remote
from .server import Server, lan_ips
from .settings import COLORS, Settings
from .transcribe import Transcriber
from .updates import Updater

log = logging.getLogger("comslog")

MODELS = [
    {"id": "tiny.en", "label": "Tiny (English) - fastest, least accurate", "size": "75 MB"},
    {"id": "base.en", "label": "Base (English) - good on most computers", "size": "145 MB"},
    {"id": "small.en", "label": "Small (English) - more accurate, needs a faster computer", "size": "480 MB"},
    {"id": "medium.en", "label": "Medium (English) - most accurate, needs a fast computer", "size": "1.5 GB"},
    {"id": "base", "label": "Base (any language)", "size": "145 MB"},
    {"id": "small", "label": "Small (any language)", "size": "480 MB"},
]


class App:
    def __init__(self):
        self.settings = Settings()
        self.tr = Transcriber(self.settings)
        self.tr.on_item = self._on_item
        self.audio = AudioMonitor(self.tr.submit)
        self.server = Server(self)
        self.updates = Updater(self.settings)
        self.window = None           # set by window.py: object with alert(), apply_window_settings()
        self.alerts = []             # recent keyword alerts for the page (seq, words)
        self._rstate = None          # last good /api/state from the Coms Log being followed
        self._rerror = None

    def start(self):
        self.tr.start()
        self.audio.apply([] if self.following else self.settings.get("channels"))
        self.server.start()
        self.updates.start()

    # ------------------------------------------------------------------
    def devices(self):
        try:
            return {"devices": list_devices(), "error": None}
        except Exception as e:
            return {"devices": [], "error": str(e)}

    @property
    def following(self):
        return self.settings.get("source") == "remote" and bool(self.settings.get("remote_url"))

    def remote_state(self):
        try:
            st, body, _ = remote.fetch(self.settings.get("remote_url"), "/api/state", timeout=3)
            if st == 200:
                self._rstate, self._rerror = json.loads(body), None
            else:
                self._rerror = f"HTTP {st}"
        except Exception as e:
            self._rerror = remote._short(e)
        return self._rstate

    def state(self, full=True):
        s = self.settings.all()
        if self.following and full:
            r = self.remote_state() or {}
            s = dict(s, channels=r.get("channels") or [], groups=r.get("groups") or [], keywords=r.get("keywords") or [])
        out = {"version": __version__, "host": remote.host_name(), "source": "remote" if self.following else "local",
               "remote": {"url": s.get("remote_url"), "name": s.get("remote_name"), "ok": self._rerror is None,
                          "error": self._rerror} if self.following else None,
               "channels": s["channels"], "groups": s.get("groups") or [], "keywords": s["keywords"],
               "font_size": s["font_size"], "tint": s["tint"], "engine": self.tr.status(),
               "share_lan": s["share_lan"], "port": self.server.port,
               "lan_urls": [f"http://{ip}:{self.server.port}/" for ip in lan_ips()] if s["share_lan"] else []}
        if full:
            out.update({"update": self.updates.status(), "settings": s, "models": MODELS, "colors": COLORS, "data_dir": data_dir(),
                        "device_errors": self.audio.device_errors(), "audio_error": self.audio.error})
        return out

    def update_settings(self, b):
        allowed = {"channels", "groups", "keywords", "model", "language", "threads", "prompt", "on_top", "see_through",
                   "opacity", "font_size", "tint", "chime", "flash_on_keyword", "share_lan", "keep_days", "window", "check_updates",
                   "source", "remote_url", "remote_name"}
        changes = {k: v for k, v in (b or {}).items() if k in allowed}
        if "channels" in changes:
            chans = []
            for i, c in enumerate(changes["channels"] or []):
                cid = re.sub(r"[^A-Za-z0-9_-]", "", str(c.get("id") or "")) or "ch-" + secrets.token_hex(3)
                chans.append({"id": cid, "name": str(c.get("name") or f"Channel {i + 1}")[:40],
                              "color": c.get("color") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(c.get("color"))) else COLORS[i % len(COLORS)],
                              "device": str(c.get("device") or ""), "channel": max(1, int(c.get("channel") or 1)),
                              "gate_db": max(-80.0, min(-10.0, float(c.get("gate_db", -45)))),
                              "enabled": bool(c.get("enabled", True)), "hidden": bool(c.get("hidden", False))})
            changes["channels"] = chans
        if "groups" in changes or "channels" in changes:
            ids = {c["id"] for c in (changes.get("channels") or self.settings.get("channels"))}
            groups = []
            for i, g in enumerate((changes.get("groups") if "groups" in changes else self.settings.get("groups")) or []):
                if not isinstance(g, dict):
                    continue
                gid = re.sub(r"[^A-Za-z0-9_-]", "", str(g.get("id") or "")) or "g-" + secrets.token_hex(3)
                members = [str(x) for x in (g.get("channels") or []) if str(x) in ids]
                groups.append({"id": gid, "name": str(g.get("name") or f"Group {i + 1}")[:40],
                               "channels": list(dict.fromkeys(members))})
            changes["groups"] = groups[:20]
        if "keywords" in changes:
            kws = changes["keywords"]
            if isinstance(kws, str):
                kws = kws.split(",")
            changes["keywords"] = [k.strip() for k in kws if k and k.strip()][:50]
        if "source" in changes:
            changes["source"] = "remote" if changes["source"] == "remote" else "local"
        if "remote_url" in changes:
            changes["remote_url"] = remote.normalize_url(changes["remote_url"]) or ""
        if "remote_name" in changes:
            changes["remote_name"] = str(changes["remote_name"] or "")[:60]
        if self.following or changes.get("source") == "remote":
            changes.pop("channels", None)            # the followed computer owns these
            changes.pop("groups", None)
            changes.pop("keywords", None)
        if "opacity" in changes:
            changes["opacity"] = max(0.25, min(1.0, float(changes["opacity"])))
        before = self.settings.all()
        after = self.settings.update(changes)
        audio_keys = lambda s: ([] if s.get("source") == "remote" and s.get("remote_url") else
                                [(c["id"], c["device"], c["channel"], c["enabled"]) for c in s["channels"]])
        if audio_keys(before) != audio_keys(after):
            self.audio.apply([] if self.following else after["channels"])
        else:
            for c in after["channels"]:
                self.audio.set_gate(c["id"], c["gate_db"])
        if before["model"] != after["model"] or before["threads"] != after["threads"]:
            self.tr.reload_model()
        if after.get("check_updates") and not before.get("check_updates"):
            self.updates.check_now()
        if (before["share_lan"], before.get("source"), before.get("remote_url")) != \
                (after["share_lan"], after.get("source"), after.get("remote_url")):
            self._rstate, self._rerror = None, None
            self.server.restart()
        if self.window:
            self.window.apply_window_settings(after)
        return self.state()

    def set_gate(self, ch, db):
        chans = self.settings.get("channels")
        for c in chans:
            if c["id"] == ch:
                c["gate_db"] = db
        self.settings.update({"channels": chans})
        self.audio.set_gate(ch, db)

    def add_note(self, ch_id, text):
        text = (text or "").strip()[:500]
        if not text:
            return None
        ch = next((c for c in self.settings.get("channels") if c["id"] == ch_id), None)
        return self.tr.add({"ch": ch["id"] if ch else "note", "name": ch["name"] if ch else "Note",
                            "color": ch["color"] if ch else "#ffffff", "ts": round(time.time(), 2),
                            "text": text, "kind": "typed"})

    def remote_items(self, items):
        """Lines fetched from the followed Coms Log: flash the Dock/taskbar for keyword hits, like local ones."""
        for it in items or []:
            self._on_item(it)

    def _on_item(self, item):
        if item.get("hits") and item.get("kind") == "voice":
            self.alert(f"{item['name']}: {', '.join(item['hits'])}")

    def alert(self, text):
        if self.window and self.settings.get("flash_on_keyword"):
            self.window.alert(text)

    def logs_dir(self):
        return sub("logs")

    def stop(self):
        self.audio.apply([])
        log.info("stopped")


def setup_logging():
    log_path = os.path.join(data_dir(), "comslog.log")
    try:
        if os.path.getsize(log_path) > 2_000_000:
            os.replace(log_path, log_path + ".1")
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()])
    for noisy in ("httpx", "httpx2", "httpcore", "huggingface_hub", "urllib3", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
