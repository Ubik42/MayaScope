"""CLI for MayaScope's user-level Maya 2025 module registration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .deployment import install_module, inspect_module, restore_module, uninstall_module


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayascope-install")
    parser.add_argument(
        "action", choices=("status", "install", "uninstall", "restore")
    )
    parser.add_argument("--module-dir", type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            result = inspect_module(args.module_dir)
        elif args.action == "install":
            result = install_module(args.module_dir)
        elif args.action == "uninstall":
            result = uninstall_module(args.module_dir)
        else:
            if args.backup is None:
                raise ValueError("restore requires --backup")
            result = restore_module(args.backup, args.module_dir)
    except Exception as exc:
        print(json.dumps({"state": "error", "detail": str(exc)}, ensure_ascii=False))
        return 1
    print(result.to_json())
    return 0 if result.state not in {"foreign", "unreadable"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
