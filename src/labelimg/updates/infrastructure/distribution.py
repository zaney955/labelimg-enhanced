"""Identify how the running application was distributed."""

from enum import Enum
import json
from pathlib import Path
import sys


MANAGED_INSTALL_MARKER = "managed-install.json"


class DistributionStrategy(Enum):
    PYTHON = "python"
    PORTABLE_FROZEN = "portable-frozen"
    MANAGED_WINDOWS = "managed-windows"


def detect_distribution_strategy(
    *, frozen=None, executable=None, platform_name=None
):
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    platform_name = sys.platform if platform_name is None else str(platform_name)
    if not frozen:
        return DistributionStrategy.PYTHON
    if platform_name != "win32":
        return DistributionStrategy.PORTABLE_FROZEN
    executable = Path(sys.executable if executable is None else executable)
    marker = executable.resolve().parent / MANAGED_INSTALL_MARKER
    try:
        identity = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return DistributionStrategy.PORTABLE_FROZEN
    if identity != {"installer": "inno", "scope": "current-user"}:
        return DistributionStrategy.PORTABLE_FROZEN
    return DistributionStrategy.MANAGED_WINDOWS
