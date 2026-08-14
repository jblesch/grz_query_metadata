"""Survey which metadata values are actually used across GRZ submissions."""

from importlib.metadata import PackageNotFoundError, version

from .fields import BTO_ID, ENUM_FIELDS, FREETEXT_FIELDS

try:
    __version__ = version("grz_query_metadata")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"

__all__ = ["BTO_ID", "ENUM_FIELDS", "FREETEXT_FIELDS", "__version__"]
