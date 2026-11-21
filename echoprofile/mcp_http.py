"""Stateless Streamable HTTP transport for the EchoProfile extension MCP tools."""
from __future__ import annotations

import ipaddress
import json
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from echoprofile.mcp_server import SERVER_NAME, handle

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _allowed_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.environ.get("ECHOPROFILE_MCP_HTTP_ALLOWED_CLIENTS", "172.20.0.0/16,127.0.0.1/32,::1/128")
    return [ipaddress.ip_network(item.strip(), strict=False) for item in raw.split(",") if item.strip()]


def _authorized(request: Request) -> bool:
    if request.client is None:
        return False
    try:
        address = ipaddress.ip_address(request.client.host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in _allowed_networks())


def _invalid_request(request_id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid request"}}


def _process(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return _invalid_request()
    return handle(message)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "server": SERVER_NAME}


@app.post("/mcp")
async def mcp_post(request: Request) -> Response:
    if not _authorized(request):
        return Response(status_code=403)
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(_invalid_request(), status_code=400)

    if isinstance(payload, list):
        responses = [response for item in payload if (response := _process(item)) is not None]
        if not responses:
            return Response(status_code=202)
        return JSONResponse(responses, headers={"Cache-Control": "no-cache, no-transform"})

    response = _process(payload)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(response, headers={"Cache-Control": "no-cache, no-transform"})


@app.get("/mcp")
async def mcp_get(request: Request) -> Response:
    if not _authorized(request):
        return Response(status_code=403)
    return Response(status_code=405, headers={"Allow": "POST, DELETE"})


@app.delete("/mcp")
async def mcp_delete(request: Request) -> Response:
    if not _authorized(request):
        return Response(status_code=403)
    return Response(status_code=200)


def main() -> None:
    host = os.environ.get("ECHOPROFILE_MCP_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("ECHOPROFILE_MCP_HTTP_PORT", "8757"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
