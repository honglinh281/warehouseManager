# Archive — Discord media manager bot

Archive indexes files, images, and links shared in a Discord server and makes them searchable through a native Discord interface.

## Features

- `!file` opens an interactive media browser
- Files, Images, and Links tabs
- Sender, date, and file-type filters
- Search modal for names and URLs
- Newest-first pagination
- Automatic indexing for new messages
- SQLite storage with duplicate protection
- `!filescan` backfills media from older messages
- Deleted messages are removed from the index
- Results respect the requesting member's channel visibility permissions

## Setup

1. Create an application and bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. In **Bot → Privileged Gateway Intents**, enable **Message Content Intent**.
3. Invite the bot with these permissions:
   - View Channels
   - Send Messages
   - Embed Links
   - Read Message History
4. Install and configure the project:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

5. Put the token in `.env`, then run:

```bash
python3 bot.py
```

## First use

New media is indexed automatically. To include existing media, a server manager should run:

```text
!filescan 1000
```

Then any member can run:

```text
!file
```

Runtime and command errors are written to `logs/archive.log`. If `!file` reports
missing permissions, update the bot role or the current channel overrides to allow
View Channels, Send Messages, Embed Links, and Read Message History.

Discord does not allow bots to render arbitrary Figma/HTML interfaces inside a message. This implementation translates the design into native embeds, buttons, dropdowns, and modals so it works directly in Discord desktop and mobile.
