"""settings.json in the data folder. Everything is editable from the app's Settings panel."""
import copy
import json
import os
import threading

from .paths import data_dir

COLORS = ["#5ac8fa", "#ff9f0a", "#30d158", "#ff375f", "#bf5af2", "#ffd60a", "#64d2ff", "#ff6961"]

DEFAULTS = {
    "channels": [],              # [{"id","name","color","device","channel","gate_db","enabled"}]
    "keywords": [],              # highlighted + alert (flash window, chime)
    "model": "base.en",          # tiny.en / base.en / small.en / medium.en (or multilingual: base, small ...)
    "language": "en",
    "threads": 4,
    "prompt": "Production intercom for a live event. Talkback between camera operators, audio, lighting and the director.",
    "on_top": True,
    "see_through": False,
    "opacity": 0.8,
    "font_size": 15,
    "tint": "#5a8cff",
    "chime": True,
    "flash_on_keyword": True,
    "share_lan": False,
    "port": 8770,
    "keep_days": 30,
    "check_updates": True,
    "window": {"width": 440, "height": 760, "x": None, "y": None},
}


class Settings:
    def __init__(self):
        self.path = os.path.join(data_dir(), "settings.json")
        self.lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULTS)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass

    def get(self, k, default=None):
        with self.lock:
            return copy.deepcopy(self.data.get(k, default))

    def all(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def update(self, changes):
        with self.lock:
            for k, v in changes.items():
                if k in DEFAULTS:
                    self.data[k] = v
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
            return copy.deepcopy(self.data)
