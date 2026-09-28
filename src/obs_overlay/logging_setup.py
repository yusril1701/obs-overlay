"""Logging configuration.

Logs go to a rotating file under the app's data directory and, when a console
is attached, to stderr. A GUI application usually has no console on Windows,
which is exactly why the file matters: it is the only record of why something
did not work, and the control panel links to it.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from . import paths
from .constants import (
    LOG_BACKUP_COUNT,
    LOG_DATE_FORMAT,
    LOG_FILE_NAME,
    LOG_FORMAT,
    LOG_MAX_BYTES,
)

_configured = False


def log_file_path() -> Path:
    return paths.logs_dir() / LOG_FILE_NAME


def setup_logging(level: str = "INFO", console: bool | None = None) -> Path:
    """Configure the root logger. Safe to call more than once.

    Returns the log file path, or a path that does not exist if the file
    handler could not be created (a read-only install directory, say) — in
    which case logging still works, just not to disk.
    """
    global _configured

    numeric = getattr(logging, str(level).upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric)

    if _configured:
        for handler in root.handlers:
            handler.setLevel(numeric)
        return log_file_path()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    destination = log_file_path()

    try:
        paths.ensure_dirs()
        file_handler = logging.handlers.RotatingFileHandler(
            destination,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(numeric)
        root.addHandler(file_handler)
    except OSError as exc:  # pragma: no cover - depends on the filesystem
        print(f"Could not open the log file {destination}: {exc}", file=sys.stderr)

    # sys.stderr is None in a windowed (pythonw / --noconsole) build.
    if console is None:
        console = sys.stderr is not None
    if console and sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(numeric)
        root.addHandler(stream_handler)

    # Qt's own categories are noisy at DEBUG and rarely useful here.
    logging.getLogger("PyQt6").setLevel(max(numeric, logging.INFO))

    _configured = True
    return destination


def install_excepthook() -> None:
    """Route uncaught exceptions to the log instead of a silent death.

    Without this, an exception on the GUI thread of a windowed build vanishes:
    there is no console to print the traceback to.
    """
    logger = logging.getLogger("obs_overlay.crash")
    previous = sys.excepthook

    def handler(exc_type, exc_value, exc_traceback):  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
        previous(exc_type, exc_value, exc_traceback)

    sys.excepthook = handler
