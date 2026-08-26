"""Versioned Scene Clinic audit payload migration."""

from __future__ import annotations

from .schema import MigrationRegistry


AUDIT_SCHEMA_VERSION = 2
AUDIT_MIGRATIONS = MigrationRegistry("Scene Clinic audit", AUDIT_SCHEMA_VERSION)


@AUDIT_MIGRATIONS.register(1)
def _audit_v1_to_v2(payload):
    payload["schema_version"] = 2
    payload.setdefault("gate_mode", "absolute")
    payload.setdefault("absolute_gate_failed", bool(payload.get("gate_failed", False)))
    payload.setdefault(
        "audit_exit_code",
        1 if not payload.get("ok", False) else 2 if payload.get("gate_failed", False) else 0,
    )
    payload.setdefault("performance", None)
    return payload


def migrate_audit_payload(payload):
    return AUDIT_MIGRATIONS.migrate(payload)
