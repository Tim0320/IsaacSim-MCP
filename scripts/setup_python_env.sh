#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Pick a Python >= 3.10 (project requires-python = ">=3.10").
# Override by exporting PYTHON_SPEC (a path or a uv version like "3.11").
if [[ -z "${PYTHON_SPEC:-}" ]]; then
  for candidate in python3.10 python3.11 python3.12 python3.13 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_SPEC="$(command -v "$candidate")"
      break
    fi
  done
fi

if [[ -z "${PYTHON_SPEC:-}" ]]; then
  echo "Error: no suitable Python (>=3.10) found on PATH." >&2
  echo "Install Python 3.10+ or set PYTHON_SPEC to an interpreter path/version." >&2
  exit 1
fi

cd "$REPO_ROOT"

if [[ ! -d .venv ]]; then
  echo "Creating virtual environment with: $PYTHON_SPEC"
  uv venv --python "$PYTHON_SPEC"
else
  echo "Using existing virtual environment at: $REPO_ROOT/.venv"
fi

echo "Installing isaacsim-mcp-server and dependencies"
uv pip install --python .venv/bin/python -e "."

echo
echo "Done."
echo "Activate with: source .venv/bin/activate"
