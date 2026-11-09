from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from echoprofile.config import Config
from echoprofile.server import create_app


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


if __name__ == "__main__":
    unittest.main()
