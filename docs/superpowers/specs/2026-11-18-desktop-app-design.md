# Standup Generator as a desktop app — design

Status: Approved direction, not yet planned (2026-11-18). Interim: `run.sh` (see §10).

## 1. Intent

Today the tool is a local web server: open a terminal, activate the virtualenv,
remember `standup serve`, remember the port, open a browser. The owner wants it to
behave like a desktop app: **click an icon, a window opens, it does its thing;
close the window and it is gone.** It must not be tied to the Mac — the same app
should run on Windows, Linux and macOS.

Nothing about *what* the tool does changes. This is purely how it is launched,
shown and packaged.

## 2. Goals

- One click from the OS's normal launcher (Dock/Applications, Start menu, Linux app
  launcher) opens a window showing the existing UI.
- No terminal, no virtualenv, no Python install, no port to remember.
- Closing the window (or Cmd+Q / Alt+F4) shuts the server down cleanly.
- macOS, Windows and Linux from one codebase.
- Builds for all three produced automatically from the GitHub repo.
- `pip install` / `standup serve` / library use keep working exactly as now.

## 3. Non-goals

- Code signing / notarisation (unsigned builds; one-time OS warning is accepted).
- Auto-update. Users download a new release by hand.
- An in-app settings editor (v1 points at the config folder instead; see §6.5).
- App-store distribution, installers (.dmg/.msi/.deb). Zipped app folders are enough.
- Multi-user or network access. Still single user, localhost only.

## 4. Anti-goals

- **Silent failure.** If the app cannot start (bad config, port, missing web view),
  the user must see a message, not an icon that bounces and vanishes.
- **Losing the localhost-only guarantee.** The server must never listen on anything
  but 127.0.0.1, and other websites must not be able to drive it.
- **Forking the UI.** The window shows the same HTML/JS as the browser version;
  no second frontend.
- **Secrets inside the bundle.** Tokens stay in the user's `.env`, never baked in.

## 5. Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | **pywebview native window + PyInstaller**, built per OS in GitHub Actions, browser fallback | Real app on all OSes, one codebase. Unsigned, 40–80 MB, Linux needs a system web view package. | **Chosen** |
| B | Single executable that opens the default browser + tray icon (pystray) | Fewest OS dependencies. But it's a browser tab, not an app; tray icons are flaky on some Linux desktops. | Rejected as primary; its idea survives as A's fallback |
| C | Electron / Tauri shell with Python sidecar | Polished installers, but rewrites the shell in JS/Rust and bundles Python on the side — many moving parts for no gain over A. | Rejected |
| D | Docker / docker compose | Not clickable; every input (repos, git email, timezone, .env, history) must be mounted, each a silent-wrong-result risk. | Rejected |

A was picked because the owner asked for a clickable app with its own window that
runs on all three OSes; pywebview uses each OS's built-in web view (WebKit on
macOS, Edge WebView2 on Windows, GTK/Qt WebKit on Linux), so the Python code is
identical everywhere and only the build is per-OS.

## 6. Design

### 6.1 New entry point

New module `standup_generator/desktop.py`, exposed as:

- console script `standup-app` (for running from source), and
- `standup app` subcommand (same thing), and
- the PyInstaller entry for the bundled app.

`pywebview` becomes an optional extra: `pip install standup-generator[desktop]`.
The core package does not depend on it.

### 6.2 Startup sequence

1. Resolve config (§6.5). On failure → show error dialog (§6.7), exit non-zero.
2. Pick a free port: bind a socket to `127.0.0.1:0`, read the port, close it.
   (Small race accepted; uvicorn failing to bind is reported like any other error.)
3. Start uvicorn **in a background thread** with `uvicorn.Server(Config(app,
   host="127.0.0.1", port=port, log_config=<file logging>))`, keeping a handle so
   it can be stopped via `server.should_exit = True`.
4. Wait until ready: poll `GET /api/window` (Host `127.0.0.1`) every 100 ms,
   timeout 15 s. Timeout → error dialog, stop server, exit.
