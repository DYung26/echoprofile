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
