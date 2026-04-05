"""Edge dataclass and relationship type constants for the call graph."""

from __future__ import annotations

from dataclasses import dataclass

LOCAL_CALL = "LOCAL_CALL"
EXTERNAL_CALL = "EXTERNAL_CALL"
IMPORT_REL = "IMPORT"
RUNTIME_BOUNDARY = "RUNTIME_BOUNDARY"


@dataclass(frozen=True)
class Edge:
    """A directed call or import relationship between two code units."""

    src_id: str
    dst_id: str
    rel_type: str  # LOCAL_CALL | EXTERNAL_CALL | IMPORT | RUNTIME_BOUNDARY
    file: str      # source file where the call expression appears
