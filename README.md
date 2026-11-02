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
| `echoprofile login` | Open the persistent headed profile. Loads Switchboard and configured Multica by default; optional ChatGPT and custom unpacked extensions can be added with flags. |
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

EchoProfile Browser Control, Switchboard and Multica (Manifest V3) are loaded only into the persistent `login` window, never into clones. Clones inherit login state from the snapshot, not from the extensions.

### Extension loading and independent browser control

EchoProfile Browser Control is an unpacked Manifest V3 extension shipped inside the Python package and loaded automatically in the persistent `login` profile. It controls its own browser directly through Chrome extension APIs (`tabs`, `scripting`, and `debugger`); it does not use Playwright or CDP.

The EchoProfile server is only the agent-to-extension message relay. The extension keeps an authenticated WebSocket to `/extension/connect`; the agent sends actions through `POST /extension/action` with `Authorization: Bearer <pairing-token>`, and the extension executes them locally in its browser and returns the result. This is a separate control path from Playwright/CDP, not a fallback or wrapper around it.

On first use, EchoProfile creates a random pairing token at `~/.config/echoprofile/extension-token` with owner-only permissions. The extension has a pinned identity and retrieves that token automatically from the local server through an origin-restricted bootstrap endpoint; no server URL or token needs to be entered or copied. The token is persisted in extension storage and reused after browser/server restarts. The bootstrap endpoint accepts only loopback clients, rejects other supplied origins, and scopes its CORS response to the pinned extension origin. The token is then required for the authenticated WebSocket and action API.

### EchoProfile MCP server

EchoProfile includes a dedicated stdio MCP server for the extension-backed browser. It is an independent control mechanism from the Playwright/CDP browser tools: MCP calls the EchoProfile HTTP API, which relays the action to the paired extension over its WebSocket.

Install EchoProfile in the environment used by your MCP client, then register this server:

```json
{
  "mcpServers": {
    "echoprofile-browser": {
      "command": "echoprofile-mcp"
    }
  }
}
```

The MCP process reads the same local pairing-token file and host/port configuration as the API server, so no separate token or endpoint configuration is needed. By default, it connects to `http://127.0.0.1:8756`; the extension endpoint is fixed to that local address. The tools expose browser status, tab management, navigation, page title/text/HTML, click, fill, keypress, scrolling, and screenshots. Start `echoprofile serve` and open the persistent `login` profile; once the extension is loaded, pairing happens automatically.

Supported extension actions currently include `status`, `tabs.list`, `tabs.active`, `tabs.new`, `tabs.close`, `tabs.activate`, `navigate`, `page.title`, `page.text`, `page.html`, `page.click`, `page.fill`, `page.press`, `page.scroll`, and `page.screenshot`.

EchoProfile can also load multiple additional unpacked Chromium extensions into the same persistent profile. Chromium starts each extension in the browser process; extension service workers/background pages and content scripts then run under the extension's own permissions and lifecycle. An extension is not automatically a Playwright controller: EchoProfile must speak the extension's documented messaging/API bridge if it wants to ask that extension to perform actions.

The default loader uses `--load-extension` without `--disable-extensions-except`. This lets extensions installed normally in the profile remain enabled too. Use `--restrict-extensions` only when you explicitly want an allow-list containing the extensions supplied for that launch.

```bash
# Built-ins + ChatGPT extension from its configured path
echoprofile login --chatgpt-extension

# Built-ins + any additional unpacked extension(s)
echoprofile login --extension ~/Projects/some-extension/dist

echoprofile login --extension ~/Projects/extension-a/dist --extension ~/Projects/extension-b/dist
```

Set `ECHOPROFILE_CHATGPT_EXTENSION_DIR` to the directory containing the ChatGPT extension's `manifest.json` before using `--chatgpt-extension`. Custom `--extension` paths are passed to the serving EchoProfile instance, so they must exist on the machine running that server. Close and reopen the persistent profile to change its launch-time extension set.

The ChatGPT extension is designed to connect the browser to ChatGPT Work/Codex. Its documented setup is through ChatGPT desktop Settings → Computer Use, then selecting the browser and installing the store extension; it uses browser permissions such as debugger access and communication with cooperating native applications. This makes it usable by ChatGPT, but does not expose a documented third-party bridge for EchoProfile to invoke. Keep it independently installed/enabled in the profile; EchoProfile does not need to manage or repackage it. CDP remains the direct Playwright/browser-control path; EchoProfile extensions can expose a bridge we own, while the ChatGPT extension remains ChatGPT's own integration.

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
| `ECHOPROFILE_CHATGPT_EXTENSION_DIR` | unset |
| `ECHOPROFILE_EXTENSION_TOKEN` | generated at `~/.config/echoprofile/extension-token` |
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
| `POST` | `/persistent/open` | Optional `load_switchboard`, `load_multica`, `load_chatgpt`, `extension_dirs` (array of paths), and `restrict_extensions`. 409 if already open. |
| `POST` | `/persistent/close` | 409 if not open. |
| `GET` | `/persistent` | `{ "open": bool }` |
| `GET` | `/extension/status` | Whether EchoProfile Browser Control is connected. |
| `POST` | `/extension/action` | Execute an action in the extension-controlled browser (separate from Playwright). Requires `Authorization: Bearer <pairing-token>`. Body `{ "action": "tabs.list", "payload": {} }`. |
| `POST` | `/browser/action` | Existing Switchboard/Multica extension actions bridged through the persistent Playwright context. |
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

## Device selection and failover

Automatic cross-device failover is disabled by default to prevent commands
from unexpectedly controlling another machine. In `auto` mode, commands use
the local EchoProfile API unless `ECHOPROFILE_AUTO_FALLBACK=true` is set. When
enabled, the CLI selects the first healthy endpoint in the configured order.
You can instead pin commands to one device; a pinned device never silently
falls back when offline.

    echoprofile device status
    echoprofile device use laptop
    echoprofile list
    echoprofile --device vps list
    echoprofile device use auto

Known device names are arch, laptop, and vps. The persistent selection is
stored in ~/.config/echoprofile/device (or $XDG_CONFIG_HOME/echoprofile/device).
ECHOPROFILE_DEVICE overrides the saved selection; --device overrides both for
one command. An explicit base URL can also be passed with --device.

Enable automatic failover explicitly with `ECHOPROFILE_AUTO_FALLBACK=true`.
Override its endpoint order with comma-separated `ECHOPROFILE_FAILOVER_URLS`, for example:

    ECHOPROFILE_FAILOVER_URLS=http://127.0.0.1:8756,http://100.76.52.7:8756,http://100.98.45.0:8756,http://100.82.234.105:8756 echoprofile list

Device selection chooses the server receiving a command; it does not migrate
existing browser windows, cookies, or clones between machines.


## HTTP routing resolver

GET /routing/resolve returns the base URL selected by EchoProfile's persisted device choice and automatic-fallback configuration. Clients such as AiSP should query this local control-plane endpoint, then send browser actions to the returned base_url instead of maintaining their own device URL setting.
