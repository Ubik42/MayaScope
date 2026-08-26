"""Strict declarative configuration for deployable Scene Clinic rule sets.

JSON loaded here never imports modules or executes code. Trusted Python rule
extensions use :mod:`MayaScope.analysis.sdk` through an explicit host call.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .clinic import (
    DEFAULT_PROFILES,
    DEFAULT_REGISTRY,
    RuleProfile,
    RuleRegistry,
    RuleSpec,
    profile_map,
)
from .rules import (
    HighFanoutRule,
    NamespaceDepthRule,
    NodeTypePolicyRule,
    SceneContract,
    SceneContractRule,
    Severity,
)


CONFIG_SCHEMA_VERSION = 2
MAX_CONFIG_BYTES = 1_048_576
MAX_CUSTOM_RULES = 64
MAX_PROFILES = 32
CONFIG_ENV_VAR = "MAYASCOPE_CLINIC_CONFIG"
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version", "thresholds", "disabled_rules", "custom_rules", "profiles",
        "scene_contract",
    }
)


class ClinicConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ClinicEnvironment:
    registry: RuleRegistry
    profiles: Tuple[RuleProfile, ...]
    source: str = "built-in"
    fingerprint: str = "built-in"

    def __post_init__(self) -> None:
        object.__setattr__(self, "profiles", tuple(self.profiles))
        profile_map(self.profiles, self.registry)

    @classmethod
    def default(cls) -> "ClinicEnvironment":
        # Clone the mutable registry so extensions never mutate the process-wide default.
        return cls(RuleRegistry(DEFAULT_REGISTRY.specs), DEFAULT_PROFILES)


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ClinicConfigError("Duplicate JSON key: %s" % key)
        result[key] = value
    return result


def _expect_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ClinicConfigError("%s must be an object" % label)
    return value


def _expect_list(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ClinicConfigError("%s must be an array" % label)
    return value


def _reject_unknown(mapping: Mapping[str, Any], allowed, label: str) -> None:
    unknown = set(mapping).difference(allowed)
    if unknown:
        raise ClinicConfigError("Unknown %s field: %s" % (label, sorted(unknown)[0]))


def _rule_id(value: Any, label: str = "rule id") -> str:
    result = str(value)
    if not _ID_PATTERN.fullmatch(result):
        raise ClinicConfigError("Invalid %s: %s" % (label, result))
    return result


def _bounded_text(value: Any, label: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ClinicConfigError("%s must be 1-%s characters" % (label, limit))
    return value.strip()


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ClinicConfigError("%s must be an integer from %s to %s" % (label, minimum, maximum))
    return value


def _boolean(value: Any, label: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ClinicConfigError("%s must be true or false" % label)
    return value


def _severity(value: Any) -> Severity:
    name = str(value or "WARNING").upper()
    try:
        return Severity[name]
    except KeyError as exc:
        raise ClinicConfigError("Unsupported severity: %s" % name) from exc


def _unique_text_list(value: Any, label: str, maximum: int = 128) -> Tuple[str, ...]:
    values = tuple(_bounded_text(item, label, 260) for item in _expect_list(value, label))
    if len(values) > maximum:
        raise ClinicConfigError("%s contains more than %s entries" % (label, maximum))
    if len(set(values)) != len(values):
        raise ClinicConfigError("%s contains duplicates" % label)
    return values


def _scene_contract_spec(payload: Any) -> RuleSpec:
    item = _expect_mapping(payload, "scene_contract")
    allowed = {
        "allowed_time_units", "required_linear_unit", "required_angular_unit",
        "required_up_axis", "required_color_management", "allowed_rendering_spaces",
        "required_plugins", "forbidden_plugins", "severity",
    }
    _reject_unknown(item, allowed, "scene_contract")
    if not item:
        raise ClinicConfigError("scene_contract must declare at least one requirement")
    up_axis = str(item.get("required_up_axis", "")).lower()
    if up_axis and up_axis not in {"y", "z"}:
        raise ClinicConfigError("scene_contract required_up_axis must be y or z")
    color = item.get("required_color_management")
    if color is not None and not isinstance(color, bool):
        raise ClinicConfigError("scene_contract required_color_management must be true or false")
    contract = SceneContract(
        allowed_time_units=_unique_text_list(item.get("allowed_time_units", []), "allowed_time_units"),
        required_linear_unit=str(item.get("required_linear_unit", "")),
        required_angular_unit=str(item.get("required_angular_unit", "")),
        required_up_axis=up_axis,
        required_color_management=color,
        allowed_rendering_spaces=_unique_text_list(
            item.get("allowed_rendering_spaces", []), "allowed_rendering_spaces"
        ),
        required_plugins=_unique_text_list(item.get("required_plugins", []), "required_plugins"),
        forbidden_plugins=_unique_text_list(item.get("forbidden_plugins", []), "forbidden_plugins"),
    )
    if set(contract.required_plugins).intersection(contract.forbidden_plugins):
        raise ClinicConfigError("scene_contract cannot require and forbid the same plugin")
    return RuleSpec(
        SceneContractRule(contract, _severity(item.get("severity", "ERROR"))),
        "场景制片规范",
        "pipeline",
        "deterministic",
    )


def _custom_spec(payload: Any) -> RuleSpec:
    item = _expect_mapping(payload, "custom rule")
    allowed = {
        "id", "kind", "title", "description", "node_types", "severity",
        "category", "confidence", "cost", "default_enabled",
    }
    _reject_unknown(item, allowed, "custom rule")
    if item.get("kind") != "forbidden_node_types":
        raise ClinicConfigError("Unsupported custom rule kind: %s" % item.get("kind"))
    rule_id = _rule_id(item.get("id"))
    title = _bounded_text(item.get("title"), "custom rule title", 120)
    description = _bounded_text(
        item.get("description", "Studio policy forbids these node types in this production stage."),
        "custom rule description",
    )
    raw_types = _expect_list(item.get("node_types"), "custom rule node_types")
    if not 1 <= len(raw_types) <= 128:
        raise ClinicConfigError("custom rule node_types must contain 1-128 entries")
    node_types = tuple(_bounded_text(value, "node type", 100) for value in raw_types)
    if len(set(node_types)) != len(node_types):
        raise ClinicConfigError("custom rule node_types contains duplicates")
    severity = _severity(item.get("severity"))
    rule = NodeTypePolicyRule(rule_id, title, node_types, description, severity)
    try:
        return RuleSpec(
            rule,
            title,
            str(item.get("category", "pipeline")),
            str(item.get("confidence", "deterministic")),
            cost=str(item.get("cost", "instant")),
            default_enabled=_boolean(item.get("default_enabled"), "default_enabled", True),
        )
    except ValueError as exc:
        raise ClinicConfigError(str(exc)) from exc


def _configured_profile(payload: Any) -> RuleProfile:
    item = _expect_mapping(payload, "profile")
    allowed = {"id", "title", "description", "rule_ids", "include_expensive"}
    _reject_unknown(item, allowed, "profile")
    profile_id = _rule_id(item.get("id"), "profile id")
    rule_ids = tuple(
        _rule_id(value) for value in _expect_list(item.get("rule_ids"), "profile rule_ids")
    )
    if len(set(rule_ids)) != len(rule_ids):
        raise ClinicConfigError("profile rule_ids contains duplicates")
    try:
        return RuleProfile(
            profile_id,
            _bounded_text(item.get("title"), "profile title", 80),
            _bounded_text(item.get("description", "Studio Clinic profile."), "profile description"),
            rule_ids,
            _boolean(item.get("include_expensive"), "include_expensive", False),
        )
    except ValueError as exc:
        raise ClinicConfigError(str(exc)) from exc


def build_environment(payload: Mapping[str, Any], source: str = "memory") -> ClinicEnvironment:
    payload = _expect_mapping(payload, "Clinic config")
    payload = dict(payload)
    # Schema 1 remains source-compatible; version 2 adds the optional scene contract.
    if payload.get("schema_version") == 1:
        payload["schema_version"] = CONFIG_SCHEMA_VERSION
    _reject_unknown(payload, _TOP_LEVEL_KEYS, "top-level")
    if payload.get("schema_version") != CONFIG_SCHEMA_VERSION:
        raise ClinicConfigError(
            "Unsupported Clinic config schema: %s" % payload.get("schema_version")
        )

    specs = list(DEFAULT_REGISTRY.specs)
    thresholds = _expect_mapping(payload.get("thresholds", {}), "thresholds")
    _reject_unknown(thresholds, {"high-fanout", "namespace-depth"}, "threshold")
    configured = []
    for spec in specs:
        if spec.id == "high-fanout" and spec.id in thresholds:
            spec = replace(
                spec,
                rule=HighFanoutRule(_integer(thresholds[spec.id], spec.id, 2, 100_000)),
            )
        elif spec.id == "namespace-depth" and spec.id in thresholds:
            spec = replace(
                spec,
                rule=NamespaceDepthRule(_integer(thresholds[spec.id], spec.id, 1, 32)),
            )
        configured.append(spec)
    specs = configured
    if "scene_contract" in payload:
        specs.append(_scene_contract_spec(payload["scene_contract"]))

    custom_payloads = _expect_list(payload.get("custom_rules", []), "custom_rules")
    if len(custom_payloads) > MAX_CUSTOM_RULES:
        raise ClinicConfigError("Too many custom rules")
    specs.extend(_custom_spec(item) for item in custom_payloads)
    known = {spec.id for spec in specs}
    if len(known) != len(specs):
        raise ClinicConfigError("Duplicate rule id across built-in and custom rules")

    disabled_values = _expect_list(payload.get("disabled_rules", []), "disabled_rules")
    disabled = {_rule_id(value) for value in disabled_values}
    missing_disabled = disabled.difference(known)
    if missing_disabled:
        raise ClinicConfigError("disabled_rules references unknown rule: %s" % sorted(missing_disabled)[0])
    specs = [replace(spec, default_enabled=False) if spec.id in disabled else spec for spec in specs]
    registry = RuleRegistry(specs)

    profiles_by_id = {profile.id: profile for profile in DEFAULT_PROFILES}
    # Global disables apply to built-in profiles. Custom default rules join All Signals.
    try:
        for profile_id, profile in tuple(profiles_by_id.items()):
            ids = tuple(rule_id for rule_id in profile.rule_ids if rule_id not in disabled)
            if profile_id == "all":
                ids = tuple(spec.id for spec in specs if spec.default_enabled)
            elif profile_id == "publish" and "scene-contract" in known and "scene-contract" not in disabled:
                ids = ids + ("scene-contract",)
            profiles_by_id[profile_id] = replace(profile, rule_ids=ids)
    except ValueError as exc:
        raise ClinicConfigError("disabled_rules leaves an empty profile: %s" % exc) from exc
    profile_payloads = _expect_list(payload.get("profiles", []), "profiles")
    if len(profile_payloads) > MAX_PROFILES:
        raise ClinicConfigError("Too many configured profiles")
    for item in profile_payloads:
        profile = _configured_profile(item)
        profiles_by_id[profile.id] = profile
    profiles = tuple(profiles_by_id.values())
    try:
        profile_map(profiles, registry)
    except ValueError as exc:
        raise ClinicConfigError(str(exc)) from exc

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ClinicEnvironment(registry, profiles, source, fingerprint)


def load_clinic_config(path: str | Path) -> ClinicEnvironment:
    try:
        candidate = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ClinicConfigError("Clinic config does not exist: %s" % path) from exc
    if not candidate.is_file():
        raise ClinicConfigError("Clinic config is not a file: %s" % candidate)
    size = candidate.stat().st_size
    if size > MAX_CONFIG_BYTES:
        raise ClinicConfigError("Clinic config exceeds %s bytes" % MAX_CONFIG_BYTES)
    try:
        text = candidate.read_text(encoding="utf-8")
        payload = json.loads(text, object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClinicConfigError("Could not read Clinic config: %s" % exc) from exc
    return build_environment(payload, source=str(candidate))


def load_environment_from_env(env: Optional[Mapping[str, str]] = None) -> ClinicEnvironment:
    variables = os.environ if env is None else env
    path = str(variables.get(CONFIG_ENV_VAR, "")).strip()
    return load_clinic_config(path) if path else ClinicEnvironment.default()
