from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord

from storage import Category, MediaItem, MediaRepository

PAGE_SIZE = 5
log = logging.getLogger("archive.browser")
CATEGORY_META = {
    "file": ("Files", "📄", "Documents and files shared in this server"),
    "image": ("Images", "🖼️", "Images shared in this server"),
    "link": ("Links", "🔗", "Links and resources shared in this server"),
}


@dataclass
class BrowserState:
    category: Category = "file"
    sender_id: int | None = None
    date_range: str = "all"
    file_type: str | None = None
    search: str | None = None
    page: int = 0


def human_size(value: int | None) -> str:
    if value is None:
        return ""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            precision = 0 if unit == "B" else 1
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    return f"{value} B"


def escape_markdown(text: str) -> str:
    return discord.utils.escape_markdown(text).replace("]", "\\]")


class SearchModal(discord.ui.Modal, title="Search media"):
    query = discord.ui.TextInput(
        label="Name or URL",
        placeholder="e.g. roadmap, invoice, figma.com",
        required=False,
        max_length=100,
    )

    def __init__(self, browser: "MediaBrowserView") -> None:
        super().__init__()
        self.browser = browser
        self.query.default = browser.state.search or ""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.browser.state.search = self.query.value.strip() or None
        self.browser.state.page = 0
        await interaction.response.defer()
        await self.browser.refresh_message()


class CategoryButton(discord.ui.Button["MediaBrowserView"]):
    def __init__(self, category: Category, count: int) -> None:
        title, emoji, _ = CATEGORY_META[category]
        super().__init__(label=f"{title} · {count}", emoji=emoji, row=0)
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        browser = self.view
        browser.state.category = self.category
        browser.state.sender_id = None
        browser.state.file_type = None
        browser.state.page = 0
        await browser.rebuild_filters()
        await browser.respond(interaction)


