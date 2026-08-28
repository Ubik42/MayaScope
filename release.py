"""Build and verify a deterministic MayaScope Maya 2025 showcase archive."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable, Optional, Tuple
import zipfile

from . import __version__


RELEASE_SCHEMA = 1
EXCLUDED_PARTS = frozenset(
    {".git", "__pycache__", "tests", "legacy", "mel-outline", "AnalyseAdv", "work"}
)
ALLOWED_SUFFIXES = frozenset({".py", ".md", ".json", ".png", ".ma", ".exr"})


@dataclass(frozen=True)
class ReleaseReceipt:
    archive: str
    archive_sha256: str
    manifest: str
    file_count: int


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_files(root: Path) -> Tuple[Path, ...]:
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS or part.startswith(".") for part in relative.parts):
            continue
        files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _zip_write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def build_release(
    output_dir: Path,
    *,
    root: Optional[Path] = None,
    showcase_files: Iterable[Path] = (),
) -> ReleaseReceipt:
    package = (root or Path(__file__).resolve().parent).expanduser().resolve()
    output = output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / ("MayaScope-%s-Maya2025.zip" % __version__)
    manifest_path = output / ("MayaScope-%s-release-manifest.json" % __version__)

    entries = []
    payloads = {}
    for path in _runtime_files(package):
        name = "MayaScope/%s" % path.relative_to(package).as_posix()
        data = path.read_bytes()
        payloads[name] = data
        entries.append({"path": name, "size": len(data), "sha256": _sha256_bytes(data)})
    for path in sorted((Path(item).expanduser().resolve() for item in showcase_files), key=str):
        if not path.is_file():
            raise ValueError("Showcase file does not exist: %s" % path)
        name = "showcase/%s" % path.name
        if name in payloads:
            raise ValueError("Duplicate release path: %s" % name)
        data = path.read_bytes()
        payloads[name] = data
        entries.append({"path": name, "size": len(data), "sha256": _sha256_bytes(data)})
    entries.sort(key=lambda item: item["path"])
    manifest = {
        "format": "mayascope.release",
        "schema_version": RELEASE_SCHEMA,
        "version": __version__,
        "target": {"maya": "2025", "qt": "PySide6", "platform": "Windows"},
        "entrypoints": {
            "ui": 'from MayaScope import launch; launch.run("workspace")',
            "doctor": "python -m MayaScope.doctor",
            "install": "python -m MayaScope.install install",
            "runner": "python -m MayaScope.runner --help",
            "audit": "python -m MayaScope.audit --help",
            "install_replay": "python -m MayaScope.install_replay --help",
        },
        "files": entries,
    }
    manifest_data = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    temporary = archive_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w") as archive:
        for name in sorted(payloads):
            _zip_write(archive, name, payloads[name])
        _zip_write(archive, "release-manifest.json", manifest_data)
    temporary.replace(archive_path)
    manifest_temporary = manifest_path.with_suffix(".json.tmp")
    manifest_temporary.write_bytes(manifest_data)
    manifest_temporary.replace(manifest_path)
    receipt = ReleaseReceipt(
        archive=str(archive_path),
        archive_sha256=_sha256_file(archive_path),
        manifest=str(manifest_path),
        file_count=len(entries),
    )
    verify_release(archive_path)
    return receipt


def verify_release(path: Path) -> dict:
    archive_path = path.expanduser().resolve()
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = tuple(archive.namelist())
        if len(names) != len(set(names)):
            raise ValueError("Release archive contains duplicate paths")
        if any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("Release archive contains an unsafe path")
        try:
            manifest = json.loads(archive.read("release-manifest.json"))
        except Exception as exc:
            raise ValueError("Release manifest is unreadable: %s" % exc) from exc
        if manifest.get("format") != "mayascope.release":
            raise ValueError("Unexpected release format")
        if int(manifest.get("schema_version", 0)) != RELEASE_SCHEMA:
            raise ValueError("Unsupported release schema")
        expected = {"release-manifest.json"}
        for item in manifest.get("files", ()):
            name = str(item["path"])
            data = archive.read(name)
            if len(data) != int(item["size"]) or _sha256_bytes(data) != item["sha256"]:
                raise ValueError("Release payload checksum mismatch: %s" % name)
            expected.add(name)
        if set(names) != expected:
            raise ValueError("Release archive has unmanifested or missing payloads")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayascope-release")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("output", type=Path)
    build.add_argument("--showcase", type=Path, action="append", default=[])
    verify = commands.add_parser("verify")
    verify.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = asdict(build_release(args.output, showcase_files=args.showcase))
        else:
            manifest = verify_release(args.archive)
            result = {"verified": True, "version": manifest["version"], "file_count": len(manifest["files"])}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
