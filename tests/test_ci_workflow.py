from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_ci_runs_for_pull_requests_and_main_pushes() -> None:
    assert "pull_request:\n    branches: [main]" in WORKFLOW
    assert "push:\n    branches: [main]" in WORKFLOW


def test_ci_covers_declared_python_versions_and_launchers() -> None:
    assert 'python-version: ["3.10", "3.11", "3.12"]' in WORKFLOW
    assert "windows-launcher:" in WORKFLOW
    assert "linux-launcher:" in WORKFLOW


def test_ci_checks_generated_metadata_and_clean_wheel() -> None:
    assert "generate_tool_inventory.py --check" in WORKFLOW
    assert "python -m build --wheel" in WORKFLOW
    assert "python -m venv" in WORKFLOW
    assert "pip install dist/*.whl" in WORKFLOW