5. Open the window: `webview.create_window("Standup Generator vX.Y.Z",
   f"http://127.0.0.1:{port}/", width=1000, height=800, min_size=(640, 480))`,
   then `webview.start()` (blocks on the main thread — required on macOS).
6. When `webview.start()` returns (window closed / app quit): set
   `server.should_exit = True`, join the thread (timeout 5 s), exit 0.

### 6.3 Browser fallback

If `import webview` fails, or `webview.start()` raises because no GUI backend is
available (typical on a minimal Linux install without WebKitGTK/Qt):

- open `http://127.0.0.1:{port}/?app=1` with `webbrowser.open`,
- log why the native window was unavailable,
- keep running until the user clicks **Quit** in the page (§6.4) or the process is
  terminated (SIGINT/SIGTERM handled → clean shutdown).

### 6.4 Quit button and shutdown endpoint

In app mode only (both window and fallback), the page shows a small **Quit** button
in the header. It calls `POST /api/shutdown`, which sets the server's exit flag and
closes the window if one exists.

- The endpoint is registered only when `create_app(..., app_mode=True)`.
- **Origin check (new, app-wide):** add middleware rejecting any non-GET request
  whose `Origin` header is present and not `http://127.0.0.1:<port>` /
  `http://localhost:<port>`. Today's Host guard stops DNS rebinding but not a
  malicious page POSTing straight to `127.0.0.1:<port>`; with a shutdown endpoint
  that gap matters. (This also closes the "no Origin check" deferred minor.)
- The page learns it is in app mode from `GET /api/app-info` →
  `{"app_mode": true, "version": "...", "config_dir": "..."}`.

### 6.5 Config, `.env` and data locations

A bundled app's working directory is `/` (macOS) or wherever the shortcut points, so
`./standup.yaml` and `./.env` are meaningless. In app mode:

