import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from echoprofile.config import Config
from echoprofile.core import CloneManager


class PersistentBrowserRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def manager(self):
        return CloneManager(Config(Path("/tmp/profile"), "127.0.0.1", 8756, "about:blank"))

    def test_closed_context_is_not_reported_open(self):
        manager = self.manager()
        context = Mock()
        context.is_closed.return_value = True
        manager._persistent_context = context
        self.assertFalse(manager.persistent_open)

    async def test_open_recovers_after_external_browser_close(self):
        manager = self.manager()
        stale_context, stale_driver = Mock(), Mock()
        stale_context.is_closed.return_value = True
        manager._persistent_context = stale_context
        manager._persistent_playwright = stale_driver
        new_driver, new_context = Mock(), Mock()
        new_context.is_closed.return_value = False
        with patch("echoprofile.core.close_persistent_profile", new=AsyncMock()) as close, patch("echoprofile.core.open_persistent_profile", new=AsyncMock(return_value=(new_driver, new_context))) as open_profile:
            await manager.open_persistent()
        close.assert_awaited_once_with(stale_driver, stale_context)
        open_profile.assert_awaited_once()
        self.assertTrue(manager.persistent_open)

    async def test_close_tolerates_browser_closed_outside_api(self):
        manager = self.manager()
        context, driver = Mock(), Mock()
        context.is_closed.return_value = True
        manager._persistent_context = context
        manager._persistent_playwright = driver
        with patch("echoprofile.core.close_persistent_profile", new=AsyncMock()) as close:
            result = await manager.close_persistent()
        self.assertFalse(result)
        close.assert_awaited_once_with(driver, context)
        self.assertFalse(manager.persistent_open)


if __name__ == "__main__":
    unittest.main()
