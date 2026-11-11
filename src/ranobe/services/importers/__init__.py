"""Importing a module registers its importer."""

from ranobe.services.importers import cbz, epub, text
from ranobe.services.importers.base import (
    ImportedBook,
    ImportFailed,
    UnsupportedFormat,
    importer_for,
    supported_extensions,
)

__all__ = [
    "ImportFailed",
    "ImportedBook",
    "UnsupportedFormat",
    "cbz",
    "epub",
    "importer_for",
    "supported_extensions",
    "text",
]
