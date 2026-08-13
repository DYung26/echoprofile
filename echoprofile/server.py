from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from echoprofile.config import Config, load_config
from echoprofile.core import CloneManager


class CloneRequest(BaseModel):
    url: str | None = None


class OpenPersistentRequest(BaseModel):
    load_switchboard: bool = False


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    manager = CloneManager(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await manager.close_all()

    app = FastAPI(title="echoprofile", lifespan=lifespan)

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
        await manager.open_persistent(load_switchboard=request.load_switchboard)
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

    import uvicorn

    config = load_config()
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
        uvicorn.run(create_app(config), host=config.host, port=config.port)
