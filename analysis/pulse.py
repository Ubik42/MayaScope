"""Parser and analysis primitives for Maya Profiler Pulse captures."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from ..model import ProfilerCapture, ProfilerCategory, ProfilerEvent, SceneSnapshot


class ProfilerParseError(ValueError):
    pass


def _split_tabs(line: str) -> Tuple[str, ...]:
    return tuple(part for part in line.rstrip("\r\n").split("\t") if part != "")


def _node_name_index(snapshot: Optional[SceneSnapshot]) -> Mapping[str, str]:
    if snapshot is None:
        return {}
    candidates: Dict[str, set] = defaultdict(set)
    for node in snapshot.nodes:
        candidates[node.name].add(node.id)
        for path in node.dag_paths:
            candidates[path].add(node.id)
            candidates[path.rsplit("|", 1)[-1]].add(node.id)
    return {
        name: next(iter(node_ids))
        for name, node_ids in candidates.items()
        if len(node_ids) == 1
    }


def parse_maya_profiler_output(
    text: str,
    snapshot: Optional[SceneSnapshot] = None,
    *,
    source_scene: str = "",
    maya_version: str = "",
) -> ProfilerCapture:
    """Parse Maya profiler output format v2 into a versioned capture."""
    lines = text.splitlines()
    if len(lines) < 7 or not lines[0].startswith("#File Version"):
        raise ProfilerParseError("Missing Maya profiler file header")
    header = _split_tabs(lines[1])
    if len(header) < 3:
        raise ProfilerParseError("Malformed Maya profiler header")
    try:
        file_version, declared_events, cpu_count = map(int, header[:3])
    except ValueError as exc:
        raise ProfilerParseError("Non-numeric Maya profiler header") from exc
    if file_version != 2:
        raise ProfilerParseError("Unsupported Maya profiler file version: %s" % file_version)

    category_names = _split_tabs(lines[2])
    category_descriptions = _split_tabs(lines[3])
    categories = tuple(
        ProfilerCategory(
            index=index,
            name=name,
            description=category_descriptions[index] if index < len(category_descriptions) else "",
        )
        for index, name in enumerate(category_names)
    )

    try:
        mapping_start = next(
            index for index in range(4, len(lines)) if lines[index].startswith("#Comment mapping")
        )
        mapping_end = next(
            index
            for index in range(mapping_start + 1, len(lines))
            if lines[index].startswith("#Comment mapping")
        )
        event_header = mapping_end + 1
    except StopIteration as exc:
        raise ProfilerParseError("Missing Maya profiler comment mapping") from exc
    if event_header >= len(lines) or not lines[event_header].startswith("#Event time"):
        raise ProfilerParseError("Missing Maya profiler event header")

    comments = {}
    for line in lines[mapping_start + 1 : mapping_end]:
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        comments[key.strip()] = "" if value == "(null)" else value

    event_lines = []
    for line in lines[event_header + 1 :]:
        if line.startswith("#"):
            break
        event_lines.append(line)
    if len(event_lines) != declared_events:
        raise ProfilerParseError(
            "Profiler event count mismatch: declared %s, found %s"
            % (declared_events, len(event_lines))
        )

    description_start = event_header + 1 + len(event_lines)
    descriptions = {}
    if description_start < len(lines) and lines[description_start].startswith(
        "#Begin comment description mapping"
    ):
        for line in lines[description_start + 1 :]:
            if line.startswith("#Begin comment description mapping"):
                break
            if " = " in line:
                key, value = line.split(" = ", 1)
                descriptions[key.strip()] = value

    raw_rows = []
    for index, line in enumerate(event_lines):
        fields = _split_tabs(line)
        if len(fields) != 9:
            raise ProfilerParseError("Malformed profiler event row %s" % index)
        try:
            raw_rows.append(
                (
                    int(fields[0]),
                    fields[1],
                    fields[2],
                    int(fields[3]),
                    int(fields[4]),
                    int(fields[5]),
                    int(fields[6]),
                    int(fields[7]),
                    int(fields[8]),
                )
            )
        except ValueError as exc:
            raise ProfilerParseError("Non-numeric profiler event row %s" % index) from exc

    origin = min((row[0] for row in raw_rows), default=0)
    names = _node_name_index(snapshot)
    events = []
    for index, row in enumerate(raw_rows):
        (
            raw_start,
            comment_key,
            extra_key,
            category_index,
            duration,
            thread_duration,
            thread_id,
            cpu_id,
            color_id,
        ) = row
        name = comments.get(comment_key, comment_key)
        extra = comments.get(extra_key, extra_key)
        node_id = names.get(extra, "") or names.get(name, "")
        category_name = (
            categories[category_index].name
            if 0 <= category_index < len(categories)
            else "Category %s" % category_index
        )
        events.append(
            ProfilerEvent(
                index=index,
                start_us=raw_start - origin,
                duration_us=duration,
                thread_duration_raw=thread_duration,
                thread_id=thread_id,
                cpu_id=cpu_id,
                category_index=category_index,
                category_name=category_name,
                color_index=color_id,
                name=name,
                extra=extra,
                description=descriptions.get(comment_key.lstrip("@"), ""),
                node_id=node_id,
            )
        )
    return ProfilerCapture(
        events=tuple(events),
        categories=categories,
        source_snapshot_id=snapshot.snapshot_id if snapshot else "",
        source_scene=source_scene or (snapshot.source_scene if snapshot else ""),
        maya_version=maya_version or (snapshot.maya_version if snapshot else ""),
        metadata={
            "maya_profiler_file_version": file_version,
            "cpu_count": cpu_count,
            "declared_event_count": declared_events,
            "time_unit": "microseconds",
        },
    )


@dataclass(frozen=True)
class PulseNodeStat:
    node_id: str
    inclusive_duration_us: int
    event_count: int
    capture_share: float


def node_stats(
    capture: ProfilerCapture,
    start_us: int = 0,
    end_us: Optional[int] = None,
) -> Tuple[PulseNodeStat, ...]:
    """Aggregate observed inclusive event duration for mapped nodes."""
    end = capture.duration_us if end_us is None else end_us
    durations: Dict[str, int] = defaultdict(int)
    counts: Dict[str, int] = defaultdict(int)
    events = capture.events_in_range(start_us, end)
    for event in events:
        if not event.node_id:
            continue
        overlap = max(0, min(event.end_us, end) - max(event.start_us, start_us))
        durations[event.node_id] += overlap
        counts[event.node_id] += 1
    total = sum(durations.values()) or 1
    stats = [
        PulseNodeStat(node_id, duration, counts[node_id], duration / float(total))
        for node_id, duration in durations.items()
    ]
    return tuple(sorted(stats, key=lambda stat: (-stat.inclusive_duration_us, stat.node_id)))
