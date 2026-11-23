"""Tells the user when a newer Coms Log is on GitHub. Checks at startup and every 6 hours; never downloads or
installs anything by itself. Only the public "latest release" page is read; nothing about this computer is sent
beyond a generic User-Agent."""
import json
import logging
import re
import threading
import time
import urllib.request

from . import __version__

log = logging.getLogger("comslog.updates")
REPO = "connorduckett/coms-log"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases/latest"


def _ssl_context():
    """The packaged macOS app's Python can't see the Mac's own certificate store, so HTTPS fails with
    CERTIFICATE_VERIFY_FAILED. Use the certifi bundle shipped inside the app; fall back to the system store."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _ver(s):
    return tuple(int(x) for x in re.findall(r"\d+", s or "")[:3]) or (0,)


class Updater:
    def __init__(self, settings):
        self.settings = settings
        self.latest = None        # {"version", "url", "notes", "published"}
        self.checked = 0.0
        self.error = None
        self._wake = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="updates").start()

    def check_now(self):
        self._wake.set()

    def _loop(self):
        time.sleep(5)
        while True:
            if self.settings.get("check_updates", True):
                self._check()
            self._wake.wait(6 * 3600)
            self._wake.clear()

    def _check(self):
        try:
            req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": f"ComsLog/{__version__}"})
            with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as r:
                d = json.load(r)
            self.latest = {"version": (d.get("tag_name") or "").lstrip("v"), "url": d.get("html_url") or RELEASES,
                           "notes": (d.get("body") or "")[:2000], "published": d.get("published_at")}
            self.error = None
        except Exception as e:
            self.error = str(e)
            log.info("update check failed: %s", e)
        self.checked = time.time()

    def status(self):
        lt = self.latest
        newer = bool(lt and lt["version"] and _ver(lt["version"]) > _ver(__version__))
        return {"current": __version__, "available": newer, "latest": lt["version"] if lt else None,
                "url": lt["url"] if lt else RELEASES, "checked": self.checked, "error": self.error,
                "enabled": bool(self.settings.get("check_updates", True))}
