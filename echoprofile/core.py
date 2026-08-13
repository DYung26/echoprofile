from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from echoprofile.config import Config

_PROFILE_UNLOCK_TIMEOUT_S = 5.0
_PROFILE_UNLOCK_POLL_INTERVAL_S = 0.1


def _normalize_url(url: str) -> str:
    """Default a bare host/URL with no scheme to https://.

    page.goto() requires a scheme - "claude.ai" is rejected outright, while
    "https://claude.ai" isn't, so a bare host typed on the CLI needs this
    before it ever reaches Playwright.
    """
    if "://" not in url:
        return f"https://{url}"
    return url


async def _wait_for_profile_unlocked(profile_dir: Path) -> None:
    """Wait out Edge's SingletonLock on a profile before launching into it.

    Closing a persistent context can return before the underlying Edge
    process has actually exited and released this lock. Launching against a
    still-locked profile doesn't fail loudly - Edge just forwards the launch
    to the dying process instead of starting a new one.
    """
    lock_file = profile_dir / "SingletonLock"
    loop = asyncio.get_event_loop()
    deadline = loop.time() + _PROFILE_UNLOCK_TIMEOUT_S
    while lock_file.exists():
        if loop.time() >= deadline:
            return
        await asyncio.sleep(_PROFILE_UNLOCK_POLL_INTERVAL_S)


async def launch_persistent_profile(
    config: Config,
    *,
    headless: bool = False,
    load_switchboard: bool = False,
) -> tuple[Playwright, BrowserContext]:
    """Launch the one real, on-disk Edge profile for manual login.

    Cookies/localStorage written here live in config.profile_dir and survive
    restarts. Caller owns the returned Playwright/BrowserContext and must
    close both itself.

    load_switchboard loads the Switchboard extension (Manifest V3, so it
    only works in a persistent context, never in the worker browser or a
    clone). Switchboard's own service worker only starts headed, so this
    should be combined with headless=False - a headless launch with
    load_switchboard=True will load the extension but its service worker
    won't run.
    """
    config.profile_dir.mkdir(parents=True, exist_ok=True)
    await _wait_for_profile_unlocked(config.profile_dir)

    args = ["--disable-blink-features=AutomationControlled"]
    ignore_default_args = ["--enable-automation"]
    if not headless:
        args.append("--start-maximized")
    if load_switchboard:
        if config.switchboard_extension_dir is None or not config.switchboard_extension_dir.exists():
            raise RuntimeError(
                f"Switchboard extension not found at {config.switchboard_extension_dir}"
            )
        extension_dir = str(config.switchboard_extension_dir)
        args += [
            f"--disable-extensions-except={extension_dir}",
            f"--load-extension={extension_dir}",
        ]
        # Playwright's own default launch args include a blanket
        # --disable-extensions, which fights --disable-extensions-except
        # rather than yielding to it, so it has to be dropped explicitly.
        ignore_default_args.append("--disable-extensions")

    playwright = await async_playwright().start()
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(config.profile_dir),
        channel=config.channel,
        headless=headless,
        args=args,
        ignore_default_args=ignore_default_args,
        no_viewport=True,
        color_scheme="dark",
    )
    return playwright, context


async def open_persistent_profile(
    config: Config, *, load_switchboard: bool = False
) -> tuple[Playwright, BrowserContext]:
    """Launch the one real, on-disk Edge profile, headed, for the caller to
    keep open and reuse.

    Unlike a one-shot login flow, the returned context is meant to live for
    as long as the caller wants: you can keep browsing/logging into sites in
    it, and every later snapshot_storage_state() call against it reads
    whatever is currently on it - no separate launch per read. Caller owns
    both returned values and must close/stop them itself (or via
    close_persistent_profile).
    """
    return await launch_persistent_profile(config, headless=False, load_switchboard=load_switchboard)


async def close_persistent_profile(playwright: Playwright, context: BrowserContext) -> None:
    """Close a context/driver pair returned by open_persistent_profile."""
    await context.close()
    await playwright.stop()


async def snapshot_storage_state(context: BrowserContext) -> dict[str, Any]:
    """Read the current cookies/localStorage off an already-open persistent
    context - no launch, no teardown, just a point-in-time read.
    """
    return await context.storage_state()


