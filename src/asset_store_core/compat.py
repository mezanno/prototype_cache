"""Python 3.10 compatibility shims (project targets 3.12+)."""

from __future__ import annotations

import sys
from enum import Enum

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:

    class StrEnum(str, Enum):
        """Minimal backport of :class:`enum.StrEnum`."""
