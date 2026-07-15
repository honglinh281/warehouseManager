from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal

Category = Literal["file", "image", "link"]


@dataclass(frozen=True)
class MediaItem:
    source_key: str
    guild_id: int
    channel_id: int
    message_id: int
    author_id: int
    author_name: str
    category: Category
    name: str
    url: str
    jump_url: str
    file_type: str | None
    size_bytes: int | None
    sent_at: datetime
    id: int | None = None


@dataclass(frozen=True)
class MediaPage:
    items: list[MediaItem]
    total: int


class MediaRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL UNIQUE,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    author_name TEXT NOT NULL,
                    category TEXT NOT NULL CHECK(category IN ('file', 'image', 'link')),
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    jump_url TEXT NOT NULL,
                    file_type TEXT,
                    size_bytes INTEGER,
                    sent_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_media_browse
                    ON media(guild_id, category, sent_at DESC);
                CREATE INDEX IF NOT EXISTS idx_media_message
                    ON media(guild_id, message_id);
                CREATE INDEX IF NOT EXISTS idx_media_sender
                    ON media(guild_id, author_id);
                """
            )

    async def add_many(self, items: Iterable[MediaItem]) -> int:
        batch = list(items)
        if not batch:
            return 0
        return await asyncio.to_thread(self._add_many_sync, batch)

    def _add_many_sync(self, items: list[MediaItem]) -> int:
        values = [
            (
                item.source_key,
                item.guild_id,
                item.channel_id,
                item.message_id,
                item.author_id,
                item.author_name,
                item.category,
                item.name,
                item.url,
                item.jump_url,
                item.file_type,
                item.size_bytes,
                item.sent_at.isoformat(),
            )
            for item in items
        ]
        with self._connect() as connection:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT OR IGNORE INTO media (
                    source_key, guild_id, channel_id, message_id, author_id,
                    author_name, category, name, url, jump_url, file_type,
                    size_bytes, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return connection.total_changes - before

    async def delete_message(self, guild_id: int, message_id: int) -> None:
        await asyncio.to_thread(self._delete_message_sync, guild_id, message_id)

    def _delete_message_sync(self, guild_id: int, message_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM media WHERE guild_id = ? AND message_id = ?",
                (guild_id, message_id),
            )

    async def query(
        self,
        guild_id: int,
        category: Category,
        *,
        channel_ids: set[int] | None = None,
        sender_id: int | None = None,
        after: datetime | None = None,
        file_type: str | None = None,
        search: str | None = None,
        limit: int = 5,
        offset: int = 0,
    ) -> MediaPage:
        return await asyncio.to_thread(
            self._query_sync,
            guild_id,
            category,
            channel_ids,
            sender_id,
            after,
            file_type,
            search,
            limit,
            offset,
        )

    def _query_sync(
        self,
        guild_id: int,
        category: Category,
        channel_ids: set[int] | None,
        sender_id: int | None,
        after: datetime | None,
        file_type: str | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> MediaPage:
        clauses = ["guild_id = ?", "category = ?"]
        params: list[object] = [guild_id, category]

        if channel_ids is not None:
            if not channel_ids:
                return MediaPage([], 0)
            placeholders = ",".join("?" for _ in channel_ids)
            clauses.append(f"channel_id IN ({placeholders})")
            params.extend(sorted(channel_ids))

        if sender_id is not None:
            clauses.append("author_id = ?")
            params.append(sender_id)
        if after is not None:
            clauses.append("sent_at >= ?")
            params.append(after.isoformat())
        if file_type and category == "file":
            clauses.append("file_type = ?")
            params.append(file_type.lower())
        if search:
            clauses.append("(LOWER(name) LIKE ? OR LOWER(url) LIKE ?)")
            pattern = f"%{search.lower()}%"
            params.extend((pattern, pattern))

        where = " AND ".join(clauses)
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM media WHERE {where}", params
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM media WHERE {where} "
                "ORDER BY sent_at DESC, id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return MediaPage([self._row_to_item(row) for row in rows], total)

    async def senders(
        self, guild_id: int, category: Category, channel_ids: set[int] | None = None
    ) -> list[tuple[int, str, int]]:
        return await asyncio.to_thread(self._senders_sync, guild_id, category, channel_ids)

    def _senders_sync(
        self, guild_id: int, category: Category, channel_ids: set[int] | None
    ) -> list[tuple[int, str, int]]:
        channel_sql, channel_params = self._channel_filter(channel_ids)
        if channel_sql is None:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT author_id, MAX(author_name) AS author_name, COUNT(*) AS total
                FROM media WHERE guild_id = ? AND category = ? {channel_sql}
                GROUP BY author_id ORDER BY total DESC LIMIT 24
                """,
                (guild_id, category, *channel_params),
            ).fetchall()
        return [(row["author_id"], row["author_name"], row["total"]) for row in rows]

    async def file_types(
        self, guild_id: int, channel_ids: set[int] | None = None
    ) -> list[tuple[str, int]]:
        return await asyncio.to_thread(self._file_types_sync, guild_id, channel_ids)

    def _file_types_sync(
        self, guild_id: int, channel_ids: set[int] | None
    ) -> list[tuple[str, int]]:
        channel_sql, channel_params = self._channel_filter(channel_ids)
        if channel_sql is None:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT file_type, COUNT(*) AS total FROM media
                WHERE guild_id = ? AND category = 'file' AND file_type IS NOT NULL
                {channel_sql}
                GROUP BY file_type ORDER BY total DESC LIMIT 24
                """,
                (guild_id, *channel_params),
            ).fetchall()
        return [(row["file_type"], row["total"]) for row in rows]

    async def counts(
        self, guild_id: int, channel_ids: set[int] | None = None
    ) -> dict[str, int]:
        return await asyncio.to_thread(self._counts_sync, guild_id, channel_ids)

    def _counts_sync(self, guild_id: int, channel_ids: set[int] | None) -> dict[str, int]:
        channel_sql, channel_params = self._channel_filter(channel_ids)
        if channel_sql is None:
            return {}
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT category, COUNT(*) AS total FROM media "
                f"WHERE guild_id = ? {channel_sql} GROUP BY category",
                (guild_id, *channel_params),
            ).fetchall()
        return {row["category"]: row["total"] for row in rows}

    @staticmethod
    def _channel_filter(channel_ids: set[int] | None) -> tuple[str | None, list[int]]:
        if channel_ids is None:
            return "", []
        if not channel_ids:
            return None, []
        ordered = sorted(channel_ids)
        placeholders = ",".join("?" for _ in ordered)
        return f"AND channel_id IN ({placeholders})", ordered

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> MediaItem:
        return MediaItem(
            id=row["id"],
            source_key=row["source_key"],
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            message_id=row["message_id"],
            author_id=row["author_id"],
            author_name=row["author_name"],
            category=row["category"],
            name=row["name"],
            url=row["url"],
            jump_url=row["jump_url"],
            file_type=row["file_type"],
            size_bytes=row["size_bytes"],
            sent_at=datetime.fromisoformat(row["sent_at"]),
        )
