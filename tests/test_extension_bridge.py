import asyncio
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from echoprofile.config import Config
from echoprofile.server import BROWSER_EXTENSION_ID, ExtensionBridge, create_app


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class ExtensionBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_resolves_matching_extension_response(self):
        bridge = ExtensionBridge()
        websocket = FakeWebSocket()
        await bridge.attach(websocket)
        request = asyncio.create_task(bridge.request("tabs.list", {}))
        await asyncio.sleep(0)
        command = websocket.messages[0]
        self.assertEqual(command["action"], "tabs.list")
        await bridge.resolve({"id": command["id"], "ok": True, "result": [{"id": 1}]})
        self.assertEqual(await request, [{"id": 1}])

    async def test_extension_error_is_returned_to_caller(self):
        bridge = ExtensionBridge()
        websocket = FakeWebSocket()
        await bridge.attach(websocket)
        request = asyncio.create_task(bridge.request("page.click", {"selector": "#missing"}))
        await asyncio.sleep(0)
        await bridge.resolve({"id": websocket.messages[0]["id"], "ok": False, "error": "Element not found"})
        with self.assertRaisesRegex(ValueError, "Element not found"):
            await request

    async def test_disconnect_rejects_pending_requests(self):
        bridge = ExtensionBridge()
        websocket = FakeWebSocket()
        await bridge.attach(websocket)
        request = asyncio.create_task(bridge.request("tabs.list", {}))
        await asyncio.sleep(0)
        await bridge.detach(websocket)
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            await request


class ExtensionApiTests(unittest.TestCase):
    def test_manifest_identity_matches_bootstrap_allow_origin(self):
        manifest_path = Path(__file__).parents[1] / "echoprofile" / "browser_extension" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        public_key = base64.b64decode(manifest["key"])
        digest = hashlib.sha256(public_key).digest()[:16]
        extension_id = "".join(chr(97 + (byte >> 4)) + chr(97 + (byte & 15)) for byte in digest)
        self.assertEqual(extension_id, BROWSER_EXTENSION_ID)

    def test_action_requires_paired_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = Config(
                profile_dir=root / "profile", host="127.0.0.1", port=8756,
                default_url="about:blank", switchboard_extension_dir=None,
                multica_extension_dir=None, extension_token="secret",
            )
            with TestClient(create_app(config)) as client:
                self.assertEqual(client.get("/extension/status").json(), {"connected": False})
                unauthorized = client.post("/extension/action", json={"action": "tabs.list"})
                self.assertEqual(unauthorized.status_code, 401)
                response = client.post(
                    "/extension/action", json={"action": "tabs.list"},
                    headers={"Authorization": "Bearer secret"},
                )
                self.assertEqual(response.status_code, 409)
                self.assertIn("not connected", response.json()["detail"])

    def test_bootstrap_is_loopback_only_and_scopes_cors_to_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = Config(
                profile_dir=root / "profile", host="127.0.0.1", port=8756,
                default_url="about:blank", switchboard_extension_dir=None,
                multica_extension_dir=None, extension_token="secret",
            )
            with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
                denied = TestClient(
                    create_app(config), client=("8.8.8.8", 50000)
                ).get("/extension/bootstrap")
                self.assertEqual(denied.status_code, 403)
                attacker_origin = client.get(
                    "/extension/bootstrap", headers={"Origin": "https://example.com"}
                )
                self.assertEqual(attacker_origin.status_code, 403)
                allowed = client.get(
                    "/extension/bootstrap",
                    headers={"Origin": "chrome-extension://bocgihfkibcmlmldnegcakfppijcdlhb"},
                )
                self.assertEqual(allowed.status_code, 200)
                self.assertEqual(allowed.json(), {"token": "secret"})
                self.assertEqual(
                    allowed.headers["access-control-allow-origin"],
                    "chrome-extension://bocgihfkibcmlmldnegcakfppijcdlhb",
                )

    def test_connection_requires_pairing_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = Config(
                profile_dir=root / "profile", host="127.0.0.1", port=8756,
                default_url="about:blank", switchboard_extension_dir=None,
                multica_extension_dir=None, extension_token="secret",
            )
            with TestClient(create_app(config)) as client:
                with client.websocket_connect("/extension/connect") as websocket:
                    websocket.send_json({"type": "authenticate", "token": "wrong"})
                    with self.assertRaises(Exception):
                        websocket.receive_json()


if __name__ == "__main__":
    unittest.main()
