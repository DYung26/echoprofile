from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

import httpx

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from echoprofile.config import Config

_CHATGPT_CONVERSATION_URL = "https://chatgpt.com/backend-api/f/conversation"
_CHATGPT_API_ROUTE = "**/backend-api/f/conversation"
_CHATGPT_API_TIMEOUT_S = 15 * 60

_PROFILE_UNLOCK_TIMEOUT_S = 5.0
_PROFILE_UNLOCK_POLL_INTERVAL_S = 0.1


def _extension_args(
    config: Config, *, load_switchboard: bool, load_multica: bool
) -> list[str]:
    extension_dirs: list[Path] = []
    if load_switchboard:
        extension_dirs.append(
            _require_extension_dir(config.switchboard_extension_dir, "Switchboard")
        )
    if load_multica and config.multica_extension_dir is not None:
        extension_dirs.append(
            _require_extension_dir(config.multica_extension_dir, "Multica Web Runtime")
        )

    if not extension_dirs:
        return []

    paths = ",".join(str(path) for path in extension_dirs)
    return [f"--disable-extensions-except={paths}", f"--load-extension={paths}"]


def _require_extension_dir(extension_dir: Path | None, name: str) -> Path:
    if extension_dir is None or not extension_dir.is_dir():
        raise RuntimeError(f"{name} extension not found at {extension_dir}")
    return extension_dir


def _chat_id_from_url(url: str) -> str | None:
    try:
        path = urlsplit(url).path
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[-2] in {"c", "chat", "conversation"}:
            return parts[-1]
    except Exception:
        pass
    return None


