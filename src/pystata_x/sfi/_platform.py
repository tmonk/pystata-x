"""Platform detection for pystata-x SFI dispatch.

Provides a single source of truth for platform identification,
replacing scattered sys.platform/arch checks across the codebase.
No runtime dependencies on _engine or _core — safe to import anywhere.
"""
import sys
import platform as _sys_platform

# ── Architecture detection ────────────────────────────────────
_ARCH = _sys_platform.machine().lower()

IS_X86_64 = (
    sys.platform in ("linux", "linux2") and _ARCH in ("x86_64", "amd64")
)
IS_ARM64 = (
    sys.platform == "darwin" and _ARCH in ("arm64", "aarch64")
)
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform in ("linux", "linux2")
IS_MACOS = sys.platform == "darwin"

# Human-readable platform identifier
PLATFORM_NAME = (
    "x86_64-linux" if IS_X86_64
    else "arm64-darwin" if IS_ARM64
    else "windows-amd64" if (IS_WINDOWS and _ARCH in ("x86_64", "amd64"))
    else "unknown"
)
