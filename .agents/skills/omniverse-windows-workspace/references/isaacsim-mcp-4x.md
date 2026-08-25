# IsaacSim-MCP integration lifecycle 4.x

Use this reference for completed Phase 4 work in
`docs/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md`. It is a retrieval and safety
index; read the linked contract and verifier before changing behavior or making
a current live-support claim.

## Retrieval workflow

1. Map the request to 4.1 through 4.4 below.
2. Read the linked contract completely for prerequisites, schema, stable errors,
   preview/timeline rules, ownership, rollback, and evidence limits.
3. Inspect the named tools, extension handler, focused tests, and dedicated live
   verifier before editing or running live control.
4. Query current `get_capabilities`; all command counts, extension versions, and
   live results below are historical evidence.
5. Use an exact owned scratch namespace and preserve unrelated Stage, jobs,
   artifacts, timelines, files, and runtime resources.

## Numbering map

| Research label | Task item | Capability | Named tools | Contract | Live verifier |
| --- | --- | --- | --- | --- | --- |
| 4.1 | Phase 4 item 16 | Action Graph lifecycle, runtime status, exact ScriptNode configuration/reload and explicit evaluation | `create_action_graph`, `edit_action_graph`, `list_action_graphs`, `get_action_graph`, `delete_action_graph`, `connect_action_graph`, `disconnect_action_graph`, `set_action_graph_enabled`, `get_action_graph_status`, `configure_script_node`, `reload_script_node`, `evaluate_action_graph` | `docs/OMNIGRAPH_LIFECYCLE.md` | `scripts/verify_omnigraph_lifecycle_live.py` |
| 4.2 | Phase 4 item 17 | Typed ROS 2 Clock, TF, JointState, Camera and RTX LiDAR publisher workflows | `get_ros2_status`, `list_ros2_workflows`, `create_ros2_clock_publisher`, `create_ros2_tf_publisher`, `create_ros2_joint_state_publisher`, `create_ros2_camera_publisher`, `create_ros2_lidar_publisher`, `delete_ros2_workflow` | `docs/ROS2_WORKFLOWS.md` | `scripts/verify_ros2_workflows_live.py` |
| 4.3 | Phase 4 item 18 | Bounded Replicator BasicWriter synthetic-data jobs and managed manifests | `get_replicator_status`, `create_sdg_job`, `start_sdg_job`, `get_sdg_job_status`, `cancel_sdg_job`, `get_sdg_manifest`, `delete_sdg_job` | `docs/REPLICATOR_SDG.md` | `scripts/verify_replicator_sdg_live.py` |
| 4.4 | Phase 4 item 19 | MCP-owned IRA human lifecycle, Behavior Agent tasks/settings and NavMesh | `spawn_human`, `list_humans`, `get_human`, `delete_human`, `set_human_target`, `set_human_look_at`, `set_human_idle`, `set_human_behavior`, `get_navmesh_status`, `bake_navmesh` | `docs/HUMAN_LIFECYCLE.md` | `scripts/verify_human_lifecycle_live.py` |

## Cross-task invariants

- Run live operations through the extension socket and prove them with exact
  read-back. Documentation MCP output and static imports are not live evidence.
- New 4.x writes default to `preview=true`; pass `preview=false` only after all
  prerequisites and exact targets have been checked. The legacy graph create
  and edit interfaces are exceptions documented in the 4.1 contract.
- Require stopped timeline for graph/workflow authoring, SDG setup, NavMesh bake,
  and deletion unless the contract explicitly permits another state. Human
  MoveTo, LookAt, and Idle require Play. Playing-time graph emergency disable is
  the only 4.1 authoring-state exception.
- Mutate and delete only exact MCP-owned resources. Never infer ownership from a
  path name, scan and remove neighboring resources, or fall back across graphs,
  humans, workflows, jobs, writers, render products, or artifacts.
- Validate complete requests before the first mutation. Verify postconditions;
  use operation-specific inverse/undo or snapshot rollback and report partial or
  unknown state if rollback fails.
- Run each dedicated verifier only after its read-only guard passes. Confirm
  fixture/artifact absence, restored registries and settings, stopped timeline,
  responsive Kit/TCP, bounded logs, and no new native dump.
