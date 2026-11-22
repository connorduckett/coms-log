"""Audio capture: any input the computer can see (USB interface, Dante Virtual Soundcard, MADI, a mic ...).

Each *channel* in Coms Log is one input of one device. Devices are opened once with enough inputs for every
channel that uses them; the PortAudio callback only copies the block and hands it to a worker thread, which
splits it into channels, updates the meters and feeds each channel's voice gate.
"""
import logging
import queue
import threading
import time

log = logging.getLogger("comslog.audio")
FLOOR = -90.0


def _db(x):
    import math
    return max(FLOOR, 20 * math.log10(x)) if x > 0 else FLOOR


# Best host APIs first; duplicates of the same input through older Windows APIs are left out
_API_RANK = {"ASIO": 0, "Windows WASAPI": 1, "Core Audio": 1, "ALSA": 1, "JACK Audio Connection Kit": 2, "MME": 3,
             "Windows DirectSound": 4}
_SKIP = ("Microsoft Sound Mapper", "Primary Sound Capture Driver")


def list_devices(show_all=False):
    """Input devices as [{"key","name","hostapi","inputs","samplerate"}]. key = "name|hostapi" so a saved
    choice survives devices being plugged in a different order."""
    import sounddevice as sd
    apis = sd.query_hostapis()
    out = []
    for d in sd.query_devices():
        if d["max_input_channels"] < 1 or d["name"].startswith(_SKIP):
            continue
        api = apis[d["hostapi"]]["name"]
        if api == "Windows WDM-KS" and not show_all:
            continue
        out.append({"key": f"{d['name']}|{api}", "name": d["name"], "hostapi": api,
                    "inputs": d["max_input_channels"], "samplerate": int(d["default_samplerate"])})
    if not show_all:  # keep each input only through its best API (MME truncates names to 31 characters)
        best = {}
        for d in out:
            k = d["name"][:31]
            if k not in best or _API_RANK.get(d["hostapi"], 5) < _API_RANK.get(best[k]["hostapi"], 5):
                best[k] = d
        out = list(best.values())
    out.sort(key=lambda d: (_API_RANK.get(d["hostapi"], 5), d["name"].lower()))
    return out


def _find(key):
    import sounddevice as sd
    apis = sd.query_hostapis()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and f"{d['name']}|{apis[d['hostapi']]['name']}" == key:
            return i, d
    return None, None


class Gate:
    """Cuts a channel's audio into utterances: speech until `hang` seconds of quiet, at most 20 s."""

    def __init__(self, ch, sr, on_utterance):
        self.ch, self.sr, self.cb = ch, sr, on_utterance
        self.set_threshold(ch.get("gate_db", -45))
        self.buf, self.speaking, self.quiet, self.t0 = [], False, 0.0, 0.0
        self.pre = []
        self.level = FLOOR
        self.last_voice = 0.0

    def set_threshold(self, db):
        self.thr = 10 ** (float(db) / 20)

    def feed(self, mono, now):
        import numpy as np
        dt = len(mono) / self.sr
        rms = float(np.sqrt(np.mean(mono * mono))) if len(mono) else 0.0
        self.level = _db(rms)
        loud = rms > self.thr
        if loud:
            self.last_voice = now
        if not self.speaking:
            self.pre.append(mono.copy())
            self.pre = self.pre[-4:]                 # ~400 ms pre-roll so the first word isn't clipped
            if loud:
                self.speaking, self.quiet, self.t0 = True, 0.0, now - dt * len(self.pre)
                self.buf = list(self.pre)
            return
        self.buf.append(mono.copy())
        self.quiet = 0.0 if loud else self.quiet + dt
        dur = sum(len(b) for b in self.buf) / self.sr
        if self.quiet >= 0.8 or dur >= 20:
            audio = np.concatenate(self.buf)
            self.buf, self.speaking, self.pre = [], False, []
            if dur - self.quiet >= 0.35:              # ignore clicks and bumps
                self.cb(self.ch, self.t0, audio, self.sr)


