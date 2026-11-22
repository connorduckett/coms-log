import sys

from .app import App, setup_logging


def selftest():
    """Used by the build: every native piece must import inside the packaged app."""
    import ctranslate2, faster_whisper, numpy, sounddevice, webview  # noqa: F401
    from .paths import resource
    import os
    assert os.path.isfile(resource("static", "index.html")), "index.html missing"
    msg = f"selftest ok {faster_whisper.__version__} {ctranslate2.__version__} {sounddevice.__version__}"
    i = sys.argv.index("--selftest")
    if len(sys.argv) > i + 1:          # windowed builds have no console: write to the given file
        with open(sys.argv[i + 1], "w") as f:
            f.write(msg)
    elif sys.stdout:
        print(msg, flush=True)


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
    app.stop()


if __name__ == "__main__":
    main()