- Never mix `tests/test_integration.py` into an offline regression run while TCP
  `8766` is reachable. It can accumulate Camera, LiDAR, and robot fixtures and
  has historically caused a native crash during later simulation playback.

## 4.1 OmniGraph and ScriptNode

- Require exact graph, node, and attribute paths. Connections must stay inside
  one graph and use connection-state read-back plus inverse-edit rollback.
- Treat graph enabled state as runtime-only, not persistent USD authoring.
- Keep inline and file ScriptNode modes mutually exclusive. File mode accepts an
  existing canonical `.py`; configure/reload only the exact node. A successful
  reload reports pending evaluation until a later evaluation/status proves no
  compile or runtime error.
- Explicit evaluation reports compute-count deltas and node messages. It does
  not prove downstream playback behavior when OnPlaybackTick never fires.

Historical 2026-08-25 evidence used a 98-command registry and an owned three-node
graph. It verified exact edge handling, inline `A→B→RECOVERED`, file `C→D`,
disabled compute-count stability, runtime error status, delete absence, graph-list
restore, and stopped timeline.

## 4.2 ROS 2 workflows

- Keep `isaacsim.ros2.bridge`, `isaacsim.ros2.core`, and
  `isaacsim.ros2.nodes` optional for MCP startup but mandatory for workflow
  creation. Missing prerequisites must fail without graph authoring.
- Validate domain 0 through 232, topic, namespace, relative frame IDs, QoS,
  target prims, sensor runtimes, and render products before create.
- Stamp ownership metadata on created graphs and refuse foreign graph deletion.
  Publishers emit only during Play.

Historical 2026-08-25 Clock evidence used a 106-command registry and an external
Jazzy `rclpy` subscriber on domain 42. It received 20
`rosgraph_msgs/msg/Clock` messages at about 60.23 Hz and verified complete graph
cleanup. This does not live-verify TF, JointState, Camera, or LiDAR schemas.

## 4.3 Replicator SDG jobs

- Keep the first contract bounded to `BasicWriter`, manual trigger, one active
  job, 1,000 frames, 4096 pixels per axis, typed transform/light randomizers,
  and currently live-supported annotation types.
- Start asynchronously; cancel cooperatively only at a completed-frame boundary.
  Publish terminal state only after writer detach, render-product destruction,
  trigger cleanup, randomizer restoration, artifact ingestion, and manifest.
- Determinism covers normalized configuration and randomization trace. Record
  renderer hashes for integrity but do not promise bitwise equality across
  machines or drivers.

Historical 2026-08-25 evidence used a 113-command registry and Replicator
`1.13.27`. Two seed-4317 jobs produced matching two-frame RGB and semantic traces;
a 100-frame job cancelled at a bounded safe point with all cleanup flags true.

## 4.4 IRA human lifecycle

- Read-only list/get may describe external Behavior Agents, but control and
  delete require the exact schema `1.0` MCP ownership marker and matching group.
- Convert `speed_mps` with Stage `metersPerUnit` and return raw stage-units/sec
  read-back. A running task proves dispatch and acceptance, not target arrival;
  verify later position and task state with `get_human`.
- Bake only with a real Navigation Core NavMeshVolume and stopped/paused
  timeline. Isaac Sim 6.0.1 needs five application updates after volume authoring
  before bake. A scaled Cube is not equivalent evidence.

Historical 2026-08-25 evidence used the 122-command registry, IRA `1.6.8`, and
Behavior/Navigation Core `110.1.4`. It verified NavMesh ready, owned spawn,
stopped-state rejection, MoveTo acceptance plus `0.2639` stage-unit displacement,
LookAt, Idle, exact deletion, fixture/list restore, and stopped timeline.

## Current-claim checklist

1. Record repository root, remote, branch, HEAD, status, and a verified backup.
2. Confirm Isaac Sim 6.0.1, current registry/capabilities, required extension
   versions, timeline, live TCP `8766`, and process identity.
3. Run only the matching dedicated verifier in its owned scratch namespace.
4. Capture preview/apply/read-back, stable errors, rollback, cleanup, restored
   settings/registries, Kit response, run-scoped logs, and native dumps.
5. Label the values in this reference historical whenever the verifier was not
   rerun against the current checkout and runtime.
