# Windows Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `PreviredDownloader.exe` — a self-contained Windows launcher that installs the bot environment on first run, auto-updates from GitHub on every run, and opens the Streamlit app in the browser.

**Architecture:** A new Python project in `previred-launcher/` with four focused modules (setup, updater, runner, launcher) compiled into a single `.exe` via PyInstaller. First run bootstraps Python embeddable + Playwright Chromium; subsequent runs do a GitHub zip pull and launch Streamlit.

**Tech Stack:** Python 3.12, tkinter (stdlib), requests, PyInstaller, GitHub REST API (zip download)

---

## File Map

| File | Responsibility |
|------|---------------|
| `previred-launcher/config.py` | GitHub token, owner, repo — developer fills in |
| `previred-launcher/setup.py` | First-run: download Python embeddable, install pip |
| `previred-launcher/updater.py` | Fetch latest SHA, download + extract GitHub zip, run pip install |
| `previred-launcher/runner.py` | Start Streamlit subprocess, poll until ready, open browser |
| `previred-launcher/launcher.py` | tkinter window, progress queue, orchestrates setup→update→run |
| `previred-launcher/requirements.txt` | `requests` only (tkinter + subprocess are stdlib) |
| `previred-launcher/build.bat` | PyInstaller one-file build command |
| `previred-launcher/tests/test_setup.py` | Unit tests for setup module |
| `previred-launcher/tests/test_updater.py` | Unit tests for updater module |
| `previred-launcher/tests/test_runner.py` | Unit tests for runner module |

---

## Task 1: Project scaffold

**Files:**
- Create: `previred-launcher/config.py`
- Create: `previred-launcher/requirements.txt`
- Create: `previred-launcher/tests/__init__.py`

- [ ] **Step 1: Create `previred-launcher/config.py`**

```python
# Fill these in before building the .exe
GITHUB_TOKEN = "ghp_REPLACE_WITH_YOUR_TOKEN"
GITHUB_OWNER = "REPLACE_WITH_GITHUB_USERNAME"
GITHUB_REPO  = "previred"
GITHUB_BRANCH = "main"
```

- [ ] **Step 2: Create `previred-launcher/requirements.txt`**

```
requests>=2.31.0
pyinstaller>=6.0.0
pytest>=8.0.0
```

- [ ] **Step 3: Create `previred-launcher/tests/__init__.py`** (empty file)

- [ ] **Step 4: Install dev dependencies**

```bash
cd previred-launcher
pip install -r requirements.txt
```

Expected: installs requests, pyinstaller, pytest with no errors.

- [ ] **Step 5: Commit**

```bash
git add previred-launcher/
git commit -m "feat: scaffold previred-launcher project"
```

---

## Task 2: setup module

**Files:**
- Create: `previred-launcher/setup.py`
- Create: `previred-launcher/tests/test_setup.py`

- [ ] **Step 1: Write the failing tests**

Create `previred-launcher/tests/test_setup.py`:

```python
import pytest
from pathlib import Path
import setup


def test_is_python_ready_false(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "PYTHON_DIR", tmp_path / "python")
    assert setup.is_python_ready() is False


def test_is_python_ready_true(tmp_path, monkeypatch):
    python_dir = tmp_path / "python"
    python_dir.mkdir()
    (python_dir / "python.exe").write_text("")
    monkeypatch.setattr(setup, "PYTHON_DIR", python_dir)
    assert setup.is_python_ready() is True


def test_is_playwright_ready_false(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "PLAYWRIGHT_MARKER", tmp_path / ".playwright_done")
    assert setup.is_playwright_ready() is False


def test_is_playwright_ready_true(tmp_path, monkeypatch):
    marker = tmp_path / ".playwright_done"
    marker.write_text("done")
    monkeypatch.setattr(setup, "PLAYWRIGHT_MARKER", marker)
    assert setup.is_playwright_ready() is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd previred-launcher
python -m pytest tests/test_setup.py -v
```

Expected: `ModuleNotFoundError: No module named 'setup'`