class Device:
    def __init__(self, key, monitor):
        self.key, self.mon = key, monitor
        self.stream, self.error, self.sr = None, None, 48000
        self.gates = {}                               # input index (0-based) -> [Gate]
        self.chs = []
        self.work = queue.Queue(maxsize=200)
        self.last_data = 0.0
        self.alive = True
        threading.Thread(target=self._worker, daemon=True, name=f"audio-{key[:20]}").start()

    def open(self, channels):
        import sounddevice as sd
        self.chs = channels
        idx, d = _find(self.key)
        if idx is None:
            self.error = "Not found (unplugged, or Dante Virtual Soundcard not running?)"
            return
        need = max(c["channel"] for c in channels)   # channel numbers are 1-based
        n = min(int(d["max_input_channels"]), max(1, need))
        self.sr = int(d["default_samplerate"]) or 48000
        self.gates = {}
        for c in channels:
            if c["channel"] <= n:
                self.gates.setdefault(c["channel"] - 1, []).append(Gate(c, self.sr, self.mon.on_utterance))
            else:
                self.mon.channel_error[c["id"]] = f"device has only {n} inputs"
        try:
            self.stream = sd.InputStream(device=idx, channels=n, samplerate=self.sr, dtype="float32",
                                         blocksize=self.sr // 10, callback=self._cb)
            self.stream.start()
            self.error = None
            log.info("opened %s (%d in @ %d Hz)", self.key, n, self.sr)
        except Exception as e:
            self.error = str(e)
            log.warning("couldn't open %s: %s", self.key, e)

    def _cb(self, indata, frames, t, status):
        try:
            self.work.put_nowait((indata.copy(), time.time()))
        except queue.Full:
            pass

    def _worker(self):
        while self.alive:
            try:
                x, now = self.work.get(timeout=1)
            except queue.Empty:
                continue
            self.last_data = now
            for i, gs in list(self.gates.items()):
                if i < x.shape[1]:
                    for g in gs:
                        try:
                            g.feed(x[:, i], now)
                        except Exception as e:
                            log.debug("gate: %s", e)

    def close(self):
        self.alive = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None


class AudioMonitor:
    def __init__(self, on_utterance):
        self.on_utterance = on_utterance
        self.devices = {}
        self.channel_error = {}
        self.lock = threading.Lock()
        self.error = None

    def apply(self, channels):
        """(Re)open devices for the enabled channels."""
        with self.lock:
            for d in self.devices.values():
                d.close()
            self.devices, self.channel_error = {}, {}
            try:
                import sounddevice  # noqa: F401
            except Exception as e:
                self.error = f"audio library missing: {e}"
                return
            self.error = None
            by_dev = {}
            for c in channels:
                if c.get("enabled", True) and c.get("device"):
                    by_dev.setdefault(c["device"], []).append({**c, "channel": int(c.get("channel") or 1)})
            for key, chs in by_dev.items():
                d = Device(key, self)
                d.open(chs)
                self.devices[key] = d

    def set_gate(self, ch_id, db):
        with self.lock:
            for d in self.devices.values():
                for gs in d.gates.values():
                    for g in gs:
                        if g.ch["id"] == ch_id:
                            g.set_threshold(db)
                            g.ch["gate_db"] = db

    def status(self):
        now = time.time()
        out = {}
        with self.lock:
            for d in self.devices.values():
                live = d.stream is not None and now - d.last_data < 3
                gates = {g.ch["id"]: g for gs in d.gates.values() for g in gs}
                for c in d.chs:
                    g = gates.get(c["id"])
                    err = self.channel_error.get(c["id"]) or d.error or (None if live else "no audio yet")
                    out[c["id"]] = {"level": round(g.level, 1) if (g and live) else None,
                                    "speaking": bool(g and g.speaking and live), "error": err}
        return out

    def device_errors(self):
        with self.lock:
            return {k: d.error for k, d in self.devices.items() if d.error}
