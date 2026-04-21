#!/usr/bin/env python3
"""
Unified logging for video-expert-analyzer-vnext.

Usage:
    from logger import get_logger
    log = get_logger("pipeline")

    log.info("下载完成: %s", filename)
    log.warning("转录失败，使用空文本")
    log.debug("帧数=%d, 场景=%d", frames, scenes)

The logger writes to stderr by default (visible in terminal).
Set VE_LOG_LEVEL=DEBUG / VE_LOG_FILE=path/to.log in environment to customize.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_root_initialized = False


def _ensure_root() -> None:
    global _root_initialized
    if _root_initialized:
        return
    _root_initialized = True

    level_name = os.environ.get("VE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]

    log_file = os.environ.get("VE_LOG_FILE")
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(level=level, format=_FORMAT, datefmt=_DATE_FORMAT, handlers=handlers)


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the 'vea' namespace.

    Example: get_logger("pipeline") -> 'vea.pipeline'
    """
    _ensure_root()
    return logging.getLogger(f"vea.{name}")