- [ ] **Step 3: Create `previred-launcher/setup.py`**

```python
import os
import subprocess
import urllib.request
import zipfile
from pathlib import Path

BASE_DIR         = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PreviredDownloader"
PYTHON_DIR       = BASE_DIR / "python"
PLAYWRIGHT_MARKER = BASE_DIR / ".playwright_done"

_PYTHON_VERSION  = "3.12.9"
_PYTHON_URL      = (
    f"https://www.python.org/ftp/python/{_PYTHON_VERSION}"
    f"/python-{_PYTHON_VERSION}-embed-amd64.zip"
)
_GET_PIP_URL     = "https://bootstrap.pypa.io/get-pip.py"


def is_python_ready() -> bool:
    return (PYTHON_DIR / "python.exe").exists()


def is_playwright_ready() -> bool:
    return PLAYWRIGHT_MARKER.exists()


def install_python(on_status=None) -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)

    if on_status:
        on_status("Descargando Python...")
    zip_path = BASE_DIR / "python_embed.zip"
    urllib.request.urlretrieve(_PYTHON_URL, zip_path)

    if on_status:
        on_status("Instalando Python...")
    PYTHON_DIR.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(PYTHON_DIR)
    zip_path.unlink()

    # Enable site-packages so pip can install packages
    pth_file = PYTHON_DIR / "python312._pth"
    text = pth_file.read_text()
    pth_file.write_text(text.replace("#import site", "import site"))

    if on_status:
        on_status("Instalando pip...")
    get_pip = BASE_DIR / "get-pip.py"
    urllib.request.urlretrieve(_GET_PIP_URL, get_pip)
    subprocess.run(
        [str(PYTHON_DIR / "python.exe"), str(get_pip)],
        check=True,
        creationflags=_NO_WINDOW,
    )
    get_pip.unlink()


def install_playwright(on_status=None) -> None:
    if on_status:
        on_status("Descargando Chromium (primera vez, ~300 MB)...")
    playwright_exe = PYTHON_DIR / "Scripts" / "playwright.exe"
    subprocess.run(
        [str(playwright_exe), "install", "chromium"],
        check=True,
        creationflags=_NO_WINDOW,
    )
    PLAYWRIGHT_MARKER.write_text("done")


# Windows-only flag; safe to define on all platforms
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd previred-launcher
python -m pytest tests/test_setup.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add previred-launcher/setup.py previred-launcher/tests/test_setup.py
git commit -m "feat: add setup module with Python embeddable install"
```

---

## Task 3: updater module

**Files:**
- Create: `previred-launcher/updater.py`
- Create: `previred-launcher/tests/test_updater.py`

- [ ] **Step 1: Write the failing tests**

Create `previred-launcher/tests/test_updater.py`:

```python
import io
import zipfile
import pytest
from pathlib import Path
import updater


def test_get_local_sha_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "VERSION_FILE", tmp_path / ".version")
    assert updater.get_local_sha() == ""


def test_get_local_sha_existing(tmp_path, monkeypatch):
    f = tmp_path / ".version"
    f.write_text("abc123\n")
    monkeypatch.setattr(updater, "VERSION_FILE", f)
    assert updater.get_local_sha() == "abc123"


def test_needs_update_true(tmp_path, monkeypatch):
    f = tmp_path / ".version"
    f.write_text("abc123")
    monkeypatch.setattr(updater, "VERSION_FILE", f)
    monkeypatch.setattr(updater, "get_remote_sha", lambda: "def456")
    assert updater.needs_update() is True


def test_needs_update_false(tmp_path, monkeypatch):
    f = tmp_path / ".version"
    f.write_text("abc123")
    monkeypatch.setattr(updater, "VERSION_FILE", f)
    monkeypatch.setattr(updater, "get_remote_sha", lambda: "abc123")
    assert updater.needs_update() is False


def _make_github_zip(files: dict) -> bytes:
    """Build a zip mimicking GitHub's zipball structure (top-level owner-repo-sha/ folder)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(f"owner-repo-abc123/{name}", content)
    return buf.getvalue()


def test_extract_zip_contents(tmp_path):
    raw = _make_github_zip({
        "app.py": "print('hello')",
        "bot/__init__.py": "",
        "requirements.txt": "streamlit\n",
    })
    app_dir = tmp_path / "app"
    updater.extract_zip_contents(raw, app_dir)

    assert (app_dir / "app.py").read_text() == "print('hello')"
    assert (app_dir / "bot" / "__init__.py").exists()
    assert (app_dir / "requirements.txt").read_text() == "streamlit\n"


def test_extract_zip_overwrites_existing(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "old_file.txt").write_text("old")

    raw = _make_github_zip({"app.py": "new"})
    updater.extract_zip_contents(raw, app_dir)

    assert not (app_dir / "old_file.txt").exists()
    assert (app_dir / "app.py").read_text() == "new"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd previred-launcher
python -m pytest tests/test_updater.py -v
```

