from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from echoprofile.config import Config
from echoprofile.routing import candidate_urls, is_healthy, resolve_base_url


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(
            profile_dir=Path(tempfile.gettempdir()) / "profile",
            host="127.0.0.1",
            port=8756,
            default_url="about:blank",
        )

    def test_default_priority_is_local_then_laptop_then_vps(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                candidate_urls(self.config),
                [
                    "http://127.0.0.1:8756",
                    "http://100.98.45.0:8756",
                    "http://100.82.234.105:8756",
                ],
            )

    def test_custom_priority_is_trimmed_and_deduplicated(self) -> None:
        self.assertEqual(
            candidate_urls(self.config, env_value=" http://a:1/ ,http://b:2,http://a:1 "),
            ["http://a:1", "http://b:2"],
        )

    def test_health_requires_expected_payload(self) -> None:
        response = httpx.Response(200, json={"status": "ok"})
        client = type("Client", (), {"get": lambda _self, _url: response})()
        self.assertTrue(is_healthy("http://a:1", client=client))
        response = httpx.Response(200, json={"status": "degraded"})
        self.assertFalse(is_healthy("http://a:1", client=client))

    def test_health_rejects_http_errors(self) -> None:
        def fail(_url: str):
            raise httpx.ConnectError("offline")
        client = type("Client", (), {"get": lambda _self, url: fail(url)})()
        self.assertFalse(is_healthy("http://a:1", client=client))

    def test_resolver_selects_first_healthy_and_recovers_priority(self) -> None:
        with patch("echoprofile.routing.candidate_urls", return_value=["http://arch", "http://laptop", "http://vps"]), patch(
            "echoprofile.routing.is_healthy", side_effect=[False, True]
        ):
            self.assertEqual(resolve_base_url(self.config), "http://laptop")
        with patch("echoprofile.routing.candidate_urls", return_value=["http://arch", "http://laptop", "http://vps"]), patch(
            "echoprofile.routing.is_healthy", side_effect=[True]
        ):
            self.assertEqual(resolve_base_url(self.config), "http://arch")

    def test_resolver_returns_primary_if_all_endpoints_are_down(self) -> None:
        with patch("echoprofile.routing.candidate_urls", return_value=["http://arch", "http://laptop"]), patch(
            "echoprofile.routing.is_healthy", return_value=False
        ):
            self.assertEqual(resolve_base_url(self.config), "http://arch")


if __name__ == "__main__":
    unittest.main()
