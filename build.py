"""Build the Coms Log desktop app with PyInstaller.

    python -m pip install -r requirements-build.txt
    python build.py

Output goes to release/:
  Windows  ComsLog-<version>-windows-x64.zip   (folder with "Coms Log.exe")
  macOS    ComsLog-<version>-macos-<arch>.zip  (Coms Log.app)
"""
import os
import platform
import plistlib
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from comslog import __version__  # noqa: E402

PLAT = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
ARCH = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(),
                                                                                   platform.machine().lower())
NAME = f"ComsLog-{__version__}-{PLAT}-{ARCH}"
APP = "Coms Log"
DIST, OUT = os.path.join(ROOT, "dist"), os.path.join(ROOT, "release")


def pyinstaller():
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", APP, "--windowed",
            "--icon", os.path.join("comslog", "static", "icon-512.png"),
            "--add-data", f"comslog{os.sep}static{os.pathsep}comslog/static",
            "--collect-all", "faster_whisper",     # includes its assets
            "--collect-all", "ctranslate2",        # native inference library
            "--collect-all", "tokenizers",
            "--collect-all", "sounddevice",
            "--collect-all", "_sounddevice_data",  # bundled PortAudio (Windows / macOS wheels)
            "--collect-submodules", "webview",
            "--exclude-module", "onnxruntime",     # only needed for Whisper's VAD filter, which isn't used
            "--exclude-module", "tkinter"]
    if PLAT == "macos":
        args += ["--osx-bundle-identifier", "app.comslog.desktop"]
    subprocess.check_call(args + ["run.py"], cwd=ROOT)


def mac_plist(app):
    """Microphone permission text (macOS refuses audio input without it), then re-sign since the bundle changed."""
    p = os.path.join(app, "Contents", "Info.plist")
    with open(p, "rb") as f:
        info = plistlib.load(f)
    info.update({
        "CFBundleDisplayName": APP,
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "NSMicrophoneUsageDescription": "Coms Log listens to your intercom / talkback inputs and writes down what is "
                                        "said. Audio is transcribed on this Mac and never sent anywhere.",
        "NSLocalNetworkUsageDescription": "Coms Log can share its live log with phones and computers on your network "
                                          "when you turn on Share.",
        "NSHighResolutionCapable": True,
    })
    with open(p, "wb") as f:
        plistlib.dump(info, f)
    subprocess.check_call(["codesign", "--force", "--deep", "--sign", "-", app])


def package():
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, NAME + ".zip")
    if os.path.exists(dst):
        os.remove(dst)
    if PLAT == "windows":
        shutil.make_archive(dst[:-4], "zip", DIST, APP)
        return dst, os.path.join(DIST, APP, APP + ".exe")
    if PLAT == "macos":
        app = os.path.join(DIST, APP + ".app")
        mac_plist(app)
        subprocess.check_call(["ditto", "-c", "-k", "--keepParent", app, dst])
        return dst, os.path.join(app, "Contents", "MacOS", APP)
    shutil.make_archive(dst[:-4], "zip", DIST, APP)
    return dst, os.path.join(DIST, APP, APP)


def smoke(exe):
    res = os.path.join(OUT, "selftest.txt")
    if os.path.exists(res):
        os.remove(res)
    try:
        out = subprocess.run([exe, "--selftest", res], capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired as e:
        out = e
    text = open(res, encoding="utf-8").read() if os.path.exists(res) else "(no selftest output)"
    print(text, getattr(out, "stdout", ""), getattr(out, "stderr", ""))
    os.path.exists(res) and os.remove(res)
    if "selftest ok" not in text:
        raise SystemExit("smoke test failed")


if __name__ == "__main__":
    pyinstaller()
    dst, exe = package()
    smoke(exe)
    print("built", dst, f"{os.path.getsize(dst) / 1e6:.0f} MB")
