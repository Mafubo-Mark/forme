"""Pull cloud submissions into the local workflow and publish reviewed progress.

Only the cloud server is contacted. No local listener or inbound port is needed.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import Settings
from .production_flow import workflow_snapshot
from .store import Store
from .worker import validate_claimed


class CloudBridge:
    def __init__(self, base_url: str, key: str, settings: Settings, store: Store):
        base = base_url.rstrip("/")
        parsed = urllib.parse.urlparse(base)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("FORME_CLOUD_URL must be HTTPS (localhost HTTP is allowed for tests)")
        if not key or len(key) < 32:
            raise ValueError("FORME_CLOUD_WORKER_KEY must be a strong secret")
        self.base, self.key, self.settings, self.store = base, key, settings, store

    def request(self, method: str, path: str, payload: dict | None = None, *, job_token: str | None = None,
                file: Path | None = None, sha256: str | None = None) -> dict:
        headers = {"Authorization": "Bearer " + self.key,
                   "User-Agent": "FormeMacBridge/1.0"}
        if job_token:
            headers["X-Job-Token"] = job_token
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if file is not None:
            data = file.read_bytes()
            headers.update({"Content-Type": "application/octet-stream", "X-File-Name": file.name,
                            "X-Content-SHA256": sha256 or hashlib.sha256(data).hexdigest()})
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=600 if file else 30) as response:
            return json.load(response)

    def download_video(self, job: dict) -> Path:
        target = self.settings.data_dir / "uploads" / job["uploadId"] / "source.video"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and self.file_hash(target) == job["sha256"] and target.stat().st_size == job["byteSize"]:
            return target
        temporary = target.with_suffix(".video.part")
        req = urllib.request.Request(self.base + "/api/worker/jobs/" + job["submissionId"] + "/video",
                                     headers={"Authorization": "Bearer " + self.key,
                                              "User-Agent": "FormeMacBridge/1.0"})
        digest = hashlib.sha256()
        count = 0
        try:
            with urllib.request.urlopen(req, timeout=120) as response, temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    count += len(block)
                    if count > job["byteSize"]:
                        raise ValueError("CLOUD_VIDEO_SIZE_MISMATCH")
                    digest.update(block)
                    output.write(block)
            if count != job["byteSize"] or digest.hexdigest() != job["sha256"]:
                raise ValueError("CLOUD_VIDEO_HASH_MISMATCH")
            os.replace(temporary, target)
            return target
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def import_job(self, job: dict, token: str) -> None:
        if job.get('schemaVersion') != 1:
            raise ValueError('UNSUPPORTED_CLOUD_JOB_SCHEMA')
        sid, upload_id = job["submissionId"], job["uploadId"]
        upload = self.store.get_upload(upload_id)
        if upload and upload["sha256"] and upload["sha256"] != job["sha256"]:
            raise ValueError("LOCAL_UPLOAD_HASH_CONFLICT")
        existing_submission = self.store.get_submission(sid)
        if existing_submission and existing_submission["upload_id"] != upload_id:
            raise ValueError("LOCAL_SUBMISSION_ID_CONFLICT")
        self.download_video(job)
        session_id = "cloud-" + sid
        with self.store._connect() as db:
            db.execute("INSERT OR IGNORE INTO customer_sessions(id,authenticated,created_at) VALUES(?,1,datetime('now'))", (session_id,))
        if upload is None:
            self.store.create_upload(upload_id, job["filename"], job["contentType"], job["byteSize"], session_id)
            upload = self.store.get_upload(upload_id)
        if upload["status"] == "initiated":
            self.store.transition(upload_id, "initiated", "uploaded", actual_bytes=job["byteSize"], sha256=job["sha256"])
        if self.store.get_submission(sid) is None:
            self.store.create_submission(sid, session_id, upload_id, job["color"], job["material"],
                                         job["inspiration"], job["templateId"])
        self.request("POST", f"/api/worker/jobs/{sid}/imported", job_token=token)
        claimed = self.store.claim_for_validation(upload_id)
        if claimed:
            validate_claimed(self.store, self.settings, claimed)

    def sync_job(self, sid: str, remote_artifact_sha: str | None) -> None:
        submission = self.store.get_submission(sid)
        if submission is None:
            return
        upload = submission["upload"]
        model = self.store.model_job_for_submission(sid)
        if upload["status"] in {"rejected", "needs_recapture"}:
            status, stage, note = "needs_recapture", "stopped", upload.get("next_action") or "本机视频质检未通过，请重新拍摄。"
        elif upload["status"] == "validation_failed":
            status, stage, note = "modeling", "stopped", "本机视频质检工具不可用，请操作员检查。"
        elif model:
            stage = model["stage"] if model["stage"] in {"queued", "extracting_frames", "features", "matching", "sparse_reconstruction", "dense_reconstruction", "scale_review", "stopped"} else "modeling"
            status = "accepted" if stage == "queued" else "modeling"
            note = model.get("next_action") or ("本机建模任务已排队。" if stage == "queued" else "本机建模工作流正在处理。")
        else:
            status, stage = "accepted", "queued"
            note = "本机已接收视频，等待操作员复核拍摄与标尺。" if upload["status"] != "accepted" else "本机拍摄审核已通过，等待建模任务。"
        snapshot = workflow_snapshot(self.store, self.settings.data_dir, sid) if upload['status'] == 'accepted' else None
        candidate = snapshot.get('trialCandidate') if snapshot else None
        if candidate:
            status, stage = 'modeling', 'modeling'
            note = '数字试样 STL 候选已生成，待尺寸、切片与人工审查；尚未验证佩戴适配。'
        if remote_artifact_sha:
            task_dir = self.settings.data_dir / "cover_tasks" / sid
            review_path = task_dir / "candidate_review.json"
            if review_path.is_file():
                review = json.loads(review_path.read_text(encoding="utf-8"))
                candidate_id = review.get("candidateId")
                report_path = task_dir / "candidate_print_trial" / candidate_id / "build_report.json" if isinstance(candidate_id, str) else None
                if report_path and report_path.is_file():
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    if report.get("sourceMode") == "HISTORICAL_SAME_CAPTURE_REPLAY_FOR_BRIDGE_VALIDATION":
                        note = "同一拍摄素材的历史数字试样已回传，仅验证云端文件链路；当前新点云和混元白模未重新拟合此保护套，禁止客户发布。"
        self.request("POST", f"/api/worker/jobs/{sid}/progress", {"status": status, "stage": stage, "note": note[:500]})
        if upload["status"] != "accepted":
            return
        if not candidate:
            return
        candidate_id = candidate["candidateId"]
        if candidate.get('deliveryFormat') == 'stl_zip':
            from .scan_workflow import result_files
            found = result_files(self.settings.data_dir, sid)
            if not found:
                return
            out, report = found
            artifact = out/'cover_trial_mm.stl'
            digest = self.file_hash(artifact)
            if digest != report['files']['cover_trial_mm.stl']:
                raise ValueError('SCAN_COMBINED_STL_HASH_MISMATCH')
            if digest != remote_artifact_sha:
                self.request('PUT', f'/api/worker/jobs/{sid}/artifact', file=artifact, sha256=digest)
            return
        artifact = self.settings.data_dir / "cover_tasks" / sid / "candidate_print_trial" / candidate_id / "cover_trial_mm.stl"
        if not artifact.is_file():
            return
        sha = self.file_hash(artifact)
        if sha != remote_artifact_sha:
            report = json.loads((artifact.parent / "build_report.json").read_text(encoding="utf-8"))
            if report.get("combinedStlSha256") != sha:
                raise ValueError("COMBINED_STL_HASH_MISMATCH")
            replay = report.get("sourceMode") == "HISTORICAL_SAME_CAPTURE_REPLAY_FOR_BRIDGE_VALIDATION"
            self.request("PUT", f"/api/worker/jobs/{sid}/artifact", file=artifact, sha256=sha)
            self.request("POST", f"/api/worker/jobs/{sid}/progress",
                         {"status": "modeling", "stage": "modeling", "note": (
                             "同一拍摄素材的历史数字试样已回传，仅验证云端文件链路；当前新点云和混元白模未重新拟合此保护套，禁止客户发布。"
                             if replay else note)})

    def cycle(self) -> None:
        existing = self.request("GET", "/api/worker/jobs")["items"]
        for job in existing:
            if self.store.get_submission(job["submissionId"]) is None:
                self.request("POST", f"/api/worker/jobs/{job['submissionId']}/requeue")
            else:
                self.sync_job(job["submissionId"], job.get("artifactSha256"))
        claimed = self.request("POST", "/api/worker/claim")
        if claimed.get("job"):
            self.import_job(claimed["job"], claimed["jobToken"])
            self.sync_job(claimed["job"]["submissionId"], None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cloud to Mac Forme workflow bridge")
    parser.add_argument("--once", action="store_true", help="Run a single sync and claim cycle")
    args = parser.parse_args()
    # Settings requires a local API token; the bridge never sends or uses it.
    os.environ.setdefault("FORME_DEV_TOKEN", secrets.token_hex(24))
    # The bridge validates newly imported media synchronously, so it needs the
    # same bundled FFmpeg tools as run-local.sh even when launched by launchd.
    tools_dir = Path("/Volumes/extra/workspace1/colmap-metal/.pixi/envs/default/bin")
    for variable, name in (("FORME_FFPROBE", "ffprobe"), ("FORME_FFMPEG", "ffmpeg")):
        binary = tools_dir / name
        if variable not in os.environ and binary.is_file() and os.access(binary, os.X_OK):
            os.environ[variable] = str(binary)
    settings = Settings.from_env()
    config_path = os.environ.get("FORME_CLOUD_CONFIG")
    private = {}
    if config_path:
        path = Path(config_path).expanduser()
        if path.stat().st_mode & 0o077:
            raise ValueError("FORME_CLOUD_CONFIG must be owner-only (chmod 600)")
        private = json.loads(path.read_text(encoding="utf-8"))
    bridge = CloudBridge(os.environ.get("FORME_CLOUD_URL", private.get("base_url", "")),
                         os.environ.get("FORME_CLOUD_WORKER_KEY", private.get("worker_key", "")),
                         settings, Store(settings.data_dir))
    with (settings.data_dir / "cloud_bridge.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit("Cloud bridge is already running for this data directory") from exc
        while True:
            try:
                bridge.cycle()
            except (OSError, ValueError, urllib.error.HTTPError) as exc:
                print(f"Cloud bridge: {type(exc).__name__}: {exc}", flush=True)
            if args.once:
                break
            time.sleep(30)


if __name__ == "__main__":
    main()
