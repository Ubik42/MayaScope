"""Auditable Maya 2025 module installation without touching Maya preferences."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
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


def install_module(module_dir: Optional[Path] = None) -> ModuleStatus:
    directory = (module_dir or default_module_directory()).expanduser().resolve()
    target = directory / "MayaScope.mod"
    current = inspect_module(directory)
    if current.state in {"foreign", "unreadable"}:
        raise RuntimeError(current.detail)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".mod.tmp")
    data = module_text()
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(target))
    return ModuleStatus("installed", str(target), str(package_root()))


def uninstall_module(module_dir: Optional[Path] = None) -> ModuleStatus:
    directory = (module_dir or default_module_directory()).expanduser().resolve()
    current = inspect_module(directory)
    if current.state == "not-installed":
        return current
    if current.state in {"foreign", "unreadable"}:
        raise RuntimeError(current.detail)
    target = Path(current.module_file)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = target.with_name("MayaScope.mod.uninstalled-%s.bak" % stamp)
    os.replace(str(target), str(backup))
    return ModuleStatus(
        "uninstalled",
        str(target),
        str(package_root()),
        "recoverable backup retained",
        str(backup),
    )
