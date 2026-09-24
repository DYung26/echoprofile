import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from echoprofile.config import Config, MULTICA_EXTENSION_DIR, load_config
from echoprofile.core import _extension_args


class ExtensionArgsTests(unittest.TestCase):
    def make_config(self, switchboard: Path, multica: Path | None) -> Config:
        return Config(
            profile_dir=switchboard.parent / "profile",
            host="127.0.0.1",
            port=8756,
            default_url="about:blank",
            switchboard_extension_dir=switchboard,
            multica_extension_dir=multica,
        )

    def test_default_config_enables_multica(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()

        self.assertEqual(config.multica_extension_dir, MULTICA_EXTENSION_DIR)

    def test_empty_multica_env_disables_multica(self) -> None:
        with patch.dict(os.environ, {"ECHOPROFILE_MULTICA_DIR": ""}, clear=True):
            config = load_config()

        self.assertIsNone(config.multica_extension_dir)

    def test_loads_switchboard_and_multica_together(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            switchboard = root / "switchboard"
            multica = root / "multica"
            switchboard.mkdir()
            multica.mkdir()

            args = _extension_args(
                self.make_config(switchboard, multica),
                load_switchboard=True,
                load_multica=True,
            )

            paths = f"{switchboard},{multica}"
            self.assertEqual(
                args,
                [f"--disable-extensions-except={paths}", f"--load-extension={paths}"],
            )

    def test_loads_only_multica_when_switchboard_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            multica = root / "multica"
            multica.mkdir()
            switchboard = root / "switchboard"

            args = _extension_args(
                self.make_config(switchboard, multica),
                load_switchboard=False,
                load_multica=True,
            )

            self.assertEqual(
                args,
                [
                    f"--disable-extensions-except={multica}",
                    f"--load-extension={multica}",
                ],
            )

    def test_loads_only_switchboard_when_multica_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            switchboard = root / "switchboard"
            switchboard.mkdir()
            multica = root / "multica"

            args = _extension_args(
                self.make_config(switchboard, multica),
                load_switchboard=True,
                load_multica=False,
            )

            self.assertEqual(
                args,
                [
                    f"--disable-extensions-except={switchboard}",
                    f"--load-extension={switchboard}",
                ],
            )

    def test_no_extensions_returns_no_extension_args(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            switchboard = root / "switchboard"
            multica = root / "multica"

            self.assertEqual(
                _extension_args(
                    self.make_config(switchboard, multica),
                    load_switchboard=False,
                    load_multica=False,
                ),
                [],
            )

    def test_missing_enabled_extension_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            switchboard = root / "switchboard"
            multica = root / "multica"
            multica.mkdir()

            with self.assertRaisesRegex(RuntimeError, "Switchboard extension not found"):
                _extension_args(
                    self.make_config(switchboard, multica),
                    load_switchboard=True,
                    load_multica=True,
                )

    def test_missing_multica_fails_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            switchboard = root / "switchboard"
            switchboard.mkdir()
            multica = root / "multica"

            with self.assertRaisesRegex(
                RuntimeError, "Multica Web Runtime extension not found"
            ):
                _extension_args(
                    self.make_config(switchboard, multica),
                    load_switchboard=True,
                    load_multica=True,
                )


if __name__ == "__main__":
    unittest.main()
