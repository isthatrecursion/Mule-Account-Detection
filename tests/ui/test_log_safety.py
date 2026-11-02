import io
from uuid import UUID, uuid4

import pytest

from ui import dto
from ui.errors import ApiFailure
from ui.logging_setup import configure_logging
from ui.mock.backend import create_workspace, identity


def test_journey_logs_and_safe_errors_exclude_credentials_notes_and_feature_values(monkeypatch):
    workspace, backend = create_workspace()
    stream = io.StringIO()
    logger = configure_logging(stream)
    workspace.authenticate()
    token = workspace.api.provider.credential().token.get_secret_value()
    private_note = "PRIVATE_JOURNEY_NOTE_48329"
    private_feature = "PRIVATE_FEATURE_VALUE_73821"
    original_read = backend.read

    def evidence_read(path, params):
        result = original_read(path, params)
        if path.endswith("/evidence"):
            result["facts"]["raw_aggregates"][0]["observed_value"] = private_feature
        return result

    monkeypatch.setattr(backend, "read", evidence_read)
    case = UUID(identity("case-1"))
    workspace.api.assign(case, dto.AssignmentRequest(expected_version=0), key=uuid4())
    workspace.api.start_review(case, dto.VersionedRequest(expected_version=1), key=uuid4())
    workspace.api.review(
        case,
        dto.ReviewRequest(
            expected_version=2, conclusion="NEEDS_MORE_INFORMATION", note=private_note
        ),
        key=uuid4(),
    )
    workspace.api.get_evidence(case)
    path = "/v1/cases/" + str(case) + "/evidence"
    backend.inject("GET", path, 500, 500, 500)
    with pytest.raises(ApiFailure) as error:
        workspace.api.get_evidence(case)
    output = stream.getvalue() + error.value.safe_message + str(error.value)
    assert token not in output and private_note not in output
    assert private_feature not in output
    assert "observed_value" not in output and "Authorization" not in output
    logger.handlers = []
