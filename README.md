# Coms Log

A floating, see-through transcript of your production intercom. Plug in your talkback / PL / Dante feeds and Coms
Log writes down what's said on each channel, colour-coded, time-stamped and searchable. Everything runs on your
computer (OpenAI Whisper via [faster-whisper](https://github.com/SYSTRAN/faster-whisper)); no audio goes to the internet.

Made for church production teams. Free and open source (MIT).

## Features

- **Any input**: USB interfaces, Dante Virtual Soundcard / Dante Via, MADI, a laptop mic. Each channel is one input.
- **Live transcript**: lines appear a moment after someone stops talking. A "…" bubble shows who is talking right now.
- **Groups**: put channels together (say Director + Cameras as "Production") and watch them in one view, next to All and the single channels.
- **Floats on top** of ProPresenter, your switcher software or anything else, and can be **see-through**
  (25-100 % opacity) so it never fully covers what's under it.
- **Liquid-glass look** with a choice of tint colours and text sizes.
- **Keywords**: names, "standby", "go"… are highlighted and flash the window (plus an optional chime).
- **Type a note** into any channel (shown with a keyboard icon) when you can't talk.
- **Search** the live view or every saved day. **Export** any day as text or CSV.
- **Share on the network** (optional): phones and other computers on the same network can follow the log
  read-only in a browser.
- Logs are saved per day and kept for 30 days by default.

## Download

Get the latest from [Releases](https://github.com/connorduckett/coms-log/releases):

- **Windows 10/11 (64-bit)**: `ComsLog-…-windows-x64.zip`. Unzip anywhere and run `Coms Log.exe`.
  The app isn't code-signed yet, so Windows SmartScreen may say "Windows protected your PC". Click **More info → Run anyway**.
  On PCs with Smart App Control turned on, unsigned apps are blocked; run it from source instead (below).
- **macOS (Apple Silicon)**: `ComsLog-…-macos-arm64.zip`. Unzip and move **Coms Log** to Applications.
  The first time, right-click it and choose **Open** (it isn't notarized). Allow microphone access when asked.

The first start downloads the speech model (about 145 MB for "Base"), once.

**Updating**: Coms Log checks GitHub for a new version when it starts (and every few hours) and shows a
banner with a Download button. It never installs anything by itself: download the new zip and replace the old app.
Your channels, settings, logs and speech model are kept (they live in the data folder, not in the app).
Turn the check off under Settings → More.

## Setting it up

1. Open **Settings → Channels** and **Add channel**.
2. Choose the input device and input number, give it a name (Director, Cameras, Audio, Lighting…) and a colour.
3. Talk on it and drag the **Gate** just above the noise floor (the white line on the meter), so it only listens when
   someone is talking.
4. Add your **keywords** under **Alerts**.

**Dante**: in Dante Controller, route the intercom / talkback channels to Dante Virtual Soundcard (or Dante Via), then
press **Refresh devices** in Coms Log. On Windows each pair of DVS channels shows up as its own device ("DVS Receive 1-2"),
so pick the device and then input 1 or 2.

**Which speech model?** "Base (English)" is a good start on most computers. If the log falls behind
("catching up" in the title bar), use "Tiny"; on a fast computer "Small" is more accurate.

## Run from source

Needs Python 3.10+.

```
python -m pip install -r requirements.txt
python run.py
```

`python run.py --headless` runs without a window and prints an address to open in a browser.

Settings, logs and models are kept in `%APPDATA%\Coms Log` (Windows) or `~/Library/Application Support/Coms Log` (macOS).

## Building

`python -m pip install -r requirements-build.txt` then `python build.py` (PyInstaller). Pushing a `v*` tag builds the
Windows and macOS apps on GitHub Actions and publishes a Release.

## License

MIT, see [LICENSE](LICENSE).
