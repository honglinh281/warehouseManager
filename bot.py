from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import discord
from discord.ext import commands

from browser import MediaBrowserView
from config import Settings
from media_index import extract_media
from storage import MediaRepository

log = logging.getLogger("archive")


class ArchiveBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.guilds = True
        super().__init__(command_prefix=settings.prefix, intents=intents, help_command=None)
        self.settings = settings
        self.media = MediaRepository(settings.database_path)

    async def setup_hook(self) -> None:
        await self.media.initialize()
        if self.settings.sync_commands:
            synced = await self.tree.sync()
            log.info("Synced %s application commands", len(synced))


def create_bot(settings: Settings) -> ArchiveBot:
    bot = ArchiveBot(settings)

    @bot.event
    async def on_ready() -> None:
        assert bot.user is not None
        log.info("Logged in as %s (%s)", bot.user, bot.user.id)

    @bot.listen("on_message")
    async def index_message(message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        await bot.media.add_many(extract_media(message))

    @bot.listen("on_raw_message_delete")
    async def remove_deleted_message(payload: discord.RawMessageDeleteEvent) -> None:
        if payload.guild_id is not None:
            await bot.media.delete_message(payload.guild_id, payload.message_id)

    @bot.hybrid_command(name="file", aliases=["files"], description="Browse files, images, and links shared in this server")
    @commands.guild_only()
    @commands.bot_has_guild_permissions(
        view_channel=True,
        send_messages=True,
        embed_links=True,
    )
    @commands.cooldown(2, 10, commands.BucketType.user)
    async def file_browser(ctx: commands.Context[ArchiveBot]) -> None:
        assert ctx.guild is not None
        assert isinstance(ctx.author, discord.Member)
        visible_channels = {
            channel.id
            for channel in [*ctx.guild.text_channels, *ctx.guild.threads]
            if channel.permissions_for(ctx.author).view_channel
        }
        view = await MediaBrowserView.create(
            bot.media, ctx.guild.id, ctx.author.id, visible_channels
        )
        embed = await view.build_embed()
        await view.rebuild_filters()
        view.message = await ctx.send(embed=embed, view=view)

    @bot.command(name="filescan")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(
        view_channel=True,
        send_messages=True,
        embed_links=True,
        read_message_history=True,
    )
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def file_scan(ctx: commands.Context[ArchiveBot], limit: int = 500) -> None:
        """Backfill media from existing channel history. Requires Manage Server."""
        assert ctx.guild is not None
        limit = max(1, min(limit, 5000))
        status = await ctx.send(f"🔎 Scanning up to {limit:,} messages per channel…")
        scanned = indexed = skipped = 0

        for channel in ctx.guild.text_channels:
            try:
                async for message in channel.history(limit=limit, oldest_first=True):
                    scanned += 1
                    if message.author.bot:
                        continue
                    indexed += await bot.media.add_many(extract_media(message))
            except (discord.Forbidden, discord.HTTPException):
                skipped += 1
                log.warning("Could not scan #%s in %s", channel.name, ctx.guild.name)

        await status.edit(
            content=(
                f"✅ Scan complete — checked **{scanned:,}** messages and indexed "
                f"**{indexed:,}** new media items."
                + (f" Skipped **{skipped}** inaccessible channels." if skipped else "")
            )
        )

    @bot.command(name="filehelp")
    async def file_help(ctx: commands.Context[ArchiveBot]) -> None:
        embed = discord.Embed(
            title="Archive bot commands",
            color=discord.Color.from_rgb(102, 87, 223),
            description=(
                "`!file` — open your interactive media browser\n"
                "`!filescan [limit]` — index older messages (Manage Server required)\n"
                "`!filehelp` — show this help"
            ),
        )
        await ctx.send(embed=embed)

    @bot.event
    async def on_command_error(ctx: commands.Context[ArchiveBot], error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send("This command can only be used inside a server.")
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You need the **Manage Server** permission to run this command.")
            return
        if isinstance(error, commands.BotMissingPermissions):
            labels = {
                "view_channel": "View Channels",
                "send_messages": "Send Messages",
                "embed_links": "Embed Links",
                "read_message_history": "Read Message History",
            }
            missing = ", ".join(labels.get(item, item) for item in error.missing_permissions)
            await ctx.send(
                f"I am missing these permissions in this channel: **{missing}**. "
                "Update the bot role or channel permissions, then try again."
            )
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Please wait {error.retry_after:.1f}s and try again.")
            return
        original = getattr(error, "original", error)
        log.error(
            "Command %s failed: %s",
            getattr(ctx.command, "qualified_name", "unknown"),
            original,
            exc_info=(type(original), original, original.__traceback__),
        )
        try:
            await ctx.send(
                "Something went wrong while processing that command. "
                "The detailed error was saved to `logs/archive.log`."
            )
        except discord.HTTPException:
            log.error("Could not send the error message; check bot channel permissions")

    return bot


def main() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        log_dir / "archive.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[console, file_handler],
    )
    settings = Settings.from_env()
    create_bot(settings).run(settings.token, log_handler=None)


if __name__ == "__main__":
    main()
