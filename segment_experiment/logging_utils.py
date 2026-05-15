from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logging(log_dir: Path, run_key: str) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_key}_{datetime.utcnow():%Y%m%dT%H%M%SZ}.log"

    logger = logging.getLogger("segment_experiment")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info("Logging to %s", log_path)
    return logger


def log_section(logger: logging.Logger, title: str) -> None:
    line = "=" * 96
    logger.info("")
    logger.info(line)
    logger.info(title)
    logger.info(line)


def log_subsection(logger: logging.Logger, title: str) -> None:
    logger.info("")
    logger.info("-" * 96)
    logger.info(title)
    logger.info("-" * 96)


def log_key_values(logger: logging.Logger, title: str, values: dict[str, object]) -> None:
    log_subsection(logger, title)
    max_key_len = max((len(key) for key in values), default=0)
    for key, value in values.items():
        logger.info("%-*s : %s", max_key_len, key, value)
