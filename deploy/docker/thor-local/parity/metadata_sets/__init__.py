"""Static, fail-closed Thor metadata-set selection."""

from .resolver import MetadataSetError, MetadataSnapshot, resolve_metadata_set

__all__ = ["MetadataSetError", "MetadataSnapshot", "resolve_metadata_set"]
