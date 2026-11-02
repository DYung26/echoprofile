"""Minimal MCP stdio server exposing EchoProfile's extension-backed browser API."""
from __future__ import annotations

import json
import sys
from typing import Any

import httpx

from echoprofile.config import load_config


SERVER_NAME = "echoprofile-browser"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

TOOLS: list[dict[str, Any]] = [
    {"name": "browser_status", "description": "Check whether the first-party EchoProfile browser extension is connected.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "tabs_list", "description": "List tabs in the extension-controlled browser.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "active_tab", "description": "Get the active tab in the extension-controlled browser.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "new_tab", "description": "Create a browser tab and optionally navigate it to a URL.", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "active": {"type": "boolean", "default": True}}, "additionalProperties": False}},
    {"name": "close_tab", "description": "Close a browser tab by its tab ID.", "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "integer"}}, "required": ["tab_id"], "additionalProperties": False}},
    {"name": "activate_tab", "description": "Activate and focus a browser tab by its tab ID.", "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "integer"}}, "required": ["tab_id"], "additionalProperties": False}},
    {"name": "navigate", "description": "Navigate a tab, or the active tab, to a URL.", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "tab_id": {"type": "integer"}}, "required": ["url"], "additionalProperties": False}},
    {"name": "page_title", "description": "Read the title and URL of a tab, or the active tab.", "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "integer"}}, "additionalProperties": False}},
    {"name": "page_text", "description": "Read visible text from a tab, or the active tab.", "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "integer"}}, "additionalProperties": False}},
    {"name": "page_html", "description": "Read the current document HTML from a tab, or the active tab.", "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "integer"}}, "additionalProperties": False}},
    {"name": "page_click", "description": "Click the first element matching a CSS selector.", "inputSchema": {"type": "object", "properties": {"selector": {"type": "string"}, "tab_id": {"type": "integer"}}, "required": ["selector"], "additionalProperties": False}},
    {"name": "page_fill", "description": "Fill an input, textarea, or contenteditable element selected by CSS selector.", "inputSchema": {"type": "object", "properties": {"selector": {"type": "string"}, "value": {"type": "string"}, "tab_id": {"type": "integer"}}, "required": ["selector", "value"], "additionalProperties": False}},
    {"name": "page_press", "description": "Press a keyboard key, optionally focusing an element first.", "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}, "selector": {"type": "string"}, "tab_id": {"type": "integer"}}, "required": ["key"], "additionalProperties": False}},
    {"name": "page_scroll", "description": "Scroll a tab by horizontal and vertical pixel offsets.", "inputSchema": {"type": "object", "properties": {"x": {"type": "integer", "default": 0}, "y": {"type": "integer", "default": 0}, "tab_id": {"type": "integer"}}, "additionalProperties": False}},
    {"name": "page_screenshot", "description": "Capture a screenshot of a tab. Returns an image when supported by the MCP client.", "inputSchema": {"type": "object", "properties": {"format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"}, "full_page": {"type": "boolean", "default": False}, "tab_id": {"type": "integer"}}, "additionalProperties": False}},
]

ACTION_MAP = {
    "tabs_list": ("tabs.list", lambda a: {}),
    "active_tab": ("tabs.active", lambda a: {}),
    "new_tab": ("tabs.new", lambda a: {"url": a.get("url", "about:blank"), "active": a.get("active", True)}),
    "close_tab": ("tabs.close", lambda a: {"tabId": a["tab_id"]}),
    "activate_tab": ("tabs.activate", lambda a: {"tabId": a["tab_id"]}),
    "navigate": ("navigate", lambda a: {"url": a["url"], **({"tabId": a["tab_id"]} if "tab_id" in a else {})}),
    "page_title": ("page.title", lambda a: ({"tabId": a["tab_id"]} if "tab_id" in a else {})),
    "page_text": ("page.text", lambda a: ({"tabId": a["tab_id"]} if "tab_id" in a else {})),
    "page_html": ("page.html", lambda a: ({"tabId": a["tab_id"]} if "tab_id" in a else {})),
    "page_click": ("page.click", lambda a: {"selector": a["selector"], **({"tabId": a["tab_id"]} if "tab_id" in a else {})}),
    "page_fill": ("page.fill", lambda a: {"selector": a["selector"], "value": a["value"], **({"tabId": a["tab_id"]} if "tab_id" in a else {})}),
    "page_press": ("page.press", lambda a: {"key": a["key"], **({"selector": a["selector"]} if "selector" in a else {}), **({"tabId": a["tab_id"]} if "tab_id" in a else {})}),
    "page_scroll": ("page.scroll", lambda a: {"x": a.get("x", 0), "y": a.get("y", 0), **({"tabId": a["tab_id"]} if "tab_id" in a else {})}),
    "page_screenshot": ("page.screenshot", lambda a: {"format": a.get("format", "png"), "fullPage": a.get("full_page", False), **({"tabId": a["tab_id"]} if "tab_id" in a else {})}),
}


def _api() -> tuple[str, str]:
    config = load_config()
    base_url = config.base_url.rstrip("/")
    return base_url, config.extension_token


def _call_api(action: str, payload: dict[str, Any] | None = None) -> Any:
    base_url, token = _api()
    with httpx.Client(timeout=45.0) as client:
        response = client.post(
            f"{base_url}/extension/action",
            json={"action": action, "payload": payload or {}},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()


def _tool_call(name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    if name == "browser_status":
        base_url, _ = _api()
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{base_url}/extension/status")
            response.raise_for_status()
            result = response.json()
    elif name in ACTION_MAP:
        action, payload_builder = ACTION_MAP[name]
        result = _call_api(action, payload_builder(arguments))
    else:
        raise ValueError(f"Unknown EchoProfile tool: {name}")
    if name == "page_screenshot" and isinstance(result, dict) and isinstance(result.get("dataUrl"), str):
        header, encoded = result["dataUrl"].split(",", 1)
        mime_type = header[5:].split(";", 1)[0]
        return [{"type": "image", "data": encoded, "mimeType": mime_type}]
    return [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]


def _response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(method, str):
        return _error(request_id, -32600, "Invalid request") if request_id is not None else None
    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None
    if method == "initialize":
        return _response(request_id, {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method == "ping":
        return _response(request_id, {})
    if method == "tools/list":
        return _response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            content = _tool_call(name, arguments)
            return _response(request_id, {"content": content, "isError": False})
        except Exception as error:
            return _response(request_id, {"content": [{"type": "text", "text": str(error)}], "isError": True})
    if method == "resources/list":
        return _response(request_id, {"resources": []})
    return _error(request_id, -32601, f"Method not found: {method}") if request_id is not None else None


def main() -> None:
    """Run the MCP stdio transport. stdout is reserved for JSON-RPC frames."""
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC message must be an object")
            response = handle(message)
        except Exception as error:
            response = _error(None, -32700, str(error))
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":"), ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