class SenderSelect(discord.ui.Select["MediaBrowserView"]):
    def __init__(self, senders: list[tuple[int, str, int]], selected: int | None) -> None:
        options = [discord.SelectOption(label="Anyone", value="all", default=selected is None)]
        options.extend(
            discord.SelectOption(
                label=name[:100], value=str(author_id), description=f"{total} items",
                default=selected == author_id,
            )
            for author_id, name, total in senders
        )
        super().__init__(placeholder="Filter by sender", options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.state.sender_id = None if self.values[0] == "all" else int(self.values[0])
        self.view.state.page = 0
        await self.view.respond(interaction)


class DateSelect(discord.ui.Select["MediaBrowserView"]):
    def __init__(self, selected: str) -> None:
        choices = [("Any time", "all"), ("Today", "today"), ("Last 7 days", "week"), ("Last 30 days", "month")]
        super().__init__(
            placeholder="Filter by date",
            options=[discord.SelectOption(label=label, value=value, default=selected == value) for label, value in choices],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.state.date_range = self.values[0]
        self.view.state.page = 0
        await self.view.respond(interaction)


class FileTypeSelect(discord.ui.Select["MediaBrowserView"]):
    def __init__(self, types: list[tuple[str, int]], selected: str | None, enabled: bool) -> None:
        options = [discord.SelectOption(label="All file types", value="all", default=selected is None)]
        options.extend(
            discord.SelectOption(label=file_type.upper(), value=file_type, description=f"{total} files", default=selected == file_type)
            for file_type, total in types
        )
        if not enabled:
            options = [discord.SelectOption(label="File type filter · Files only", value="all")]
        super().__init__(placeholder="Filter by file type", options=options, row=3, disabled=not enabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.state.file_type = None if self.values[0] == "all" else self.values[0]
        self.view.state.page = 0
        await self.view.respond(interaction)


class ActionButton(discord.ui.Button["MediaBrowserView"]):
    def __init__(self, action: str, *, label: str | None = None, emoji: str | None = None, disabled: bool = False) -> None:
        super().__init__(label=label, emoji=emoji, row=4, disabled=disabled, style=discord.ButtonStyle.secondary)
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        browser = self.view
        if self.action == "search":
            await interaction.response.send_modal(SearchModal(browser))
            return
        if self.action == "reset":
            category = browser.state.category
            browser.state = BrowserState(category=category)
            await browser.rebuild_filters()
        elif self.action == "previous":
            browser.state.page = max(0, browser.state.page - 1)
        elif self.action == "next":
            browser.state.page += 1
        await browser.respond(interaction)


class MediaBrowserView(discord.ui.View):
    def __init__(
        self,
        repository: MediaRepository,
        guild_id: int,
        owner_id: int,
        channel_ids: set[int],
    ) -> None:
        super().__init__(timeout=300)
        self.repository = repository
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.channel_ids = channel_ids
        self.state = BrowserState()
        self.message: discord.Message | None = None
        self.total = 0

    @classmethod
    async def create(
        cls,
        repository: MediaRepository,
        guild_id: int,
        owner_id: int,
        channel_ids: set[int],
    ) -> "MediaBrowserView":
        view = cls(repository, guild_id, owner_id, channel_ids)
        await view.rebuild_filters()
        return view

    async def rebuild_filters(self) -> None:
        self.clear_items()
        counts = await self.repository.counts(self.guild_id, self.channel_ids)
        for category in ("file", "image", "link"):
            button = CategoryButton(category, counts.get(category, 0))
            button.style = discord.ButtonStyle.primary if category == self.state.category else discord.ButtonStyle.secondary
            self.add_item(button)

        senders = await self.repository.senders(
            self.guild_id, self.state.category, self.channel_ids
        )
        file_types = await self.repository.file_types(self.guild_id, self.channel_ids)
        self.add_item(SenderSelect(senders, self.state.sender_id))
        self.add_item(DateSelect(self.state.date_range))
        self.add_item(FileTypeSelect(file_types, self.state.file_type, self.state.category == "file"))
        self.add_item(ActionButton("search", label="Search", emoji="🔎"))
        self.add_item(ActionButton("reset", label="Reset", emoji="🔄"))
        self.add_item(ActionButton("previous", label="Previous", disabled=self.state.page == 0))
        self.add_item(ActionButton("next", label="Next", disabled=(self.state.page + 1) * PAGE_SIZE >= self.total if self.total else True))

    def after_date(self) -> datetime | None:
        now = datetime.now(timezone.utc)
        return {
            "today": now - timedelta(days=1),
            "week": now - timedelta(days=7),
            "month": now - timedelta(days=30),
        }.get(self.state.date_range)

    async def media_page(self):
        result = await self.repository.query(
            self.guild_id,
            self.state.category,
            channel_ids=self.channel_ids,
            sender_id=self.state.sender_id,
            after=self.after_date(),
            file_type=self.state.file_type,
            search=self.state.search,
            limit=PAGE_SIZE,
            offset=self.state.page * PAGE_SIZE,
        )
        if not result.items and self.state.page > 0:
            self.state.page = max(0, math.ceil(result.total / PAGE_SIZE) - 1)
            return await self.media_page()
        self.total = result.total
        return result

    async def build_embed(self) -> discord.Embed:
        page = await self.media_page()
        title, emoji, description = CATEGORY_META[self.state.category]
        embed = discord.Embed(
            title=f"{emoji}  Media Archive · {title}",
            description=description,
            color=discord.Color.from_rgb(102, 87, 223),
            timestamp=datetime.now(timezone.utc),
        )

        filters = []
        if self.state.sender_id:
            filters.append(f"from <@{self.state.sender_id}>")
        if self.state.date_range != "all":
            filters.append(self.state.date_range)
        if self.state.file_type:
            filters.append(self.state.file_type.upper())
        if self.state.search:
            filters.append(f'“{escape_markdown(self.state.search)}”')
        if filters:
            embed.description += "\n**Filters:** " + " · ".join(filters)

        if not page.items:
            embed.add_field(
                name="No media found",
                value="Try another tab, change the filters, or run `!filescan` to index older messages.",
                inline=False,
            )
        else:
            for number, item in enumerate(page.items, start=self.state.page * PAGE_SIZE + 1):
                embed.add_field(
                    name=f"{number}. {self.item_icon(item)} {escape_markdown(item.name)[:220]}",
                    value=self.item_details(item),
                    inline=False,
                )
            if self.state.category == "image":
                embed.set_thumbnail(url=page.items[0].url)

        total_pages = max(1, math.ceil(page.total / PAGE_SIZE))
        embed.set_footer(text=f"{page.total} results  •  Page {self.state.page + 1}/{total_pages}  •  Newest first")
        return embed

    @staticmethod
    def item_icon(item: MediaItem) -> str:
        if item.category == "image":
            return "🖼️"
        if item.category == "link":
            return "🔗"
        icons = {"pdf": "📕", "doc": "📘", "docx": "📘", "xls": "📗", "xlsx": "📗", "zip": "🗜️", "txt": "📝"}
        return icons.get(item.file_type or "", "📄")

    @staticmethod
    def item_details(item: MediaItem) -> str:
        timestamp = int(item.sent_at.timestamp())
        size = f" · {human_size(item.size_bytes)}" if item.size_bytes is not None else ""
        file_type = f" · {(item.file_type or '').upper()}" if item.category != "link" and item.file_type else ""
        return (
            f"[Open media]({item.url}) · [Original message]({item.jump_url})\n"
            f"<@{item.author_id}> in <#{item.channel_id}>{file_type}{size} · <t:{timestamp}:R>"
        )

    async def respond(self, interaction: discord.Interaction) -> None:
        embed = await self.build_embed()
        await self.rebuild_filters()
        await interaction.response.edit_message(embed=embed, view=self)

    async def refresh_message(self) -> None:
        if self.message is None:
            return
        embed = await self.build_embed()
        await self.rebuild_filters()
        await self.message.edit(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "This media browser belongs to another user. Run `!file` to open your own.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        log.error(
            "Media browser interaction failed for %s: %s",
            type(item).__name__,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "This interaction failed. The error was saved to `logs/archive.log`.",
                ephemeral=True,
            )