Expected: `ModuleNotFoundError: No module named 'updater'`

- [ ] **Step 3: Create `previred-launcher/updater.py`**

```python
import os
import shutil
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path

import requests

from config import GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH
from setup import PYTHON_DIR, BASE_DIR

APP_DIR      = BASE_DIR / "app"
VERSION_FILE = BASE_DIR / ".version"

_HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def get_remote_sha() -> str:
    url = (
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
        f"/commits/{GITHUB_BRANCH}"
    )
    resp = requests.get(url, headers=_HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()["sha"]


def get_local_sha() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return ""


def needs_update() -> bool:
    return get_remote_sha() != get_local_sha()


def extract_zip_contents(raw_zip: bytes, app_dir: Path) -> None:
    """Extract a GitHub zipball (has top-level owner-repo-sha/ wrapper) into app_dir."""
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)

    with zipfile.ZipFile(BytesIO(raw_zip)) as zf:
        names = zf.namelist()
        # GitHub wraps everything in a single top-level folder
        top = names[0].split("/")[0] + "/"
        for member in names:
            relative = member[len(top):]
            if not relative:
                continue
            target = app_dir / relative
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))


def download_and_install(on_status=None) -> None:
    if on_status:
        on_status("Descargando actualización...")
    url = (
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
        f"/zipball/{GITHUB_BRANCH}"
    )
    resp = requests.get(url, headers=_HEADERS, timeout=60)
    resp.raise_for_status()

    if on_status:
        on_status("Instalando actualización...")
    extract_zip_contents(resp.content, APP_DIR)

    if on_status:
        on_status("Actualizando dependencias...")
    pip_exe = PYTHON_DIR / "Scripts" / "pip.exe"
    subprocess.run(
        [str(pip_exe), "install", "-r", str(APP_DIR / "requirements.txt"), "-q"],
        check=True,
        creationflags=_NO_WINDOW,
    )

    VERSION_FILE.write_text(get_remote_sha())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd previred-launcher
python -m pytest tests/test_updater.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add previred-launcher/updater.py previred-launcher/tests/test_updater.py
git commit -m "feat: add updater module with GitHub zip download"
```

---

## Task 4: runner module

**Files:**
- Create: `previred-launcher/runner.py`
- Create: `previred-launcher/tests/test_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `previred-launcher/tests/test_runner.py`:

```python
import pytest
import runner


def test_wait_for_server_success(monkeypatch):
    class _Resp:
        status_code = 200

    monkeypatch.setattr(runner.requests, "get", lambda url, timeout: _Resp())
    assert runner.wait_for_server(8501, timeout=2) is True


def test_wait_for_server_timeout(monkeypatch):
    import requests as _req

    def _fail(url, timeout):
        raise _req.ConnectionError()

    monkeypatch.setattr(runner.requests, "get", _fail)
    assert runner.wait_for_server(8501, timeout=0.1) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd previred-launcher
