from __future__ import annotations

import os
from collections.abc import Iterable

import httpx

from echoprofile.config import Config

_DEFAULT_FALLBACK_URLS = (
    "http://100.98.45.0:8756",  # laptop-ab9612ik
    "http://100.82.234.105:8756",  # VPS
)
_HEALTH_TIMEOUT_S = 0.8


def candidate_urls(config: Config, env_value: str | None = None) -> list[str]:
    """Return unique endpoints in configured failover order."""
    configured = os.environ.get("ECHOPROFILE_FAILOVER_URLS") if env_value is None else env_value
    values: Iterable[str]
    if configured is None:
        values = (config.base_url, *_DEFAULT_FALLBACK_URLS)
    else:
        values = (item.strip().rstrip("/") for item in configured.split(","))
    result: list[str] = []
    for value in values:
        url = value.strip().rstrip("/")
        if url and url not in result:
            result.append(url)
    return result


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


def resolve_base_url(config: Config) -> str:
    """Select the first healthy endpoint, preserving strict priority order."""
    candidates = candidate_urls(config)
    for base_url in candidates:
        if is_healthy(base_url):
            return base_url
    return candidates[0] if candidates else config.base_url
