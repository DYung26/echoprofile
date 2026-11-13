from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from echoprofile.config import DEFAULT_BROWSER_EXTENSION_DIR, load_config


class BrowserExtensionConfigTests(unittest.TestCase):
    def test_browser_extension_dir_defaults_to_packaged_assets(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "echoprofile.config._load_or_create_extension_token", return_value="test-token"
        ):
            config = load_config()
        self.assertEqual(config.browser_extension_dir, DEFAULT_BROWSER_EXTENSION_DIR)

    def test_extra_extension_dirs_are_split_using_platform_path_separator(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second, patch.dict(
            os.environ,
            {"ECHOPROFILE_EXTRA_EXTENSION_DIRS": os.pathsep.join([first, second])},
            clear=True,
        ), patch("echoprofile.config._load_or_create_extension_token", return_value="test-token"):
            config = load_config()
        self.assertEqual(config.extra_extension_dirs, [Path(first), Path(second)])

    def test_browser_extension_dir_can_be_overridden_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"ECHOPROFILE_BROWSER_EXTENSION_DIR": directory}, clear=True
        ), patch("echoprofile.config._load_or_create_extension_token", return_value="test-token"):
            config = load_config()
        self.assertEqual(config.browser_extension_dir, Path(directory))


if __name__ == "__main__":
    unittest.main()