async def capture_storage_state(config: Config) -> dict[str, Any]:
    """One-shot variant: open the persistent profile just long enough to
    snapshot it, then close it again.

    Kept for cases with no already-open persistent context to read from
    (e.g. a clone requested before the persistent window has ever been
    opened this session). Prefer snapshot_storage_state against an
    already-open context when one exists - see CloneManager.create_clone.
    """
    playwright, context = await launch_persistent_profile(config, headless=True)
    try:
        return await context.storage_state()
    finally:
        await context.close()
        await playwright.stop()


async def launch_worker_browser(config: Config) -> tuple[Playwright, Browser]:
    """Launch the one non-persistent Edge process ephemeral clones share.

    Never touches config.profile_dir, so it never contends for the profile
    directory's SingletonLock and can host any number of concurrent,
    fully-isolated clone contexts.
    """
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        channel=config.channel,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    return playwright, browser


@dataclass
class Clone:
    id: str
    url: str
    created_at: datetime
    context: BrowserContext = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "created_at": self.created_at.isoformat(),
        }


class CloneManager:
    """Owns the shared worker Browser process, the optional long-lived
    persistent profile context, and every live ephemeral clone spawned from
    the worker.

    One instance lives for the lifetime of the `serve` process. Each clone
    is a fully isolated BrowserContext (own cookies, own storage) seeded
    once from a storage_state snapshot - after creation it has no ongoing
    link back to the persistent profile.

    The persistent context is opt-in: call open_persistent() to launch it
    headed and keep it open for reuse (log into new sites in it, switch
    Switchboard accounts in it), and every create_clone() call after that
    reads its current storage_state directly with no extra launch. Without
    an open persistent context, create_clone() falls back to a one-shot
    headless launch-snapshot-close per call.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._clones: dict[str, Clone] = {}
        self._lock = asyncio.Lock()

        self._persistent_playwright: Playwright | None = None
        self._persistent_context: BrowserContext | None = None
        self._persistent_lock = asyncio.Lock()

    async def _ensure_worker_browser(self) -> Browser:
        if self._browser is None:
            playwright, browser = await launch_worker_browser(self._config)
            self._playwright = playwright
            self._browser = browser
        return self._browser

    @property
    def persistent_open(self) -> bool:
        return self._persistent_context is not None

    async def open_persistent(self, *, load_switchboard: bool = False) -> None:
        """Launch the persistent profile headed and keep it open for reuse.

        A no-op if already open - call close_persistent() first to relaunch
        with different options (e.g. toggling load_switchboard).
        """
        async with self._persistent_lock:
            if self._persistent_context is not None:
                return
            playwright, context = await open_persistent_profile(
                self._config, load_switchboard=load_switchboard
            )
            self._persistent_playwright = playwright
            self._persistent_context = context

    async def close_persistent(self) -> bool:
        """Close the persistent profile if open. Returns whether it was open."""
        async with self._persistent_lock:
            if self._persistent_context is None:
                return False
            await close_persistent_profile(self._persistent_playwright, self._persistent_context)
            self._persistent_context = None
            self._persistent_playwright = None
            return True

    async def create_clone(self, url: str | None = None) -> Clone:
        target_url = _normalize_url(url or self._config.default_url)

        # Prefer reading off the already-open persistent context (no extra
        # launch) - fall back to a one-shot headless snapshot only when
        # nothing is open yet, so `clone` still works before `open_persistent`
        # has ever been called this session.
        async with self._persistent_lock:
            if self._persistent_context is not None:
                storage_state = await snapshot_storage_state(self._persistent_context)
            else:
                storage_state = None
        if storage_state is None:
            storage_state = await capture_storage_state(self._config)

        async with self._lock:
            browser = await self._ensure_worker_browser()
            context = await browser.new_context(
                storage_state=storage_state,
                no_viewport=True,
                color_scheme="dark",
            )
            page = await context.new_page()
            await page.goto(target_url)

            clone = Clone(
                id=uuid.uuid4().hex[:8],
                url=target_url,
                created_at=datetime.now(timezone.utc),
                context=context,
            )
            self._clones[clone.id] = clone
            return clone

    def list_clones(self) -> list[Clone]:
        return sorted(self._clones.values(), key=lambda c: c.created_at)

    async def close_clone(self, clone_id: str) -> bool:
        async with self._lock:
            clone = self._clones.pop(clone_id, None)
            if clone is None:
                return False
            await clone.context.close()
            return True

    async def close_all(self) -> None:
        await self.close_persistent()
        async with self._lock:
            for clone in list(self._clones.values()):
                try:
                    await clone.context.close()
                except Exception:
                    pass
            self._clones.clear()
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
