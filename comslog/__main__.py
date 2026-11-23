import logging
import os
import sys

from .app import App, setup_logging


def selftest():
    """Used by the build: every native piece must import inside the packaged app. Never raises (a windowed
    build would show an error dialog and hang the build); the result or traceback goes to the given file."""
    import os
    import traceback
    i = sys.argv.index("--selftest")
    out = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
    lines = []
    ok = True
    for mod in ("numpy", "ctranslate2", "tokenizers", "av", "faster_whisper", "sounddevice", "webview"):
        try:
            m = __import__(mod)
            lines.append(f"{mod} {getattr(m, '__version__', '')}")
        except BaseException:
            ok = False
            lines.append(f"FAILED {mod}:\n{traceback.format_exc()}")
    try:
        from .paths import resource
        assert os.path.isfile(resource("static", "index.html")), "index.html missing"
    except BaseException:
        ok = False
        lines.append("FAILED static:\n" + traceback.format_exc())
    try:   # the update check must be able to verify GitHub's certificate inside the packaged app
        import urllib.request
        from .updates import API, _ssl_context
        req = urllib.request.Request(API, headers={"User-Agent": "ComsLog-selftest"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as r:
            lines.append(f"https ok ({r.status})")
    except urllib.error.HTTPError as e:      # reached GitHub over verified TLS (e.g. rate limited): fine
        lines.append(f"https ok (HTTP {e.code})")
    except BaseException:
        ok = False
        lines.append("FAILED https:\n" + traceback.format_exc())
    msg = ("selftest ok\n" if ok else "selftest FAILED\n") + "\n".join(lines)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(msg)
    elif sys.stdout:
        print(msg, flush=True)
    os._exit(0)


def main():
    if "--selftest" in sys.argv:
        return selftest()
    setup_logging()
    app = App()
    app.start()
    if "--headless" in sys.argv:              # server only: open the printed address in a browser
        import time
        print(app.server.local_url, flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        from .window import Shell
        Shell(app).run()
    # the window is gone: close the audio devices, but never let a stuck driver keep the process alive
    import threading
    t = threading.Thread(target=app.stop, daemon=True)
    t.start()
    t.join(3)
    logging.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
