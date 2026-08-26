# Physics material contract

Item 14 exposes typed friction, restitution, query, and binding read-back
without requiring `execute_script`.

## Named tools

| Tool | Purpose |
|---|---|
| `create_material` | Create PBR or physics material with validated fields |
| `get_material` | Read material type, parameters, and units |
| `apply_material` | Bind with `auto`, `physics`, or `visual` purpose |
| `get_material_binding` | Read resolved/direct material path, relationship, and strength |

Physics materials are authored as `UsdShade.Material` prims with
`UsdPhysics.MaterialAPI`. Physics binding uses the dedicated
`material:binding:physics` relationship. Visual binding uses USD all-purpose
binding and remains backward compatible.

## Validation and units

- `static_friction` and `dynamic_friction` are finite dimensionless
  coefficients greater than or equal to zero.
- `dynamic_friction <= static_friction` is required.
- `restitution` is finite, dimensionless, and within `[0, 1]`.
- PBR color, roughness, and metallic use normalized `[0, 1]` values.
- Physics material creation and binding require a stopped timeline.
- Existing physics-material paths are rejected. Failed create/read-back removes
  the newly created prim.
- Binding snapshots the previous direct relationship. Failed bind/read-back
  restores the previous material and strength.
- Float32 USD read-back uses `rel_tol=1e-6`, `abs_tol=1e-7`.

## Backend status

Isaac Sim `6.0.1-rc.7` PhysX is `supported/verified`. Newton remains
`untested`; USD schema compatibility alone is not runtime evidence.

## Live acceptance

```powershell
uv run python scripts/verify_physics_material_live.py
```

The verifier creates two materials and eight physics-purpose bindings under
`/World/MCP_Task_3_4`. Across 181 exact PhysX steps, the zero-friction body
travels at least 2 m farther than the high-friction body, while the high
restitution sphere rebounds at least 1 m higher than the zero-restitution
sphere. It rejects an invalid friction pair before prim creation, then deletes
the scratch root and verifies absence.
