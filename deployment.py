"""Auditable Maya 2025 module installation without touching Maya preferences."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Optional

from . import __version__


MODULE_SCHEMA = 1
MANAGED_MARKER = "# MAYASCOPE-MANAGED-MODULE schema=1"


@dataclass(frozen=True)
class ModuleStatus:
    state: str
    module_file: str
    package_root: str
    detail: str = ""
    backup_file: str = ""
    rollback_file: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def package_root() -> Path:
    return Path(__file__).resolve().parent


def default_module_directory() -> Path:
    maya_app = os.environ.get("MAYA_APP_DIR")
    base = Path(maya_app).expanduser() if maya_app else Path.home() / "Documents" / "maya"
    return base.resolve() / "2025" / "modules"


def module_text(root: Optional[Path] = None) -> str:
    package = (root or package_root()).expanduser().resolve()
    if package.name != "MayaScope" or not (package / "__init__.py").is_file():
        raise ValueError("MayaScope package root must contain MayaScope/__init__.py")
    parent = package.parent.as_posix()
    package_path = package.as_posix()
    return (
        "%s\n"
        "+ MayaScope %s %s\n"
        "PYTHONPATH +:= .\n"
        "MAYASCOPE_ROOT := %s\n"
        % (MANAGED_MARKER, __version__.removesuffix("-dev"), parent, package_path)
    )


def inspect_module(module_dir: Optional[Path] = None) -> ModuleStatus:
    directory = (module_dir or default_module_directory()).expanduser().resolve()
    target = directory / "MayaScope.mod"
    if not target.is_file():
        return ModuleStatus("not-installed", str(target), str(package_root()))
    try:
        content = target.read_text(encoding="utf-8")
    except Exception as exc:
        return ModuleStatus("unreadable", str(target), str(package_root()), str(exc))
    if MANAGED_MARKER not in content:
        return ModuleStatus(
            "foreign", str(target), str(package_root()), "existing file is not managed by MayaScope"
        )
    expected = module_text()
    return ModuleStatus(
        "installed" if content == expected else "update-available",
        str(target),
        str(package_root()),
    )


def _backup_name(target: Path, reason: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return target.with_name("%s.%s-%s.bak" % (target.name, reason, stamp))


def _atomic_write(target: Path, data: str) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=target.name + ".",
            suffix=".tmp",
            dir=str(target.parent),
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary_path), str(target))
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _write_backup(target: Path, content: str, reason: str) -> Path:
    backup = _backup_name(target, reason)
    _atomic_write(backup, content)
    return backup


def install_module(module_dir: Optional[Path] = None) -> ModuleStatus:
    directory = (module_dir or default_module_directory()).expanduser().resolve()
    target = directory / "MayaScope.mod"
    current = inspect_module(directory)
    if current.state in {"foreign", "unreadable"}:
        raise RuntimeError(current.detail)
    directory.mkdir(parents=True, exist_ok=True)
    data = module_text()
    if current.state == "installed":
        return current
    backup = ""
    if current.state == "update-available":
        previous = target.read_text(encoding="utf-8")
        backup = str(_write_backup(target, previous, "pre-upgrade"))
    _atomic_write(target, data)
    return ModuleStatus(
        "installed",
        str(target),
        str(package_root()),
        "previous managed Module retained" if backup else "",
        backup,
    )


def uninstall_module(module_dir: Optional[Path] = None) -> ModuleStatus:
    directory = (module_dir or default_module_directory()).expanduser().resolve()
    current = inspect_module(directory)
    if current.state == "not-installed":
        return current
    if current.state in {"foreign", "unreadable"}:
        raise RuntimeError(current.detail)
    target = Path(current.module_file)
    backup = _backup_name(target, "uninstalled")
    os.replace(str(target), str(backup))
    return ModuleStatus(
        "uninstalled",
        str(target),
        str(package_root()),
        "recoverable backup retained",
        str(backup),
    )


def restore_module(backup_file: Path, module_dir: Optional[Path] = None) -> ModuleStatus:
    """Restore one explicit managed backup without consuming that backup."""

    directory = (module_dir or default_module_directory()).expanduser().resolve()
    backup = backup_file.expanduser().resolve()
    target = directory / "MayaScope.mod"
    if not backup.is_file():
        raise ValueError("Module backup does not exist: %s" % backup)
    if (
        backup.parent != directory
        or not backup.name.startswith("MayaScope.mod.")
        or not backup.name.endswith(".bak")
    ):
        raise ValueError(
            "Module backup must be a MayaScope .bak file in the target module directory"
        )
    content = backup.read_text(encoding="utf-8")
    if MANAGED_MARKER not in content:
        raise RuntimeError("backup is not managed by MayaScope")
    current = inspect_module(directory)
    if current.state in {"foreign", "unreadable"}:
        raise RuntimeError(current.detail)
    rollback = ""
    if target.is_file() and target.read_text(encoding="utf-8") != content:
        rollback = str(
            _write_backup(target, target.read_text(encoding="utf-8"), "pre-restore")
        )
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, content)
    return ModuleStatus(
        "restored",
        str(target),
        str(package_root()),
        "backup retained; previous active Module retained" if rollback else "backup retained",
        str(backup),
        rollback,
    )
