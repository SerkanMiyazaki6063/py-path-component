# py-path-component

Validates that each segment of a path conforms to OS-specific rules for length, reserved names, illegal characters, and case folding before filesystem operations.

```python
from py_path_component import validate_component, validate_path

# Check a single segment
report = validate_component("CON.txt", os_name="windows")
print(report.valid)   # False
print(report.errors)  # ['component uses reserved name 'CON'']

# Check every segment of a full path
reports = validate_path("good\\CON\\bad", os_name="windows")
print([r.valid for r in reports])  # [True, False, True]
```

## Why this exists

Filesystem errors from a bad path segment tend to surface as opaque `OSError` messages long after the string was built — often inside a loop or a worker that had no context for the original input. This library checks the segment string *before* it reaches the disk, so the caller can report a precise validation failure ("reserved name", "illegal character", "too long") instead of a cryptic system error.

The trade-off: this is pure string logic. It never stats the filesystem, so it cannot tell you whether a name *collides with an existing file* — only whether the name is *legal* on the target OS. Use it as a pre-flight check, not a replacement for handling `OSError` from real I/O.

## Supported platforms

Two platforms are modelled: `windows` and `posix`. Anything else raises `ComponentError`. We deliberately do not guess: applying Windows rules to a POSIX path (or vice versa) would produce nonsense results, and a wrong default is worse than an explicit error.

## Edge cases you will hit

- **Length is measured in characters, not bytes.** POSIX filesystems enforce a 255-*byte* limit. A component full of multi-byte UTF-8 characters could pass this validator and still fail on disk. If your input is non-ASCII, re-check the byte length yourself.
- **`validate_path` splits on exactly one separator per platform** (`\` on Windows, `/` on POSIX). It does not split on both. Mixing separators silently is a common path bug, so the caller gets one predictable rule.
- **Empty segments are kept and reported as invalid**, not silently dropped. A leading `/` or a doubled separator produces an empty segment that is not a legal filename.
- **Case folding is a warning, not an error.** On Windows, `CamelCase` is valid but may collide with `camelcase`. The library reports this in `report.warnings` and leaves the decision to the caller.

## Exports

- `validate_component(component: str, os_name: str | None = None) -> ValidationReport`
- `validate_path(path: str, os_name: str | None = None) -> list[ValidationReport]`
- `ValidationReport` — frozen dataclass with fields `component`, `os_name`, `valid`, `errors`, `warnings`
- `ComponentError` — subclass of `ValueError`, raised for programmer errors (wrong type, unsupported OS) but not for bad components

## Running the tests

```
PYTHONPATH=src python -m unittest discover -s tests
```
