from pathlib import Path
import unittest
from unittest.mock import MagicMock, call, patch

from fastapi.testclient import TestClient

from echoprofile.config import Config
from echoprofile.server import _bind_server_sockets, create_app


class RoutingEndpointTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(
            profile_dir=Path("/tmp/echoprofile-test-profile"),
            host="127.0.0.1",
            port=8756,
            default_url="about:blank",
        )

    def test_resolve_returns_selected_and_resolved_device(self):
        with (
            patch("echoprofile.server.resolve_base_url", return_value="http://100.76.52.7:8756"),
            patch("echoprofile.server.selected_device", return_value="arch"),
            patch("echoprofile.server.automatic_fallback_enabled", return_value=True),
            patch("echoprofile.server.candidate_urls", return_value=["http://100.76.52.7:8756"]),
        ):
            with TestClient(create_app(self.config)) as client:
                response = client.get("/routing/resolve")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["base_url"], "http://100.76.52.7:8756")
        self.assertEqual(response.json()["selected_device"], "arch")
        self.assertEqual(response.json()["resolved_device"], "arch")
        self.assertTrue(response.json()["auto_fallback_enabled"])

    def test_invalid_device_is_reported_as_bad_request(self):
        with patch("echoprofile.server.resolve_base_url", side_effect=ValueError("unknown device")):
            with TestClient(create_app(self.config)) as client:
                response = client.get("/routing/resolve")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "unknown device")


class ServerSocketBindingTests(unittest.TestCase):
    def test_bind_loopback_adds_local_listener_without_wildcard_binding(self):
        sockets = [MagicMock(), MagicMock()]
        with patch("socket.socket", side_effect=sockets):
            result = _bind_server_sockets("100.82.234.105", 8756, bind_loopback=True)

        self.assertEqual(result, sockets)
        self.assertEqual(sockets[0].bind.call_args, call(("100.82.234.105", 8756)))
        self.assertEqual(sockets[1].bind.call_args, call(("127.0.0.1", 8756)))
        for server_socket in sockets:
            server_socket.listen.assert_called_once_with(2048)
            server_socket.setblocking.assert_called_once_with(False)

    def test_bind_loopback_does_not_duplicate_loopback_listener(self):
        server_socket = MagicMock()
        with patch("socket.socket", return_value=server_socket):
            result = _bind_server_sockets("127.0.0.1", 8756, bind_loopback=True)

        self.assertEqual(result, [server_socket])
        server_socket.bind.assert_called_once_with(("127.0.0.1", 8756))


if __name__ == "__main__":
    unittest.main()
