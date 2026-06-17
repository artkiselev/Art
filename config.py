from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent


def load_env(path: Path = ROOT_DIR / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    result_email: str
    yandex_smtp_login: str
    yandex_smtp_app_password: str
    export_chat_id: int | None
    database_path: Path
    output_dir: Path


def get_settings() -> Settings:
    load_env()
    output_dir = ROOT_DIR / os.getenv("OUTPUT_DIR", "outputs")
    database_path = ROOT_DIR / os.getenv("DATABASE_PATH", "data/wedding_bot.sqlite3")
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        result_email=os.getenv("RESULT_EMAIL", "mkshow@yandex.ru"),
        yandex_smtp_login=os.getenv("YANDEX_SMTP_LOGIN", "mkshow@yandex.ru"),
        yandex_smtp_app_password=os.getenv("YANDEX_SMTP_APP_PASSWORD", ""),
        export_chat_id=_get_optional_int("EXPORT_CHAT_ID"),
        database_path=database_path,
        output_dir=output_dir,
    )


def _get_optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    return int(value)
