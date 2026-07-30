from __future__ import annotations

from pathlib import Path

import httpx


def send_documents_to_telegram(
    bot_token: str,
    chat_id: int,
    documents: list[tuple[Path, str | None]],
) -> None:
    if not bot_token:
        raise RuntimeError("Telegram bot token is empty.")
    if not chat_id:
        raise RuntimeError("Telegram export chat id is empty.")

    with httpx.Client(timeout=120) as client:
        for path, caption in documents:
            with path.open("rb") as file:
                data: dict[str, str | int] = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                response = client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendDocument",
                    data=data,
                    files={"document": (path.name, file, "application/octet-stream")},
                )
            response.raise_for_status()
