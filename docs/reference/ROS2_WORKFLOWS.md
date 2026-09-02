# ROS 2 named workflow contract

Task 4.2 adds eight typed ROS 2 tools to IsaacSim-MCP. They build Isaac Sim 6.0 Action Graph pipelines without requiring callers to assemble raw OmniGraph nodes.

## Prerequisites and status

`get_ros2_status` reports `isaacsim.ros2.bridge`, `isaacsim.ros2.core`, and `isaacsim.ros2.nodes`, plus `ROS_DOMAIN_ID`, `ROS_DISTRO`, RMW implementation, the configured distro fallback and owned workflow count. The MCP extension keeps the bridge dependency optional so IsaacSim-MCP still loads when ROS 2 is unavailable.

Create operations require all three ROS 2 extensions. Missing prerequisites return `status=unsupported`, `code=ROS2_PREREQUISITE_MISSING`, the exact missing extensions, and a restart instruction. No graph is authored on that path.

ROS 2 publishers only emit messages during Timeline Play. Graph creation and deletion require Stop and default to `preview=true`.

## Dependency-aware acceptance

Check `get_ros2_status` before grading a publisher workflow. If `isaacsim.ros2.bridge`, `isaacsim.ros2.core`, or `isaacsim.ros2.nodes` is disabled, an apply-mode create is correctly blocked with `ROS2_PREREQUISITE_MISSING`. Because that create authored no graph, a later list may contain no matching workflow and a delete of the requested path may correctly return `GRAPH_NOT_FOUND`. That downstream result is not evidence of a `delete_ros2_workflow` bug.

Deletion can only be accepted after creation succeeded in the same isolated lifecycle. The required sequence is:

```text
get_ros2_status (all required extensions enabled)
→ create_*_publisher with preview=false
→ list_ros2_workflows (exact owned graph present)
→ delete_ros2_workflow with preview=false
→ list_ros2_workflows (exact graph absent)
```

If create is blocked, classify the remaining list/delete checks as `blocked_by=create_ros2_*_publisher` (with the ROS 2 extension prerequisite as root blocker). Do not convert an expected post-create `GRAPH_NOT_FOUND` into an independent deletion failure. Conversely, once create succeeds, deletion still requires exact graph/prim/ownership-marker absence and the final list read-back.

## Domain and QoS

`domain_id=null` connects `ROS2Context` to the process `ROS_DOMAIN_ID`, falling back to domain 0. An explicit domain must be an integer from 0 through 232 and sets `useDomainIDEnvVar=false`.

Every graph owns a `ROS2QoSProfile` node connected to the publisher. Accepted profiles are:

| MCP value | Isaac Sim preset | Intended use |
|---|---|---|
| `default` | Default for publishers/subscribers | Clock, TF and JointState default |
| `sensor_data` | Sensor Data | Camera and LiDAR default; best-effort depth 5 |
| `system_default` | System Default | DDS implementation defaults |
| `services` | Services | Explicit reliable services-style preset |

Invalid topic, namespace, relative frame ID, domain, QoS profile, sensor type, target prim or render product fails before graph creation.

## Publisher workflows

- Clock: Playback Tick, ROS2 Context, Read Simulation Time, QoS and ROS2 Publish Clock.
- TF: Isaac Sim 6.0 `IsaacComputeTransformTree` feeds parent/child frames, translations and orientations to ROS2 Publish Transform Tree.
- JointState: `IsaacReadJointState` feeds joint names, positions, velocities, efforts, DOF types, stage scale and sensor time to ROS2 Publish Joint State.
- Camera: `ROS2CameraHelper` publishes an existing MCP camera runtime. The tool resolves that camera's exact render product; supported payloads include RGB, depth, point cloud and typed annotations.
- RTX LiDAR: `ROS2RtxLidarHelper` publishes `point_cloud` or `laser_scan` from an existing MCP LiDAR runtime and its exact render product.

Camera and LiDAR accept an explicit `render_product_path` override for a render product created outside MCP. The sensor prim and render product must both exist.

## Ownership and deletion

Created graphs receive three USD custom-data keys: schema version, workflow type and topic. `delete_ros2_workflow` refuses graphs without this marker using `ROS2_WORKFLOW_NOT_OWNED`; it delegates exact deletion/read-back/rollback to the OmniGraph lifecycle handler. Successful deletion requires graph, backing prim and ownership marker to be absent.

## Stable errors

`ROS2_PREREQUISITE_MISSING`, `INVALID_ROS2_TOPIC`, `INVALID_ROS2_NAMESPACE`, `INVALID_ROS2_FRAME_ID`, `INVALID_ROS2_DOMAIN_ID`, `INVALID_ROS2_QOS_PROFILE`, `INVALID_ROS2_SENSOR_TYPE`, `ROS2_TARGET_PRIM_NOT_FOUND`, `ROS2_PARENT_PRIM_NOT_FOUND`, `ROS2_SENSOR_PRIM_NOT_FOUND`, `ROS2_SENSOR_RUNTIME_NOT_FOUND`, `ROS2_RENDER_PRODUCT_NOT_FOUND`, `ROS2_WORKFLOW_NOT_OWNED`, `ROS2_WORKFLOW_ROLLED_BACK`, and `ROS2_WORKFLOW_ROLLBACK_FAILED`.

## Verification evidence

The offline suite covers all eight public signatures and command forwarding, the 106-name registry, response wrapper, capabilities, input validation, explicit preview, the 6.0 TF and JointState topology, sensor helper selection, owned runtime render-product resolution, marker read-back and foreign-graph deletion refusal. Task-focused tests are 43 passed; the complete safe suite excluding Windows launcher and destructive live integration is 336 passed.

`scripts/verify_ros2_workflows_live.py` uses `/World/MCP_Task_4_2_Clock`, domain 42 and a separate `C:\isaacsim\python.bat` Jazzy rclpy process. On the latest 2026-08-25 run it received 20 `/mcp_task_4_2/clock` messages of type `rosgraph_msgs/msg/Clock`; the first timestamp was `0.116666666 s`, the last was `0.433333333 s`, and the observed receive frequency was about `60.23 Hz`. Cleanup proved graph, prim and marker absent, workflow list restored, and timeline stopped.

The 2026-08-25 Clock result remains historical evidence. It does not override a current-runtime `ROS2_PREREQUISITE_MISSING`: when the required extensions are currently disabled, create and its dependent lifecycle checks are blocked and must be rerun after enabling the extensions and restarting Isaac Sim. Only a fresh create → list → delete → list run can establish the current runtime's deletion result.

This Clock result does not prove the asset-specific TF, JointState, Camera or LiDAR message schemas. Those workflows require their own matching fixture and external subscriber before being marked live-verified; their current evidence is implementation, offline contract and graph topology only.
