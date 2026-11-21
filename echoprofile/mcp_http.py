"""Stateless Streamable HTTP transport for the EchoProfile extension MCP tools."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from echoprofile.mcp_server import SERVER_NAME, handle

LOGGER = logging.getLogger(__name__)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _allowed_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.environ.get("ECHOPROFILE_MCP_HTTP_ALLOWED_CLIENTS", "172.20.0.0/16,127.0.0.1/32,::1/128")
    return [ipaddress.ip_network(item.strip(), strict=False) for item in raw.split(",") if item.strip()]


def _allowed_origins() -> set[str]:
    raw = os.environ.get("ECHOPROFILE_MCP_HTTP_ALLOWED_ORIGINS", "")
    return {origin.strip() for origin in raw.split(",") if origin.strip()}


def _authorized_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True
    return origin in _allowed_origins()


def _supported_protocol_version() -> str:
    from echoprofile.mcp_server import PROTOCOL_VERSION

    return PROTOCOL_VERSION


def _valid_protocol_header(request: Request) -> bool:
    version = request.headers.get("mcp-protocol-version")
    return version is None or version == _supported_protocol_version()


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
    try:
        response = handle(message)
    except Exception:
        LOGGER.exception("Unhandled exception while processing EchoProfile MCP request")
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": -32603, "message": "Internal MCP server error"},
        }
    if response is None:
        return None
    result = response.get("result")
    if isinstance(result, dict) and result.get("isError") is True:
        safe_response = dict(response)
        safe_result = dict(result)
        safe_result["content"] = [
            {
                "type": "text",
                "text": "Tool execution failed. Check EchoProfile server logs.",
            }
        ]
        safe_response["result"] = safe_result
        return safe_response
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "server": SERVER_NAME}


@app.post("/mcp")
async def mcp_post(request: Request) -> Response:
    if not _authorized(request) or not _authorized_origin(request):
        return Response(status_code=403)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return Response(status_code=415)
    if not _valid_protocol_header(request):
        return Response(status_code=400)
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(_invalid_request(), status_code=400)

    if isinstance(payload, list):
        responses = [
            response
            for item in payload
            if (response := await run_in_threadpool(_process, item)) is not None
        ]
        if not responses:
            return Response(status_code=202)
        return JSONResponse(responses, headers={"Cache-Control": "no-cache, no-transform"})

    response = await run_in_threadpool(_process, payload)
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
