import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from echoprofile.config import Config, MULTICA_EXTENSION_DIR, load_config
from echoprofile.core import _extension_args, _replace_chatgpt_placeholder
from echoprofile.server import OpenPersistentRequest


class DownloadConfigurationTests(unittest.TestCase):
    def test_downloads_are_explicitly_enabled_for_both_browser_context_types(self) -> None:
        core_path = Path(__file__).parents[1] / "echoprofile" / "core.py"
        source = core_path.read_text()

        self.assertEqual(source.count("accept_downloads=True"), 2)
        self.assertIn("accept_downloads=True", source[source.index("launch_persistent_context("):source.index("return playwright, context")])
        clone_context = source.index("context = await browser.new_context(")
        self.assertIn("accept_downloads=True", source[clone_context:source.index("page = await context.new_page()", clone_context)])


class PersistentRequestDefaultsTests(unittest.TestCase):
    def test_extensions_are_opt_in_for_persistent_open(self) -> None:
        request = OpenPersistentRequest()

        self.assertFalse(request.load_switchboard)
        self.assertFalse(request.load_multica)
        self.assertFalse(request.load_chatgpt)
        self.assertEqual(request.extension_dirs, [])
        self.assertFalse(request.restrict_extensions)

    def test_multica_can_be_explicitly_enabled(self) -> None:
        request = OpenPersistentRequest(load_multica=True)

        self.assertTrue(request.load_multica)


