from __future__ import annotations

import unittest

from MayaScope.audit_schema import migrate_audit_payload
from MayaScope.schema import MigrationRegistry, SchemaMigrationError


class SchemaMigrationTests(unittest.TestCase):
    def test_registry_migrates_a_copy_one_step_at_a_time(self):
        registry = MigrationRegistry("fixture", 3)

        @registry.register(1)
        def one_to_two(payload):
            payload.update(schema_version=2, added="two")
            return payload

        @registry.register(2)
        def two_to_three(payload):
            payload.update(schema_version=3, final=True)
            return payload

        source = {"schema_version": 1, "nested": {"value": 1}}
        migrated = registry.migrate(source)
        self.assertEqual(migrated["schema_version"], 3)
        self.assertTrue(migrated["final"])
        self.assertEqual(source, {"schema_version": 1, "nested": {"value": 1}})

    def test_future_missing_and_nonadvancing_migrations_fail_closed(self):
        registry = MigrationRegistry("fixture", 2)
        with self.assertRaisesRegex(SchemaMigrationError, "newer"):
            registry.migrate({"schema_version": 3})
        with self.assertRaisesRegex(SchemaMigrationError, "Missing"):
            registry.migrate({"schema_version": 1})

        @registry.register(1)
        def broken(payload):
            return payload

        with self.assertRaisesRegex(SchemaMigrationError, "exactly one"):
            registry.migrate({"schema_version": 1})

    def test_audit_v1_defaults_migrate_to_v2(self):
        migrated = migrate_audit_payload(
            {
                "schema_version": 1,
                "format": "mayascope.clinic-audit",
                "ok": True,
                "gate_failed": True,
            }
        )
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["gate_mode"], "absolute")
        self.assertTrue(migrated["absolute_gate_failed"])
        self.assertEqual(migrated["audit_exit_code"], 2)


if __name__ == "__main__":
    unittest.main()
