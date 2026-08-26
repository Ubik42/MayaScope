"""Strict, host-independent schema migration primitives."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, Mapping


class SchemaMigrationError(ValueError):
    pass


class MigrationRegistry:
    def __init__(self, name: str, current_version: int, version_field: str = "schema_version"):
        if current_version < 1:
            raise ValueError("current_version must be positive")
        self.name = name
        self.current_version = int(current_version)
        self.version_field = version_field
        self._steps: Dict[int, Callable[[Dict[str, Any]], Mapping[str, Any]]] = {}

    def register(
        self,
        from_version: int,
        migrate: Callable[[Dict[str, Any]], Mapping[str, Any]] | None = None,
    ):
        if migrate is None:
            return lambda function: self.register(from_version, function)
        if from_version < 1 or from_version >= self.current_version:
            raise ValueError("Migration source must precede the current version")
        if from_version in self._steps:
            raise ValueError("Duplicate %s migration from version %s" % (self.name, from_version))
        self._steps[from_version] = migrate
        return migrate

    def migrate(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        result = deepcopy(dict(payload))
        try:
            version = int(result[self.version_field])
        except Exception as exc:
            raise SchemaMigrationError("%s has no valid %s" % (self.name, self.version_field)) from exc
        if version > self.current_version:
            raise SchemaMigrationError(
                "%s schema %s is newer than supported schema %s"
                % (self.name, version, self.current_version)
            )
        if version < 1:
            raise SchemaMigrationError("Unsupported %s schema %s" % (self.name, version))
        while version < self.current_version:
            step = self._steps.get(version)
            if step is None:
                raise SchemaMigrationError(
                    "Missing %s migration %s -> %s" % (self.name, version, version + 1)
                )
            migrated = dict(step(deepcopy(result)))
            next_version = int(migrated.get(self.version_field, 0))
            if next_version != version + 1:
                raise SchemaMigrationError(
                    "%s migration %s must advance exactly one version" % (self.name, version)
                )
            result = migrated
            version = next_version
        return result
