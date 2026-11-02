from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROFILE_DIR = Path.home() / ".local" / "share" / "echoprofile" / "edge-profile"
DEFAULT_PORT = 8756
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "echoprofile"
EXTENSION_TOKEN_FILE = DEFAULT_CONFIG_DIR / "extension-token"
DEFAULT_HOST = "127.0.0.1"

# Maestro's own persistent Chromium profile - a one-time copy source for
# `echoprofile seed-from-maestro`, never launched into or written to
# directly. Copying instead of pointing at this path avoids two tools
# contending for the same profile directory's SingletonLock: Maestro's own
# BrowserSessionManager can hold this open indefinitely once it launches it.
MAESTRO_PROFILE_DIR = Path.home() / ".local" / "share" / "maestro" / "browser-profile"

# Switchboard is a Manifest V3 extension used only for the manual `login`
# flow (it needs a persistent, headed context - see core.launch_persistent_profile).
# Never loaded into the worker browser or any clone: clones inherit their
# login state from a storage_state snapshot instead, so they have no use
# for the extension itself.
SWITCHBOARD_EXTENSION_DIR = Path.home() / "Projects" / "switchboard" / "dist"
MULTICA_EXTENSION_DIR = Path.home() / "Projects" / "multica-web-runtime" / "extension" / "dist"
ECHOPROFILE_EXTENSION_DIR = Path(__file__).parent / "browser_extension"

# Playwright `channel` value for launches. None means "use Playwright's
# bundled Chromium" (no channel= passed at all) - this is what we use by
# default, since Edge is only reliably launchable via a native OS install
# (apt/rpm-based, or manual download), which `playwright install msedge`
# cannot set up on Arch, and a Flatpak Edge install isn't launchable by
# Playwright at all (sandboxed, not a plain executable path). Set to
# "msedge" only once a native (non-Flatpak) Edge install is confirmed
# working via ECHOPROFILE_CHANNEL.
EDGE_CHANNEL: str | None = None


def _load_or_create_extension_token() -> str:
    """Load a private local pairing token, creating it on first use."""
    configured = os.environ.get("ECHOPROFILE_EXTENSION_TOKEN", "").strip()
    if configured:
        return configured
    EXTENSION_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(EXTENSION_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        token = EXTENSION_TOKEN_FILE.read_text().strip()
        if not token:
            raise RuntimeError(f"Extension pairing token file is empty: {EXTENSION_TOKEN_FILE}")
        try:
            EXTENSION_TOKEN_FILE.chmod(0o600)
        except OSError:
            pass
        return token
    token = secrets.token_urlsafe(32)
    with os.fdopen(descriptor, "w") as token_file:
        token_file.write(token + "\n")
    return token


@dataclass(frozen=True)
class Config:
    profile_dir: Path
    host: str
    port: int
    default_url: str
    channel: str | None = None
    switchboard_extension_dir: Path | None = None
    multica_extension_dir: Path | None = None
    chatgpt_extension_dir: Path | None = None
    extension_token: str = ""
    browser_extension_dir: Path = ECHOPROFILE_EXTENSION_DIR

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def load_config() -> Config:
    profile_dir = Path(os.environ.get("ECHOPROFILE_PROFILE_DIR", DEFAULT_PROFILE_DIR)).expanduser()
    host = os.environ.get("ECHOPROFILE_HOST", DEFAULT_HOST)
    port = int(os.environ.get("ECHOPROFILE_PORT", DEFAULT_PORT))
    default_url = os.environ.get("ECHOPROFILE_DEFAULT_URL", "about:blank")
    channel = os.environ.get("ECHOPROFILE_CHANNEL", EDGE_CHANNEL) or None
    switchboard_extension_dir = Path(
        os.environ.get("ECHOPROFILE_SWITCHBOARD_DIR", SWITCHBOARD_EXTENSION_DIR)
    ).expanduser()
    multica_dir = os.environ.get("ECHOPROFILE_MULTICA_DIR", str(MULTICA_EXTENSION_DIR))
    multica_disabled = multica_dir.strip().lower() in {"", "0", "false", "none", "off", "disabled"}
    multica_extension_dir = Path(multica_dir).expanduser() if not multica_disabled else None
    chatgpt_dir = os.environ.get("ECHOPROFILE_CHATGPT_EXTENSION_DIR", "").strip()
    chatgpt_extension_dir = Path(chatgpt_dir).expanduser() if chatgpt_dir else None
    extension_token = _load_or_create_extension_token()
    return Config(
        profile_dir=profile_dir,
        host=host,
        port=port,
        default_url=default_url,
        channel=channel,
        switchboard_extension_dir=switchboard_extension_dir,
        multica_extension_dir=multica_extension_dir,
        chatgpt_extension_dir=chatgpt_extension_dir,
        extension_token=extension_token,
        browser_extension_dir=ECHOPROFILE_EXTENSION_DIR,
    )
