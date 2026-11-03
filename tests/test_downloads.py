import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from echoprofile.config import load_config
from echoprofile.core import _safe_download_filename, _save_download


class DownloadTests(unittest.TestCase):
    def test_filename_is_sanitized(self):
        self.assertEqual(_safe_download_filename(r"C:\temp\report?.pdf"), "report_.pdf")
        self.assertEqual(_safe_download_filename("CON.txt"), "_CON.txt")
        self.assertEqual(_safe_download_filename("../"), "download")

    def test_save_uses_suggested_name_and_preserves_existing_file(self):
        class FakeDownload:
            suggested_filename = "report.pdf"
            async def save_as(self, path):
                Path(path).write_bytes(b"downloaded")
        with tempfile.TemporaryDirectory() as directory:
            target_dir = Path(directory)
            (target_dir / "report.pdf").write_bytes(b"existing")
            saved = asyncio.run(_save_download(FakeDownload(), target_dir, asyncio.Lock()))
            self.assertEqual(saved.name, "report (1).pdf")
            self.assertEqual(saved.read_bytes(), b"downloaded")
            self.assertEqual((target_dir / "report.pdf").read_bytes(), b"existing")

    def test_download_directory_override(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"ECHOPROFILE_DOWNLOAD_DIR": directory}, clear=True):
                self.assertEqual(load_config().download_dir, Path(directory))

    def test_downloads_enabled_on_persistent_and_clone_contexts(self):
        source = (Path(__file__).parents[1] / "echoprofile" / "core.py").read_text()
        self.assertEqual(source.count("accept_downloads=True"), 2)
