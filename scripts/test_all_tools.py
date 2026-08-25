#!/usr/bin/env python3
"""Compatibility entry point for the safe unified tool-evidence report.

The historical implementation called ``clear_scene`` and mutated the connected
stage. Phase 6.1 intentionally removed that behavior. Per-tool writes now
belong to dedicated guarded verifiers; this command aggregates their evidence
and captures a read-only snapshot of the current 8766 runtime.
"""

from generate_all_tools_report import main

if __name__ == "__main__":
    raise SystemExit(main())
