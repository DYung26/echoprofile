from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROFILE_DIR = Path.home() / ".local" / "share" / "echoprofile" / "edge-profile"
DEFAULT_PORT = 8756
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

# Playwright `channel` value for launches. None means "use Playwright's
# bundled Chromium" (no channel= passed at all) - this is what we use by
# default, since Edge is only reliably launchable via a native OS install
# (apt/rpm-based, or manual download), which `playwright install msedge`
# cannot set up on Arch, and a Flatpak Edge install isn't launchable by
# Playwright at all (sandboxed, not a plain executable path). Set to
# "msedge" only once a native (non-Flatpak) Edge install is confirmed
# working via ECHOPROFILE_CHANNEL.
EDGE_CHANNEL: str | None = None


@dataclass(frozen=True)
class Config:
    profile_dir: Path
    host: str
    port: int
    default_url: str
    channel: str | None = None
    switchboard_extension_dir: Path | None = None
    multica_extension_dir: Path | None = None

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
    multica_extension_dir = Path(multica_dir).expanduser() if multica_dir else None
    return Config(
        profile_dir=profile_dir,
        host=host,
        port=port,
        default_url=default_url,
        channel=channel,
        switchboard_extension_dir=switchboard_extension_dir,
        multica_extension_dir=multica_extension_dir,
    )
