"""Bounded local sequence inspection for Maya-managed external paths.

The scanner is intentionally independent from Maya.  It never walks child
directories and refuses network/environment paths so a scene capture cannot
turn into an unbounded filesystem crawl on the host UI thread.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from time import perf_counter
from typing import Optional, Tuple


@dataclass(frozen=True)
class SequenceInventory:
    kind: str = ""
    member_count: int = 0
    expected_count: Optional[int] = None
    missing_count: Optional[int] = None
    missing_samples: Tuple[str, ...] = ()
    scan_complete: bool = False
    scan_reason: str = "not-sequence"


def _matcher(filename: str, token: str):
    lowered = token.casefold()
    position = filename.casefold().find(lowered)
    if position < 0:
        return "", None, None
    prefix = re.escape(filename[:position])
    suffix = re.escape(filename[position + len(token):])
    formatter = None
    if lowered == "<udim>":
        kind, member = "udim", r"(?P<member>[1-9]\d{3})"
    elif lowered == "<uvtile>":
        kind, member = "uvtile", r"(?P<member>u\d+_v\d+)"
    elif token.startswith("#"):
        width = len(token)
        kind, member = "frame", r"(?P<member>-?\d{%s})" % width
        formatter = lambda value, width=width: ("-%0*d" if value < 0 else "%0*d") % (
            width, abs(value)
        )
    elif lowered.startswith("%0") and lowered.endswith("d"):
        try:
            width = int(lowered[2:-1])
        except ValueError:
            return "", None, None
        kind, member = "frame", r"(?P<member>-?\d{%s})" % width
        formatter = lambda value, width=width: ("-%0*d" if value < 0 else "%0*d") % (
            width, abs(value)
        )
    elif lowered == "<f>":
        kind, member = "frame", r"(?P<member>-?\d+)"
        formatter = str
    else:
        return "", None, None
    return kind, re.compile(r"^%s%s%s$" % (prefix, member, suffix), re.IGNORECASE), formatter


def inspect_local_sequence(
    resolved_pattern: str,
    token: str,
    *,
    path_kind: str,
    max_entries: int = 10_000,
    max_seconds: float = 0.05,
    sample_limit: int = 12,
) -> SequenceInventory:
    """Inspect one flat local directory with explicit entry/time budgets."""

    if not token:
        return SequenceInventory()
    if path_kind == "network":
        return SequenceInventory(scan_reason="network-path")
    if path_kind == "environment":
        return SequenceInventory(scan_reason="unexpanded-environment")
    directory, filename = os.path.split(os.path.normpath(resolved_pattern))
    kind, matcher, formatter = _matcher(filename, token)
    if not kind or matcher is None:
        return SequenceInventory(scan_reason="unsupported-pattern")
    if not directory:
        return SequenceInventory(kind=kind, scan_reason="missing-directory")

    values = set()
    checked = 0
    deadline = perf_counter() + max(0.0, max_seconds)
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                checked += 1
                if checked > max_entries:
                    return SequenceInventory(
                        kind, len(values), scan_reason="entry-budget-exceeded"
                    )
                if checked % 64 == 0 and perf_counter() > deadline:
                    return SequenceInventory(
                        kind, len(values), scan_reason="time-budget-exceeded"
                    )
                if not entry.is_file(follow_symlinks=False):
                    continue
                match = matcher.match(entry.name)
                if not match:
                    continue
                value = match.group("member")
                values.add(int(value) if kind in {"frame", "udim"} else value.casefold())
    except FileNotFoundError:
        values = set()
    except OSError:
        return SequenceInventory(kind, scan_reason="filesystem-error")

    if kind != "frame":
        return SequenceInventory(kind, len(values), scan_complete=True, scan_reason="complete")
    if not values:
        return SequenceInventory(kind, 0, 0, 0, (), True, "complete")
    first, last = min(values), max(values)
    expected_count = last - first + 1
    missing_count = expected_count - len(values)
    missing_samples = []
    if missing_count:
        for value in range(first, last + 1):
            if value not in values:
                missing_samples.append(formatter(value) if formatter else str(value))
                if len(missing_samples) >= sample_limit:
                    break
    return SequenceInventory(
        kind,
        len(values),
        expected_count,
        missing_count,
        tuple(missing_samples),
        True,
        "complete",
    )
