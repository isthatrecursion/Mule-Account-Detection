import importlib
import json
from dataclasses import FrozenInstanceError
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from mule_detection.application.context import ExecutionContext
from mule_detection.application.logging import configure_logging
from mule_detection.cli import main
from mule_detection.domain.clock import ManualClock, MonotonicTimer, SystemClock
from mule_detection.domain.errors import DomainError, ErrorCode
from tests.factories import actor_claims, manifest, model_metadata, require_test_database, snapshots


def test_import_boundaries():
    for name in (
        "domain",
        "application",
        "persistence",
        "ingestion",
        "features",
        "training",
        "registry",
        "scoring",
        "explanations",
        "reconciliation",
        "monitoring",
        "api",
    ):
        importlib.import_module("mule_detection." + name)


def test_clocks_keep_virtual_delay_separate_from_compute(clock):
    before = clock.now()
    timer = MonotonicTimer()
    clock.advance(timedelta(minutes=10))
    assert (clock.now() - before).total_seconds() == 600
    assert 0 <= timer.elapsed_seconds() < 10
    assert SystemClock().now().utcoffset() == timedelta(0)
    with pytest.raises(ValueError):
        ManualClock(before.replace(tzinfo=None))
    with pytest.raises(ValueError):
        clock.advance(timedelta(seconds=-1))


def test_context_is_immutable_and_preservable():
    context = ExecutionContext.create("synthetic", "test")
    assert str(context.correlation_id)
    with pytest.raises(FrozenInstanceError):
        context.actor_id = "other"


def test_sensitive_error_and_log_redaction():
    output = StringIO()
    logger = configure_logging(output)
    secret = "password=SECRET_ROW_AND_NOTE"
    try:
        raise ValueError(secret)
    except ValueError:
        logger.exception(
            secret,
            extra={
                "event": "command_failed",
                "authorization": secret,
                "raw_rows": secret,
                "analyst_notes": secret,
                "error_code": "INTERNAL_ERROR",
            },
        )
    assert secret not in output.getvalue()
    assert json.loads(output.getvalue())["error_code"] == "INTERNAL_ERROR"
    error = DomainError(ErrorCode.INTERNAL_ERROR)
    assert secret not in json.dumps(error.public())


def test_malformed_logging_extras_cannot_trigger_sensitive_formatter_error(capsys):
    output = StringIO()
    logger = configure_logging(output)
    secret = "SYNTHETIC_CREDENTIAL_AND_ROW"
    logger.error(secret, extra={"event": {"payload": secret}, "error_code": {"token": secret}})
    assert json.loads(output.getvalue())["event"] == "redacted_event"
    assert secret not in output.getvalue() + capsys.readouterr().err


def test_synthetic_factories_repeat_and_cover_edge_cases(synthetic_batch):
    assert snapshots() == synthetic_batch
    assert {row["label"] for row in synthetic_batch} == {0, 1}
    assert any(row["S1"] is None for row in synthetic_batch)
    assert any(row["category"] == "UNKNOWN" for row in synthetic_batch)
    assert manifest() == manifest()
    assert model_metadata() == model_metadata()
    assert actor_claims() == actor_claims()
    root = Path(__file__).resolve().parents[1] / "fixtures/foundation"
    assert (root / "duplicate_columns.csv").read_text().splitlines()[0] == "account_id,S1,S1"
    assert "not-a-timestamp" in (root / "invalid_timestamps.csv").read_text()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://user@localhost/mule",
        "postgresql+psycopg://user@localhost/postgres",
        "sqlite:///mule_test_unit",
        "postgresql+psycopg://user@localhost/mule_test_x?options=unsafe",
    ],
)
def test_database_guard_denies_operational_urls(url):
    with pytest.raises(ValueError):
        require_test_database(url)


def test_database_guard_accepts_dedicated_name():
    url = "postgresql+psycopg://test_user@localhost/mule_test_fixture"
    assert require_test_database(url) == url


def test_cli_health_is_honest_and_safe(app_root, capsys):
    assert main(["--root", str(app_root), "health"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "foundation_only"
    assert result["operational_readiness"] == "NOT_IMPLEMENTED"
    assert result["qualified_approval"] == "NOT_GRANTED"


@pytest.mark.parametrize(
    "arguments",
    [
        ["validate-batch", "--manifest", "synthetic.json"],
        ["train", "--config", "synthetic.yaml", "--mode", "research"],
        ["evaluate", "--run-id", "00000000-0000-0000-0000-000000000001"],
        [
            "score",
            "--batch-id",
            "00000000-0000-0000-0000-000000000001",
            "--model-version",
            "synthetic",
        ],
        ["reconcile", "--source", "synthetic"],
        ["replay", "--scenario", "synthetic.json"],
    ],
)
def test_unimplemented_commands_fail_explicitly(app_root, capsys, arguments):
    assert main(["--root", str(app_root), *arguments]) == 4
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "UNSUPPORTED_OPERATION"


def test_cli_bad_arguments_never_dispatch():
    with patch("mule_detection.cli.dispatch") as dispatch:
        with pytest.raises(SystemExit) as result:
            main(["score", "--batch-id", "not-a-uuid", "--model-version", "synthetic"])
        assert result.value.code == 2
        dispatch.assert_not_called()


def test_cli_internal_error_never_leaks(app_root, capsys):
    with patch("mule_detection.cli.dispatch", side_effect=ValueError("PRIVATE_PAYLOAD")):
        assert main(["--root", str(app_root), "health"]) == 1
    output = capsys.readouterr()
    assert "PRIVATE_PAYLOAD" not in output.out + output.err
    assert json.loads(output.out)["error"]["correlation_id"]
