"""Audited backend capability facts for the Isaac Sim 6 adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Dict

from .context import RuntimeContext

CapabilityRecordBuilder = Callable[..., Dict[str, Any]]


class CapabilityRuntime:
    """Build the V6 backend matrix from shared runtime facts and base policy."""

    def __init__(
        self,
        context: RuntimeContext,
        capability_record_builder: CapabilityRecordBuilder,
    ) -> None:
        self._context = context
        self._capability_record = capability_record_builder

    def get_backend_capability_matrix(self) -> Dict[str, Any]:
        """Return the audited Isaac Sim 6.0.1 PhysX/Newton matrix."""
        verified = "Isaac Sim 6.0.1 guarded PhysX live matrix (Tasks 1.x, 2.x, 3.1)"
        untested = "No Isaac Sim 6.0.1 Newton live acceptance evidence"
        physx_only = "Implementation depends on PhysX runtime or PhysxSchema"
        features = {
            "simulation.timeline": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "simulation.step": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "simulation.reset": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "physics.state": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "physics.gravity": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "physics.time_step": self._capability_record(
                physx_supported=True,
                newton_supported=False,
                physx_evidence=verified,
                newton_reason=physx_only,
            ),
            "physics.gpu_enabled": self._capability_record(
                physx_supported=True,
                newton_supported=False,
                physx_evidence=verified,
                newton_reason=physx_only,
            ),
            "physics.body_authoring": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence="Isaac Sim 6.0.1 guarded PhysX live acceptance (Task 3.3)",
                newton_reason=untested,
            ),
            "physics.collision_groups": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence="Isaac Sim 6.0.1 guarded PhysX live acceptance (Task 3.3)",
                newton_reason=untested,
            ),
            "physics.joint_authoring": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence="Isaac Sim 6.0.1 guarded PhysX live acceptance (Task 3.3)",
                newton_reason=untested,
            ),
            "physics.materials": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence="Isaac Sim 6.0.1 guarded PhysX live acceptance (Task 3.4)",
                newton_reason=untested,
            ),
            "sensor.camera": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "sensor.lidar": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "sensor.lifecycle": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "robot.joint_state": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "robot.joint_command": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "robot.joint_drive_config": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "robot.joint_drive_config.max_velocity": self._capability_record(
                physx_supported=True,
                newton_supported=False,
                physx_evidence=verified,
                newton_reason="max_velocity is authored through PhysxSchema.PhysxJointAPI",
            ),
            "motion.ik_and_planning": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "robot.gripper_profiles": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
            "robot.mobile_base_profiles": self._capability_record(
                physx_supported=True,
                newton_supported=None,
                physx_evidence=verified,
                newton_reason=untested,
            ),
        }
        return {
            "schema_version": "1.0",
            "active_backend": self._context.active_backend,
            "policy": {
                "supported_requires_live_verification": True,
                "null_supported_means": "untested",
                "false_supported_means": "unsupported",
            },
            "features": features,
        }
