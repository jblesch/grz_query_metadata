"""Survey which metadata values are actually used across GRZ submissions."""

import logging
from importlib.metadata import PackageNotFoundError, version

from .fields import BTO_ID, ENUM_FIELDS, FREETEXT_FIELDS

try:
    __version__ = version("grz_query_metadata")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"


class _CliFormatter(logging.Formatter):
    """Plain lines for the normal run commentary, a level prefix from
    warnings upward — CLI output, not a log file."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.levelno >= logging.WARNING:
            return f"{record.levelname.lower()}: {message}"
        return message


def setup_cli_logging() -> None:
    """Attach the CLI handler to this package's logger.

    Called by the two entry points, deliberately not at import time: importing
    the package as a library must not configure any logging. Idempotent, so
    tests may drive main() repeatedly."""
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        handler = logging.StreamHandler()  # stderr, like any diagnostic output
        handler.setFormatter(_CliFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        # propagation stays on: the root logger has no handlers in CLI use, so
        # nothing double-prints, and test/log-capture tooling keeps working.


__all__ = ["BTO_ID", "ENUM_FIELDS", "FREETEXT_FIELDS", "__version__", "setup_cli_logging"]
