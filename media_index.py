from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

import discord

from storage import MediaItem

URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?)]}'\""
IMAGE_EXTENSIONS = {
    "avif", "bmp", "gif", "heic", "jpeg", "jpg", "png", "svg", "tif", "tiff", "webp"
}


def extension(filename: str) -> str | None:
    suffix = PurePosixPath(filename).suffix.lower().lstrip(".")
    return suffix or None


def is_image(attachment: discord.Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True
    return extension(attachment.filename) in IMAGE_EXTENSIONS


def link_name(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.") or "Shared link"
    path = unquote(parsed.path).strip("/")
    if not path:
        return host
    label = f"{host} / {path}"
    return label if len(label) <= 90 else f"{label[:87]}…"


def extract_media(message: discord.Message) -> list[MediaItem]:
    if message.guild is None:
        return []

    author_name = getattr(message.author, "display_name", message.author.name)
    base = {
        "guild_id": message.guild.id,
        "channel_id": message.channel.id,
        "message_id": message.id,
        "author_id": message.author.id,
        "author_name": author_name,
        "jump_url": message.jump_url,
        "sent_at": message.created_at,
    }
    items: list[MediaItem] = []

    for attachment in message.attachments:
        category = "image" if is_image(attachment) else "file"
        items.append(
            MediaItem(
                source_key=f"attachment:{attachment.id}",
                category=category,
                name=attachment.filename,
                url=attachment.url,
                file_type=extension(attachment.filename),
                size_bytes=attachment.size,
                **base,
            )
        )

    for position, match in enumerate(URL_PATTERN.finditer(message.content)):
        url = match.group(0).rstrip(TRAILING_PUNCTUATION)
        if not url:
            continue
        items.append(
            MediaItem(
                source_key=f"link:{message.id}:{position}",
                category="link",
                name=link_name(url),
                url=url,
                file_type=None,
                size_bytes=None,
                **base,
            )
        )
    return items
