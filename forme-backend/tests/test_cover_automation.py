from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from forme_backend.api import create_app
from forme_backend.config import Settings
from forme_backend.store import Store


def test_frontend_cover_handoff_is_private_and_blocked(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", "operator-secret", "ffprobe", "ffmpeg")
    store = Store(settings.data_dir)
    session_id = str(uuid.uuid4())
    upload_id = str(uuid.uuid4())
    submission_id = str(uuid.uuid4())
    store.create_session(session_id)
    store.create_upload(upload_id, "sample.mov", "video/quicktime", 100, session_id)
    store.create_submission(submission_id, session_id, upload_id, "black", "PETG", "matte finish")
    client = TestClient(create_app(settings))
    url = f"/api/internal/submissions/{submission_id}/cover-task"
    assert client.get(url).status_code == 401
    auth = {"Authorization": "Bearer operator-secret"}
    assert client.get(url, headers=auth).json()["status"] == "not_prepared"
    assert client.post(url, headers=auth, json={"template_id": "not-a-template"}).status_code == 422
    response = client.post(url, headers=auth, json={"template_id": "04"})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "awaiting_reference_and_registration"
    assert result["conceptBuildAllowed"] is False
    assert "VERIFIED_MM_REFERENCE_REQUIRED" in result["blockers"]
    manifest = json.loads(Path(result["manifestPath"]).read_text())
    assert manifest["submissionId"] == submission_id
    assert manifest["templateId"] == "04"
    assert manifest["conceptBuildAllowed"] is False
    assert manifest["generationPolicy"]["sha256"] == result["generationPolicy"]["sha256"]
    assert result["candidateReview"] is None
    # A locally written review, even if it claims approval, cannot release a build.
    review_path = Path(result["manifestPath"]).parent / "candidate_review.json"
    review_path.write_text(json.dumps({
        "schemaVersion": 1,
        "candidateId": "test-candidate",
        "policySha256": result["generationPolicy"]["sha256"],
        "status": "CONCEPT_CANDIDATE_NOT_FIT_VERIFIED",
        "blockers": ["PHYSICAL_FIT_UNVERIFIED"],
        "manufacturingApproved": True,
    }))
    reviewed = client.get(url, headers=auth).json()
    assert reviewed["candidateReview"]["manufacturingApproved"] is False
    assert reviewed["conceptBuildAllowed"] is False
    assert "PHYSICAL_FIT_UNVERIFIED" in reviewed["blockers"]
    review_path.write_text(json.dumps({"schemaVersion": 1, "candidateId": "test-candidate",
                                       "policySha256": "outdated", "blockers": []}))
    assert client.get(url, headers=auth).json()["candidateReview"]["status"] == "STALE_REVIEW"
    assert client.get(f"/api/internal/submissions/{submission_id}", headers=auth).json()["coverTask"]["templateId"] == "04"