def _replace_chatgpt_placeholder(body: dict[str, Any], placeholder: str, replacement: str) -> None:
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise ValueError("ChatGPT conversation request has no messages array")
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        author = message.get("author")
        if not isinstance(author, dict) or author.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for index, part in enumerate(parts):
            if isinstance(part, str) and placeholder in part:
                parts[index] = part.replace(placeholder, replacement)
                return
    raise ValueError("armed ChatGPT placeholder was not found in the user message")


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
    load_multica: bool = True,
) -> tuple[Playwright, BrowserContext]:
    """Launch the one real, on-disk Edge profile for manual login.

    Cookies/localStorage written here live in config.profile_dir and survive
    restarts. Caller owns the returned Playwright/BrowserContext and must
    close both itself.

    Enabled extensions load only in the persistent context. Their service
    workers require a headed launch, so extension loading is intended for
    open_persistent_profile rather than clone or worker-browser launches.
    """
    config.profile_dir.mkdir(parents=True, exist_ok=True)
    await _wait_for_profile_unlocked(config.profile_dir)

    args = ["--disable-blink-features=AutomationControlled"]
    ignore_default_args = ["--enable-automation"]
    if not headless:
        args.append("--start-maximized")
    extension_args = _extension_args(
        config, load_switchboard=load_switchboard, load_multica=load_multica
    )
    if extension_args:
        args.extend(extension_args)
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
    config: Config, *, load_switchboard: bool = False, load_multica: bool = True
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
    return await launch_persistent_profile(
        config,
        headless=False,
        load_switchboard=load_switchboard,
        load_multica=load_multica,
    )


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
class ChatGPTApiOperation:
    id: str
    placeholder: str
    replacement: str
    queue: asyncio.Queue[bytes | None] = field(default_factory=asyncio.Queue, repr=False)
    matched: bool = False
    status: int | None = None
    content_type: str | None = None
    chat_id: str | None = None
    error: str | None = None
    stream_task: asyncio.Task[None] | None = field(default=None, repr=False)
    route_handler: Any = field(default=None, repr=False)
    expiry_task: asyncio.Task[None] | None = field(default=None, repr=False)


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
        self._chatgpt_operations: dict[str, ChatGPTApiOperation] = {}

    async def _ensure_worker_browser(self) -> Browser:
        if self._browser is None:
            playwright, browser = await launch_worker_browser(self._config)
            self._playwright = playwright
            self._browser = browser
        return self._browser

    @property
    def persistent_open(self) -> bool:
        return self._persistent_context is not None

    async def open_persistent(
        self, *, load_switchboard: bool = False, load_multica: bool = True
    ) -> None:
        """Launch the persistent profile headed and keep it open for reuse.

        A no-op if already open - call close_persistent() first to relaunch
        with different options (e.g. toggling load_switchboard).
        """
        async with self._persistent_lock:
            if self._persistent_context is not None:
                return
            playwright, context = await open_persistent_profile(
                self._config,
                load_switchboard=load_switchboard,
                load_multica=load_multica,
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

    async def browser_action(self, action: str, payload: dict[str, Any]) -> Any:
        """Execute a browser capability through an extension in the live context.

        The persistent Playwright context remains the only browser owner.
        Switchboard performs the actual browser-network operation; EchoProfile
        only bridges the action into the already-running extension.
        """
        if action not in {
            "switchboard.network.list",
            "switchboard.network.get",
            "switchboard.network.save",
            "switchboard.network.delete",
            "switchboard.network.fetch",
            "switchboard.network.list_saved",
            "switchboard.network.get_saved",
            "switchboard.network.replay",
            "multica.extension.reload",
        }:
            raise ValueError(f"Unsupported browser action: {action}")

        async with self._persistent_lock:
            context = self._persistent_context
            if context is None:
                raise RuntimeError("persistent profile is not open")

            if action == "multica.extension.reload":
                for worker in context.service_workers:
                    try:
                        is_multica = await worker.evaluate(
                            "() => globalThis.__MULTICA_WEB_RUNTIME_EXTENSION__ === true || chrome.runtime.getManifest().name === 'Multica Web Runtime'"
                        )
                    except Exception:
                        continue
                    if is_multica:
                        await worker.evaluate("() => chrome.runtime.reload()")
                        return {"reloaded": True}
                raise RuntimeError("Multica Web Runtime extension service worker is not available")

            switchboard_worker = None
            for worker in context.service_workers:
                try:
                    is_switchboard = await worker.evaluate(
                        "() => globalThis.__SWITCHBOARD_EXTENSION__ === true"
                    )
                except Exception:
                    continue
                if is_switchboard:
                    switchboard_worker = worker
                    break

            if switchboard_worker is None:
                raise RuntimeError("Switchboard extension service worker is not available")

            parsed_worker_url = urlsplit(switchboard_worker.url)
            extension_origin = f"{parsed_worker_url.scheme}://{parsed_worker_url.netloc}"
            bridge_page = await context.new_page()
            try:
                await bridge_page.goto(
                    f"{extension_origin}/src/sidepanel/index.html",
                    wait_until="domcontentloaded",
                )
                message_type = {
                    "switchboard.network.list": "switchboard/network/list",
                    "switchboard.network.get": "switchboard/network/get",
                    "switchboard.network.save": "switchboard/network/save",
                    "switchboard.network.delete": "switchboard/network/delete",
                    "switchboard.network.fetch": "switchboard/network/fetch",
                    "switchboard.network.list_saved": "switchboard/network/saved/list",
                    "switchboard.network.get_saved": "switchboard/network/saved/get",
                    "switchboard.network.replay": "switchboard/network/replay",
                }[action]
                message_payload = dict(payload)
                if action == "switchboard.network.replay":
                    message_payload["target"] = "active"
                return await bridge_page.evaluate(
                    """async ({type, payload}) =>
                        await chrome.runtime.sendMessage({type, payload})""",
                    {"type": message_type, "payload": message_payload},
                )
            finally:
                await bridge_page.close()

    async def prepare_chatgpt_api(self, placeholder: str, replacement: str) -> dict[str, str]:
        """Arm one authenticated ChatGPT conversation request for API-mode execution.

        The browser frontend creates the ephemeral Sentinel/conduit state. When it
        submits the unique placeholder turn, the request is intercepted before it
        reaches ChatGPT, the message content is replaced, and the modified request
        is streamed through a lightweight httpx connection instead of the browser.
        """
        if not placeholder or not replacement:
            raise ValueError("placeholder and replacement are required")
        async with self._persistent_lock:
            context = self._persistent_context
            if context is None:
                raise RuntimeError("persistent profile is not open")

            operation_id = uuid.uuid4().hex
            operation = ChatGPTApiOperation(
                id=operation_id,
                placeholder=placeholder,
                replacement=replacement,
            )

            async def handle_route(route: Any) -> None:
                request = route.request
                if operation.matched or request.method.upper() != "POST":
                    await route.fallback()
                    return
                if request.url != _CHATGPT_CONVERSATION_URL:
                    await route.fallback()
                    return
                raw_body = request.post_data or ""
                if operation.placeholder not in raw_body:
                    # Only our uniquely armed request is eligible. This prevents
                    # an unrelated manual ChatGPT turn from being intercepted.
                    await route.fallback()
                    return

                operation.matched = True
                try:
                    body = json.loads(raw_body)
                    _replace_chatgpt_placeholder(body, operation.placeholder, operation.replacement)
                    request_headers = await request.all_headers()
                    filtered_headers = {
                        key: value
                        for key, value in request_headers.items()
                        if key.lower() not in {
                            "content-length",
                            "host",
                            "connection",
                            "transfer-encoding",
                        }
                    }
                    page = request.frame.page
                    operation.chat_id = _chat_id_from_url(page.url)
                    operation.stream_task = asyncio.create_task(
                        self._stream_chatgpt_request(
                            operation,
                            request.url,
                            filtered_headers,
                            json.dumps(body, separators=(",", ":")),
                        )
                    )
                    # The browser request must not reach ChatGPT: the daemon-owned
                    # HTTP stream above is now the sole owner of this generation.
                    await route.abort()
                    # API-mode pages are disposable. The browser is needed only to
                    # obtain the frontend-generated ephemeral request state.
                    if "#multica-api=" in page.url:
                        await page.close()
                except Exception as error:
                    operation.error = str(error)
                    await operation.queue.put(None)
                    try:
                        await route.abort()
                    except Exception:
                        pass

            operation.route_handler = handle_route
            await context.route(_CHATGPT_API_ROUTE, handle_route)
            self._chatgpt_operations[operation_id] = operation
            operation.expiry_task = asyncio.create_task(self._expire_chatgpt_operation(operation_id))
            return {"operation_id": operation_id}

    def has_chatgpt_operation(self, operation_id: str) -> bool:
        return operation_id in self._chatgpt_operations

    async def _expire_chatgpt_operation(self, operation_id: str) -> None:
        await asyncio.sleep(60)
        operation = self._chatgpt_operations.get(operation_id)
        if operation is not None and not operation.matched:
            operation.error = "ChatGPT API interception timed out before the placeholder request arrived"
            await operation.queue.put(None)
            await self._cleanup_chatgpt_operation(operation_id)

    async def stream_chatgpt_api(self, operation_id: str) -> AsyncIterator[bytes]:
        operation = self._chatgpt_operations.get(operation_id)
        if operation is None:
            raise KeyError(f"ChatGPT API operation {operation_id!r} not found")

        try:
            while True:
                chunk = await operation.queue.get()
                if chunk is None:
                    if operation.error:
                        raise RuntimeError(operation.error)
                    break
                yield chunk
        finally:
            await self._cleanup_chatgpt_operation(operation_id)

    async def _stream_chatgpt_request(
        self,
        operation: ChatGPTApiOperation,
        url: str,
        headers: dict[str, str],
        body: str,
    ) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(_CHATGPT_API_TIMEOUT_S, connect=30.0),
                follow_redirects=False,
                http2=False,
            ) as client:
                async with client.stream("POST", url, headers=headers, content=body) as response:
                    operation.status = response.status_code
                    operation.content_type = response.headers.get("content-type")
                    meta = json.dumps({
                        "status": response.status_code,
                        "content_type": operation.content_type,
                        "chat_id": operation.chat_id,
                    }, separators=(",", ":")).encode()
                    await operation.queue.put(b"event: multica-meta\ndata: " + meta + b"\n\n")

                    if response.status_code != 200:
                        detail = (await response.aread())[:4096].decode(errors="replace")
                        raise RuntimeError(f"ChatGPT conversation request returned HTTP {response.status_code}: {detail}")

                    async for chunk in response.aiter_bytes():
                        if chunk:
                            await operation.queue.put(chunk)
        except Exception as error:
            operation.error = str(error)
        finally:
            await operation.queue.put(None)

    async def _cleanup_chatgpt_operation(self, operation_id: str) -> None:
        operation = self._chatgpt_operations.pop(operation_id, None)
        if operation is None:
            return
        if operation.expiry_task is not None and operation.expiry_task is not asyncio.current_task():
            operation.expiry_task.cancel()
            try:
                await operation.expiry_task
            except asyncio.CancelledError:
                pass
        async with self._persistent_lock:
            context = self._persistent_context
            if context is not None and operation.route_handler is not None:
                try:
                    await context.unroute(_CHATGPT_API_ROUTE, operation.route_handler)
                except Exception:
                    pass
        if operation.stream_task is not None and not operation.stream_task.done():
            operation.stream_task.cancel()
            try:
                await operation.stream_task
            except asyncio.CancelledError:
                pass

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
        for operation_id in list(self._chatgpt_operations):
            await self._cleanup_chatgpt_operation(operation_id)
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
