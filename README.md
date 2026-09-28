# echoprofile

Spin up ephemeral, isolated Chromium sessions cloned from one persistent logged-in profile.

Keep a single headed profile open (`echoprofile login`), then `echoprofile clone` to fork its cookies/localStorage into a throwaway browser context. Each clone is isolated after creation — it has no ongoing link back to the persistent profile. Close clones independently; the source login stays put.

Requires Python 3.11+.

## Install

This is a local package (not on PyPI). Install it **editable** so source edits take effect without reinstalling. Two common ways:

1. **Project venv** — isolated to this repo, activate it when you work here.
2. **Global tool** — `echoprofile` on your PATH, still pointing at this checkout.

Both can coexist. The global install is what you want for daily use; the venv is what you want for hacking on the package itself (tests, extra deps, a pinned interpreter).

### Editable install in a venv

From the repo root, with [uv](https://docs.astral.sh/uv/) (already used by this checkout):

```bash
cd ~/Projects/echoprofile
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e .
playwright install chromium
```

Plain `venv` + `pip` works the same:

```bash
cd ~/Projects/echoprofile
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

`-e` / `--editable` is the important flag: it links the venv at this directory instead of copying files in. Changing `echoprofile/*.py` is live immediately. Re-run the install only when `pyproject.toml` changes (new dependencies, a new console script).

With the venv activated:

```bash
echoprofile --help
```

Without activating, call it through the venv:

```bash
~/Projects/echoprofile/.venv/bin/echoprofile --help
# or
uv run --directory ~/Projects/echoprofile echoprofile --help
```

### Editable install globally

This puts `echoprofile` on `PATH` (`~/.local/bin/echoprofile`) while still tracking the live source tree. Preferred on this machine: `uv tool`.

```bash
cd ~/Projects/echoprofile
uv tool install --editable .
```

Or pass the path from anywhere:

```bash
uv tool install --editable ~/Projects/echoprofile
```

Confirm:

```bash
uv tool list
which echoprofile          # ~/.local/bin/echoprofile
echoprofile --help
```

`~/.local/bin` must be on `PATH` (it already is if `uv` itself works as `uv`).

Install Playwright's Chromium **into the tool environment**, not the system:

```bash
~/.local/share/uv/tools/echoprofile/bin/playwright install chromium
```

After changing dependencies in `pyproject.toml`:

```bash
uv tool install --editable --reinstall ~/Projects/echoprofile
```

Uninstall:

```bash
uv tool uninstall echoprofile
```

#### pipx alternative

If you use pipx instead of uv:

```bash
pipx install --editable ~/Projects/echoprofile
# Playwright browsers live in pipx's env:
~/.local/share/pipx/venvs/echoprofile/bin/playwright install chromium
```

#### Do not pip-install into system Python

Arch (and any PEP 668 distro) marks the system interpreter as externally managed. `pip install -e .` against `/usr/bin/python` will refuse, and `--break-system-packages` is the wrong workaround. Use a venv or `uv tool` / `pipx`.

## Quick start

The CLI is a thin HTTP client. Start the server first and leave it running.

```bash
echoprofile serve
```

In another terminal:

```bash
# Optional: copy Maestro's existing login state into echoprofile's own profile dir
echoprofile seed-from-maestro

# Open the persistent headed profile. Log in by hand in that window.
echoprofile login

# Fork the current login into an isolated session
echoprofile clone https://claude.ai

echoprofile list
echoprofile close <clone_id>

echoprofile logout          # close the persistent window
```

`clone` still works if the persistent window is not open: the server does a one-shot headless snapshot of the on-disk profile instead. Prefer keeping `login` open — then each clone is a cheap `storage_state` read off the live context.

Hot reload is **on by default** (off on Windows). A file change restarts `serve` and orphans any open profile/clone windows (they stay on screen; the server loses track of them). Disable with:

```bash
ECHOPROFILE_NO_RELOAD=1 echoprofile serve
```

## Commands

| Command | What it does |
| --- | --- |
| `echoprofile serve` | Start the local FastAPI server (`127.0.0.1:8756`). Required for every other command except `seed-from-maestro`. |
| `echoprofile login` | Open the persistent headed profile and keep it open. Loads the Switchboard extension by default; pass `--no-switchboard` to skip. |
| `echoprofile logout` | Close the persistent profile. |
| `echoprofile persistent-status` | Print `open` or `closed`. |
| `echoprofile seed-from-maestro` | Filesystem copy of Maestro's profile into echoprofile's. Refuses if Maestro looks open (`SingletonLock`) or the dest already exists; `--force` overrides both. |
| `echoprofile clone [url]` | Spin up an ephemeral clone. Bare hosts get `https://` prepended. Defaults to `ECHOPROFILE_DEFAULT_URL` (`about:blank`). |
| `echoprofile list` | List active clones (`id`, created-at, url). |
| `echoprofile close <clone_id>` | Close one clone. |

## How it works

```
persistent profile (on disk)     worker browser (one process)
 ~/.local/share/echoprofile/      no user-data-dir, no SingletonLock
 edge-profile                     |
        |                         +-- clone context (storage_state snapshot)
        |                         +-- clone context
        +-- `login` window        +-- ...
            (headed, reusable)
```

- **Persistent profile** — the one real on-disk Chromium user-data-dir. Cookies written here survive restarts. Opened headed via `login`, or snapped headless if you `clone` without it.
- **Worker browser** — a single non-persistent Chromium process owned by `serve`. Never touches the profile dir, so it never fights `SingletonLock`.
- **Clones** — `BrowserContext`s on the worker, each seeded once from a `storage_state` snapshot. Isolated after that.

Default browser is Playwright's bundled Chromium, not Microsoft Edge. Native Edge on Arch is not something `playwright install msedge` can set up, and a Flatpak Edge is not launchable by Playwright. Set `ECHOPROFILE_CHANNEL=msedge` only if a native (non-Flatpak) Edge install is actually on `PATH`.

Switchboard (Manifest V3) is loaded only into the persistent `login` window, never into clones. Clones inherit login state from the snapshot, not from the extension.

## Configuration

All optional; override with env vars.

| Variable | Default |
| --- | --- |
| `ECHOPROFILE_PROFILE_DIR` | `~/.local/share/echoprofile/edge-profile` |
| `ECHOPROFILE_HOST` | `127.0.0.1` |
| `ECHOPROFILE_PORT` | `8756` |
| `ECHOPROFILE_DEFAULT_URL` | `about:blank` |
| `ECHOPROFILE_CHANNEL` | unset (bundled Chromium). `msedge` for native Edge. |
| `ECHOPROFILE_SWITCHBOARD_DIR` | `~/Projects/switchboard/dist` |
| `ECHOPROFILE_NO_RELOAD` | unset (reload on). Set to disable uvicorn `--reload`. |
| `ECHOPROFILE_FORCE_RELOAD` | Windows only: set to turn reload back on. |

`seed-from-maestro` copies from `~/.local/share/maestro/browser-profile`. It is a plain `shutil.copytree` — it never launches either profile.

## HTTP API

The CLI is a wrapper around this. Base URL is `http://$ECHOPROFILE_HOST:$ECHOPROFILE_PORT`.

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/clone` | Body `{ "url": "..." }` (url optional). |
| `GET` | `/clones` | |
| `POST` | `/clones/{id}/close` | 404 if unknown. |
| `POST` | `/persistent/open` | Body `{ "load_switchboard": true }`. 409 if already open. |
| `POST` | `/persistent/close` | 409 if not open. |
| `GET` | `/persistent` | `{ "open": bool }` |
| `POST` | `/browser/action` | Executes an allow-listed browser capability through an extension in the live persistent context. |
| `GET` | `/health` | `{ "status": "ok" }` |

### Browser actions

The browser-action endpoint keeps EchoProfile as the sole Playwright/browser
owner while delegating provider-specific network work to Switchboard.

Current action: `switchboard.network.replay`, with a payload containing the
Switchboard saved request id and optional string replacements. The replay runs
against the active web tab in the already-running persistent browser.
EchoProfile does not launch another browser or attach a second Playwright
process to the profile.

## Layout

```
echoprofile/
  __init__.py
  cli.py        # argparse client; talks to the server over httpx
  server.py     # FastAPI + uvicorn
  core.py       # Playwright launches, CloneManager
  config.py     # paths, port, channel, env overrides
pyproject.toml
```
