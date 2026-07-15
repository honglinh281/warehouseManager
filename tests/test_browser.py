from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from browser import ActionButton, CategoryButton, MediaBrowserView
from storage import MediaRepository


class FakeResponse:
    def __init__(self) -> None:
        self.edited = False

    async def edit_message(self, **kwargs) -> None:
        self.edited = bool(kwargs.get("embed") and kwargs.get("view"))


class FakeInteraction:
    def __init__(self) -> None:
        self.response = FakeResponse()


class MediaBrowserInteractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = MediaRepository(Path(self.tempdir.name) / "browser.sqlite3")
        asyncio.run(self.repository.initialize())

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def make_view(self) -> MediaBrowserView:
        return asyncio.run(MediaBrowserView.create(self.repository, 1, 10, {20}))

    def test_category_callback_survives_component_rebuild(self) -> None:
        view = self.make_view()
        button = next(
            item for item in view.children
            if isinstance(item, CategoryButton) and item.category == "image"
        )
        interaction = FakeInteraction()
        asyncio.run(button.callback(interaction))
        self.assertEqual(view.state.category, "image")
        self.assertTrue(interaction.response.edited)

    def test_reset_callback_survives_component_rebuild(self) -> None:
        view = self.make_view()
        view.state.search = "roadmap"
        button = next(
            item for item in view.children
            if isinstance(item, ActionButton) and item.action == "reset"
        )
        interaction = FakeInteraction()
        asyncio.run(button.callback(interaction))
        self.assertIsNone(view.state.search)
        self.assertTrue(interaction.response.edited)


if __name__ == "__main__":
    unittest.main()
