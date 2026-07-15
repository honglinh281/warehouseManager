from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from storage import MediaItem, MediaRepository


class MediaRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = MediaRepository(Path(self.tempdir.name) / "test.sqlite3")
        asyncio.run(self.repository.initialize())

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def item(self, key: str, category: str = "file", name: str = "roadmap.pdf") -> MediaItem:
        return MediaItem(
            source_key=key,
            guild_id=1,
            channel_id=2,
            message_id=3,
            author_id=4,
            author_name="Linh",
            category=category,
            name=name,
            url="https://cdn.discord.test/media",
            jump_url="https://discord.test/channels/1/2/3",
            file_type="pdf" if category == "file" else None,
            size_bytes=1024,
            sent_at=datetime.now(timezone.utc),
        )

    def test_add_is_idempotent_and_queryable(self) -> None:
        item = self.item("attachment:1")
        self.assertEqual(asyncio.run(self.repository.add_many([item])), 1)
        self.assertEqual(asyncio.run(self.repository.add_many([item])), 0)
        page = asyncio.run(self.repository.query(1, "file"))
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].name, "roadmap.pdf")

    def test_filters_search_and_delete(self) -> None:
        asyncio.run(self.repository.add_many([self.item("attachment:2")]))
        self.assertEqual(asyncio.run(self.repository.query(1, "file", search="roadmap")).total, 1)
        self.assertEqual(asyncio.run(self.repository.query(1, "file", file_type="docx")).total, 0)
        asyncio.run(self.repository.delete_message(1, 3))
        self.assertEqual(asyncio.run(self.repository.query(1, "file")).total, 0)

    def test_channel_permissions_are_applied_to_queries_and_counts(self) -> None:
        asyncio.run(self.repository.add_many([self.item("attachment:3")]))
        visible = asyncio.run(self.repository.query(1, "file", channel_ids={2}))
        hidden = asyncio.run(self.repository.query(1, "file", channel_ids={999}))
        self.assertEqual(visible.total, 1)
        self.assertEqual(hidden.total, 0)
        self.assertEqual(asyncio.run(self.repository.counts(1, {999})), {})


if __name__ == "__main__":
    unittest.main()
