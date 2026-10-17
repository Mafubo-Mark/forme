from __future__ import annotations

import subprocess
import os
import shutil
import base64
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forme_backend.api import create_app
from forme_backend.config import Settings
from forme_backend.store import Store
from forme_backend.worker import process_one


TOOLS = Path("/Volumes/extra/workspace1/colmap-metal/.pixi/envs/default/bin")
FFMPEG = os.environ.get("FORME_TEST_FFMPEG") or shutil.which("ffmpeg") or str(TOOLS / "ffmpeg")
FFPROBE = os.environ.get("FORME_TEST_FFPROBE") or shutil.which("ffprobe") or str(TOOLS / "ffprobe")


@pytest.fixture(autouse=True)
def media_tools_available() -> None:
    if not Path(FFMPEG).is_file() or not Path(FFPROBE).is_file():
        pytest.skip("FFmpeg and FFprobe are required for workflow integration tests")


def make_video(path: Path) -> bytes:
    subprocess.run(
        [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x640:rate=2", "-t", "6", "-c:v", "mpeg4", "-y", str(path)],
        check=True,
        timeout=60,
    )
    return path.read_bytes()


def test_vision_provider_environment_selects_matching_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORME_DEV_TOKEN", "operator")
    monkeypatch.setenv("FORME_DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("FORME_TOKENHUB_API_KEY", "tokenhub-test-key")
    direct = Settings.from_env()
    assert direct.vision_model == "deepseek-flash"
    assert direct.vision_api_key == "deepseek-test-key"
    assert direct.vision_api_url == "https://api.deepseek.com/chat/completions"

    monkeypatch.setenv("FORME_VISION_PROVIDER", "tokenhub")
    tokenhub = Settings.from_env()
    assert tokenhub.vision_model == "deepseek/deepseek-flash"
    assert tokenhub.vision_api_key == "tokenhub-test-key"
    assert tokenhub.vision_api_url == "https://tokenhub-intl.tencentcloudmaas.com/v1/chat/completions"


def test_upload_validation_and_manual_gate(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", "test-secret", FFPROBE, FFMPEG)
    client = TestClient(create_app(settings))
    auth = {"Authorization": "Bearer test-secret"}
    video = make_video(tmp_path / "sample.mp4")

    assert client.get("/operator/").status_code == 200
    assert "工作流控制台" in client.get("/operator/").text
    assert client.get("/operator/js/app.js").status_code == 200
    assert client.get("/backend-test.html").status_code == 404
    assert client.get("/api/uploads/no-such-id").status_code == 401
    created = client.post("/api/uploads/init", headers=auth, json={
        "filename": "sample.mp4", "content_type": "video/mp4", "byte_size": len(video)
    })
    assert created.status_code == 201
    upload_id = created.json()["uploadId"]
    put = client.put(f"/api/uploads/{upload_id}/content", headers=auth, content=video)
    assert put.status_code == 200
    assert put.json()["status"] == "uploaded"
    assert client.post(f"/api/uploads/{upload_id}/complete", headers=auth).status_code == 200

    assert client.get("/api/uploads", headers=auth).json()["items"][0]["id"] == upload_id
    assert client.post(f"/api/internal/uploads/{upload_id}/validate", headers=auth).status_code == 202
    result = client.get(f"/api/uploads/{upload_id}", headers=auth).json()
    assert result["status"] == "needs_capture_review"
    assert result["reasonCode"] == "MARKER_AND_VIEW_COVERAGE_UNVERIFIED"
    assert len(result["quality"]["review_frames"]) == 8
    frame = client.get(f"/api/uploads/{upload_id}/review-frames/review_01.jpg", headers=auth)
    assert frame.status_code == 200
    assert frame.headers["content-type"] == "image/jpeg"
    assert client.post("/api/model/generate", headers=auth).status_code == 501

    decision = client.post(f"/api/internal/uploads/{upload_id}/decision", headers=auth, json={
        "approved": True, "notes": "人工核对标靶和视角符合要求"
    })
    assert decision.status_code == 200
    assert decision.json()["status"] == "accepted"
    assert client.get(f"/api/uploads/{upload_id}", headers=auth).json()["reviewNotes"] == "人工核对标靶和视角符合要求"


def test_size_mismatch_can_retry(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", "test-secret", FFPROBE, FFMPEG)
    client = TestClient(create_app(settings))
    auth = {"Authorization": "Bearer test-secret"}
    created = client.post("/api/uploads/init", headers=auth, json={
        "filename": "video.mp4", "content_type": "video/mp4", "byte_size": 10
    })
    upload_id = created.json()["uploadId"]
    mismatch = client.put(f"/api/uploads/{upload_id}/content", headers=auth, content=b"short")
    assert mismatch.status_code == 422
    assert client.get(f"/api/uploads/{upload_id}", headers=auth).json()["status"] == "initiated"
    good_size = client.put(f"/api/uploads/{upload_id}/content", headers=auth, content=b"0123456789")
    assert good_size.status_code == 200
    assert process_one(Store(settings.data_dir), settings)
    assert client.get(f"/api/uploads/{upload_id}", headers=auth).json()["status"] == "rejected"


@pytest.mark.parametrize('material', ['PLA', 'ABS', 'Durable Nylon'])
def test_frontend_submission_appears_in_operator_panel(tmp_path: Path, material: str) -> None:
    settings = Settings(tmp_path / "data", "operator-secret", FFPROBE, FFMPEG, customer_access_key="private-customer-key")
    app = create_app(settings)
    customer = TestClient(app)
    operator = TestClient(app)
    another_customer = TestClient(app)
    video = make_video(tmp_path / "front-submission.mp4")
    admin_headers = {"Authorization": "Bearer operator-secret"}

    assert customer.post("/api/customer/session").status_code == 405
    assert customer.post("/api/customer/login", json={"access_key": "wrong"}).status_code == 401
    assert customer.get("/api/customer/session").status_code == 401
    assert customer.post("/api/customer/login", json={"access_key": "private-customer-key"}).status_code == 200
    assert customer.get("/api/customer/session").status_code == 200
    initialized = customer.post("/api/uploads/init", json={
        "filename": "front-submission.mp4", "content_type": "video/mp4", "byte_size": len(video)
    })
    assert initialized.status_code == 201
    upload_id = initialized.json()["uploadId"]
    assert customer.put(f"/api/uploads/{upload_id}/content", content=video).status_code == 200
    assert customer.post(f"/api/uploads/{upload_id}/complete").status_code == 200
    submitted = customer.post("/api/customer/submissions", json={
        "upload_id": upload_id, "color": "Ocean Blue", "material": material,
        "inspiration": "海蓝色哑光外观", "template_id": "04",
    })
    assert submitted.status_code == 201
    submission_id = submitted.json()["submissionId"]
    assert customer.get("/api/customer/submissions").json()["items"][0]["id"] == submission_id

    image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/mL8AAAAASUVORK5CYII=")
    uploaded_image = customer.put(
        f"/api/customer/submissions/{submission_id}/inspiration-image",
        content=image, headers={"Content-Type": "image/png", "X-File-Name": "inspiration.png"},
    )
    assert uploaded_image.status_code == 200
    assert another_customer.get(f"/api/customer/submissions/{submission_id}").status_code == 401
    assert another_customer.post("/api/customer/login", json={"access_key": "private-customer-key"}).status_code == 200
    assert another_customer.get(f"/api/customer/submissions/{submission_id}").status_code == 404

    assert operator.get("/api/internal/submissions", headers=admin_headers).json()["items"][0]["id"] == submission_id
    detail = operator.get(f"/api/internal/submissions/{submission_id}", headers=admin_headers).json()
    assert detail["choices"]["color"] == "Ocean Blue"
    assert detail["choices"]["material"] == material
    assert detail["choices"]["templateId"] == "04"
    assert detail["capture"]["status"] == "needs_capture_review"
    assert detail["workflow"]["referenceModel"] == "not_started"
    assert detail["resources"]["inspirationImage"]["filename"] == "inspiration.png"
    assert detail["resources"]["video"]["previewUrl"]
    assert any(event["status"] == "validating" for event in detail["events"])
    assert operator.get(detail["resources"]["video"]["url"]).status_code == 401
    assert operator.get(detail["resources"]["video"]["previewUrl"]).status_code == 401
    assert operator.post("/api/internal/connect", headers=admin_headers).status_code == 200
    assert operator.get(detail["resources"]["video"]["url"]).content == video
    preview = operator.get(detail["resources"]["video"]["previewUrl"])
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "video/mp4"
    assert b"ftyp" in preview.content[:16]
    assert operator.get(detail["resources"]["inspirationImage"]["url"]).content == image
    assert customer.post("/api/customer/logout").status_code == 200
    assert customer.get("/api/customer/submissions").status_code == 401


def test_old_anonymous_session_cannot_upload_after_key_login_rollout(tmp_path: Path) -> None:
    import sqlite3
    data = tmp_path / "data"
    data.mkdir()
    with sqlite3.connect(data / "forme.sqlite3") as db:
        db.execute("CREATE TABLE customer_sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)")
        db.execute("INSERT INTO customer_sessions VALUES (?, datetime('now'))", ("old-anonymous-cookie",))
    client = TestClient(create_app(Settings(data, "operator", FFPROBE, FFMPEG, customer_access_key="new-key")))
    client.cookies.set("forme_customer", "old-anonymous-cookie", domain="testserver.local", path="/")
    assert client.get("/api/customer/session").status_code == 401
    assert client.post("/api/uploads/init", json={"filename": "x.mp4", "content_type": "video/mp4", "byte_size": 100}).status_code == 401
    assert client.post("/api/customer/login", json={"access_key": "new-key"}).status_code == 200
    assert client.get("/api/customer/session").status_code == 200


def test_model_job_requires_capture_review_and_records_worker_failure(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", "test-secret", FFPROBE, FFMPEG, colmap=str(tmp_path / "missing-colmap"), customer_access_key="test-customer-key")
    client = TestClient(create_app(settings))
    auth = {"Authorization": "Bearer test-secret"}
    video = make_video(tmp_path / "model-input.mp4")
    assert client.post("/api/customer/login", json={"access_key": "test-customer-key"}).status_code == 200
    upload_id = client.post("/api/uploads/init", json={
        "filename": "model-input.mp4", "content_type": "video/mp4", "byte_size": len(video),
    }).json()["uploadId"]
    client.put(f"/api/uploads/{upload_id}/content", content=video)
    submission_id = client.post("/api/customer/submissions", json={
        "upload_id": upload_id, "color": "Ocean Blue", "material": "Durable Nylon",
    }).json()["submissionId"]
    path = f"/api/internal/submissions/{submission_id}/model-jobs"
    assert client.post(path, headers=auth).status_code == 409
    client.post(f"/api/internal/uploads/{upload_id}/decision", headers=auth, json={
        "approved": True, "notes": "标靶及各视角已由测试人员核对",
    })
    queued = client.post(path, headers=auth)
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"
    assert client.post(path, headers=auth).status_code == 409
    assert client.get(path).status_code == 401
    from forme_backend.model_worker import process_one as process_model_one
    assert process_model_one(Store(settings.data_dir), settings)
    job = client.get(path, headers=auth).json()
    assert job["status"] == "failed"
    assert job["reason_code"] == "PROCESSING_UNAVAILABLE"
    assert any(event["stage"] == "extracting_frames" for event in job["events"])
    assert client.get(f"/api/customer/submissions/{submission_id}").json()["model"]["status"] == "failed"
    cloud_url = f"{path}/cloud"
    assert client.get(cloud_url, headers=auth).status_code == 404
    cloud = settings.data_dir / "model_jobs" / queued.json()["jobId"] / "dense" / "fused.ply"
    cloud.parent.mkdir(parents=True, exist_ok=True)
    cloud.write_bytes(b"ply\nformat ascii 1.0\nend_header\n")
    assert client.get(cloud_url).status_code == 401
    assert client.get(cloud_url, headers=auth).status_code == 200


def test_colmap_worker_reports_no_parallax_as_needs_input(tmp_path: Path) -> None:
    colmap = Path("/Volumes/extra/workspace1/colmap-metal/build/src/colmap/exe/colmap")
    if not colmap.is_file():
        pytest.skip("Local COLMAP Metal build is unavailable")
    settings = Settings(tmp_path / "data", "test-secret", FFPROBE, FFMPEG, colmap=str(colmap))
    store = Store(settings.data_dir)
    video = make_video(tmp_path / "static-pattern.mp4")
    store.create_session("session")
    store.create_upload("upload", "static-pattern.mp4", "video/mp4", len(video), "session")
    source = settings.data_dir / "uploads" / "upload" / "source.video"
    source.parent.mkdir(parents=True)
    source.write_bytes(video)
    store.transition("upload", "initiated", "uploading")
    store.transition("upload", "uploading", "uploaded", actual_bytes=len(video))
    store.transition("upload", "uploaded", "validating")
    store.transition("upload", "validating", "needs_capture_review", metadata_json='{"duration_seconds": 6.0}')
    store.transition("upload", "needs_capture_review", "accepted", review_notes="synthetic test only")
    store.create_submission("submission", "session", "upload", "Ocean Blue", "Durable Nylon", "")
    store.create_model_job("job", "submission")
    from forme_backend.model_worker import process_one as process_model_one
    assert process_model_one(store, settings)
    result = store.get_model_job("job")
    assert result["status"] == "needs_input"
    assert result["reason_code"] == "CAMERAS_NOT_REGISTERED"
    assert "真实环绕视差" in result["next_action"]


def test_operator_view_selection_and_vision_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(tmp_path / "data", "secret", FFPROBE, FFMPEG, vision_model="test-vision", vision_api_key="test-key")
    store = Store(settings.data_dir)
    store.create_session("session")
    video = make_video(tmp_path / "views.mp4")
    store.create_upload("upload", "views.mp4", "video/mp4", len(video), "session")
    source = settings.data_dir / "uploads" / "upload" / "source.video"
    source.parent.mkdir(parents=True)
    source.write_bytes(video)
    store.transition("upload", "initiated", "uploading")
    store.transition("upload", "uploading", "uploaded", actual_bytes=len(video))
    store.transition("upload", "uploaded", "validating")
    store.transition("upload", "validating", "needs_capture_review", metadata_json='{"duration_seconds": 6.0}')
    store.create_submission("submission", "session", "upload", "Ocean Blue", "Durable Nylon", "")
    client = TestClient(create_app(settings))
    auth = {"Authorization": "Bearer secret"}
    base = "/api/internal/submissions/submission/views"
    assert client.post(f"{base}/prepare").status_code == 401
    assert client.post(f"{base}/prepare", headers=auth).status_code == 202
    review = client.get(base, headers=auth).json()
    assert review["status"] == "ready"
    names = [frame["name"] for frame in review["data"]["frames"]]
    assert len(names) >= 6
    assert 0 <= review["data"]["frames"][0]["quality"]["score"] <= 1
    assert client.get(f"{base}/frames/{names[0]}").status_code == 401
    assert client.get(f"{base}/frames/{names[0]}", headers=auth).status_code == 200
    assert client.get(f"{base}/frames/../../source.video", headers=auth).status_code != 200
    assert client.post(f"{base}/selection", headers=auth, json={"selections":{"top":"missing.jpg"},"notes":"真实上口还没有拍到"}).status_code == 422
    assert client.post(f"{base}/selection", headers=auth, json={"selections":{"front":names[0],"back":names[0]},"notes":"两个方向不能使用同一帧"}).status_code == 422

    unconfigured = TestClient(create_app(Settings(tmp_path / "data", "secret", FFPROBE, FFMPEG)))
    unavailable = unconfigured.post(f"{base}/classify", headers=auth, json={})
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "VISION_API_NOT_CONFIGURED"

    import forme_backend.view_review as view_review
    monkeypatch.setattr(view_review, "_ask_vision", lambda settings, image, anchor: {
        "label": "unknown", "confidence": 0.3, "reason": "无法可靠判断实物方向"})
    result = client.post(f"{base}/classify", headers=auth, json={"front_anchor":names[0]})
    assert result.status_code == 202
    review = client.get(base, headers=auth).json()
    assert review["status"] == "classified"
    assert review["data"]["suggestions"]["front"] == [names[0]]
    assert "top" in review["data"]["missing"]
    saved = client.post(f"{base}/selection", headers=auth, json={
        "selections":{"front":names[0]}, "notes":"正面已确认，顶部需要补拍"})
    assert saved.json()["status"] == "incomplete"
    assert "top" in saved.json()["missing"]
    monkeypatch.setattr(view_review, "_ask_vision", lambda settings, image, anchor: {
        "label": "left", "confidence": 0.9, "reason": "鞋头在画面中朝左"})
    assert client.post(f"{base}/classify", headers=auth, json={}).status_code == 202
    unanchored = client.get(base, headers=auth).json()
    assert unanchored["data"]["frames"][0]["label"] == "unknown"
    assert unanchored["data"]["frames"][0]["rawAiLabel"] == "left"
    monkeypatch.setattr(view_review, "_ask_vision", lambda settings, image, anchor: (_ for _ in ()).throw(RuntimeError("DeepSeek 返回 HTTP 401")))
    assert client.post(f"{base}/classify", headers=auth, json={}).status_code == 202
    failed = client.get(base, headers=auth).json()
    assert failed["status"] == "failed"
    assert failed["data"]["apiErrors"][0]["message"] == "DeepSeek 返回 HTTP 401"


def test_deepseek_vision_request_uses_server_key_and_base64(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import forme_backend.view_review as view_review
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"\xff\xd8\xfftest")
    settings = Settings(tmp_path / "data", "operator", FFPROBE, FFMPEG,
                        vision_model="deepseek-flash", vision_api_key="private-test-key")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data)
        return io.BytesIO(json.dumps({"id":"request-123", "usage":{"total_tokens":42}, "choices":[{
            "message":{"content":'{"label":"top","confidence":0.92,"reason":"上口完整可见"}'}}]}).encode())

    monkeypatch.setattr(view_review.urllib.request, "urlopen", fake_urlopen)
    result = view_review._ask_vision(settings, image, None)
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["authorization"] == "Bearer private-test-key"
    assert captured["body"]["model"] == "deepseek-flash"
    assert captured["body"]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert result["label"] == "top"
    assert result["completionId"] == "request-123"
    assert result["totalTokens"] == 42
