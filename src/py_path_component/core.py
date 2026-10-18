"""OS-aware validation of individual path segments.

The filesystem is a hostile place: segment length limits, reserved device
names, illegal characters, and case-fold collisions can all turn a perfectly
reasonable-looking string into an error *after* it hits the disk. This module
checks a segment string before that happens, so the caller can surface a clear
validation error instead of a cryptic ``OSError`` from the operating system.

Design choices
--------------

* **Per-segment, never the whole path.** ``validate_path`` splits on the OS
  separator but each segment is validated independently. We never try to
  ``stat`` or otherwise touch the filesystem — this is pure string logic, so
  it is deterministic and side-effect-free.

* **Two platforms only: Windows and POSIX.** Mapping every exotic filesystem
  would balloon the surface area. These two cover the systems where the vast
  majority of path-component bugs actually occur. Unknown platforms are
  rejected explicitly rather than guessed at.

* **Windows reserved names are treated as a hard error.** On Windows, creating
  a file literally named ``CON.txt`` succeeds at the Win32 API level but is
  then invisible to most tools and unopenable by many. We fail early.

* **POSIX allows almost everything except ``/`` and NUL.** We honour that:
  only those two bytes are illegal. POSIX does not reserve any names by
  convention, so the reserved-name list for POSIX is empty.

* **Folding is reported, not silently rewritten.** On case-insensitive
  systems two segments that differ only in case will collide on disk. Rather
  than silently lowercasing the caller's string — which would hide intent — we
  return a warning in the report. The caller decides what to do.

* **Length limits are conservative and integer-only.** We never compare floats
  and we never touch wall-clock time; everything is a pure function of its
  inputs, so tests are deterministic.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Windows forbids these exact characters in path components. They come from the
# Win32 file naming rules; backslash is excluded because we split on separators
# first, so a component never contains one by construction.
_WIN_ILLEGAL_CHARS: str = '<>:"|?*'

# Reserved base names on Windows. These match with or without an extension and
# are case-insensitive. A segment named ``CON`` or ``CON.txt`` or ``LPT1.log``
# is invisible/blocked by most Win32 tools.
_WIN_RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
)

# Conservative component length ceiling. NTFS allows 255 characters; most
# POSIX filesystems allow 255 *bytes*. Using 255 keeps us inside both.
_MAX_COMPONENT_LENGTH: int = 255

# Characters whose presence in a path component is illegal regardless of OS.
# The NUL byte terminates C strings and is forbidden essentially everywhere.
_UNIVERSAL_ILLEGAL: str = "\x00"


class ComponentError(ValueError):
    """Raised when a path component violates OS naming rules.

    Subclassing ``ValueError`` so callers who already catch ``ValueError`` for
    bad input keep working, while those who want specificity can catch this.
    """


@dataclass(frozen=True)
class ValidationReport:
    """Result of validating a single path component.

    A valid component has ``valid is True`` and empty ``errors``. ``warnings``
    may still be populated (e.g. a case-folding notice on a case-insensitive
    OS) — warnings never block validation, they merely inform.
    """

    component: str
    os_name: str
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _detect_os_name() -> str:
    """Map ``sys.platform`` to one of our supported platform keys.

    We collapse the various Windows platform strings (``win32``, ``cygwin``)
    onto ``'windows'`` and everything else that looks Unix-ish onto
    ``'posix'``. Anything we cannot classify raises rather than silently
    defaulting — a wrong default here would mean applying the wrong rules.
    """
    p = sys.platform
    if p.startswith("win") or p == "cygwin":
        return "windows"
    if p.startswith("linux") or p.startswith("darwin") or p == "posix":
        return "posix"
    raise ComponentError(f"Unsupported platform: {p!r}")


def _strip_extension(name: str) -> str:
    """Return ``name`` with a single trailing extension removed.

    Windows reserved-name matching is against the *base*, so ``CON.txt`` is
    still reserved. We strip at most one dot so ``file.tar.gz`` keeps ``.tar``
    — that is enough because the reserved list never contains a dot.
    """
    idx = name.rfind(".")
    if idx <= 0:  # hidden file (leading dot) or no dot at all
        return name
    return name[:idx]


def validate_component(component: str, os_name: str | None = None) -> ValidationReport:
    """Validate a single path component for the given or current OS.

    Parameters
    ----------
    component:
        The segment string to check. Must not contain a path separator —
        separators are the caller's responsibility (see :func:`validate_path`).
    os_name:
        ``'windows'`` or ``'posix'``. If omitted, the current platform is
        detected via :func:`_detect_os_name`.

    Returns
    -------
    ValidationReport
        Always returns a report; never raises for a *bad component* (that is
        encoded in ``valid``/``errors``). Raises :class:`ComponentError` only
        for programmer errors: wrong type, unsupported OS.
    """
    if not isinstance(component, str):
        raise ComponentError("component must be a string")
    if os_name is None:
        os_name = _detect_os_name()
    if os_name not in ("windows", "posix"):
        raise ComponentError(f"Unsupported os_name: {os_name!r}")

    errors: List[str] = []
    warnings: List[str] = []

    # Universal checks ------------------------------------------------------
    if component == "":
        errors.append("component is empty")
    if any(ch in _UNIVERSAL_ILLEGAL for ch in component):
        errors.append("component contains NUL byte")

    # Length check uses character count. On POSIX this is conservative when
    # the string contains multi-byte UTF-8 (filesystems count bytes, not
    # characters); we document that and let callers re-check byte length if
    # they know their locale is non-ASCII.
    if len(component) > _MAX_COMPONENT_LENGTH:
        errors.append(
            f"component exceeds {_MAX_COMPONENT_LENGTH} characters "
            f"(got {len(component)})"
        )

    # Platform-specific checks ---------------------------------------------
    if os_name == "windows":
        illegal = [c for c in _WIN_ILLEGAL_CHARS if c in component]
        if illegal:
            errors.append(
                "component contains illegal characters: "
                + ", ".join(repr(c) for c in illegal)
            )
        # Control characters 0x01–0x1f are forbidden by Win32.
        ctrl = [c for c in component if 0 < ord(c) < 32]
        if ctrl:
            errors.append(
                f"component contains {len(ctrl)} control character(s)"
            )
        if component.endswith(" ") or component.endswith("."):
            errors.append("component ends with space or dot (disallowed on Windows)")
        base = _strip_extension(component).upper()
        if base in _WIN_RESERVED_NAMES:
            errors.append(f"component uses reserved name {base!r}")
        # Case folding: warn, do not rewrite.
        if component != component.lower():
            warnings.append(
                "Windows filenames are case-insensitive; "
                "this component may collide with a lowercase variant"
            )

    elif os_name == "posix":
        # Only '/' and NUL are illegal. '/' would already be a separator and
        # thus absent from a well-split segment, but checking defends callers
        # who pass a raw string.
        if "/" in component:
            errors.append("component contains '/' (path separator)")

    return ValidationReport(
        component=component,
        os_name=os_name,
        valid=(len(errors) == 0),
        errors=errors,
        warnings=warnings,
    )


def validate_path(path: str, os_name: str | None = None) -> List[ValidationReport]:
    """Split ``path`` on the OS separator and validate each segment.

    The OS separator is chosen by :func:`os.sep` for the *target* platform
    when ``os_name`` is given, otherwise the running platform's. On POSIX this
    is ``'/'``; on Windows it is ``'\\'``. We deliberately do not split on
    both — mixing separators silently is a common source of path bugs, so the
    caller gets exactly one split rule per platform.

    Empty segments (e.g. from a leading ``/`` or doubled separators) are kept
    and will be reported as invalid by :func:`validate_component`, because an
    empty component is not a valid filename on either platform.
    """
    if not isinstance(path, str):
        raise ComponentError("path must be a string")
    if os_name is None:
        os_name = _detect_os_name()
    sep = "\\" if os_name == "windows" else "/"
    return [validate_component(seg, os_name=os_name) for seg in path.split(sep)]