- Config dir: `~/.config/standup/` on all three OSes (already in the lookup order;
  works on Windows as `C:\Users\<u>\.config\standup\`). `STANDUP_CONFIG` env var
  overrides the file path.
- `.env` is read from the config dir (already supported: `.env` next to the
  config file).
- History DB unchanged: `~/.local/share/standup-generator/history.db`.
- Log file: `~/.local/share/standup-generator/app.log`, rotating, 1 MB × 3.

**First run** (no config found): copy `standup.example.yaml` → `standup.yaml` and
`env.example` → `.env` into the config dir, then open the UI with a **Setup needed**
panel listing what's missing (Jira URL, tokens, repo folders), the config folder path,
and an **Open config folder** button (`os.startfile` / `open` / `xdg-open`). Sources
already report missing settings as readable errors, so the panel can reuse
`/api/generate`'s error list via a lightweight `GET /api/setup-check` that builds
sources without calling them.

### 6.6 Environment differences a GUI app has

- **PATH:** apps launched from Finder get `PATH=/usr/bin:/bin:/usr/sbin:/sbin`.
  `git` resolves to `/usr/bin/git` (Xcode CLT shim) — fine. On Windows, `git` must
  be on the system PATH (Git for Windows default). If `git` is missing, the
  git_local source must say so ("git: not found on PATH"), not crash.
- **No stdout/stderr:** PyInstaller `--windowed` on Windows sets `sys.stdout` /
  `sys.stderr` to `None`; uvicorn's default logging writes to them and crashes.
  Configure logging to the log file before starting uvicorn and guard any `print`.
- **Global git email:** read via `git config --global` as now — works because the
  app runs as the user, not in a sandbox.
- **Timezone:** system local time, as now.

### 6.7 Error dialogs

Before the window exists there is nowhere to render errors, so use
`webview.create_window` with an inline HTML error page when pywebview is available;
otherwise `tkinter.messagebox` (stdlib) when available; otherwise write to the log
and, on fallback, open the browser to a static error page. Every fatal path writes
the full traceback to the log file and the dialog shows its path.

### 6.8 Packaging

- `packaging/standup.spec` (PyInstaller), **onedir** mode (faster start than onefile,
  fewer antivirus false positives on Windows), `--windowed`.
- Bundle package data: `templates/*`, `web/static/*` via `collect_data_files`.
- Icons: `packaging/icons/standup.icns` (macOS), `.ico` (Windows), `.png` (Linux).
- Outputs:
  - macOS: `Standup Generator.app` → `standup-generator-<ver>-macos-arm64.zip`
  - Windows: `Standup Generator\Standup Generator.exe` → `…-windows-x64.zip`
  - Linux: `standup-generator/` folder + `standup-generator.desktop` +
    `install.sh` (copies the `.desktop` file into `~/.local/share/applications`)
    → `…-linux-x64.tar.gz`
- Platform extras for pywebview: macOS `pyobjc` (pulled in automatically);
  Windows `pythonnet` (Edge WebView2 runtime ships with Windows 10/11);
  Linux GTK backend using the system's `libwebkit2gtk-4.1` + `gir1.2-webkit2-4.1`
  (documented runtime requirement; absent → browser fallback).

### 6.9 Build pipeline

`.github/workflows/release.yml`, triggered by pushing a tag `v*`:

- Matrix: `macos-14` (arm64), `windows-latest`, `ubuntu-22.04`.
- Steps: checkout → set up Python 3.12 → install `.[desktop,dev]` + PyInstaller
  (+ apt packages on Linux) → `pytest` → `pyinstaller packaging/standup.spec` →
  **smoke test** (§6.10) → archive → upload to a GitHub Release for the tag.
- Version comes from `pyproject.toml`; the workflow fails if the tag and the
  version disagree.

### 6.10 Testing

- Unit tests (`tests/test_desktop.py`), pywebview mocked:
  - free-port helper returns a bindable port;
  - server thread starts, readiness poll succeeds, `stop()` joins within 5 s;
  - window close → server stopped;
  - `import webview` failure → browser fallback path chosen, `webbrowser.open`
    called with `?app=1`;
  - `/api/shutdown` absent when `app_mode=False`, present and effective when True;
  - Origin middleware: foreign Origin on POST → 403; same Origin → allowed;
    no Origin (CLI/curl) → allowed;
  - first run copies templates into an empty config dir and never overwrites;
  - stdout `None` does not crash startup (simulate by patching `sys.stdout`).
- Smoke test flag: `standup-app --self-test` starts the server headless, hits
  `/api/window` and `/api/app-info`, stops, exits 0. Run by CI on each built
  bundle, so every OS's artefact is proven to start.
- Manual checklist per OS before a release: launch from the OS launcher, generate,
  copy prompt, save final, close window → process gone, relaunch → history kept.
  Only the macOS build can be checked by the current owner day to day; Windows and
  Linux rely on the CI smoke test until someone runs them.

## 7. What changes in existing code

- `web/app.py`: `create_app(config, sources=None, app_mode=False, on_shutdown=None)`;
  Origin middleware; `/api/app-info`; `/api/shutdown` (app mode); `/api/setup-check`.
- `web/static/*`: Quit button + Setup-needed panel, both shown only when
  `/api/app-info` says app mode.
- `cli.py`: `app` subcommand → `desktop.main`.
- `sources/git_local.py`: friendly error when `git` is not on PATH.
- `pyproject.toml`: `desktop` extra, `standup-app` script.
- README: "Desktop app" section (download, first-run warning per OS, config folder,
  Linux package requirement).

## 8. Open questions (for when this is picked up)

1. Intel Macs: add a `macos-13` x86_64 build, or universal2? (Default: arm64 only.)
2. Second launch while running: allow two windows, or focus the existing one via a
   lock file holding the port? (Default: allow; SQLite copes.)
3. Should a later version add an in-app settings editor so `.env` never needs
   hand-editing?
4. Signing: worth an Apple Developer ID / Windows certificate later if shared with
   teammates?

## 9. Builder's latitude

Window size, icon artwork, log format, exact wording of dialogs and the Setup panel,
and the CI job layout are the builder's call within the constraints above.

## 10. Interim: `run.sh`

Until the app exists, `./run.sh` at the repo root gives one-command start on
macOS/Linux (and Git Bash on Windows): it creates/refreshes the virtualenv with `uv`
when needed, picks a free port starting at 8765, starts the server, opens the
browser once it answers, and on Ctrl+C stops the server cleanly.
