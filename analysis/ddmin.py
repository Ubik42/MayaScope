"""Deterministic delta debugging for isolated failing candidate sets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, Iterable, Mapping, Optional, Sequence, Tuple


PASS = "pass"
FAIL = "fail"
UNRESOLVED = "unresolved"
OUTCOMES = frozenset({PASS, FAIL, UNRESOLVED})


class DeltaDebugError(RuntimeError):
    pass


class DeltaDebugCancelled(DeltaDebugError):
    pass


@dataclass(frozen=True)
class DeltaDebugStep:
    probe_index: int
    candidate_ids: Tuple[str, ...]
    outcome: str
    purpose: str
    granularity: int
    cached: bool = False


@dataclass(frozen=True)
class DeltaDebugResult:
    original_candidate_ids: Tuple[str, ...]
    minimal_candidate_ids: Tuple[str, ...]
    steps: Tuple[DeltaDebugStep, ...]
    complete: bool
    reason: str
    probe_count: int
    cache_hits: int


def _partitions(values: Sequence[str], count: int) -> Tuple[Tuple[str, ...], ...]:
    count = max(1, min(count, len(values)))
    quotient, remainder = divmod(len(values), count)
    result = []
    offset = 0
    for index in range(count):
        size = quotient + (1 if index < remainder else 0)
        result.append(tuple(values[offset : offset + size]))
        offset += size
    return tuple(result)


def minimize_failing_set(
    candidate_ids: Iterable[str],
    test: Callable[[Tuple[str, ...]], str],
    *,
    max_probes: int = 256,
    cancelled: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[DeltaDebugStep], None]] = None,
    known_outcomes: Optional[Mapping[FrozenSet[str], str]] = None,
) -> DeltaDebugResult:
    """Return a deterministic 1-minimal failing subset using classic ddmin.

    UNRESOLVED probes are retained in the trace but never treated as PASS or
    FAIL. The caller controls process isolation; this function only schedules
    candidate subsets and never touches a scene or filesystem.
    """
    original = tuple(candidate_ids)
    if not original or len(original) != len(set(original)):
        raise ValueError("Delta debugging candidates must be non-empty and unique")
    if max_probes < 1:
        raise ValueError("Delta debugging probe budget must be positive")
    cache: Dict[frozenset, str] = {}
    for values, outcome in (known_outcomes or {}).items():
        key = frozenset(values)
        normalized = str(outcome).lower()
        if not key.issubset(original):
            raise ValueError("Known outcome contains an unknown candidate")
        if normalized not in OUTCOMES:
            raise ValueError("Known outcome has an invalid result")
        cache[key] = normalized
    steps = []
    probe_count = 0
    cache_hits = 0

    def probe(values: Tuple[str, ...], purpose: str, granularity: int) -> str:
        nonlocal probe_count, cache_hits
        if cancelled and cancelled():
            raise DeltaDebugCancelled("Delta debugging cancelled")
        key = frozenset(values)
        if key in cache:
            outcome = cache[key]
            cache_hits += 1
            step = DeltaDebugStep(probe_count, values, outcome, purpose, granularity, True)
        else:
            if probe_count >= max_probes:
                raise DeltaDebugError("Delta debugging probe budget exhausted")
            outcome = str(test(values)).lower()
            if outcome not in OUTCOMES:
                raise DeltaDebugError("Probe returned invalid outcome: %s" % outcome)
            probe_count += 1
            cache[key] = outcome
            step = DeltaDebugStep(probe_count, values, outcome, purpose, granularity, False)
        steps.append(step)
        if progress:
            progress(step)
        return outcome

    initial = probe(original, "confirm-source-failure", 1)
    if initial != FAIL:
        return DeltaDebugResult(
            original,
            original,
            tuple(steps),
            False,
            "initial candidate set is %s, not fail" % initial,
            probe_count,
            cache_hits,
        )

    current = original
    granularity = 2
    complete = True
    reason = "1-minimal failing set"
    try:
        while len(current) >= 2:
            chunks = _partitions(current, granularity)
            reduced = False
            for chunk in chunks:
                if probe(chunk, "subset", granularity) == FAIL:
                    current = chunk
                    granularity = max(2, granularity - 1)
                    reduced = True
                    break
            if reduced:
                continue
            for chunk in chunks:
                removed = set(chunk)
                complement = tuple(value for value in current if value not in removed)
                if complement and probe(complement, "complement", granularity) == FAIL:
                    current = complement
                    granularity = max(2, granularity - 1)
                    reduced = True
                    break
            if reduced:
                continue
            if granularity >= len(current):
                break
            granularity = min(len(current), granularity * 2)
    except DeltaDebugCancelled:
        complete = False
        reason = "cancelled"
    except DeltaDebugError as exc:
        if "budget exhausted" not in str(exc):
            raise
        complete = False
        reason = "probe budget exhausted"

    return DeltaDebugResult(
        original,
        current,
        tuple(steps),
        complete,
        reason,
        probe_count,
        cache_hits,
    )
