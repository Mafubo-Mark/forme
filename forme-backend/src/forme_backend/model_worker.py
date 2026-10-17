"""Local reconstruction worker. Its output is an unscaled COLMAP candidate, not a fitted prosthesis."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import struct
import time
import traceback
from pathlib import Path

from .config import Settings
from .store import Store


class StageFailure(Exception):
    def __init__(self, code: str, action: str):
        super().__init__(code)
        self.code = code
        self.action = action


def registered_image_count(model: Path) -> int:
    with (model / 'images.bin').open('rb') as source:
        return struct.unpack('<Q', source.read(8))[0]


def select_primary_model(folder: Path) -> Path:
    models = [path for path in folder.iterdir() if path.is_dir() and (path / 'images.bin').is_file()]
    if not models:
        raise StageFailure('CAMERAS_NOT_REGISTERED', '未重建出相机位姿；请检查纹理、遮挡和拍摄覆盖，必要时补拍。')
    return max(models, key=registered_image_count)


def run_stage(command: list[str], log_path: Path, timeout: int) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("w") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StageFailure("PROCESSING_UNAVAILABLE", f"处理工具未能完成；请查看 {log_path.name} 并重试。") from exc
    if result.returncode != 0:
        raise StageFailure("RECONSTRUCTION_STAGE_FAILED", f"处理阶段失败；请查看 {log_path.name}，必要时补拍后重试。")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ply_vertex_count(path: Path) -> int:
    with path.open("rb") as stream:
        for _ in range(200):
            line = stream.readline().decode("ascii", "replace").strip()
            if line.startswith("element vertex "):
                return int(line.split()[-1])
            if line == "end_header":
                break
    raise StageFailure("INVALID_POINT_CLOUD", "COLMAP 未输出可读取的点云；请检查日志。")


def process_claimed_job(store: Store, settings: Settings, job: dict) -> None:
    job_id = job["id"]
    submission = store.get_submission(job["submission_id"])
    if submission is None or submission["upload"]["status"] != "accepted":
        store.transition_model_job(job_id, "capture_review", status="needs_input", reason_code="CAPTURE_NOT_ACCEPTED",
                                   next_action="先完成人工拍摄复核。")
        return
    source = settings.data_dir / "uploads" / submission["upload_id"] / "source.video"
    root = settings.data_dir / "model_jobs" / job_id
    frames = root / "frames"
    sparse = root / "sparse"
    dense = root / "dense"
    logs = root / "logs"
    for path in (frames, sparse, dense, logs):
        path.mkdir(parents=True, exist_ok=True)
    try:
        if not source.is_file() or not Path(settings.colmap).is_file():
            raise StageFailure("PROCESSING_UNAVAILABLE", "缺少原视频或 COLMAP 可执行文件。")
        duration = (submission["upload"]["metadata"] or {}).get("duration_seconds")
        if not duration:
            raise StageFailure("VIDEO_METADATA_MISSING", "请重新运行视频质检。")
        fps = min(2.0, 120.0 / duration)
        run_stage(
            [settings.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source),
             "-vf", f"fps={fps:.6f},scale=w='min(1600,iw)':h=-2", "-q:v", "3", "-y", str(frames / "frame_%04d.jpg")],
            logs / "extract_frames.log", 300,
        )
        frame_files = sorted(frames.glob("frame_*.jpg"))
        if len(frame_files) < 8:
            raise StageFailure("TOO_FEW_FRAMES", "有效抽帧少于 8 张；请检查视频和抽帧日志。")
        store.transition_model_job(job_id, "features", note=f"已抽取 {len(frame_files)} 帧")
        colmap = settings.colmap
        database = root / "database.db"
        run_stage([colmap, "feature_extractor", "--database_path", str(database), "--image_path", str(frames),
                   "--ImageReader.single_camera", "1", "--FeatureExtraction.use_gpu", "0"], logs / "features.log", 1800)
        store.transition_model_job(job_id, "matching")
        run_stage([colmap, "sequential_matcher", "--database_path", str(database),
                   "--FeatureMatching.use_gpu", "0", "--SequentialMatching.overlap", "12"], logs / "matching.log", 1800)
        store.transition_model_job(job_id, "sparse_reconstruction")
        try:
            run_stage([colmap, "mapper", "--database_path", str(database), "--image_path", str(frames),
                       "--output_path", str(sparse)], logs / "mapper.log", 3600)
        except StageFailure as exc:
            if exc.code == "RECONSTRUCTION_STAGE_FAILED":
                raise StageFailure("CAMERAS_NOT_REGISTERED", "COLMAP 未恢复相机位姿；请检查视频是否有真实环绕视差及足够纹理，必要时补拍。") from exc
            raise
        selected_model = select_primary_model(sparse)
        method = 'sequential'
        if registered_image_count(selected_model) < .8 * len(frame_files):
            store.transition_model_job(job_id, 'matching', note='环绕重建分段，补做全图配对与闭环匹配；保留首次稀疏模型。')
            run_stage([colmap, 'exhaustive_matcher', '--database_path', str(database),
                       '--FeatureMatching.use_gpu', '0'], logs / 'loop_matching.log', 1800)
            retry = sparse / 'closed_loop'
            retry.mkdir(exist_ok=True)
            store.transition_model_job(job_id, 'sparse_reconstruction')
            run_stage([colmap, 'mapper', '--database_path', str(database), '--image_path', str(frames),
                       '--output_path', str(retry)], logs / 'loop_mapper.log', 3600)
            repaired = select_primary_model(retry)
            if registered_image_count(repaired) > registered_image_count(selected_model):
                selected_model = repaired
                method = 'exhaustive_loop_closure_repair'
        if registered_image_count(selected_model) < .7 * len(frame_files):
            raise StageFailure('CAMERAS_NOT_REGISTERED', '环绕相机仍分成不连通片段，不能把局部点云当作完整参考；请检查运动模糊与视角重叠。')
        store.transition_model_job(job_id, "dense_reconstruction")
        run_stage([colmap, "image_undistorter", "--image_path", str(frames), "--input_path", str(selected_model),
                   "--output_path", str(dense), "--output_type", "COLMAP", "--max_image_size", "1600"],
                  logs / "undistort.log", 1800)
        run_stage([colmap, "patch_match_stereo", "--workspace_path", str(dense), "--workspace_format", "COLMAP",
                   "--PatchMatchStereo.geom_consistency", "true"], logs / "patch_match.log", 7200)
        cloud = dense / "fused.ply"
        run_stage([colmap, "stereo_fusion", "--workspace_path", str(dense), "--workspace_format", "COLMAP",
                   "--input_type", "geometric", "--output_path", str(cloud)], logs / "fusion.log", 3600)
        if not cloud.is_file():
            raise StageFailure("INVALID_POINT_CLOUD", "COLMAP 未生成点云，请查看融合日志。")
        metrics = {
            "frameCount": len(frame_files), "pointCount": ply_vertex_count(cloud),
            "cloudSha256": sha256(cloud), "sourceSha256": submission["upload"]["sha256"],
            "colmapModel": str(selected_model.relative_to(sparse)), "coordinateUnit": "colmap_unit_unscaled",
            "registeredImages": registered_image_count(selected_model), "reconstructionMethod": method,
            "scaleVerified": False,
        }
        (root / "manifest.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
        store.transition_model_job(job_id, "scale_review", status="needs_input", reason_code="SCALE_NOT_VERIFIED",
                                   next_action="COLMAP 点云已生成；请让 Agent 准备本单标尺、主体定轴、上缘及螺栓复核卡，再进入点云保护套主流程。",
                                   metrics=metrics)
    except StageFailure as exc:
        store.transition_model_job(job_id, "stopped", status="needs_input" if exc.code in {"CAMERAS_NOT_REGISTERED", "TOO_FEW_FRAMES"} else "failed",
                                   reason_code=exc.code, next_action=exc.action)
    except Exception:
        (logs / "worker_error.log").write_text(traceback.format_exc())
        store.transition_model_job(job_id, "stopped", status="failed", reason_code="UNEXPECTED_WORKER_ERROR",
                                   next_action="本机重建程序异常；请检查 worker_error.log。")


def process_one(store: Store, settings: Settings) -> bool:
    job = store.claim_model_job()
    if job is None:
        return False
    process_claimed_job(store, settings, job)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process at most one queued model job")
    args = parser.parse_args()
    settings = Settings.from_env()
    store = Store(settings.data_dir)
    # Only the worker holding this data-directory lock may recover and claim jobs.
    # Otherwise a second startup can requeue a job that the first worker is
    # actively processing, causing both processes to write into the same folder.
    lock_path = settings.data_dir / "model_worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"Another model worker is already running for {settings.data_dir}")
        lock_file.close()
        raise SystemExit(2)
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    try:
        store.requeue_interrupted_model_jobs()
        while True:
            if not process_one(store, settings):
                if args.once:
                    break
                time.sleep(3)
            elif args.once:
                break
    except KeyboardInterrupt:
        pass
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    main()
