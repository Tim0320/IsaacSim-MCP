from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = (ROOT / "docs" / "reference" / "ERROR_CODES.md").read_text(encoding="utf-8")


def test_recovery_reference_covers_high_risk_codes() -> None:
    for code in (
        "STAGE_NOT_READY",
        "TIMELINE_NOT_STOPPED",
        "IDEMPOTENCY_KEY_CONFLICT",
        "REQUEST_TOO_LARGE",
        "RESPONSE_TOO_LARGE",
        "CONNECTION_LOST",
    ):
        assert f"`{code}`" in REFERENCE


def test_recovery_reference_marks_ambiguous_write_failures_no_replay() -> None:
    assert "write 必須先 read-back" in REFERENCE
    assert "Do not replay write" in REFERENCE


def test_recovery_reference_does_not_invent_proposed_umbrella_codes() -> None:
    assert "目前沒有 `TIMELINE_MUST_BE_STOPPED`" in REFERENCE
    assert "目前沒有通用 `BACKEND_UNSUPPORTED`" in REFERENCE
    assert "目前沒有通用 `RESOURCE_NOT_OWNED`" in REFERENCE
