"""The desktop window (pywebview): frameless glass window, float on top, see-through opacity, keyword flash."""
import logging
import os
import subprocess
import sys
import threading

log = logging.getLogger("comslog.window")


class Api:
    """Called from the page as window.pywebview.api.<name>(). Only plain methods; no attributes are exposed."""

    def __init__(self, shell):
        self._shell = shell

    def minimize(self):
        self._shell.win.minimize()

    def close(self):
        self._shell.win.destroy()

    def toggle_maximize(self):
        w = self._shell.win
        if getattr(self._shell, "_maxed", False):
            w.restore()
            self._shell._maxed = False
        else:
            w.maximize()
            self._shell._maxed = True

    def open_logs(self):
        _reveal(self._shell.app.logs_dir())
        return True

    def open_data(self):
        from .paths import data_dir
        _reveal(data_dir())
        return True

    def save_export(self, day, fmt):
        import webview
        fmt = "csv" if fmt == "csv" else "txt"
        res = self._shell.win.create_file_dialog(webview.SAVE_DIALOG, save_filename=f"coms-log-{day}.{fmt}")
        if not res:
            return None
        path = res if isinstance(res, str) else res[0]
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(self._shell.app.tr.export(day, fmt))
        return path


def _reveal(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        log.warning("open folder: %s", e)


class Shell:
    def __init__(self, app):
        self.app = app
        self.win = None
        self.hwnd = None
        app.window = self

    def run(self):
        import webview
        s = self.app.settings.all()
        geo = s.get("window") or {}
        mac = sys.platform == "darwin"
        self.win = webview.create_window(
            "Coms Log", self.app.server.local_url, js_api=Api(self),
            width=int(geo.get("width") or 440), height=int(geo.get("height") or 760),
            x=geo.get("x"), y=geo.get("y"), min_size=(320, 360),
            frameless=True, easy_drag=False, on_top=bool(s.get("on_top")),
            background_color="#0b1020", transparent=mac, vibrancy=mac, text_select=True)
        self.win.events.shown += self._shown
        self.win.events.closing += self._closing
        webview.start(debug=bool(os.environ.get("COMSLOG_DEBUG")), private_mode=False,
                      storage_path=os.path.join(self._data(), "webview"))

    def _data(self):
        from .paths import data_dir
        return data_dir()

    def _shown(self):
        if sys.platform == "win32":
            try:
                self.hwnd = int(self.win.native.Handle.ToInt64())
                import ctypes
                from ctypes import byref, c_int, wintypes
                dwm = ctypes.windll.dwmapi
                dwm.DwmSetWindowAttribute(wintypes.HWND(self.hwnd), 20, byref(c_int(1)), 4)  # dark mode
                dwm.DwmSetWindowAttribute(wintypes.HWND(self.hwnd), 33, byref(c_int(2)), 4)  # rounded corners (Win 11)
            except Exception as e:
                log.warning("window handle: %s", e)
        self.apply_window_settings(self.app.settings.all())

    def _closing(self):
        try:
            w = self.win
            if not getattr(self, "_maxed", False):
                self.app.settings.update({"window": {"width": w.width, "height": w.height, "x": w.x, "y": w.y}})
        except Exception as e:
            log.debug("save geometry: %s", e)

    # ------------------------------------------------------------------
    def apply_window_settings(self, s):
        if not self.win:
            return
        try:
            if bool(s.get("on_top")) != bool(self.win.on_top):
                self.win.on_top = bool(s.get("on_top"))
        except Exception as e:
            log.warning("on top: %s", e)
        self.set_opacity(float(s.get("opacity", 0.8)) if s.get("see_through") else 1.0)

    def set_opacity(self, a):
        a = max(0.2, min(1.0, a))
        try:
            if sys.platform == "win32" and self.hwnd:
                import ctypes
                from ctypes import wintypes
                u = ctypes.windll.user32
                h = wintypes.HWND(self.hwnd)
                ex = u.GetWindowLongW(h, -20)
                if a >= 0.999:
                    u.SetWindowLongW(h, -20, ex & ~0x80000)          # drop WS_EX_LAYERED: fully opaque
                else:
                    u.SetWindowLongW(h, -20, ex | 0x80000)
                    u.SetLayeredWindowAttributes(h, 0, int(round(255 * a)), 2)  # LWA_ALPHA
            elif sys.platform == "darwin":
                from PyObjCTools import AppHelper
                nw = self.win.native
                AppHelper.callAfter(lambda: nw.setAlphaValue_(a))
        except Exception as e:
            log.warning("opacity: %s", e)

    def alert(self, text):
        """Keyword heard: flash the taskbar button / bounce the Dock icon (the page flashes itself too)."""
        try:
            if sys.platform == "win32" and self.hwnd:
                import ctypes
                from ctypes import wintypes

                class FLASHWINFO(ctypes.Structure):
                    _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                                ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]
                fi = FLASHWINFO(ctypes.sizeof(FLASHWINFO), wintypes.HWND(self.hwnd), 3 | 12, 6, 0)  # all, until focused
                ctypes.windll.user32.FlashWindowEx(ctypes.byref(fi))
            elif sys.platform == "darwin":
                from AppKit import NSApp
                from PyObjCTools import AppHelper
                AppHelper.callAfter(lambda: NSApp.requestUserAttention_(0))
        except Exception as e:
            log.debug("flash: %s", e)
