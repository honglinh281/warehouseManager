from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env(path: str | Path = ".env") -> None:
    """Load a small, dependency-free .env file without overriding shell values."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    token: str
    prefix: str = "!"
    database_path: Path = Path("data/archive.sqlite3")
    sync_commands: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        load_env()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token or token == "replace_with_your_bot_token":
            raise RuntimeError(
                "Missing DISCORD_TOKEN. Copy .env.example to .env and add your bot token."
            )
        return cls(
            token=token,
            prefix=os.getenv("COMMAND_PREFIX", "!").strip() or "!",
            database_path=Path(os.getenv("DATABASE_PATH", "data/archive.sqlite3")),
            sync_commands=os.getenv("SYNC_COMMANDS", "false").lower()
            in {"1", "true", "yes", "on"},
        )
