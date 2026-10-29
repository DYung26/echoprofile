from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import httpx

from echoprofile.config import Config

DEVICE_URLS = {
    "arch": "http://100.76.52.7:8756",
    "laptop": "http://100.98.45.0:8756",
    "vps": "http://100.82.234.105:8756",
}
_DEFAULT_FAILOVER_URLS = (DEVICE_URLS["arch"], DEVICE_URLS["laptop"], DEVICE_URLS["vps"])
_DEVICE_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "echoprofile" / "device"
_HEALTH_TIMEOUT_S = 0.8
_AUTO_FALLBACK_ENV = "ECHOPROFILE_AUTO_FALLBACK"


def automatic_fallback_enabled() -> bool:
    """Enable cross-device failover only when explicitly opted in."""
    return os.environ.get(_AUTO_FALLBACK_ENV, "false").strip().lower() in {"1", "true", "yes", "on"}


def candidate_urls(config: Config, env_value: str | None = None) -> list[str]:
    """Return unique endpoints in automatic failover order."""
    configured = os.environ.get("ECHOPROFILE_FAILOVER_URLS") if env_value is None else env_value
    values: Iterable[str]
    if configured is None:
        values = _DEFAULT_FAILOVER_URLS
    else:
        values = (item.strip().rstrip("/") for item in configured.split(","))
    result: list[str] = []
    for value in values:
        url = value.strip().rstrip("/")
        if url and url not in result:
            result.append(url)
    return result


def selected_device() -> str:
    """Return the persisted device choice, defaulting to automatic routing."""
    override = os.environ.get("ECHOPROFILE_DEVICE")
    if override:
        return override.strip().lower()
    try:
        value = _DEVICE_CONFIG.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "auto"
    return value or "auto"


def save_device(device: str) -> None:
    """Persist a device choice for future CLI commands."""
    normalized = device.strip().lower()
    if normalized not in {"auto", *DEVICE_URLS}:
        raise ValueError(f"Unknown device {device!r}; choose auto, arch, laptop, or vps")
    _DEVICE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _DEVICE_CONFIG.write_text(normalized + "\n", encoding="utf-8")


def is_healthy(base_url: str, *, client: httpx.Client | None = None) -> bool:
    """Return true only when the endpoint responds successfully to /health."""
    try:
        if client is None:
            with httpx.Client(timeout=_HEALTH_TIMEOUT_S) as owned_client:
                response = owned_client.get(f"{base_url}/health")
        else:
            response = client.get(f"{base_url}/health")
        return response.is_success and response.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def resolve_base_url(config: Config, device: str | None = None) -> str:
    """Resolve a pinned device strictly, or use automatic health-checked failover."""
    choice = (device or selected_device()).strip().lower()
    if choice != "auto":
        if choice in DEVICE_URLS:
            return DEVICE_URLS[choice]
        if choice.startswith(("http://", "https://")):
            return choice.rstrip("/")
        raise ValueError(f"Unknown device {choice!r}; choose auto, arch, laptop, or vps, or provide a URL")

    if not automatic_fallback_enabled():
        return config.base_url

    candidates = candidate_urls(config)
    for base_url in candidates:
        if is_healthy(base_url):
            return base_url
    return candidates[0] if candidates else config.base_url


def device_status() -> list[tuple[str, str, bool]]:
    """Return known device endpoints and their current health."""
    return [(name, url, is_healthy(url)) for name, url in DEVICE_URLS.items()]
