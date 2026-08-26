# Scene Clinic team configuration and Rule SDK

MayaScope separates two trust levels:

1. **Declarative team JSON** can adjust allow-listed thresholds, disable built-ins,
   add node-type policy rules, and define profiles. It cannot import a module,
   call a function, or execute Python.
2. **Trusted Python RulePack** can provide arbitrary `Rule` implementations, but
   the studio host must import and pass that pack explicitly. MayaScope never
   discovers or executes Python named by JSON.

## Declarative configuration

Start from `examples/clinic.team.json`. Point MayaScope at an explicit file before
launching Maya:

```powershell
$env:MAYASCOPE_CLINIC_CONFIG = 'D:\pipeline\mayascope\clinic.team.json'
```

The Rule Array displays `团队规则 <fingerprint>` when the file is accepted. Invalid,
missing, oversized, duplicate-key, or unknown-field configurations fall back to
built-ins and display `配置已回退`; they do not partially apply.

Schema version 2 supports everything from version 1 plus an optional
`scene_contract`. Version 1 files are upgraded in memory and remain source-compatible.
The contract can declare:

- `allowed_time_units`;
- `required_linear_unit`, `required_angular_unit`, and `required_up_axis`;
- `required_color_management` and `allowed_rendering_spaces`;
- `required_plugins` and `forbidden_plugins`;
- a rule `severity`.

Without `scene_contract`, MayaScope does not assume that 24 fps, centimeters,
Y-up, or a particular OCIO space is universally correct. When configured, the
deterministic `scene-contract` rule is automatically added to the built-in
`all` and `publish` profiles. Schema version 2 also supports:

- `thresholds.high-fanout`: integer `2..100000`;
- `thresholds.namespace-depth`: integer `1..32`;
- `disabled_rules`: existing rule IDs;
- up to 64 `custom_rules` of kind `forbidden_node_types`;
- up to 32 custom or replacement `profiles` referencing known rule IDs.

The loader is strict by design. Typos are errors instead of silently ignored
policy. A plugin cannot be both required and forbidden. The canonical migrated
JSON payload receives a SHA-256 fingerprint shown in the
UI and available as `ClinicEnvironment.fingerprint`.

## Trusted Python RulePack

A Python rule implements `id` and `evaluate(snapshot) -> Sequence[Issue]`. Build
metadata with `RuleSpec`, then construct a versioned pack:

```python
from MayaScope.analysis.clinic import RuleProfile, RuleSpec
from MayaScope.analysis.config import load_environment_from_env
from MayaScope.analysis.sdk import RulePack, extend_environment
from MayaScope.ui.workspace import show_tool

from studio_maya_rules import FrozenTransformRule

base = load_environment_from_env()
spec = RuleSpec(
    FrozenTransformRule(),
    title="Frozen delivery transforms",
    category="pipeline",
    confidence="deterministic",
    cost="moderate",
)
profile = RuleProfile(
    "studio-rig-publish",
    "Studio Rig Publish",
    "Trusted rig delivery checks.",
    (spec.id,),
)
environment = extend_environment(
    base,
    RulePack("studio-rig-rules-v1", (spec,), (profile,)),
)
show_tool(clinic_environment=environment)
```

`extend_environment` does not import modules. The caller owns that decision and
must treat the supplied RulePack as executable code. Rule IDs and profile IDs
cannot collide, SDK versions must match, and the returned environment is a new
registry rather than a mutation of global defaults.

## Rule result contract

Every rule must:

- return a sequence on every path, including the clean path;
- use its registered rule ID on every Issue;
- emit unique Issue IDs;
- reference only stable node IDs present in the input SceneSnapshot;
- make uncertainty explicit through `RuleSpec.confidence`;
- avoid direct Maya or Qt access when it can operate on snapshot data;
- remain diagnostic unless a separately reviewed ChangePlan provider can prove
  preview, identity revalidation, reference protection, postcondition verify,
  Undo, and rollback behavior.

The registry isolates exceptions per rule and reports them as Rule Faults. A
failed rule is never interpreted as a clean result.
