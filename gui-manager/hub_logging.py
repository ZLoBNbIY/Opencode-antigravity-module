"""Small local diagnostics log for the windowed Windows executable."""

import logging
from logging.handlers import RotatingFileHandler
import os


log = logging.getLogger("ai_hub")


def configure(directory):
    if log.handlers:
        return
    handler = None
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(directory, 0o700)
        log_file = directory / "hub.log"
        handler = RotatingFileHandler(log_file, maxBytes=256 * 1024,
                                      backupCount=2, encoding="utf-8")
        if os.name != "nt":
            os.chmod(log_file, 0o600)
    except OSError:
        if handler is not None:
            handler.close()
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(handler)


def failed(stage, exc):
    # Exception messages, callback arguments and CLI output can contain secrets.
    log.error("%s failed (%s)", stage, type(exc).__name__)
