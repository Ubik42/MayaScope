"""Explicit trust boundary for Python-authored Scene Clinic rule packs."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from typing import Tuple

from .clinic import RuleProfile, RuleRegistry, RuleSpec, profile_map
from .config import ClinicEnvironment


RULE_SDK_VERSION = 1


@dataclass(frozen=True)
class RulePack:
    id: str
    specs: Tuple[RuleSpec, ...]
    profiles: Tuple[RuleProfile, ...] = ()
    sdk_version: int = RULE_SDK_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "specs", tuple(self.specs))
        object.__setattr__(self, "profiles", tuple(self.profiles))
        if not self.id or not self.specs:
            raise ValueError("RulePack id and specs are required")
        if self.sdk_version != RULE_SDK_VERSION:
            raise ValueError("Unsupported RulePack SDK version: %s" % self.sdk_version)


def extend_environment(environment: ClinicEnvironment, pack: RulePack) -> ClinicEnvironment:
    """Add an already-imported, explicitly trusted pack without module loading."""
    registry = RuleRegistry(environment.registry.specs)
    for spec in pack.specs:
        registry.register(spec)
    profiles = list(environment.profiles)
    existing_profile_ids = {profile.id for profile in profiles}
    duplicates = existing_profile_ids.intersection(profile.id for profile in pack.profiles)
    if duplicates:
        raise ValueError("RulePack duplicates profile id: %s" % sorted(duplicates)[0])
    new_default_ids = tuple(spec.id for spec in pack.specs if spec.default_enabled)
    profiles = [
        replace(profile, rule_ids=profile.rule_ids + new_default_ids)
        if profile.id == "all" else profile
        for profile in profiles
    ]
    profiles.extend(pack.profiles)
    profile_map(profiles, registry)
    digest = hashlib.sha256(
        (environment.fingerprint + "|" + pack.id + "|" + "|".join(spec.id for spec in pack.specs)).encode("utf-8")
    ).hexdigest()
    return ClinicEnvironment(
        registry,
        tuple(profiles),
        source="%s + trusted:%s" % (environment.source, pack.id),
        fingerprint=digest,
    )
