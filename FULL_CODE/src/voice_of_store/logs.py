"""One place to configure logging for every command-line entry point."""

from __future__ import annotations

import logging
import os


def setup_logging() -> None:
    """Log to stderr; level from R5_LOG_LEVEL (default INFO). Messages never contain feedback text or secrets."""
    level = os.environ.get("R5_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
