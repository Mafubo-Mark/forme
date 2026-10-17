#!/usr/bin/env python3
"""Create one real cloud demo submission from the previously reviewed ruler video.

Credentials and progress stay in the Mac backend private data directory.
Re-running resumes after the last successful API step.
"""
import json
import os
import secrets
import sys
from pathlib import Path

import httpx


BASE = "https://forme.agents-time.com"
BACKEND = Path(__file__).resolve().parents[1] / "forme-backend"
STATE = BACKEND / "data" / "demo-cloud-account.json"
VIDEO = Path(__file__).resolve().parent / "cloud_ruler_demo.mp4"


def save(value):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as target:
        json.dump(value, target, ensure_ascii=False, indent=2)
    os.chmod(STATE, 0o600)


def check(response):
    if response.is_error:
        raise RuntimeError(f"Cloud API {response.status_code}: {response.text[:300]}")
    return response.json()


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if not state:
        suffix = secrets.token_hex(4)
        state = {
            "base_url": BASE,
            "email": f"forme-demo-{suffix}@example.com",
            "username": f"forme_demo_{suffix}",
            "password": secrets.token_urlsafe(24),
            "video": str(VIDEO),
        }
        save(state)
    assert state["base_url"] == BASE
    if state["video"] != str(VIDEO):
        if state.get("submission_id"):
            raise ValueError("A different video has already been submitted")
        for key in ("upload_id", "uploaded", "completed"):
            state.pop(key, None)
        state["video"] = str(VIDEO)
        save(state)
    with httpx.Client(base_url=BASE, timeout=httpx.Timeout(30, read=600), follow_redirects=False,
                      headers={"Origin": BASE}) as client:
        if not state.get("registered"):
            check(client.post("/api/customer/register", json={
                "email": state["email"], "username": state["username"],
                "password": state["password"], "full_name": "Forme 演示任务",
            }))
            state["registered"] = True
            save(state)
            print("registered", flush=True)
        else:
            check(client.post("/api/customer/login", json={
                "identifier": state["username"], "password": state["password"],
            }))
        if not state.get("upload_id"):
            result = check(client.post("/api/uploads/init", json={
                "filename": "ruler-calibrated-demo.mp4", "content_type": "video/mp4",
                "byte_size": VIDEO.stat().st_size,
            }))
            state["upload_id"] = result["uploadId"]
            save(state)
            print("upload initialized", state["upload_id"], flush=True)
        if not state.get("uploaded"):
            with VIDEO.open("rb") as source:
                check(client.put(f"/api/uploads/{state['upload_id']}/content", content=source,
                                 headers={"Content-Type": "video/mp4"}))
            state["uploaded"] = True
            save(state)
            print("video uploaded", VIDEO.stat().st_size, "bytes", flush=True)
        if not state.get("completed"):
            check(client.post(f"/api/uploads/{state['upload_id']}/complete"))
            state["completed"] = True
            save(state)
            print("upload completed", flush=True)
        if not state.get("submission_id"):
            result = check(client.post("/api/customer/submissions", json={
                "upload_id": state["upload_id"], "template_id": "01",
                "color": "Ocean Blue", "material": "Durable Nylon",
                "inspiration": "演示任务：原始视频含标定尺；根据点云、参考模型与模板生成可审查数字试样候选。",
            }))
            state["submission_id"] = result["submissionId"]
            save(state)
        result = check(client.get(f"/api/customer/submissions/{state['submission_id']}"))
        print("submission", state["submission_id"], "status", result["status"], flush=True)


if __name__ == "__main__":
    sys.exit(main())
