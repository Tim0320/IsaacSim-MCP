# NVIDIA Asset Catalog for MCP

Verified against the NVIDIA Isaac Sim 6.0 asset root on 2026-08-21.
Use `list_nvidia_assets` to query the runtime catalog and pass its exact
`asset_key` to `spawn_nvidia_asset`.

## Coverage

| Category | Verified availability | Example MCP keys | Interaction after spawn |
|---|---:|---|---|
| Robot arms | Live robot catalog | `frankapanda`, `xarm6`, KUKA, FANUC, Comau, Cobotta | `get_robot_info`, `set_joint_positions`, or an Action Graph/controller |
| Quadrupeds | Spot, Go1, Go2, A1, B2, Aliengo, ANYmal | `spot`, `go1`, `go2` | Articulation inspection is immediate; locomotion needs a compatible policy/controller |
| AGV / mobile robots | Syncro5/10, Trakr, Carter, Nova Carter, Jetbot, forklifts, Ridgeback | query category `agv` for exact keys | Wheel/base controller through Action Graph or a reusable script |
| Conveyors | 49 ConveyorBelt A variants found | `conveyor_a01`, `conveyor_a13`, `conveyor_a31` | Add belt motion with `create_action_graph`, `reload_script`, or `execute_script` |
| Warehouse | Pallets, bins, tables, dollies, racks, crates and other SimReady groups | `pallet`, `klt_bin`, `packing_table`, `warehouse_rack_3m`, `blue_crate` | `transform_object`, `clone_object`, `delete_object` |
| Factory parts | Bolts, nuts and gears | `factory_gear_small`, `factory_bolt_m12` | `transform_object`, `clone_object`, `delete_object` |
| Lifting equipment | Cargo crane, portable gantry, jib crane, mobile scissor lift table | `cargo_crane`, `portable_gantry_crane`, `jib_crane`, `scissor_lift_table` | Transform directly; hoist motion needs an Action Graph or controller script |
| Instrumentation | Oscilloscope, digital multimeter, optical alignment scanner, inspection light, wall display | `oscilloscope_a01`, `digital_multimeter_b01`, `wheel_alignment_scanner`, `rigid_inspection_task_light`, `wall_display_panel` | Visual props; connect measurement, sensor, or display behavior through scripts |
| Vegetation | Shrubs, trees, tropical plants, rocks, leaves and debris | `boxwood_shrub`, `cedar_shrub`, `japanese_cherry_tree`, `agave`, `bamboo` | `transform_object`, `clone_object`, `delete_object` |

The running Isaac Sim instance last returned 207 robot definitions. This value
is discovered live and can change with the configured asset root. The curated
non-robot list intentionally exposes a smaller set of verified entry points;
additional USDs can still be loaded with `load_usd`.

## MCP examples

```text
list_nvidia_assets(category="robot_arm", query="franka")
spawn_nvidia_asset(asset_key="frankapanda", prim_path="/World/Robots/Arm01", position=[4, 6, 0])

list_nvidia_assets(category="quadruped")
spawn_nvidia_asset(asset_key="go1", prim_path="/World/Robots/Dog01", position=[10, 4, 0])

list_nvidia_assets(category="agv")
spawn_nvidia_asset(asset_key="carter", prim_path="/World/AGVs/AGV04", position=[8, 12, 0])

spawn_nvidia_asset(asset_key="conveyor_a01", prim_path="/World/Factory/Conveyor01", position=[16, 8, 0])
spawn_nvidia_asset(asset_key="boxwood_shrub", prim_path="/World/Vegetation/Shrub01", position=[2, 30, 0])

list_nvidia_assets(category="lifting")
spawn_nvidia_asset(asset_key="portable_gantry_crane", prim_path="/World/Factory/Lifting/Gantry01")

list_nvidia_assets(category="instrumentation", query="optical")
spawn_nvidia_asset(asset_key="wheel_alignment_scanner", prim_path="/World/Factory/Inspection/Scanner01")
```

## Safety and behavior

- Spawning fails closed while the timeline is playing.
- A supplied destination must be an absolute USD prim path and cannot overwrite
  an existing prim.
- Assets are referenced into the current stage, so loading one does not reopen
  or replace the factory environment.
- A visible robot model does not imply autonomous behavior. Arms, quadrupeds,
  AGVs, and conveyors each need a controller appropriate to that asset.

## NVIDIA references

- Isaac Sim robot assets: <https://docs.isaacsim.omniverse.nvidia.com/6.0.0/assets/usd_assets_robots.html>
- Adding a robot to a scene: <https://docs.isaacsim.omniverse.nvidia.com/6.0.0/introduction/quickstart_isaacsim_robot.html>
- SimReady asset search: <https://docs.isaacsim.omniverse.nvidia.com/6.0.0/utilities/tutorial_search_extension.html>
- Asset root configuration: <https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_faq.html>
- Asset Browser and vegetation: <https://docs.omniverse.nvidia.com/kit/docs/kit-app-template/105.1/create_from_usd_explorer.html>
