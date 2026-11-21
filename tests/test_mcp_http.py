import asyncio

import httpx

from echoprofile import mcp_http, mcp_server


def request(app, method, payload=None, client=("172.20.0.3", 12345)):
    async def run():
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client_session:
            return await client_session.request(method, "/mcp", json=payload)
    return asyncio.run(run())


def test_mcp_http_rejects_clients_outside_metamcp_network():
    response = request(mcp_http.app, "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize"}, client=("10.20.30.40", 12345))
    assert response.status_code == 403


def test_mcp_http_initialize_and_list_tools():
    initialized = request(mcp_http.app, "POST", {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    })
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == mcp_server.SERVER_NAME

    listed = request(mcp_http.app, "POST", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed.status_code == 200
    assert len(listed.json()["result"]["tools"]) == len(mcp_server.TOOLS) == 15


def test_mcp_http_notifications_return_accepted():
    response = request(mcp_http.app, "POST", {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response.status_code == 202


def test_mcp_http_sanitizes_tool_error_payload(monkeypatch):
    monkeypatch.setattr(
        mcp_http,
        "handle",
        lambda message: {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": "Traceback: private path /home/dyung/secret"}],
            },
        },
    )
    response = request(
        mcp_http.app,
        "POST",
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call"},
    )
    assert response.status_code == 200
    error_text = response.json()["result"]["content"][0]["text"]
    assert error_text == "Tool execution failed. Check EchoProfile server logs."
    assert "/home/dyung/secret" not in response.text


def test_mcp_http_sanitizes_unexpected_handler_exceptions(monkeypatch):
    def fail(_message):
        raise RuntimeError("private path /home/dyung/secret")

    monkeypatch.setattr(mcp_http, "handle", fail)
    response = request(
        mcp_http.app,
        "POST",
        {"jsonrpc": "2.0", "id": 4, "method": "initialize"},
    )
    assert response.status_code == 200
    assert response.json()["error"]["message"] == "Internal MCP server error"
    assert "/home/dyung/secret" not in response.text
