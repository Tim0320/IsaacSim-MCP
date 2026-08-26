# 文件入口

這是專案文件的固定入口。文件依用途分類，避免 runtime contract、維護程序與歷史研究被誤認為同一種目前權威。

## Getting Started

- [Windows 安裝與第一次連線](getting-started/INSTALLATION_WINDOWS.md)

## Concepts

- [Artifact transport](concepts/ARTIFACT_TRANSPORT.md)
- [Command governance](concepts/COMMAND_GOVERNANCE.md)
- [Jobs 與 diagnostics](concepts/JOB_DIAGNOSTICS.md)
- [Protocol versions 與 migration](concepts/PROTOCOL_VERSIONING_AND_MIGRATION.md)

## Reference

- [Authority and Generated Metadata](reference/AUTHORITY.md)
- [Generated MCP Tool Inventory](reference/TOOL_INVENTORY.md)
- [Capabilities](reference/CAPABILITIES.md)
- [Backend capability matrix](reference/BACKEND_CAPABILITY_MATRIX.md)
- [Response schema](reference/RESPONSE_SCHEMA.md)
- Camera 與 LiDAR：[RGB](reference/CAMERA_RGB.md)、[Camera outputs](reference/CAMERA_OUTPUTS.md)、[LiDAR config](reference/LIDAR_CONFIG.md)、[Point cloud](reference/LIDAR_POINT_CLOUD.md)、[Sensor lifecycle](reference/SENSOR_LIFECYCLE.md)
- Robot 與 motion：[Joint control](reference/ROBOT_JOINT_CONTROL.md)、[Drive config](reference/ROBOT_JOINT_DRIVE_CONFIG.md)、[Motion](reference/MOTION_CONTROL.md)、[Controller profiles](reference/CONTROLLER_PROFILES.md)
- Physics 與 USD：[Parameters](reference/PHYSICS_PARAMS.md)、[Authoring](reference/PHYSICS_AUTHORING.md)、[Materials](reference/PHYSICS_MATERIALS.md)、[Stage composition](reference/STAGE_COMPOSITION.md)
- Integrations：[OmniGraph](reference/OMNIGRAPH_LIFECYCLE.md)、[ROS 2](reference/ROS2_WORKFLOWS.md)、[Replicator SDG](reference/REPLICATOR_SDG.md)、[Human lifecycle](reference/HUMAN_LIFECYCLE.md)
- Assets：[NVIDIA asset catalog](reference/NVIDIA_ASSET_CATALOG.md)

## Development

- [Live test 與 scratch-stage harness](development/LIVE_TEST_HARNESS.md)
- [Release gate](development/RELEASE_GATE.md)
- [Contribution policy](../CONTRIBUTING.md)
- [Security policy](../SECURITY.md)

## Research 與 verification history

- [Isaac Sim 6.0.1 implementation task](research/ISAACSIM_MCP_6_0_1_IMPLEMENTATION_TASK.md)
- [Unified tool evidence report](research/ALL_TOOLS_TEST_REPORT.md)
- [Machine-readable evidence snapshot](research/ALL_TOOLS_TEST_RESULTS.json)
- [Historical 42-tool report](research/ALL_TOOLS_TEST_REPORT_2026-08-20_42_TOOLS.md)
- [Capability verification history](research/CAPABILITY_HISTORY.md)

Research 檔案保存有日期的 evidence。要宣稱目前 running Isaac Sim 的能力，必須重新讀取 `get_capabilities` 並執行 guarded live verification。