python -m pytest tests/test_runner.py -v
```

Expected: `ModuleNotFoundError: No module named 'runner'`

- [ ] **Step 3: Create `previred-launcher/runner.py`**

```python
import os
import subprocess
import time
import webbrowser
from pathlib import Path

import requests

from setup import PYTHON_DIR, BASE_DIR

APP_DIR    = BASE_DIR / "app"
PORT       = 8501
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def wait_for_server(port: int, timeout: float = 30) -> bool:
    """Poll localhost until Streamlit responds or timeout expires."""
    url = f"http://localhost:{port}/healthz"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=1)
            if resp.status_code == 200:
                return True
        except requests.ConnectionError:
            time.sleep(0.5)
    return False


def launch(on_status=None) -> subprocess.Popen:
    """Start Streamlit and open the browser. Returns the subprocess."""
    if on_status:
        on_status("Iniciando aplicación...")

    python_exe = PYTHON_DIR / "python.exe"
    app_script = APP_DIR / "app.py"

    proc = subprocess.Popen(
        [
            str(python_exe), "-m", "streamlit", "run", str(app_script),
            "--server.port", str(PORT),
            "--server.headless", "true",
            "--server.enableCORS", "false",
            "--server.enableXsrfProtection", "false",
        ],
        creationflags=_NO_WINDOW,
    )

    if on_status:
        on_status("Esperando que la app esté lista...")
    if wait_for_server(PORT, timeout=60):
        webbrowser.open(f"http://localhost:{PORT}")
        if on_status:
            on_status("¡Listo! App abierta en el navegador.")
    else:
        if on_status:
            on_status("Advertencia: la app tardó más de lo esperado.")
        webbrowser.open(f"http://localhost:{PORT}")

    return proc
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd previred-launcher
python -m pytest tests/test_runner.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add previred-launcher/runner.py previred-launcher/tests/test_runner.py
git commit -m "feat: add runner module with Streamlit subprocess + browser open"
```

---

## Task 5: launcher (tkinter UI + orchestration)

**Files:**
- Create: `previred-launcher/launcher.py`

No unit tests for tkinter UI — it is verified manually in Task 7.

- [ ] **Step 1: Create `previred-launcher/launcher.py`**

```python
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

import setup
import updater
import runner


