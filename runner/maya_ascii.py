"""Conservative Maya ASCII inspection and pre-open subset slicing.

The slicer never rewrites the source file. It removes complete createNode
blocks plus explicit statements that reference excluded DAG roots or reference
namespaces, then reparses the output before an isolated mayapy process opens it.
Unsupported structural edits fail closed instead of guessing.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


class MayaAsciiSafetyError(ValueError):
    pass


@dataclass(frozen=True)
class MayaAsciiStatement:
    index: int
    text: str
    command: str
    tokens: Tuple[str, ...]
    owner: str = ""


@dataclass(frozen=True)
class MayaAsciiNode:
    name: str
    full_path: str
    type_name: str
    parent_path: str
    statement_index: int


@dataclass(frozen=True)
class MayaAsciiReference:
    path: str
    namespace: str
    reference_node: str
    statement_index: int


@dataclass(frozen=True)
class MayaAsciiDocument:
    statements: Tuple[MayaAsciiStatement, ...]
    nodes: Tuple[MayaAsciiNode, ...]
    references: Tuple[MayaAsciiReference, ...]
    trailing_text: str = ""


@dataclass(frozen=True)
class MayaAsciiSliceReport:
    source_path: str
    output_path: str
    source_sha256: str
    output_sha256: str
    removed_node_paths: Tuple[str, ...]
    removed_reference_paths: Tuple[str, ...]
    removed_statement_count: int
    kept_statement_count: int


IMPLICIT_NODE_COMMANDS = frozenset({"addAttr", "setAttr", "rename", "lockNode"})
GLOBAL_EXPLICIT_COMMANDS = frozenset(
    {
        "connectAttr",
        "disconnectAttr",
        "relationship",
        "requires",
        "currentUnit",
        "fileInfo",
        "file",
        "select",
        "sets",
        "workspace",
    }
)
STRUCTURAL_COMMANDS_REQUIRING_REJECTION = frozenset({"parent"})
TOKEN_PATTERN = re.compile(r'"((?:\\.|[^"\\])*)"|(\S+)')


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strip_comments(value: str) -> str:
    result = []
    index = 0
    quoted = False
    escaped = False
    line_comment = False
    block_comment = False
    while index < len(value):
        char = value[index]
        next_char = value[index + 1] if index + 1 < len(value) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
                result.append(char)
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if not quoted and char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if not quoted and char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        result.append(char)
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        index += 1
    return "".join(result)


def _split_statements(value: str) -> Tuple[Tuple[str, ...], str]:
    statements = []
    start = 0
    index = 0
    quoted = False
    escaped = False
    line_comment = False
    block_comment = False
    while index < len(value):
        char = value[index]
        next_char = value[index + 1] if index + 1 < len(value) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
            index += 1
            continue
        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char == ";":
            statements.append(value[start : index + 1])
            start = index + 1
        index += 1
    if quoted or block_comment:
        raise MayaAsciiSafetyError("Unterminated quote or block comment in Maya ASCII")
    return tuple(statements), value[start:]


def _tokens(statement: str) -> Tuple[str, ...]:
    cleaned = _strip_comments(statement).strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    result = []
    for match in TOKEN_PATTERN.finditer(cleaned):
        quoted, bare = match.groups()
        token = quoted if quoted is not None else bare
        result.append(token.replace(r'\"', '"').replace(r"\\", "\\"))
    return tuple(result)


def _flag_value(tokens: Sequence[str], *flags: str) -> str:
    for index, token in enumerate(tokens[:-1]):
        if token in flags:
            return tokens[index + 1]
    return ""


def _resolve_parent(raw: str, nodes: Sequence[MayaAsciiNode]) -> str:
    if not raw:
        return ""
    if raw.startswith("|"):
        matches = [node.full_path for node in nodes if node.full_path == raw]
    else:
        matches = [node.full_path for node in nodes if node.name == raw]
    if len(matches) != 1:
        raise MayaAsciiSafetyError(
            "Maya ASCII parent %r resolves to %s nodes" % (raw, len(matches))
        )
    return matches[0]


def parse_maya_ascii_text(value: str) -> MayaAsciiDocument:
    raw_statements, trailing = _split_statements(value)
    nodes: List[MayaAsciiNode] = []
    references = []
    statements = []
    current_owner = ""
    aliases: Dict[str, list] = defaultdict(list)
    for index, text in enumerate(raw_statements):
        tokens = _tokens(text)
        command = tokens[0] if tokens else ""
        if command in STRUCTURAL_COMMANDS_REQUIRING_REJECTION:
            raise MayaAsciiSafetyError(
                "Dynamic Maya ASCII parent commands are not safe to pre-slice"
            )
        if command == "createNode":
            type_name = tokens[1] if len(tokens) > 1 else ""
            name = _flag_value(tokens, "-n", "-name")
            if not type_name or not name:
                raise MayaAsciiSafetyError("Malformed createNode statement %s" % index)
            parent_raw = _flag_value(tokens, "-p", "-parent")
            parent_path = _resolve_parent(parent_raw, nodes) if parent_raw else ""
            full_path = "%s|%s" % (parent_path, name) if parent_path else "|%s" % name
            if any(node.full_path == full_path for node in nodes):
                raise MayaAsciiSafetyError("Duplicate Maya ASCII DAG identity: %s" % full_path)
            node = MayaAsciiNode(name, full_path, type_name, parent_path, index)
            nodes.append(node)
            aliases[name].append(full_path)
            aliases[full_path].append(full_path)
            current_owner = full_path
        elif command == "select":
            selected = next(
                (token for token in reversed(tokens[1:]) if not token.startswith("-")),
                "",
            )
            matches = aliases.get(selected, ())
            current_owner = matches[0] if len(matches) == 1 else selected
        if command == "file" and any(flag in tokens for flag in ("-r", "-reference")):
            path = next(
                (
                    token for token in reversed(tokens[1:])
                    if not token.startswith("-") and token.lower().endswith((".ma", ".mb"))
                ),
                "",
            )
            if not path:
                raise MayaAsciiSafetyError("Referenced file statement has no Maya path")
            references.append(
                MayaAsciiReference(
                    path,
                    _flag_value(tokens, "-ns", "-namespace"),
                    _flag_value(tokens, "-rfn", "-referenceNode"),
                    index,
                )
            )
        statements.append(MayaAsciiStatement(index, text, command, tokens, current_owner))
    return MayaAsciiDocument(tuple(statements), tuple(nodes), tuple(references), trailing)


def inspect_maya_ascii(path: os.PathLike | str) -> MayaAsciiDocument:
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() != ".ma":
        raise MayaAsciiSafetyError("Pre-open slicing only supports Maya ASCII .ma files")
    try:
        text = source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MayaAsciiSafetyError("Maya ASCII must be valid UTF-8 for safe slicing") from exc
    return parse_maya_ascii_text(text)


def _resolve_roots(document: MayaAsciiDocument, roots: Iterable[str]) -> Tuple[str, ...]:
    resolved = []
    for raw in roots:
        matches = [
            node.full_path for node in document.nodes
            if node.full_path == raw or node.name == raw
        ]
        if len(matches) != 1:
            raise MayaAsciiSafetyError(
                "Excluded DAG root %r resolves to %s nodes" % (raw, len(matches))
            )
        resolved.append(matches[0])
    return tuple(dict.fromkeys(resolved))


def _reference_key(value: str) -> str:
    return value.replace("\\", "/").casefold()


def _references_removed_alias(token: str, aliases: Sequence[str], namespaces: Sequence[str]) -> bool:
    normalized = token.lstrip(":")
    for namespace in namespaces:
        prefix = namespace.lstrip(":") + ":"
        if normalized.startswith(prefix) or ("|" + prefix) in normalized:
            return True
    for alias in aliases:
        bare = alias.lstrip("|")
        if normalized in {alias, bare}:
            return True
        if normalized.startswith(alias + ".") or normalized.startswith(bare + "."):
            return True
        if normalized.startswith(alias + "[") or normalized.startswith(bare + "["):
            return True
    return False


def slice_maya_ascii(
    source_path: os.PathLike | str,
    output_path: os.PathLike | str,
    *,
    removed_roots: Iterable[str] = (),
    removed_reference_paths: Iterable[str] = (),
) -> MayaAsciiSliceReport:
    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if source == output:
        raise MayaAsciiSafetyError("Maya ASCII slice output cannot overwrite its source")
    if source.suffix.lower() != ".ma" or output.suffix.lower() != ".ma":
        raise MayaAsciiSafetyError("Pre-open slicing requires .ma input and output")
    source_bytes = source.read_bytes()
    try:
        text = source_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MayaAsciiSafetyError("Maya ASCII must be valid UTF-8 for safe slicing") from exc
    document = parse_maya_ascii_text(text)
    roots = _resolve_roots(document, removed_roots)
    reference_keys = {_reference_key(path) for path in removed_reference_paths}
    known_reference_keys = {_reference_key(reference.path) for reference in document.references}
    missing_references = reference_keys.difference(known_reference_keys)
    if missing_references:
        raise MayaAsciiSafetyError(
            "Excluded reference path is absent from Maya ASCII: %s"
            % sorted(missing_references)[0]
        )

    children: Dict[str, list] = defaultdict(list)
    for node in document.nodes:
        if node.parent_path:
            children[node.parent_path].append(node.full_path)
    removed_nodes = set()
    queue = deque(roots)
    while queue:
        current = queue.popleft()
        if current in removed_nodes:
            continue
        removed_nodes.add(current)
        queue.extend(children.get(current, ()))
    removed_aliases = tuple(
        alias
        for node in document.nodes
        if node.full_path in removed_nodes
        for alias in (node.full_path, node.name)
    )
    removed_references = tuple(
        reference for reference in document.references
        if _reference_key(reference.path) in reference_keys
    )
    removed_namespaces = tuple(
        reference.namespace for reference in removed_references if reference.namespace
    )
    removed_indexes = {node.statement_index for node in document.nodes if node.full_path in removed_nodes}
    removed_indexes.update(reference.statement_index for reference in removed_references)

    kept = []
    removed_count = 0
    for statement in document.statements:
        remove = statement.index in removed_indexes
        if (
            not remove
            and statement.owner in removed_nodes
            and statement.command not in GLOBAL_EXPLICIT_COMMANDS
        ):
            # Maya writes node-local commands in the block following createNode.
            # Unknown/plugin commands stay with that block; explicit global
            # relationship commands are filtered by their node references below.
            remove = True
        if not remove and statement.tokens:
            remove = any(
                _references_removed_alias(token, removed_aliases, removed_namespaces)
                for token in statement.tokens[1:]
            )
        if remove:
            removed_count += 1
        else:
            kept.append(statement.text)
    body = "".join(kept) + document.trailing_text
    lines = body.splitlines(keepends=True)
    provenance = "// MayaScope isolated pre-open slice; source SHA-256 %s\n" % _sha256_bytes(source_bytes)
    # Maya identifies ASCII scenes from the first line. Provenance must follow
    # the canonical header rather than precede it.
    if lines and lines[0].lstrip("\ufeff").startswith("//Maya ASCII"):
        output_text = lines[0] + provenance + "".join(lines[1:])
    else:
        raise MayaAsciiSafetyError("Maya ASCII header must be the first line")
    reparsed = parse_maya_ascii_text(output_text)
    remaining_paths = {node.full_path for node in reparsed.nodes}
    leaked = removed_nodes.intersection(remaining_paths)
    if leaked:
        raise MayaAsciiSafetyError("Removed Maya node leaked into output: %s" % sorted(leaked)[0])
    remaining_reference_keys = {_reference_key(item.path) for item in reparsed.references}
    if reference_keys.intersection(remaining_reference_keys):
        raise MayaAsciiSafetyError("Removed Maya reference leaked into output")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    data = output_text.encode("utf-8")
    with open(temporary, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(output))
    return MayaAsciiSliceReport(
        str(source),
        str(output),
        _sha256_bytes(source_bytes),
        _sha256_bytes(data),
        tuple(sorted(removed_nodes)),
        tuple(sorted(reference.path for reference in removed_references)),
        removed_count,
        len(kept),
    )
