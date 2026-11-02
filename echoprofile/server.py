from __future__ import annotations

import asyncio
import hmac
import ipaddress
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from echoprofile.config import Config, load_config
from echoprofile.core import CloneManager
from echoprofile.routing import (
    DEVICE_URLS,
    automatic_fallback_enabled,
    candidate_urls,
    resolve_base_url,
    selected_device,
)


BROWSER_EXTENSION_ID = "bocgihfkibcmlmldnegcakfppijcdlhb"


class CloneRequest(BaseModel):
    url: str | None = None


class OpenPersistentRequest(BaseModel):
    load_switchboard: bool = False
    load_multica: bool = False
    load_chatgpt: bool = False
    load_echoprofile: bool = True
    extension_dirs: list[str] = Field(default_factory=list)
    restrict_extensions: bool = False


class BrowserActionRequest(BaseModel):
    action: str
    payload: dict[str, object] = Field(default_factory=dict)


class ExtensionActionRequest(BaseModel):
    action: str
    payload: dict[str, object] = Field(default_factory=dict)


class ChatGPTApiPrepareRequest(BaseModel):
    placeholder: str
    replacement: str


class ExtensionBridge:
    """Authenticated request/response channel to the browser extension."""

    def __init__(self) -> None:
        self.websocket: WebSocket | None = None
        self.pending: dict[str, asyncio.Future[dict[str, object]]] = {}
        self.lock = asyncio.Lock()

    async def attach(self, websocket: WebSocket) -> None:
        async with self.lock:
            if self.websocket is not None:
                await self.websocket.close(code=4001, reason="Replaced by a newer extension connection")
            self.websocket = websocket

    async def detach(self, websocket: WebSocket) -> None:
        async with self.lock:
            if self.websocket is not websocket:
                return
            self.websocket = None
            pending = list(self.pending.values())
            self.pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(RuntimeError("EchoProfile browser extension disconnected"))

    async def resolve(self, message: dict[str, object]) -> None:
        request_id = str(message.get("id", ""))
        future = self.pending.pop(request_id, None)
        if future is None or future.done():
            return
        if message.get("ok") is True:
            future.set_result({"result": message.get("result")})
        else:
            future.set_result({"error": str(message.get("error", "Extension action failed"))})

    async def request(self, action: str, payload: dict[str, object], timeout: float = 30) -> object:
        async with self.lock:
            websocket = self.websocket
            if websocket is None:
                raise RuntimeError("EchoProfile browser extension is not connected; open its options and pair it with this server")
            request_id = uuid.uuid4().hex
            future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
            self.pending[request_id] = future
            try:
                await websocket.send_json({"type": "command", "id": request_id, "action": action, "payload": payload})
            except Exception:
                self.pending.pop(request_id, None)
                raise RuntimeError("Could not send command to EchoProfile browser extension")
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as error:
            self.pending.pop(request_id, None)
            raise RuntimeError(f"Extension action timed out after {timeout:g}s: {action}") from error
        except asyncio.CancelledError:
            self.pending.pop(request_id, None)
            raise
        if "error" in response:
            raise ValueError(str(response["error"]))
        return response.get("result")

    @property
    def connected(self) -> bool:
        return self.websocket is not None


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    manager = CloneManager(config)
    extension_bridge = ExtensionBridge()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await manager.close_all()

    app = FastAPI(title="echoprofile", lifespan=lifespan)

    @app.post("/chatgpt/api/prepare")
    async def prepare_chatgpt_api(request: ChatGPTApiPrepareRequest):
        try:
            return await manager.prepare_chatgpt_api(request.placeholder, request.replacement)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/chatgpt/api/stream/{operation_id}")
    async def stream_chatgpt_api(operation_id: str):
        if not manager.has_chatgpt_operation(operation_id):
            raise HTTPException(status_code=404, detail=f"ChatGPT API operation {operation_id!r} not found")
        try:
            stream = manager.stream_chatgpt_api(operation_id)
            return StreamingResponse(
                stream,
                media_type="text/event-stream",
                headers={
                    "cache-control": "no-cache",
                    "x-accel-buffering": "no",
                },
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/routing/resolve")
    async def routing_resolve():
        try:
            base_url = resolve_base_url(config)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        resolved_device = next(
            (name for name, url in DEVICE_URLS.items() if url == base_url),
            "local" if base_url == config.base_url else "custom",
        )
        return {
            "base_url": base_url,
            "selected_device": selected_device(),
            "resolved_device": resolved_device,
            "auto_fallback_enabled": automatic_fallback_enabled(),
            "candidate_urls": candidate_urls(config),
        }

    @app.websocket("/extension/connect")
    async def extension_connect(websocket: WebSocket):
        if not config.extension_token:
            await websocket.close(code=4403, reason="ECHOPROFILE_EXTENSION_TOKEN is not configured")
            return
        await websocket.accept()
        try:
            auth = await asyncio.wait_for(websocket.receive_json(), timeout=10)
            supplied = str(auth.get("token", "")) if isinstance(auth, dict) else ""
            if not hmac.compare_digest(supplied, config.extension_token):
                await websocket.close(code=4403, reason="Invalid pairing token")
                return
            await extension_bridge.attach(websocket)
            await websocket.send_json({"type": "authenticated"})
            while True:
                try:
                    message = await asyncio.wait_for(websocket.receive_json(), timeout=20)
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "heartbeat"})
                    continue
                if isinstance(message, dict) and message.get("type") == "result":
                    await extension_bridge.resolve(message)
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        finally:
            await extension_bridge.detach(websocket)

    @app.get("/extension/bootstrap")
    async def extension_bootstrap(request: Request):
        # The extension has a pinned manifest key and a fixed CORS allow-origin.
        # Chrome extension service-worker GETs may omit Origin. If present,
        # require the pinned extension origin; always enforce a loopback client.
        expected_origin = f"chrome-extension://{BROWSER_EXTENSION_ID}"
        origin = request.headers.get("origin")
        client_host = request.client.host if request.client else ""
        try:
            is_loopback = ipaddress.ip_address(client_host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback or (origin is not None and origin != expected_origin):
            raise HTTPException(
                status_code=403,
                detail="EchoProfile pairing bootstrap is available only to local clients",
            )
        return JSONResponse(
            {"token": config.extension_token},
            headers={
                "Access-Control-Allow-Origin": expected_origin,
                "Cache-Control": "no-store",
                "Vary": "Origin",
            },
        )

    @app.get("/extension/status")
    async def extension_status():
        return {"connected": extension_bridge.connected}

    @app.post("/extension/action")
    async def extension_action(
        request: ExtensionActionRequest,
        authorization: str | None = Header(default=None),
    ):
        supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if not config.extension_token or not hmac.compare_digest(supplied, config.extension_token):
            raise HTTPException(status_code=401, detail="Invalid EchoProfile extension API token")
        try:
            return await extension_bridge.request(request.action, request.payload)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/browser/action")
    async def browser_action(request: BrowserActionRequest):
        try:
            return await manager.browser_action(request.action, request.payload)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/clone")
    async def clone(request: CloneRequest):
        try:
            clone = await manager.create_clone(request.url)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return clone.to_dict()

    @app.get("/clones")
    async def list_clones():
        return [c.to_dict() for c in manager.list_clones()]

    @app.post("/clones/{clone_id}/close")
    async def close_clone(clone_id: str):
        closed = await manager.close_clone(clone_id)
        if not closed:
            raise HTTPException(status_code=404, detail=f"clone {clone_id!r} not found")
        return {"closed": clone_id}

    @app.post("/persistent/open")
    async def open_persistent(request: OpenPersistentRequest):
        if manager.persistent_open:
            raise HTTPException(status_code=409, detail="persistent profile is already open")
        await manager.open_persistent(
            load_switchboard=request.load_switchboard,
            load_multica=request.load_multica,
            load_chatgpt=request.load_chatgpt,
            load_echoprofile=request.load_echoprofile,
            extension_dirs=[Path(path).expanduser() for path in request.extension_dirs],
            restrict_extensions=request.restrict_extensions,
        )
        return {"open": True}

    @app.post("/persistent/close")
    async def close_persistent():
        was_open = await manager.close_persistent()
        if not was_open:
            raise HTTPException(status_code=409, detail="persistent profile is not open")
        return {"open": False}

    @app.get("/persistent")
    async def persistent_status():
        return {"open": manager.persistent_open}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def run() -> None:
    import os
    import sys

    import uvicorn

    config = load_config()

    # uvicorn's --reload spawns a worker subprocess whose asyncio event loop
    # setup doesn't reliably pick up WindowsProactorEventLoopPolicy at any
    # point we can hook into from our own code - the worker ends up on
    # SelectorEventLoop, which can't run subprocesses at all, and Playwright
    # launches its driver as one. So reload defaults off on Windows; set
    # ECHOPROFILE_FORCE_RELOAD=1 to try it anyway if this gets fixed upstream.
    if sys.platform == "win32":
        reload = os.environ.get("ECHOPROFILE_FORCE_RELOAD") is not None
        if not reload:
            print(
                "Hot reload is off by default on Windows - uvicorn's reload "
                "worker breaks Playwright's subprocess launch there. Set "
                "ECHOPROFILE_FORCE_RELOAD=1 to override."
            )
    else:
        reload = os.environ.get("ECHOPROFILE_NO_RELOAD") is None

    if reload:
        print(
            "Hot reload is on (default) - any file change restarts the server "
            "process, which orphans the persistent profile window and any "
            "open clones (they stay open on screen but `serve` loses track "
            "of them). Set ECHOPROFILE_NO_RELOAD=1 to disable."
        )
        uvicorn.run(
            "echoprofile.server:create_app",
            factory=True,
            host=config.host,
            port=config.port,
            reload=True,
        )
    else:
        if sys.platform == "win32":
            import asyncio

            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        uvicorn.run(create_app(config), host=config.host, port=config.port)