class LauncherWindow:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title("Previred Downloader")
        self.root.geometry("340x130")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._status_var = tk.StringVar(value="Iniciando…")
        tk.Label(self.root, textvariable=self._status_var, wraplength=300).pack(pady=(18, 6))

        self._bar = ttk.Progressbar(self.root, mode="indeterminate", length=280)
        self._bar.pack()
        self._bar.start(12)

        self._btn = tk.Button(
            self.root, text="Abrir app", state="disabled",
            command=self._open_browser, width=16,
        )
        self._btn.pack(pady=(10, 0))

        threading.Thread(target=self._worker, daemon=True).start()
        self.root.after(100, self._poll_queue)
        self.root.mainloop()

    # ── worker (background thread) ────────────────────────────────────────────

    def _worker(self):
        try:
            if not setup.is_python_ready():
                setup.install_python(on_status=self._post)

            if not setup.is_playwright_ready() or updater.needs_update():
                updater.download_and_install(on_status=self._post)

            if not setup.is_playwright_ready():
                setup.install_playwright(on_status=self._post)

            self._proc = runner.launch(on_status=self._post)
            self._q.put(("done", None))
        except Exception as exc:
            self._q.put(("error", str(exc)))

    def _post(self, msg: str):
        self._q.put(("status", msg))

    # ── UI updates (main thread) ──────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "status":
                    self._status_var.set(payload)
                elif kind == "done":
                    self._bar.stop()
                    self._bar.config(mode="determinate", value=100)
                    self._btn.config(state="normal")
                    self._status_var.set("✓ App en ejecución")
                elif kind == "error":
                    self._bar.stop()
                    self._status_var.set(f"Error: {payload}")
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)

    def _open_browser(self):
        import webbrowser
        webbrowser.open(f"http://localhost:{runner.PORT}")

    def _on_close(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self.root.destroy()


if __name__ == "__main__":
    LauncherWindow()
```

- [ ] **Step 2: Smoke-test the UI locally (Mac/Linux — Python only, no Windows path)**

```bash
cd previred-launcher
# Set a fake LOCALAPPDATA so paths resolve
LOCALAPPDATA=/tmp python launcher.py
```

Expected: tkinter window opens, worker thread will fail (no Windows path / no token), but the window and progress bar must appear without crash. The error message should appear in the status label.

- [ ] **Step 3: Commit**

```bash
git add previred-launcher/launcher.py
git commit -m "feat: add tkinter launcher UI with background worker"
```

---

## Task 6: build script

**Files:**
- Create: `previred-launcher/build.bat`

This task runs on a Windows machine (or Windows VM/CI).

- [ ] **Step 1: Create `previred-launcher/build.bat`**

```bat
@echo off
echo Installing build dependencies...
pip install pyinstaller requests

echo Building PreviredDownloader.exe...
pyinstaller ^
  --onefile ^
  --windowed ^
  --name PreviredDownloader ^
  --add-data "config.py;." ^
  launcher.py

echo.
echo Done. File: dist\PreviredDownloader.exe
pause
```

- [ ] **Step 2: Fill in real GitHub credentials in `config.py`**

Open `previred-launcher/config.py` and replace:
- `GITHUB_TOKEN` — create a Fine-Grained PAT at github.com → Settings → Developer settings → Personal access tokens → Fine-grained tokens. Set: Repository access = only `previred`, Permissions → Repository permissions → Contents = Read-only.
- `GITHUB_OWNER` — your GitHub username
- `GITHUB_REPO` — `previred` (or whatever the repo is named)

> **Important:** Never commit `config.py` with a real token. Add it to `.gitignore`.

- [ ] **Step 3: Add `config.py` to `.gitignore`**

Add to `/Users/cristianvenegas/Documents/desarrollo/previred/.gitignore`:

```
previred-launcher/config.py
```

- [ ] **Step 4: Commit**

```bash
git add previred-launcher/build.bat .gitignore
git commit -m "feat: add PyInstaller build script and gitignore token"
```

---

## Task 7: Manual integration test on Windows

This task must be run on a real Windows 10/11 machine (or VM).

- [ ] **Step 1: Copy files to Windows machine**

Copy the entire `previred-launcher/` folder (with the real token in `config.py`) to a Windows machine. Or build there directly via `git clone`.

- [ ] **Step 2: Run `build.bat`**

```bat
cd previred-launcher
build.bat
```

Expected: `dist\PreviredDownloader.exe` created (~3 MB).

- [ ] **Step 3: First-run test**

1. Delete `%LOCALAPPDATA%\PreviredDownloader\` if it exists (clean slate)
2. Double-click `dist\PreviredDownloader.exe`
3. Verify window opens with progress bar
4. Wait ~3 min — verify status messages: "Descargando Python…", "Instalando pip…", "Descargando actualización…", "Descargando Chromium…", "¡Listo!"
5. Verify browser opens at `http://localhost:8501` with the login form

- [ ] **Step 4: Subsequent-run test**

1. Close the launcher window (terminates Streamlit)
2. Double-click `PreviredDownloader.exe` again
3. Verify it opens in ~5 seconds (no Python/Chromium install)
4. Verify browser opens again

- [ ] **Step 5: Update test**

1. Make a small visible change to `app.py` in the repo (e.g., change the title text)
2. `git push` to main
3. Close and reopen `PreviredDownloader.exe`
4. Verify the change appears in the browser

- [ ] **Step 6: Distribute**

Upload `dist\PreviredDownloader.exe` to Google Drive / send via WhatsApp to the 2 users.

> **Note on SmartScreen:** Windows may show "Windows protected your PC" on first run because the `.exe` is unsigned. User clicks "More info" → "Run anyway". This is expected for unsigned apps distributed outside the Windows Store.
