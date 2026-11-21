import unittest
from unittest.mock import patch

from echoprofile import mcp_server


class McpProtocolTests(unittest.TestCase):
    def test_initialize_and_tool_discovery(self):
        initialized = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "echoprofile-extension")
        tools = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertIn("tabs_list", {tool["name"] for tool in tools})
        self.assertIn("page_screenshot", {tool["name"] for tool in tools})

    @patch.object(mcp_server, "_call_api", return_value=[{"id": 7, "url": "about:blank"}])
    def test_tool_call_routes_through_extension_api(self, call_api):
        response = mcp_server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "tabs_list", "arguments": {}},
        })
        call_api.assert_called_once_with("tabs.list", {})
        self.assertFalse(response["result"]["isError"])


    @patch.object(mcp_server, "_tool_call", side_effect=RuntimeError("private path /home/dyung/secret"))
    def test_tool_errors_are_logged_but_not_returned(self, _tool_call):
        with self.assertLogs(mcp_server.LOGGER, level="ERROR") as captured:
            response = mcp_server.handle({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "tabs_list", "arguments": {}},
            })
        error_text = response["result"]["content"][0]["text"]
        self.assertEqual(error_text, "Tool execution failed. Check EchoProfile server logs.")
        self.assertNotIn("/home/dyung/secret", error_text)
        self.assertIn("/home/dyung/secret", "\n".join(captured.output))

    def test_notification_has_no_response(self):
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))


if __name__ == "__main__":
    unittest.main()
