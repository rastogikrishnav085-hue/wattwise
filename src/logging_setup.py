"""
logging_setup.py
------------------
One place to configure logging so every module gets consistent,
timestamped output instead of scattered print() calls.
"""

from __future__ import annotations
import logging
import sys

from .config import LOG_LEVEL

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            stream=sys.stdout,
        )
        _CONFIGURED = True
    return logging.getLogger(name)
