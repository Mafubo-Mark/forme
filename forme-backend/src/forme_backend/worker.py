from __future__ import annotations

import argparse
import fcntl
import json
import os
import time

from .config import Settings
from .quality import MediaError, create_browser_preview, extract_review_frames, probe_video
from .store import Store


def validate_claimed(store: Store, settings: Settings, upload: dict) -> None:
    upload_id = upload["id"]
    source = settings.data_dir / "uploads" / upload_id / "source.video"
    try:
        metadata = probe_video(source, settings.ffprobe)
        metadata["review_frames"] = extract_review_frames(
            source, source.parent / "review_frames", metadata["duration_seconds"], settings.ffmpeg
        )
        metadata["browser_preview"] = create_browser_preview(source, settings.ffmpeg)
    except MediaError as exc:
        code = str(exc)
        if code == "PROCESSING_UNAVAILABLE":
            store.transition(
                upload_id, "validating", "validation_failed", reason_code=code,
                next_action="后台媒体处理服务不可用，请联系管理员处理；原上传已保留。",
            )
            return
        store.transition(
            upload_id, "validating", "rejected", reason_code=code,
            next_action="请上传清晰、可播放、时长 5–180 秒且画面至少 480×480 的视频。",
        )
        return
    store.transition(
        upload_id, "validating", "needs_capture_review",
        metadata_json=json.dumps(metadata),
        reason_code="MARKER_AND_VIEW_COVERAGE_UNVERIFIED",
        next_action="等待人工核对 200 mm 标靶、上口、背面和螺栓侧；此时尚未生成模型。",
    )


def process_one(store: Store, settings: Settings) -> bool:
    upload = store.claim_uploaded()
    if upload is None:
        return False
    validate_claimed(store, settings, upload)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    store = Store(settings.data_dir)
    lock_path = settings.data_dir / "media_worker.lock"
    with lock_path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"Another media worker is already running for {settings.data_dir}")
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        store.requeue_interrupted_validation()
        while True:
            did_work = process_one(store, settings)
            if args.once:
                break
            if not did_work:
                time.sleep(2)


if __name__ == "__main__":
    main()
