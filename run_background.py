from __future__ import annotations

import logging
import sys
from pathlib import Path

from bot import main


def configure_file_logging() -> None:
    data_dir = Path(__file__).resolve().parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "bot.log"
    logging.basicConfig(
        filename=log_path,
        filemode="a",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
        force=True,
    )
    sys.stdout = log_path.open("a", encoding="utf-8")
    sys.stderr = sys.stdout


if __name__ == "__main__":
    configure_file_logging()
    try:
        main()
    except Exception:
        logging.exception("Bot stopped with an unhandled exception")
        raise
