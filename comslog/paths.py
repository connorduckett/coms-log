"""Per-user data folder: settings, logs and the downloaded speech model."""
import os
import sys

from . import APP_NAME


def data_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def sub(name):
    d = os.path.join(data_dir(), name)
    os.makedirs(d, exist_ok=True)
    return d


def resource(*parts):
    """Bundled files (PyInstaller unpacks them to sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    if hasattr(sys, "_MEIPASS"):
        base = os.path.join(base, "comslog")
    return os.path.join(base, *parts)
