"""Small local diagnostics log for the windowed Windows executable."""

import logging
from logging.handlers import RotatingFileHandler


log = logging.getLogger("ai_hub")


def configure(directory):
    if log.handlers:
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "hub.log", maxBytes=256 * 1024,
                                      backupCount=2, encoding="utf-8")
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(handler)


def failed(stage, exc):
    # Exception messages, callback arguments and CLI output can contain secrets.
    log.error("%s failed (%s)", stage, type(exc).__name__)
