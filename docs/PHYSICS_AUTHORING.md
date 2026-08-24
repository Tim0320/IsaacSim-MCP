# Typed physics authoring

Task 3.3 adds six named tools so agents no longer need `execute_script` for
common USD physics schema authoring:

| Tool | Purpose |
|---|---|
| `configure_physics_body` | Atomic dynamic, kinematic, or static body configuration |
| `get_physics_body` | Read rigid/collision APIs, approximation, mass and density |
| `create_collision_group` | Create collider membership and filtered-group relationships |
| `get_collision_group` | Read group members, filters, inversion and merge name |
| `create_physics_joint` | Create fixed, revolute, or prismatic joint |
| `get_physics_joint` | Read bodies, local frames, axis, limits and units |

## Contract

- Writes require a stopped timeline.
- Mass is kilograms; density is kilograms per cubic metre.
- Joint local positions and prismatic limits are metres.
- Revolute limits are degrees. Axes are `X`, `Y`, or `Z`.
- Local rotations are `[w, x, y, z]` quaternions and are normalized before authoring.
- `mass_kg` and `density_kg_m3` are mutually exclusive; static bodies reject both.
- Converting to static removes `RigidBodyAPI` and `MassAPI`; disabling the
  collider removes both `CollisionAPI` and `MeshCollisionAPI`.
- Collider approximation is available only on `Mesh` prims: `none`,
  `convex_hull`, `convex_decomposition`, `mesh_simplification`,
  `bounding_cube`, or `bounding_sphere`.
- Creation refuses an existing collision-group or joint path. Referenced prims
  must exist, and collision-group members must already have `CollisionAPI`.

Body configuration snapshots every managed API and authored attribute before
apply. Any apply or read-back failure restores the snapshot. Newly created
groups and joints are removed if their authoring/read-back fails.

## Backend status

Isaac Sim `6.0.1-rc.7` PhysX is `supported/verified`. Newton remains
`untested`; shared USD schemas are not treated as Newton runtime evidence.

## Live acceptance

Run only against the live-control route on TCP `8766`:

```powershell
uv run python scripts/verify_physics_authoring_live.py
```

The verifier uses `/World/MCP_Task_3_3`, validates body/mass/density,
collision-group relationships and all three joint types, proves rollback after
a mid-apply Mesh-only failure, executes exactly 120 physics steps, checks the
fixed body remains at `z=3.0`, then deletes the scratch root and verifies absence.