class ExtensionArgsTests(unittest.TestCase):
    @staticmethod
    def make_extension(path: Path) -> Path:
        path.mkdir(parents=True)
        (path / "manifest.json").write_text(
            json.dumps({"manifest_version": 3, "name": path.name, "version": "1.0"})
        )
        return path

    def make_config(
        self, switchboard: Path, multica: Path | None, chatgpt: Path | None = None
    ) -> Config:
        return Config(
            profile_dir=switchboard.parent / "profile",
            host="127.0.0.1",
            port=8756,
            default_url="about:blank",
            switchboard_extension_dir=switchboard,
            multica_extension_dir=multica,
            chatgpt_extension_dir=chatgpt,
        )

    def test_default_config_enables_multica(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch("echoprofile.config.EXTENSION_TOKEN_FILE", Path(temp_dir) / "token"), patch.dict(os.environ, {}, clear=True):
            config = load_config()

        self.assertEqual(config.multica_extension_dir, MULTICA_EXTENSION_DIR)
        self.assertIsNone(config.chatgpt_extension_dir)
        self.assertTrue((config.browser_extension_dir / "manifest.json").is_file())

    def test_echo_profile_extension_is_loaded_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            extension = self.make_extension(root / "echoprofile")
            config = self.make_config(root / "switchboard", None)
            config = Config(
                profile_dir=config.profile_dir, host=config.host, port=config.port,
                default_url=config.default_url, switchboard_extension_dir=config.switchboard_extension_dir,
                multica_extension_dir=config.multica_extension_dir, browser_extension_dir=extension,
            )
            args = _extension_args(config, load_switchboard=False, load_multica=False)
            self.assertEqual(args, [f"--load-extension={extension.resolve()}"])

    def test_chatgpt_extension_path_is_configurable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch("echoprofile.config.EXTENSION_TOKEN_FILE", Path(temp_dir) / "token"), patch.dict(os.environ, {"ECHOPROFILE_CHATGPT_EXTENSION_DIR": "~/Extensions/chatgpt"}, clear=True):
            config = load_config()

        self.assertEqual(config.chatgpt_extension_dir, Path("~/Extensions/chatgpt").expanduser())

    def test_extension_token_is_created_once_with_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch("echoprofile.config.EXTENSION_TOKEN_FILE", Path(temp_dir) / "token"), patch.dict(os.environ, {}, clear=True):
            first = load_config().extension_token
            second = load_config().extension_token
            token_path = Path(temp_dir) / "token"
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first), 40)
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)

    def test_empty_multica_env_disables_multica(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch("echoprofile.config.EXTENSION_TOKEN_FILE", Path(temp_dir) / "token"), patch.dict(os.environ, {"ECHOPROFILE_MULTICA_DIR": ""}, clear=True):
            config = load_config()

        self.assertIsNone(config.multica_extension_dir)

    def test_disabled_multica_sentinel_disables_multica(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch("echoprofile.config.EXTENSION_TOKEN_FILE", Path(temp_dir) / "token"), patch.dict(os.environ, {"ECHOPROFILE_MULTICA_DIR": "disabled"}, clear=True):
            config = load_config()

        self.assertIsNone(config.multica_extension_dir)

    def test_loads_switchboard_and_multica_together_without_disabling_others(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            switchboard = root / "switchboard"
            multica = root / "multica"
            self.make_extension(switchboard)
            self.make_extension(multica)

            args = _extension_args(
                self.make_config(switchboard, multica),
                load_switchboard=True,
                load_echoprofile=False,
                load_multica=True,
            )

            self.assertEqual(args, [f"--load-extension={switchboard},{multica}"])

    def test_loads_only_multica_when_switchboard_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            multica = root / "multica"
            self.make_extension(multica)

            args = _extension_args(
                self.make_config(root / "switchboard", multica),
                load_switchboard=False,
                load_echoprofile=False,
                load_multica=True,
            )

            self.assertEqual(args, [f"--load-extension={multica}"])

    def test_can_opt_into_allow_list_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extension = Path(temp_dir) / "extension"
            self.make_extension(extension)
            args = _extension_args(
                self.make_config(Path(temp_dir) / "switchboard", None),
                load_switchboard=False,
                load_echoprofile=False,
                load_multica=False,
                extension_dirs=[extension],
                restrict_extensions=True,
            )
            self.assertEqual(
                args,
                [
                    f"--disable-extensions-except={extension}",
                    f"--load-extension={extension}",
                ],
            )

    def test_loads_chatgpt_with_other_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            switchboard, multica, chatgpt = (root / name for name in ("switchboard", "multica", "chatgpt"))
            for directory in (switchboard, multica, chatgpt):
                self.make_extension(directory)
            args = _extension_args(
                self.make_config(switchboard, multica, chatgpt),
                load_switchboard=True,
                load_echoprofile=False,
                load_multica=True,
                load_chatgpt=True,
            )
            self.assertEqual(args, [f"--load-extension={switchboard},{multica},{chatgpt}"])

    def test_custom_extensions_are_repeatable_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            extension = root / "extension"
            self.make_extension(extension)
            args = _extension_args(
                self.make_config(root / "switchboard", None),
                load_switchboard=False,
                load_echoprofile=False,
                load_multica=False,
                extension_dirs=[extension, extension],
            )
            self.assertEqual(args, [f"--load-extension={extension}"])

    def test_no_extensions_returns_no_extension_args(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual(
                _extension_args(
                    self.make_config(root / "switchboard", root / "multica"),
                    load_switchboard=False,
                load_echoprofile=False,
                    load_multica=False,
                ),
                [],
            )

    def test_missing_enabled_extension_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            multica = root / "multica"
            multica.mkdir()
            with self.assertRaisesRegex(RuntimeError, "Switchboard extension not found"):
                _extension_args(
                    self.make_config(root / "switchboard", multica),
                    load_switchboard=True,
                load_echoprofile=False,
                    load_multica=True,
                )

    def test_missing_chatgpt_extension_fails_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(RuntimeError, "ChatGPT extension not found"):
                _extension_args(
                    self.make_config(root / "switchboard", None),
                    load_switchboard=False,
                load_echoprofile=False,
                    load_multica=False,
                    load_chatgpt=True,
                )

    def test_missing_custom_extension_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(RuntimeError, "Custom extension not found"):
                _extension_args(
                    self.make_config(root / "switchboard", None),
                    load_switchboard=False,
                load_echoprofile=False,
                    load_multica=False,
                    extension_dirs=[root / "missing"],
                )

    def test_extension_directory_without_manifest_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extension = Path(temp_dir) / "extension"
            extension.mkdir()
            with self.assertRaisesRegex(RuntimeError, "no manifest.json"):
                _extension_args(
                    self.make_config(extension.parent / "switchboard", None),
                    load_switchboard=False,
                load_echoprofile=False,
                    load_multica=False,
                    extension_dirs=[extension],
                )


class ChatGPTRequestMutationTests(unittest.TestCase):
    def test_replaces_only_the_last_user_text_part(self) -> None:
        body = {
            "messages": [
                {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["old"]}},
                {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["answer"]}},
                {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["__PLACEHOLDER__", {"type": "image"}]}},
            ]
        }

        _replace_chatgpt_placeholder(body, "__PLACEHOLDER__", "real prompt")

        self.assertEqual(body["messages"][2]["content"]["parts"], ["real prompt", {"type": "image"}])
        self.assertEqual(body["messages"][0]["content"]["parts"], ["old"])

    def test_missing_placeholder_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "placeholder"):
            _replace_chatgpt_placeholder(
                {"messages": [{"author": {"role": "user"}, "content": {"parts": ["other"]}}]},
                "__PLACEHOLDER__",
                "real prompt",
            )


if __name__ == "__main__":
    unittest.main()
