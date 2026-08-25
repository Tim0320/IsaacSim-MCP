# Script policy and command governance

Tasks 5.1 and 5.2 add a common safety boundary around the high-risk Python
escape hatch and every MCP command sent to the Isaac Sim extension.

## Script escape hatch

Prefer named tools. `execute_script` and `reload_script` remain available for
trusted code when no typed tool covers the operation. Both are controlled by
the extension policy exposed through `get_script_policy` and
`get_capabilities.data.feature_flags.execute_script`.

Default policy:

| Control | Default |
|---|---|
| enabled | `true` |
| allowed roots | canonical repository root |
| timeout | 30 s, hard maximum 300 s |
| output | 64 KiB per stdout/stderr stream, hard maximum 1 MiB |
| source size | 256 KiB |
| background scheduling | disabled |
| audit retention | last 256 records in memory |

Kit settings use `/exts/isaac.sim.mcp/server.script.*`. Environment overrides
use the matching `ISAAC_MCP_SCRIPT_*` names. `allowed_roots` is separated with
the Windows path separator. A disabled policy, an escaped `cwd`/`file_path`, an
invalid limit, excessive output, or common background scheduling mechanism is
rejected before or during execution with a stable error code.

The timeout uses Python tracing. It interrupts Python bytecode and prevents
later Python statements from mutating the Stage. A native Kit call cannot be
safely pre-empted while control remains inside native code; the timeout fires
as soon as Python control returns. This is a governance boundary for trusted
automation, not an OS sandbox for hostile Python.

`get_script_audit_log` returns command ID, timestamp, operation, source/target
SHA-256, outcome, duration, limits, and output byte counts. It never stores or
returns inline source text.

Stable script policy codes include:

- `SCRIPT_EXECUTION_DISABLED`
- `SCRIPT_POLICY_DENIED`
- `INVALID_SCRIPT_REQUEST`
- `SCRIPT_TIMEOUT`
- `SCRIPT_OUTPUT_LIMIT_EXCEEDED`

## Command ID and idempotency

Every named tool accepts optional keyword-only `command_id` and
`idempotency_key`. If `command_id` is omitted, the MCP connection generates a
UUID. Metadata is carried at the socket envelope level rather than forwarded
as handler parameters.

The extension keeps a bounded in-memory ledger of 256 entries for 600 seconds:

- first request: validate, apply, normalize, then cache the exact result;
- same key and identical canonical payload: return the cached result without
  invoking the handler again;
- same key and different command type or parameters: fail with
  `IDEMPOTENCY_KEY_CONFLICT` before apply;
- extension restart: ledger is intentionally cleared. Cross-restart durable
  idempotency is not claimed.

Every routed response adds `data.command`:

```json
{
  "type": "objects.create",
  "write": true,
  "apply_state": "applied",
  "readback_state": "verified",
  "idempotency_key": "fixture-create-1",
  "replayed": false
}
```

`readback_state=not_reported` is explicit. It must not be interpreted as a
verified postcondition. Handlers that provide exact read-back keep it in the
top-level `readback` field.

## Transactions and rollback

`apply_stage_batch` is the atomic multi-write transaction boundary. It accepts
up to 100 Stage composition operations, validates all operations, snapshots the
root/session layers and payload load rules, applies in order, and restores the
snapshot on failure. A restored failure returns `BATCH_ROLLED_BACK` with
`readback.rolled_back=true`; rollback failure remains `partial` and identifies
unknown applied state.

Universal cross-subsystem batches are deliberately unsupported. Sensor runtime,
ROS 2 graphs, Replicator jobs, motion jobs, and filesystem side effects cannot
share one reliable USD rollback mechanism. Their named handlers retain their
own validate/apply/read-back/teardown contracts.

## Verification

Offline contract:

```powershell
.\.venv\Scripts\python.exe -m pytest --ignore=tests\test_integration.py --ignore=tests\test_launcher_engine.py -q
```

Live scratch acceptance:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_command_governance_live.py
```

The live verifier uses only `/World/MCP_Task_5_1_5_2`. It checks cwd and
background denial, bounded output, timeout postcondition, idempotent create,
key collision, transaction rollback/read-back, audit metadata, cleanup,
stopped timeline, and TCP `8766` survival.
