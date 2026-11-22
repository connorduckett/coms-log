"""Speech-to-text (faster-whisper, on this computer, no cloud) and the transcript log.

Utterances from every channel go into one queue; a single worker transcribes them oldest first. Each line is
kept in memory for the live view and appended to logs/YYYY-MM-DD.jsonl so it can be searched and exported.
"""
import collections
import datetime
import glob
import json
import logging
import os
import queue
import re
import threading
import time

from .paths import sub

log = logging.getLogger("comslog.transcribe")

# Whisper's usual inventions on breath, noise and silence
JUNK = {"you", "thank you", "thanks for watching", "bye", "thank you for watching", "thanks", "so", "uh", "um",
        "please subscribe", "subtitles by the amara.org community", "."}


def _lowpass(n=63, cutoff=0.30):
    import numpy as np
    k = np.arange(n) - (n - 1) / 2
    h = np.sinc(2 * cutoff * k) * np.hamming(n)
    return (h / h.sum()).astype("float32")


class Transcriber:
    def __init__(self, settings):
        self.settings = settings
        self.q = queue.Queue(maxsize=60)
        self.items = collections.deque(maxlen=2000)
        self.seq = 0
        self.lock = threading.Lock()
        self.state, self.error = "starting", None
        self.model, self.model_name = None, None
        self.dropped = 0
        self.busy = False
        self._taps = None
        self.on_item = None           # fn(item) -> called for every new line (keyword alerts)
        self.logdir = sub("logs")
        self._reload = threading.Event()
        self._prune()

    # ------------------------------------------------------------------ model
    def start(self):
        threading.Thread(target=self._run, daemon=True, name="transcribe").start()

    def reload_model(self):
        self._reload.set()

    def _load(self):
        name = self.settings.get("model", "base.en")
        self.state = f"Downloading / loading speech model “{name}” (first time only)…"
        self.error = None
        try:
            from faster_whisper import WhisperModel
        except Exception as e:
            self.state, self.error = "error", f"speech engine missing: {e}"
            log.error(self.error)
            return False
        try:
            self.model = WhisperModel(name, device="cpu", compute_type="int8",
                                      cpu_threads=int(self.settings.get("threads", 4)),
                                      download_root=sub("models"))
            self.model_name = name
            self.state = "ready"
            log.info("speech model %s ready", name)
            return True
        except Exception as e:
            self.model = None
            self.state, self.error = "error", f"couldn't load model {name}: {e}"
            log.error(self.error)
            return False

    def submit(self, ch, t0, audio, sr):
        try:
            self.q.put_nowait((dict(ch), t0, audio, sr))
        except queue.Full:
            self.dropped += 1         # computer can't keep up: skip rather than fall further behind

    def _to16k(self, audio, sr):
        import numpy as np
        if sr == 16000:
            return audio.astype("float32")
        if sr % 16000 == 0:                       # 48k, 32k, 96k: low-pass then keep every n-th sample
            n = sr // 16000
            if not self._taps or self._taps[0] != n:
                self._taps = (n, _lowpass(32 * n - 1, 0.45 / n))
            return np.convolve(audio, self._taps[1], mode="same")[::n].astype("float32")
        k = int(len(audio) * 16000 / sr)
        return np.interp(np.linspace(0, len(audio) - 1, k), np.arange(len(audio)), audio).astype("float32")

    def _run(self):
        while True:
            if self.model is None or self._reload.is_set():
                self._reload.clear()
                self.model = None
                if not self._load():
                    self._reload.wait(30)     # retry later (e.g. no internet for the first download)
                    continue
            try:
                ch, t0, audio, sr = self.q.get(timeout=1)
            except queue.Empty:
                continue
            if time.time() - t0 > 90:
                self.dropped += 1
                continue
            self.busy = True
            try:
                kw = self.settings.get("keywords") or []
                prompt = (self.settings.get("prompt") or "") + (" " + ", ".join(kw) + "." if kw else "")
                lang = self.settings.get("language") or None
                if (self.model_name or "").endswith(".en"):
                    lang = "en"
                segs, _ = self.model.transcribe(self._to16k(audio, sr), language=lang, beam_size=1,
                                                vad_filter=False, condition_on_previous_text=False,
                                                initial_prompt=prompt or None, no_speech_threshold=0.6)
                text = " ".join(s.text.strip() for s in segs if s.no_speech_prob < 0.7).strip()
            except Exception as e:
                self.error = f"transcription error: {e}"
                log.warning(self.error)
                continue
            finally:
                self.busy = False
            if not text or text.lower().strip(" .!?,") in JUNK:
                continue
            self.add({"ch": ch["id"], "name": ch.get("name") or "", "color": ch.get("color") or "",
                      "ts": round(t0, 2), "dur": round(len(audio) / sr, 1), "text": text, "kind": "voice"})

    # ------------------------------------------------------------------ log
    def add(self, item):
        with self.lock:
            self.seq += 1
            item["seq"] = self.seq
            item["hits"] = self.hits(item["text"])
            self.items.append(item)
        self._save(item)
        if self.on_item:
            try:
                self.on_item(item)
            except Exception as e:
                log.debug("on_item: %s", e)
        return item

    def hits(self, text):
        out = []
        for w in self.settings.get("keywords") or []:
            w = w.strip()
            if w and re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.I):
                out.append(w)
        return out

    def _save(self, it):
        try:
            day = datetime.date.fromtimestamp(it["ts"]).isoformat()
            with open(os.path.join(self.logdir, f"{day}.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({k: it[k] for k in ("ts", "ch", "name", "text", "kind", "dur") if k in it}) + "\n")
        except OSError as e:
            log.warning("couldn't save log line: %s", e)

    def _prune(self):
        keep = int(self.settings.get("keep_days", 30) or 0)
        if keep <= 0:
            return
        cut = (datetime.date.today() - datetime.timedelta(days=keep)).isoformat()
        for f in glob.glob(os.path.join(self.logdir, "*.jsonl")):
            if os.path.basename(f)[:10] < cut:
                try:
                    os.remove(f)
                except OSError:
                    pass

    def feed(self, since=0):
        with self.lock:
            items = [i for i in self.items if i["seq"] > since][-500:]
        return items

    def clear_view(self):
        """Clears the live view only; the day's log file is kept."""
        with self.lock:
            self.items.clear()

    def days(self):
        return sorted((os.path.basename(f)[:10] for f in glob.glob(os.path.join(self.logdir, "*.jsonl"))), reverse=True)

    def read_day(self, day):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day or ""):
            return []
        out = []
        try:
            with open(os.path.join(self.logdir, f"{day}.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        except OSError:
            pass
        return out

    def search(self, q, limit=300):
        q = (q or "").strip().lower()
        if not q:
            return []
        out = []
        for day in self.days():
            for it in reversed(self.read_day(day)):
                if q in it.get("text", "").lower() or q in it.get("name", "").lower():
                    out.append(it)
                    if len(out) >= limit:
                        return out
        return out

    def export(self, day, fmt="txt"):
        rows = self.read_day(day)
        if fmt == "csv":
            import csv
            import io
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["time", "channel", "text", "type"])
            for r in rows:
                w.writerow([time.strftime("%H:%M:%S", time.localtime(r["ts"])), r.get("name", ""), r.get("text", ""),
                            r.get("kind", "voice")])
            return buf.getvalue()
        lines = [f"Coms Log - {day}", ""]
        for r in rows:
            mark = " (typed)" if r.get("kind") == "typed" else ""
            lines.append(f"{time.strftime('%H:%M:%S', time.localtime(r['ts']))}  [{r.get('name', '')}]{mark}  {r.get('text', '')}")
        return "\n".join(lines) + "\n"

    def status(self):
        return {"state": self.state, "error": self.error, "model": self.model_name, "backlog": self.q.qsize(),
                "busy": self.busy, "dropped": self.dropped, "seq": self.seq}
