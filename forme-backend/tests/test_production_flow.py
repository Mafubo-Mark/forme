from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from forme_backend.api import create_app
from forme_backend.config import Settings
from forme_backend.store import Store
from forme_backend.view_review import SLOTS


def test_reviewed_views_make_a_hashed_hunyuan_package_without_auto_release(tmp_path: Path) -> None:
    data = tmp_path / "data"
    settings = Settings(data, "operator-secret", "ffprobe", "ffmpeg")
    store = Store(data)
    session_id, upload_id, submission_id = (str(uuid.uuid4()) for _ in range(3))
    store.create_session(session_id)
    store.create_upload(upload_id, "sample.mp4", "video/mp4", 5, session_id)
    video = data / "uploads" / upload_id / "source.video"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    store.transition(upload_id, "initiated", "uploading")
    store.transition(upload_id, "uploading", "uploaded", actual_bytes=5,
                     sha256=hashlib.sha256(b"video").hexdigest())
    store.create_submission(submission_id, session_id, upload_id, "black", "PETG", "", "01")
    client = TestClient(create_app(settings))
    auth = {"Authorization": "Bearer operator-secret"}
    assert client.get("/api/internal/worker-status").status_code == 401
    assert client.get("/api/internal/worker-status", headers=auth).json()["media"] is False
    path = f"/api/internal/submissions/{submission_id}/hunyuan/prepare"
    assert client.post(path).status_code == 401
    assert client.post(path, headers=auth).json()["detail"]["code"] == "CAPTURE_REVIEW_REQUIRED"
    store.transition(upload_id, "uploaded", "needs_capture_review")
    store.transition(upload_id, "needs_capture_review", "accepted")
    assert client.post(path, headers=auth).json()["detail"]["code"] == "SIX_VIEWS_REVIEW_REQUIRED"
    frame_dir = data / "submissions" / submission_id / "view_frames"
    frame_dir.mkdir(parents=True)
    frames, selections = [], {}
    for index, slot in enumerate(SLOTS):
        name = f"frame_{index:03d}.jpg"
        raw = b"\xff\xd8\xff" + slot.encode()
        (frame_dir / name).write_bytes(raw)
        frames.append({"name": name, "sha256": hashlib.sha256(raw).hexdigest()})
        selections[slot] = name
    store.set_view_review(submission_id, "reviewed", {"frames": frames, "selections": selections})
    prepared = client.post(path, headers=auth)
    assert prepared.status_code == 200
    assert prepared.json()["views"] == list(SLOTS)
    manifest = json.loads(Path(prepared.json()["manifestPath"]).read_text())
    assert manifest["sourceVideoSha256"] == hashlib.sha256(b"video").hexdigest()
    assert client.post(path, headers=auth).status_code == 200
    locked = client.post(f"/api/internal/submissions/{submission_id}/views/selection", headers=auth,
                         json={"selections": selections, "notes": "repeat reviewed selection"})
    assert locked.status_code == 409
    assert locked.json()["detail"]["code"] == "VIEWS_LOCKED_BY_HUNYUAN_PACKAGE"
    flow = client.get(f"/api/internal/submissions/{submission_id}/production-flow", headers=auth).json()
    assert next(s for s in flow["stages"] if s["id"] == "hunyuan_input")["state"] == "done"
    assert flow["manufacturingApproved"] is False
    assert client.post(f"/api/internal/submissions/{submission_id}/hunyuan/submit", headers=auth).json()["detail"]["code"] == "HUNYUAN_CREDENTIALS_NOT_CONFIGURED"
    (frame_dir / selections["front"]).write_bytes(b"tampered")
    assert client.post(path, headers=auth).json()["detail"]["code"] == "SELECTED_FRAME_HASH_MISMATCH"


def test_hunyuan_submit_keeps_an_attempt_record_for_uncertain_network_result(tmp_path: Path, monkeypatch) -> None:
    from forme_backend import hunyuan_pro

    folder = tmp_path / "hunyuan_inputs"
    folder.mkdir()
    images = []
    for slot in ("front", "left", "right", "back"):
        path = folder / f"{slot}.jpg"
        path.write_bytes(b"\xff\xd8\xff" + slot.encode())
        images.append({"slot": slot, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps({"status": "prepared_not_submitted", "submissionId": "one",
                                    "sourceVideoSha256": "abc", "images": images}))
    key = tmp_path / "key.csv"
    key.write_text("SecretId,SecretKey\nexample-id,example-key\n")
    def network_failure(*_args):
        raise RuntimeError("network outcome unknown")
    monkeypatch.setattr(hunyuan_pro, "call", network_failure)
    try:
        hunyuan_pro.submit(manifest, key, "ap-singapore")
        assert False, "submit should raise"
    except RuntimeError:
        pass
    assert (folder / "hunyuan_submission_attempt.json").is_file()
    try:
        hunyuan_pro.submit(manifest, key, "ap-singapore")
        assert False, "uncertain attempt must prevent a charged retry"
    except ValueError as exc:
        assert "uncertain outcome" in str(exc)


def test_hunyuan_worker_only_polls_and_archives_existing_job(tmp_path: Path, monkeypatch) -> None:
    from forme_backend import hunyuan_worker

    data = tmp_path / "data"
    job_dir = data / "cover_tasks" / "sample" / "hunyuan_inputs"
    job_dir.mkdir(parents=True)
    record_path = job_dir / "hunyuan_job.json"
    record_path.write_text(json.dumps({"status": "submitted", "jobId": "remote-job"}))
    key = tmp_path / "key.csv"
    key.write_text("SecretId,SecretKey\nexample-id,example-key\n")
    calls = []
    def fake_poll(path, _key):
        calls.append("poll")
        return {"status": "DONE", "jobId": "remote-job"}
    def fake_archive(path):
        calls.append("archive")
        path.write_text(json.dumps({"status": "DONE", "jobId": "remote-job", "artifacts": [{"sha256": "example"}]}))
    monkeypatch.setattr(hunyuan_worker, "poll", fake_poll)
    monkeypatch.setattr(hunyuan_worker, "archive", fake_archive)
    settings = Settings(data, "operator", "ffprobe", "ffmpeg", hunyuan_key_file=key)
    assert hunyuan_worker.process_one(settings)
    assert calls == ["poll", "archive"]
    assert not hunyuan_worker.process_one(settings)
