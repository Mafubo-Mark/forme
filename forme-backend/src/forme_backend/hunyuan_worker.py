"""Poll submitted Hunyuan jobs and archive completed models without resubmitting."""
from __future__ import annotations

import argparse
import fcntl
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .hunyuan_pro import archive, poll, write_json


def process_one(settings: Settings) -> bool:
    if not settings.hunyuan_key_file or not settings.hunyuan_key_file.is_file():
        return False
    for record_path in sorted((settings.data_dir / "cover_tasks").glob("*/hunyuan_inputs/hunyuan_job.json")):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("status") == "FAIL" or (record.get("status") == "DONE" and record.get("artifacts")):
            continue
        last_query = record.get("lastQueryAt")
        if record.get("status") != "DONE" and last_query:
            try:
                if time.time() - datetime.fromisoformat(last_query).timestamp() < 60:
                    continue
            except ValueError:
                pass
        error_path = record_path.parent / "hunyuan_worker_error.json"
        if error_path.is_file():
            error = json.loads(error_path.read_text(encoding="utf-8"))
            if time.time() - error.get("timestamp", 0) < 60:
                continue
        try:
            if record.get("status") != "DONE":
                record = poll(record_path, settings.hunyuan_key_file)
            if record.get("status") == "DONE" and not record.get("artifacts"):
                archive(record_path)
            error_path.unlink(missing_ok=True)
        except (OSError, ValueError, RuntimeError) as exc:
            write_json(error_path, {"timestamp": time.time(), "at": datetime.now(timezone.utc).isoformat(),
                                    "error": str(exc)[:300]})
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    lock_path = settings.data_dir / "hunyuan_worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another Hunyuan worker already owns this data directory")
        while True:
            process_one(settings)
            if args.once:
                break
            time.sleep(20)


if __name__ == "__main__":
    main()
