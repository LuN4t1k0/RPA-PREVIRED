# Windows Launcher — Design Spec
**Date:** 2026-05-29
**Status:** Approved

## Overview

A standalone Windows executable (`PreviredDownloader.exe`) that lets non-technical users run the Previred Downloader bot on their own machine without installing Python, git, or any other tooling. The launcher handles first-run setup, auto-updates from GitHub, and launching the Streamlit app.

This is a **separate project** (`previred-launcher/`) that ships as its own repo or subfolder. The bot codebase (`app.py`, `bot/`, etc.) remains unchanged and continues to power both the Railway web deployment and the desktop launcher simultaneously.

## User Experience

1. User downloads `PreviredDownloader.exe` (~3 MB, distributed via Drive/email/WhatsApp)
2. Double-clicks — a small window appears with a progress bar and status text
3. **First run only (~2–3 min):** window shows "Instalando Python…", "Descargando dependencias…", "Descargando Chromium…", "¡Listo!"
4. Browser opens automatically at `http://localhost:8501` with the full app
5. **Subsequent runs (~3–5 sec):** window shows "Actualizando…", then browser opens
6. When the user closes the browser, the launcher window stays visible so they can relaunch without reopening the `.exe`
7. No admin rights required — everything installs under `AppData\Local\PreviredDownloader\`

## Architecture

The launcher is a separate Python project compiled to a single `.exe` via PyInstaller. It has four modules:

```
previred-launcher/
  launcher.py        # Entry point — tkinter window, orchestrates setup → update → run
  setup.py           # First-run setup: Python embeddable + pip + deps + Chromium
  updater.py         # Downloads latest code zip from private GitHub repo
  runner.py          # Launches Streamlit subprocess + opens browser
  build.bat          # Builds PreviredDownloader.exe (run by developer, not users)
  requirements.txt   # Launcher deps only (pyinstaller, requests)
```

### Directory layout on user's machine

```
%LOCALAPPDATA%\PreviredDownloader\
  python\            # Python 3.12 embeddable (from python.org)
  app\               # Latest extracted bot code (from GitHub zip)
  chromium\          # Playwright Chromium (installed by playwright CLI)
  .version           # SHA of last downloaded GitHub commit
```

### Module responsibilities

**`setup.py` — runs only on first launch**
- Downloads Python 3.12 embeddable zip from python.org
- Extracts to `python\`, patches `python312._pth` to enable pip
- Downloads and runs `get-pip.py`
- Runs `pip install -r requirements.txt` from the bot code
- Runs `playwright install chromium`
- Writes `%LOCALAPPDATA%\PreviredDownloader\.setup_done` marker file

**`updater.py` — runs on every launch**
- Calls GitHub API (`/repos/{owner}/{repo}/commits/main`) to get latest commit SHA
- Compares against `.version` file
- If different: downloads `/repos/{owner}/{repo}/zipball/main` as a zip
- Extracts top-level folder from zip and overwrites files in `app\` (GitHub zips wrap content in a `{owner}-{repo}-{sha}/` folder)
- Re-runs `pip install -r app\requirements.txt` (pip skips packages already up to date)
- Updates `%LOCALAPPDATA%\PreviredDownloader\.version` with new SHA

**`runner.py`**
- Starts `python\python.exe -m streamlit run app\app.py --server.port 8501 --server.headless true` as a subprocess
- Polls `http://localhost:8501/healthz` until ready (max 30 sec)
- Opens `http://localhost:8501` in the default browser
- Returns the subprocess handle to `launcher.py` for lifecycle management

**`launcher.py`**
- Creates a `tkinter` window (300×120 px) with app title, status label, and progress bar
- Runs setup/update/launch in a background thread, posts progress to the UI thread via a queue
- After launch, shows a "Abrir app" button and a "Cerrar" button
- On close: terminates the Streamlit subprocess gracefully

### GitHub authentication

A **fine-grained GitHub Personal Access Token** (read-only, `Contents` permission on the repo) is embedded as a constant in `updater.py`. The compiled `.exe` obfuscates it from casual inspection. Acceptable for 2 internal trusted users; not suitable for public distribution.

## Update Flow

```
Launch .exe
  └─ setup done? ──no──► run setup (one time)
       │ yes
       ▼
  fetch latest SHA from GitHub API
       │
  SHA changed? ──no──► skip download
       │ yes
       ▼
  download zip, extract to app\
  requirements.txt changed? → re-run pip install
  write new SHA to .version
       │
       ▼
  start streamlit, open browser
```

## Build Process (developer only)

1. `pip install pyinstaller requests` in a Windows environment
2. Run `build.bat` which calls:
   ```
   pyinstaller --onefile --windowed --name PreviredDownloader launcher.py
   ```
3. Output: `dist\PreviredDownloader.exe` (~3 MB)
4. Distribute via Google Drive, email, or WhatsApp

The `.exe` only needs to be rebuilt when the launcher logic itself changes (rare). Bot code updates flow through GitHub automatically.

## Coexistence with Railway deployment

The bot codebase is unchanged. Railway and the desktop launcher both run the same `app.py` from the same `main` branch. A `git push` to `main` updates both:
- Railway: redeploys automatically
- Desktop: users get the update next time they open the `.exe`

## Compatibility

- Windows 10 / 11 (64-bit)
- No admin rights required
- No Python, git, or other tooling needed on user's machine

## Out of Scope

- macOS or Linux builds
- Automatic `.exe` update (launcher logic changes require a new `.exe` to be sent manually — acceptable given 2 users and infrequent launcher changes)
- Code signing / SmartScreen bypass (Windows may show an "unknown publisher" warning on first run; user clicks "More info → Run anyway")
